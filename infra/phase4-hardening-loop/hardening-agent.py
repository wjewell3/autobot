"""
hardening-agent.py — Watches agent decision patterns and proposes
deterministic rules to replace repetitive LLM decisions.

This is the compounding mechanism. Over time, the LLM surface shrinks
and the deterministic surface grows.

How it works:
  Level 1 (v1): Count (agent, action) frequencies → propose deterministic rules
  Level 2 (v2): Analyze failure/rejection patterns → propose system message fixes
  Level 3 (future): Cluster similar failures → build knowledge docs → RAG-augment

v2 adds failure analysis on top of frequency counting:
  - Tracks severity=error/warning entries by (agent, root_cause)
  - Tracks output_rejected actions (PM pushing back on workers)
  - When the same failure pattern appears FAILURE_THRESHOLD+ times,
    proposes a system message patch to prevent recurrence
  - Posts failure-derived proposals to #hardening-proposals with context
"""

import asyncio
import json
import logging
import os
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone

import httpx
import yaml
from mcp.client.streamable_http import streamablehttp_client
from mcp import ClientSession
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("hardening-agent")

AUDIT_URL = os.getenv(
    "AUDIT_LOGGER_URL", "http://audit-logger.kagent.svc.cluster.local:8092"
)
GITHUB_MCP_URL = os.getenv(
    "GITHUB_MCP_URL", "http://github-mcp.kagent.svc.cluster.local:8087"
)
GITHUB_REPO = os.getenv("GITHUB_REPO", "wjewell3/autobot")
SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN", "")
SLACK_PROPOSALS_CHANNEL = os.getenv("SLACK_PROPOSALS_CHANNEL_ID", "")
RULES_PATH = "/etc/hardening/rules.yaml"
ANALYSIS_INTERVAL = int(os.getenv("ANALYSIS_INTERVAL_SECONDS", "300"))  # 5 min
PROPOSAL_THRESHOLD = int(os.getenv("PROPOSAL_THRESHOLD", "10"))
FAILURE_THRESHOLD = int(os.getenv("FAILURE_THRESHOLD", "3"))

mcp = FastMCP(
    "hardening-agent",
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)

# Track which patterns we've already proposed (avoid spam)
proposed_patterns: set[str] = set()
proposed_failures: set[str] = set()


async def call_mcp_tool(server_url: str, tool_name: str, arguments: dict) -> dict:
    """Call a tool on an MCP server using the proper MCP client SDK."""
    try:
        async with streamablehttp_client(f"{server_url}/mcp") as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(tool_name, arguments)
                if result.content:
                    text = result.content[0].text
                    try:
                        return json.loads(text)
                    except json.JSONDecodeError:
                        return {"text": text}
        return {"error": "No content returned"}
    except Exception as e:
        log.error(f"MCP call failed ({server_url} / {tool_name}): {e}")
        return {"error": str(e)}


async def create_pr_via_github_mcp(proposal_yaml: str, pattern_key: str) -> dict:
    """Create a branch, push a proposal file, and open a PR via github-mcp."""
    ts = int(time.time())
    branch_name = f"hardening/proposal-{ts}"

    # 1. Create branch
    branch_result = await call_mcp_tool(GITHUB_MCP_URL, "github_create_branch", {
        "repo": GITHUB_REPO,
        "branch": branch_name,
        "from_branch": "main",
    })
    if "error" in branch_result:
        log.error(f"Failed to create branch: {branch_result['error']}")
        return branch_result

    # 2. Push proposal file to the new branch
    file_path = f"infra/hardening-proposals/{pattern_key.replace(':', '-')}-{ts}.yaml"
    push_result = await call_mcp_tool(GITHUB_MCP_URL, "github_push_file", {
        "repo": GITHUB_REPO,
        "path": file_path,
        "content": proposal_yaml,
        "message": f"hardening: propose rule for {pattern_key}",
        "branch": branch_name,
    })
    if "error" in push_result:
        log.error(f"Failed to push file: {push_result['error']}")
        return push_result

    # 3. Open PR
    pr_result = await call_mcp_tool(GITHUB_MCP_URL, "github_create_pr", {
        "repo": GITHUB_REPO,
        "title": f"Hardening: propose rule for {pattern_key}",
        "body": (
            f"## Hardening Proposal\n\n"
            f"**Pattern:** `{pattern_key}`\n\n"
            f"This pattern was detected frequently in the audit log. "
            f"Review and merge to add as a deterministic rule.\n\n"
            f"**Rollback:** revert this PR or `kubectl rollout undo` affected deployments.\n\n"
            f"```yaml\n{proposal_yaml}\n```"
        ),
        "head": branch_name,
        "base": "main",
    })
    if "error" in pr_result:
        log.error(f"Failed to create PR: {pr_result['error']}")
    else:
        log.info(f"PR created: {pr_result.get('url', 'unknown')}")

    return pr_result


def load_rules() -> dict:
    try:
        with open(RULES_PATH) as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        return {}


async def get_audit_entries(count: int = 500) -> list[dict]:
    """Fetch recent audit entries."""
    try:
        result = await call_mcp_tool(AUDIT_URL, "get_recent_audit", {"count": count})
        text = result.get("text", "")
        if not text:
            return []
        entries = []
        for line in text.strip().split("\n"):
            if line.strip():
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        return entries
    except Exception as e:
        log.debug(f"Audit fetch failed: {e}")
    return []


async def post_proposal(pattern_key: str, count: int, examples: list[str],
                         proposed_rule: str):
    """Post a hardening proposal to Slack and create a GitHub PR."""
    # Create PR via github-mcp
    pr_result = await create_pr_via_github_mcp(proposed_rule, pattern_key)
    pr_url = pr_result.get("url", "")
    pr_number = pr_result.get("number", "?")

    if not SLACK_BOT_TOKEN or not SLACK_PROPOSALS_CHANNEL:
        log.info(f"PROPOSAL (no Slack): {pattern_key} ({count} occurrences) PR: {pr_url}")
        log.info(f"  Rule: {proposed_rule}")
        return

    examples_text = "\n".join(f"  • {e}" for e in examples[:5])
    pr_text = f"\n\n*PR:* <{pr_url}|#{pr_number}> — merge to approve, close to reject." if pr_url else ""
    try:
        async with httpx.AsyncClient() as client:
            await client.post(
                "https://slack.com/api/chat.postMessage",
                headers={
                    "Authorization": f"Bearer {SLACK_BOT_TOKEN}",
                    "Content-Type": "application/json",
                },
                json={
                    "channel": SLACK_PROPOSALS_CHANNEL,
                    "blocks": [
                        {
                            "type": "section",
                            "text": {
                                "type": "mrkdwn",
                                "text": (
                                    f"🔧 *Hardening Proposal*\n"
                                    f"*Pattern:* `{pattern_key}`\n"
                                    f"*Occurrences:* {count}\n\n"
                                    f"*Recent examples:*\n{examples_text}\n\n"
                                    f"*Proposed rule:*\n```{proposed_rule}```"
                                    f"{pr_text}"
                                ),
                            },
                        },
                        {
                            "type": "context",
                            "elements": [
                                {
                                    "type": "mrkdwn",
                                    "text": (
                                        "Merge the PR to approve this rule. "
                                        "Close it to reject."
                                    ),
                                }
                            ],
                        },
                    ],
                },
                timeout=10,
            )
    except Exception as e:
        log.error(f"Failed to post proposal: {e}")


def analyze_patterns(entries: list[dict]) -> list[dict]:
    """
    Level 1: Find repetitive patterns in audit entries.
    Returns list of candidate proposals for deterministic rules.
    """
    # Group by (agent_name, action) pairs
    pattern_counter: Counter = Counter()
    pattern_examples: dict[str, list[str]] = defaultdict(list)

    for entry in entries:
        if entry.get("event_type") != "AGENT_ACTION":
            continue

        agent = entry.get("agent_name", "unknown")
        action = entry.get("action", "unknown")
        details = entry.get("details", "")
        key = f"{agent}:{action}"

        pattern_counter[key] += 1
        if len(pattern_examples[key]) < 5:
            pattern_examples[key].append(details[:200])

    # Find patterns above threshold that we haven't proposed yet
    proposals = []
    for key, count in pattern_counter.most_common():
        if count >= PROPOSAL_THRESHOLD and key not in proposed_patterns:
            agent, action = key.split(":", 1)
            proposals.append({
                "pattern_key": key,
                "agent": agent,
                "action": action,
                "count": count,
                "examples": pattern_examples[key],
                "proposed_rule": (
                    f"# Auto-generated rule for {key}\n"
                    f"- pattern: \"{key}\"\n"
                    f"  agent: {agent}\n"
                    f"  action: {action}\n"
                    f"  occurrences: {count}\n"
                    f"  rule: \"deterministic\"  # Replace LLM decision\n"
                    f"  status: proposed  # Change to 'active' after approval"
                ),
            })

    return proposals


# ── Level 2: Failure Pattern Analysis ───────────────────

# Keywords that signal different failure root causes
FAILURE_CATEGORIES = {
    "empty_results": [
        "0 results", "no results", "found nothing", "no businesses",
        "nothing found", "returned 0", "empty", "none found",
    ],
    "wrong_results": [
        "churches", "cemeteries", "schools", "unrelated",
        "doesn't match", "wrong type", "irrelevant",
    ],
    "tool_failure": [
        "timeout", "connection refused", "500", "502", "503",
        "rate limit", "quota", "api error", "failed to call",
    ],
    "quality_issue": [
        "missing fields", "incomplete", "no url", "no email",
        "no address", "no name", "malformed", "invalid",
    ],
}


def categorize_failure(details: str) -> str:
    """Extract a root-cause category from failure details text."""
    details_lower = details.lower()
    for category, keywords in FAILURE_CATEGORIES.items():
        for kw in keywords:
            if kw in details_lower:
                return category
    return "uncategorized"


def analyze_failures(entries: list[dict]) -> list[dict]:
    """
    Level 2: Find failure patterns — errors, warnings, and rejections.
    Groups by (agent, failure_category) and proposes system message fixes.
    """
    failure_counter: Counter = Counter()
    failure_details: dict[str, list[dict]] = defaultdict(list)

    for entry in entries:
        if entry.get("event_type") != "AGENT_ACTION":
            continue

        severity = entry.get("severity", "info")
        action = entry.get("action", "")
        agent = entry.get("agent_name", "unknown")
        details = entry.get("details", "")

        # Capture errors/warnings and explicit rejections
        is_failure = severity in ("error", "warning", "critical")
        is_rejection = action in (
            "output_rejected", "result_rejected", "task_blocked",
            "validation_failed", "retry_requested",
        )

        if not (is_failure or is_rejection):
            continue

        category = categorize_failure(details)
        key = f"failure:{agent}:{category}"

        failure_counter[key] += 1
        if len(failure_details[key]) < 10:
            failure_details[key].append({
                "action": action,
                "details": details[:300],
                "severity": severity,
                "timestamp": entry.get("timestamp", ""),
            })

    # Generate proposals for recurring failures
    proposals = []
    for key, count in failure_counter.most_common():
        if count >= FAILURE_THRESHOLD and key not in proposed_failures:
            _, agent, category = key.split(":", 2)
            examples = failure_details[key]

            # Build a context-rich proposal
            example_summaries = "\n".join(
                f"  - [{e['severity']}] {e['action']}: {e['details'][:150]}"
                for e in examples[:5]
            )

            proposal_text = (
                f"# Failure pattern: {key}\n"
                f"# Detected {count} occurrences (threshold: {FAILURE_THRESHOLD})\n"
                f"#\n"
                f"# Root cause category: {category}\n"
                f"# Affected agent: {agent}\n"
                f"#\n"
                f"# Recent examples:\n"
                + "\n".join(f"#   {e['action']}: {e['details'][:120]}" for e in examples[:5])
                + "\n#\n"
                f"# RECOMMENDED FIX: Update {agent} system message to address this.\n"
                f"type: system_message_patch\n"
                f"agent: {agent}\n"
                f"failure_category: {category}\n"
                f"occurrences: {count}\n"
                f"status: proposed\n"
                f"recommendation: |\n"
                + _generate_recommendation(agent, category, examples)
            )

            proposals.append({
                "pattern_key": key,
                "agent": agent,
                "category": category,
                "count": count,
                "examples": [e["details"][:200] for e in examples[:5]],
                "proposed_rule": proposal_text,
                "is_failure": True,
            })

    return proposals


def _generate_recommendation(agent: str, category: str, examples: list[dict]) -> str:
    """Generate a human-readable recommendation based on failure category."""
    recs = {
        "empty_results": (
            f"  Add to {agent} system message:\n"
            f"  - If primary search method returns 0 results, try at least 2 alternative approaches before reporting failure.\n"
            f"  - Never accept 0 results for a category that obviously exists in the target area.\n"
            f"  - Log which search methods were tried and what each returned."
        ),
        "wrong_results": (
            f"  Add to {agent} system message:\n"
            f"  - Validate that results match the requested category before returning.\n"
            f"  - If results contain unrelated business types, filter them out and try more specific queries.\n"
            f"  - Quality check: does every result actually match what was asked for?"
        ),
        "tool_failure": (
            f"  Add to {agent} system message:\n"
            f"  - If a tool call fails (timeout, error), retry once with backoff.\n"
            f"  - If primary tool is unavailable, fall back to secondary tools.\n"
            f"  - Report tool failures explicitly so the issue can be diagnosed."
        ),
        "quality_issue": (
            f"  Add to {agent} system message:\n"
            f"  - Validate all required fields are present before returning results.\n"
            f"  - If key fields (name, URL, address) are missing, attempt to fill them with additional lookups.\n"
            f"  - Return partial results clearly marked as incomplete rather than silently omitting fields."
        ),
        "uncategorized": (
            f"  Review the failure examples above and add specific guardrails to {agent}'s system message.\n"
            f"  Consider: What instruction would have prevented this failure?"
        ),
    }
    return recs.get(category, recs["uncategorized"])


async def post_failure_proposal(pattern_key: str, count: int, agent: str,
                                 category: str, examples: list[str],
                                 proposed_rule: str):
    """Post a failure-pattern proposal to Slack and create a GitHub PR."""
    pr_result = await create_pr_via_github_mcp(proposed_rule, pattern_key)
    pr_url = pr_result.get("url", "")
    pr_number = pr_result.get("number", "?")

    if not SLACK_BOT_TOKEN or not SLACK_PROPOSALS_CHANNEL:
        log.info(f"FAILURE PROPOSAL (no Slack): {pattern_key} ({count}x) PR: {pr_url}")
        return

    examples_text = "\n".join(f"  • {e}" for e in examples[:5])
    pr_text = f"\n\n*PR:* <{pr_url}|#{pr_number}>" if pr_url else ""
    try:
        async with httpx.AsyncClient() as client:
            await client.post(
                "https://slack.com/api/chat.postMessage",
                headers={
                    "Authorization": f"Bearer {SLACK_BOT_TOKEN}",
                    "Content-Type": "application/json",
                },
                json={
                    "channel": SLACK_PROPOSALS_CHANNEL,
                    "blocks": [
                        {
                            "type": "section",
                            "text": {
                                "type": "mrkdwn",
                                "text": (
                                    f"🚨 *Failure Pattern Detected*\n"
                                    f"*Agent:* `{agent}`\n"
                                    f"*Category:* `{category}`\n"
                                    f"*Occurrences:* {count} (threshold: {FAILURE_THRESHOLD})\n\n"
                                    f"*Recent failures:*\n{examples_text}\n\n"
                                    f"*Recommended:* Update `{agent}` system message."
                                    f"{pr_text}"
                                ),
                            },
                        },
                        {
                            "type": "context",
                            "elements": [
                                {
                                    "type": "mrkdwn",
                                    "text": (
                                        "This is a Level 2 (failure analysis) proposal. "
                                        "Merge the PR to apply the fix."
                                    ),
                                }
                            ],
                        },
                    ],
                },
                timeout=10,
            )
    except Exception as e:
        log.error(f"Failed to post failure proposal: {e}")


async def analysis_loop():
    """Main loop — analyze patterns (Level 1) and failures (Level 2)."""
    log.info(
        f"Starting hardening analysis (interval={ANALYSIS_INTERVAL}s, "
        f"pattern_threshold={PROPOSAL_THRESHOLD}, failure_threshold={FAILURE_THRESHOLD})"
    )

    while True:
        try:
            entries = await get_audit_entries(500)
            if entries:
                # Level 1: Frequency-based pattern proposals
                proposals = analyze_patterns(entries)
                for p in proposals:
                    log.info(
                        f"L1 Proposing hardening rule: {p['pattern_key']} "
                        f"({p['count']} occurrences)"
                    )
                    await post_proposal(
                        p["pattern_key"],
                        p["count"],
                        p["examples"],
                        p["proposed_rule"],
                    )
                    proposed_patterns.add(p["pattern_key"])

                # Level 2: Failure pattern analysis
                failure_proposals = analyze_failures(entries)
                for fp in failure_proposals:
                    log.info(
                        f"L2 Failure pattern: {fp['pattern_key']} "
                        f"({fp['count']}x, category={fp['category']})"
                    )
                    await post_failure_proposal(
                        fp["pattern_key"],
                        fp["count"],
                        fp["agent"],
                        fp["category"],
                        fp["examples"],
                        fp["proposed_rule"],
                    )
                    proposed_failures.add(fp["pattern_key"])

                total_proposals = len(proposals) + len(failure_proposals)
                if total_proposals == 0:
                    log.info(
                        f"No new patterns. Analyzed {len(entries)} entries. "
                        f"(L1 threshold={PROPOSAL_THRESHOLD}, L2 threshold={FAILURE_THRESHOLD})"
                    )
        except Exception as e:
            log.error(f"Analysis error: {e}")

        await asyncio.sleep(ANALYSIS_INTERVAL)


# ── MCP Tools ────────────────────────────────────────────

@mcp.tool()
async def get_patterns() -> str:
    """
    Get current decision patterns detected across all agents.
    Shows frequency of each (agent, action) pair.
    """
    entries = await get_audit_entries(500)
    counter: Counter = Counter()
    for entry in entries:
        if entry.get("event_type") == "AGENT_ACTION":
            agent = entry.get("agent_name", "unknown")
            action = entry.get("action", "unknown")
            counter[f"{agent}:{action}"] += 1

    result = {
        "total_entries_analyzed": len(entries),
        "patterns": [
            {"pattern": k, "count": v} for k, v in counter.most_common(20)
        ],
        "proposal_threshold": PROPOSAL_THRESHOLD,
        "already_proposed": list(proposed_patterns),
    }
    return json.dumps(result, indent=2)


@mcp.tool()
async def get_failure_patterns() -> str:
    """
    Get failure patterns detected across all agents.
    Shows recurring errors, warnings, and output rejections grouped by
    (agent, failure_category). These drive Level 2 system message fix proposals.
    """
    entries = await get_audit_entries(500)

    failure_counter: Counter = Counter()
    failure_examples: dict[str, list[str]] = defaultdict(list)

    for entry in entries:
        if entry.get("event_type") != "AGENT_ACTION":
            continue
        severity = entry.get("severity", "info")
        action = entry.get("action", "")
        agent = entry.get("agent_name", "unknown")
        details = entry.get("details", "")

        is_failure = severity in ("error", "warning", "critical")
        is_rejection = action in (
            "output_rejected", "result_rejected", "task_blocked",
            "validation_failed", "retry_requested",
        )
        if not (is_failure or is_rejection):
            continue

        category = categorize_failure(details)
        key = f"{agent}:{category}"
        failure_counter[key] += 1
        if len(failure_examples[key]) < 3:
            failure_examples[key].append(details[:200])

    result = {
        "total_entries_analyzed": len(entries),
        "failure_patterns": [
            {
                "agent_category": k,
                "count": v,
                "examples": failure_examples[k],
            }
            for k, v in failure_counter.most_common(20)
        ],
        "failure_threshold": FAILURE_THRESHOLD,
        "already_proposed": list(proposed_failures),
    }
    return json.dumps(result, indent=2)


@mcp.tool()
async def get_active_rules() -> str:
    """Get the current set of approved hardening rules."""
    rules = load_rules()
    return yaml.dump(rules, default_flow_style=False) if rules else "No active rules yet."


# ── Entry point ──────────────────────────────────────────

async def main():
    import uvicorn

    PORT = int(os.getenv("HARDENING_MCP_PORT", "8094"))
    mcp_app = mcp.streamable_http_app()
    config = uvicorn.Config(mcp_app, host="0.0.0.0", port=PORT, log_level="info")
    server = uvicorn.Server(config)

    await asyncio.gather(
        analysis_loop(),
        server.serve(),
    )


if __name__ == "__main__":
    import anyio

    anyio.run(main)
