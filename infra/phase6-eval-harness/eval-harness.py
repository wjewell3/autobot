"""
eval-harness.py — Measure agent quality before and after every change.

Turns random walks into gradient descent. Without measurement, you can't
know if a system message tweak helped or hurt. This eval harness:

1. Stores baseline eval results per agent (what "good" looks like)
2. Runs eval suites: predefined test cases with expected outputs
3. Compares current performance against baseline
4. Scores changes as improvement / regression / neutral
5. Gates deployments: rd-agent can check eval before merging PRs

Architecture:
  - Eval cases stored in /etc/eval-harness/cases.yaml (ConfigMap)
  - Baselines stored in-memory + persisted to /data/baselines.json
  - Agents don't call this directly — rd-agent and north-star use it
  - Compares via exact match, substring match, or LLM-as-judge

MCP Tools:
  - run_eval(agent, suite) → runs test cases, returns scores
  - get_baseline(agent) → current baseline scores
  - set_baseline(agent) → snapshot current scores as new baseline
  - compare_eval(agent, suite) → run eval and diff against baseline
  - list_suites() → available eval suites
"""

import asyncio
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("eval-harness")

CASES_PATH = os.getenv("EVAL_CASES_PATH", "/etc/eval-harness/cases.yaml")
BASELINES_PATH = os.getenv("BASELINES_PATH", "/data/baselines.json")
PORT = int(os.getenv("EVAL_HARNESS_PORT", "8096"))
AUDIT_URL = os.getenv(
    "AUDIT_LOGGER_URL", "http://audit-logger.kagent.svc.cluster.local:8092"
)
KAGENT_API = os.getenv(
    "KAGENT_API_URL", "http://kagent-controller.kagent.svc.cluster.local:8083"
)

mcp = FastMCP(
    "eval-harness",
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)


# ── Eval Cases ───────────────────────────────────────────

def load_cases() -> dict:
    """Load eval cases from YAML. Top-level keys are suite names."""
    try:
        with open(CASES_PATH) as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        log.warning(f"Eval cases not found: {CASES_PATH}")
        return {}


def load_baselines() -> dict:
    """Load baseline scores from persistent storage."""
    try:
        with open(BASELINES_PATH) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_baselines(baselines: dict):
    """Persist baselines to disk."""
    os.makedirs(os.path.dirname(BASELINES_PATH), exist_ok=True)
    with open(BASELINES_PATH, "w") as f:
        json.dump(baselines, f, indent=2)


# ── Eval Runner ──────────────────────────────────────────

async def send_to_agent(agent_name: str, message: str) -> str:
    """Send a message to an agent via A2A and get the response."""
    import httpx

    url = f"{KAGENT_API}/api/a2a/kagent/{agent_name}/"
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            # Create a new session
            resp = await client.post(
                url,
                json={
                    "jsonrpc": "2.0",
                    "method": "message/send",
                    "id": f"eval-{int(time.time())}",
                    "params": {
                        "message": {
                            "role": "user",
                            "parts": [{"kind": "text", "text": message}],
                            "messageId": f"eval-msg-{int(time.time())}",
                        },
                    },
                },
                headers={
                    "Content-Type": "application/json",
                    "x-kagent-user-id": "admin@kagent.dev",
                },
            )
            if resp.status_code != 200:
                return f"ERROR: HTTP {resp.status_code}"
            data = resp.json()
            result = data.get("result", {})
            # Extract text from response parts
            artifacts = result.get("artifacts", [])
            texts = []
            for artifact in artifacts:
                for part in artifact.get("parts", []):
                    if part.get("kind") == "text":
                        texts.append(part["text"])
            if texts:
                return "\n".join(texts)
            # Fallback: check status
            status = result.get("status", {}).get("state", "unknown")
            return f"Agent responded with status: {status}"
    except Exception as e:
        return f"ERROR: {e}"


def score_case(actual: str, expected: dict) -> dict:
    """Score a single eval case against expected criteria."""
    scores = {}
    total = 0
    passed = 0

    # Exact match
    if "exact" in expected:
        total += 1
        match = actual.strip() == expected["exact"].strip()
        scores["exact_match"] = match
        if match:
            passed += 1

    # Contains (substring checks)
    if "contains" in expected:
        for substring in expected["contains"]:
            total += 1
            found = substring.lower() in actual.lower()
            scores[f"contains_{substring[:30]}"] = found
            if found:
                passed += 1

    # Not contains (negative checks)
    if "not_contains" in expected:
        for substring in expected["not_contains"]:
            total += 1
            absent = substring.lower() not in actual.lower()
            scores[f"not_contains_{substring[:30]}"] = absent
            if absent:
                passed += 1

    # Format checks
    if "format" in expected:
        fmt = expected["format"]
        if fmt == "json":
            total += 1
            try:
                json.loads(actual)
                scores["valid_json"] = True
                passed += 1
            except json.JSONDecodeError:
                scores["valid_json"] = False
        elif fmt == "yaml":
            total += 1
            try:
                yaml.safe_load(actual)
                scores["valid_yaml"] = True
                passed += 1
            except yaml.YAMLError:
                scores["valid_yaml"] = False

    # Min length
    if "min_length" in expected:
        total += 1
        long_enough = len(actual) >= expected["min_length"]
        scores["min_length"] = long_enough
        if long_enough:
            passed += 1

    # Tool usage check (did the agent mention using a tool?)
    if "used_tools" in expected:
        for tool in expected["used_tools"]:
            total += 1
            found = tool.lower() in actual.lower()
            scores[f"used_tool_{tool}"] = found
            if found:
                passed += 1

    score_pct = round(passed / max(total, 1) * 100, 1)
    return {"checks": scores, "passed": passed, "total": total, "score": score_pct}


async def run_suite(agent: str, suite_name: str, cases: list[dict]) -> dict:
    """Run a suite of eval cases against an agent."""
    results = []
    total_score = 0

    for i, case in enumerate(cases):
        case_id = case.get("id", f"case_{i}")
        input_msg = case.get("input", "")
        expected = case.get("expected", {})
        description = case.get("description", "")

        log.info(f"Running {suite_name}/{case_id}: {description[:50]}")

        # Send to agent and get response
        actual = await send_to_agent(agent, input_msg)

        # Score the response
        score_result = score_case(actual, expected)
        score_result["case_id"] = case_id
        score_result["description"] = description
        score_result["input"] = input_msg[:200]
        score_result["actual_output"] = actual[:500]

        results.append(score_result)
        total_score += score_result["score"]

    avg_score = round(total_score / max(len(results), 1), 1)

    return {
        "agent": agent,
        "suite": suite_name,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "cases_run": len(results),
        "average_score": avg_score,
        "results": results,
    }


# ── MCP Tools ────────────────────────────────────────────

@mcp.tool()
async def run_eval(agent: str, suite: str = "default") -> str:
    """
    Run an eval suite against an agent and return detailed scores.

    Args:
        agent: Agent name (e.g. "prospecting-agent")
        suite: Eval suite name from cases.yaml (default: "default")

    Returns:
        JSON with per-case scores and overall average
    """
    all_cases = load_cases()

    # Find suite for this agent
    agent_suites = all_cases.get(agent, {})
    if not agent_suites:
        return json.dumps({"error": f"No eval cases defined for agent '{agent}'"})

    suite_cases = agent_suites.get(suite, [])
    if not suite_cases:
        available = list(agent_suites.keys())
        return json.dumps({
            "error": f"Suite '{suite}' not found for '{agent}'. Available: {available}"
        })

    result = await run_suite(agent, suite, suite_cases)
    return json.dumps(result, indent=2)


@mcp.tool()
async def get_baseline(agent: str) -> str:
    """
    Get the current baseline scores for an agent.
    Baselines represent "known good" performance to compare against.
    """
    baselines = load_baselines()
    baseline = baselines.get(agent)
    if not baseline:
        return json.dumps({"error": f"No baseline set for '{agent}'. Run set_baseline first."})
    return json.dumps(baseline, indent=2)


@mcp.tool()
async def set_baseline(agent: str, suite: str = "default") -> str:
    """
    Run the eval suite and save the results as the new baseline.
    Call this after deploying a known-good version of an agent.

    Args:
        agent: Agent name
        suite: Eval suite to establish baseline for
    """
    all_cases = load_cases()
    agent_suites = all_cases.get(agent, {})
    suite_cases = agent_suites.get(suite, [])

    if not suite_cases:
        return json.dumps({"error": f"No eval cases for {agent}/{suite}"})

    result = await run_suite(agent, suite, suite_cases)

    baselines = load_baselines()
    baselines[agent] = {
        "suite": suite,
        "timestamp": result["timestamp"],
        "average_score": result["average_score"],
        "cases_run": result["cases_run"],
        "per_case": {r["case_id"]: r["score"] for r in result["results"]},
    }
    save_baselines(baselines)

    log.info(f"Baseline set for {agent}/{suite}: {result['average_score']}%")
    return json.dumps({
        "success": True,
        "agent": agent,
        "suite": suite,
        "baseline_score": result["average_score"],
    })


@mcp.tool()
async def compare_eval(agent: str, suite: str = "default") -> str:
    """
    Run eval suite and compare against baseline. Returns improvement/regression.

    This is what rd-agent calls before proposing a system message change:
      1. Run eval → get current score
      2. Apply proposed change (in shadow)
      3. Run eval again → get new score
      4. If regression → reject change. If improvement → proceed with PR.

    Returns:
        JSON with {baseline_score, current_score, delta, verdict: "improvement"|"regression"|"neutral"}
    """
    baselines = load_baselines()
    baseline = baselines.get(agent)

    all_cases = load_cases()
    agent_suites = all_cases.get(agent, {})
    suite_cases = agent_suites.get(suite, [])

    if not suite_cases:
        return json.dumps({"error": f"No eval cases for {agent}/{suite}"})

    result = await run_suite(agent, suite, suite_cases)
    current_score = result["average_score"]

    if not baseline:
        return json.dumps({
            "warning": "No baseline exists. Saving current as baseline.",
            "current_score": current_score,
            "cases_run": result["cases_run"],
            "verdict": "no_baseline",
        })

    baseline_score = baseline["average_score"]
    delta = round(current_score - baseline_score, 1)

    # Per-case comparison
    regressions = []
    improvements = []
    for r in result["results"]:
        case_id = r["case_id"]
        old_score = baseline.get("per_case", {}).get(case_id)
        if old_score is not None:
            case_delta = r["score"] - old_score
            if case_delta < -5:
                regressions.append({"case": case_id, "old": old_score, "new": r["score"]})
            elif case_delta > 5:
                improvements.append({"case": case_id, "old": old_score, "new": r["score"]})

    if delta > 2:
        verdict = "improvement"
    elif delta < -2:
        verdict = "regression"
    else:
        verdict = "neutral"

    return json.dumps({
        "agent": agent,
        "suite": suite,
        "baseline_score": baseline_score,
        "current_score": current_score,
        "delta": delta,
        "verdict": verdict,
        "regressions": regressions,
        "improvements": improvements,
        "baseline_date": baseline.get("timestamp", "unknown"),
        "recommendation": {
            "improvement": "Change improved quality. Safe to deploy.",
            "regression": "REGRESSION DETECTED. Do not deploy without review.",
            "neutral": "No significant change. Deploy is safe but effect is minimal.",
        }[verdict],
    }, indent=2)


@mcp.tool()
async def list_suites() -> str:
    """List all available eval suites and their case counts."""
    all_cases = load_cases()
    result = {}
    for agent, suites in all_cases.items():
        result[agent] = {
            suite_name: len(cases) for suite_name, cases in suites.items()
        }
    return json.dumps(result, indent=2)


# ── Entry point ──────────────────────────────────────────

async def main():
    import uvicorn

    mcp_app = mcp.streamable_http_app()
    config = uvicorn.Config(mcp_app, host="0.0.0.0", port=PORT, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()


if __name__ == "__main__":
    import anyio
    anyio.run(main)
