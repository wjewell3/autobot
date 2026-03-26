"""
hardening-agent.py — Watches agent decision patterns and proposes
deterministic rules to replace repetitive LLM decisions.

This is the compounding mechanism. Over time, the LLM surface shrinks
and the deterministic surface grows.

How it works:
  1. Reads audit log entries periodically
  2. Groups similar agent actions by (agent, action_type) pairs
  3. When a pattern exceeds threshold (e.g., same decision 10+ times),
     proposes a deterministic rule
  4. Posts proposals to #hardening-proposals Slack channel
  5. Human approves/rejects in Slack
  6. Approved rules get added to a rules ConfigMap

v1 is intentionally dumb — it just counts frequencies and proposes.
No ML, no embeddings, no complexity. Start the compounding early.
"""

import asyncio
import json
import logging
import os
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

mcp = FastMCP(
    "hardening-agent",
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)

# Track which patterns we've already proposed (avoid spam)
proposed_patterns: set[str] = set()


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
    Find repetitive patterns in audit entries.
    Returns list of candidate proposals.
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


async def analysis_loop():
    """Main loop — analyze patterns and propose rules."""
    log.info(
        f"Starting hardening analysis (interval={ANALYSIS_INTERVAL}s, "
        f"threshold={PROPOSAL_THRESHOLD})"
    )

    while True:
        try:
            entries = await get_audit_entries(500)
            if entries:
                proposals = analyze_patterns(entries)
                for p in proposals:
                    log.info(
                        f"Proposing hardening rule: {p['pattern_key']} "
                        f"({p['count']} occurrences)"
                    )
                    await post_proposal(
                        p["pattern_key"],
                        p["count"],
                        p["examples"],
                        p["proposed_rule"],
                    )
                    proposed_patterns.add(p["pattern_key"])

                if not proposals:
                    log.info(
                        f"No new patterns above threshold ({PROPOSAL_THRESHOLD}). "
                        f"Analyzed {len(entries)} entries."
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
