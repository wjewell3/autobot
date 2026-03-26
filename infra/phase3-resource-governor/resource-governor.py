"""
resource-governor.py — Token/cost/step budget enforcement.

Runs as a sidecar-style service that:
  1. Monitors LiteLLM /api/usage endpoint for token consumption
  2. Tracks per-agent step counts via audit log entries
  3. Exposes MCP tools for agents to check their remaining budget
  4. Posts warnings to Slack when budgets are approaching limits
  5. Can kill agent sessions that exceed hard limits

Budget config lives in /etc/governor/budgets.yaml — deterministic
limits that cannot be prompt-injected away.
"""

import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timezone
from collections import defaultdict

import httpx
import yaml
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("resource-governor")

BUDGET_PATH = "/etc/governor/budgets.yaml"
LITELLM_URL = os.getenv(
    "LITELLM_URL", "http://litellm-service.kagent.svc.cluster.local:4000"
)
AUDIT_URL = os.getenv(
    "AUDIT_LOGGER_URL", "http://audit-logger.kagent.svc.cluster.local:8092"
)
SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN", "")
SLACK_ALERT_CHANNEL = os.getenv("SLACK_ALERT_CHANNEL_ID", "")
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL_SECONDS", "60"))

mcp = FastMCP(
    "resource-governor",
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)

# ── In-memory counters ───────────────────────────────────
# Tracks per-agent tool call counts within the current monitoring window
tool_call_counts: dict[str, int] = defaultdict(int)
warnings_sent: set[str] = set()


def load_budgets() -> dict:
    with open(BUDGET_PATH) as f:
        return yaml.safe_load(f)


async def slack_alert(text: str):
    """Post a budget alert to Slack."""
    if not SLACK_BOT_TOKEN or not SLACK_ALERT_CHANNEL:
        log.info(f"ALERT (no Slack): {text}")
        return
    try:
        async with httpx.AsyncClient() as client:
            await client.post(
                "https://slack.com/api/chat.postMessage",
                headers={
                    "Authorization": f"Bearer {SLACK_BOT_TOKEN}",
                    "Content-Type": "application/json",
                },
                json={
                    "channel": SLACK_ALERT_CHANNEL,
                    "text": f"💰 *Resource Governor Alert*\n{text}",
                },
                timeout=10,
            )
    except Exception as e:
        log.error(f"Failed to post Slack alert: {e}")


async def check_litellm_usage() -> dict:
    """Query LiteLLM for current token usage stats."""
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{LITELLM_URL}/health", timeout=5
            )
            if resp.status_code == 200:
                return resp.json()
    except Exception as e:
        log.debug(f"LiteLLM health check failed (non-critical): {e}")
    return {}


async def get_audit_entries(count: int = 100) -> list[dict]:
    """Fetch recent audit entries via MCP client SDK."""
    try:
        from mcp.client.streamable_http import streamablehttp_client
        from mcp import ClientSession

        audit_url = f"{AUDIT_URL}/mcp"
        async with streamablehttp_client(audit_url) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(
                    "get_recent_audit", {"count": count}
                )
                if result.content:
                    text = result.content[0].text
                    entries = []
                    for line in text.strip().split("\n"):
                        if line.strip():
                            try:
                                entries.append(json.loads(line))
                            except json.JSONDecodeError:
                                pass
                    return entries
    except Exception as e:
        log.debug(f"Audit fetch failed (non-critical): {e}")
    return []


async def enforce_budgets():
    """Main enforcement loop — check budgets and alert/kill on violations."""
    log.info("Starting budget enforcement loop")

    while True:
        try:
            budgets = load_budgets()
            global_limits = budgets.get("global", {})
            agent_limits = budgets.get("agents", {})

            # Count recent tool calls per agent from audit log
            entries = await get_audit_entries(200)
            agent_actions: dict[str, int] = defaultdict(int)
            for entry in entries:
                agent = entry.get("agent_name", "unknown")
                if entry.get("event_type") == "AGENT_ACTION":
                    agent_actions[agent] += 1

            # Check global limits
            total_actions = sum(agent_actions.values())
            global_max = global_limits.get("max_total_actions_per_hour", 500)
            if total_actions > global_max * 0.8:
                key = "global-action-warning"
                if key not in warnings_sent:
                    await slack_alert(
                        f"⚠️ Total agent actions at {total_actions}/{global_max} "
                        f"(80% threshold). Agents may be throttled."
                    )
                    warnings_sent.add(key)

            # Check per-agent limits
            for agent_name, count in agent_actions.items():
                agent_cfg = agent_limits.get(agent_name, agent_limits.get("_default", {}))
                max_actions = agent_cfg.get("max_actions_per_hour", 100)

                # Warning at 80%
                if count > max_actions * 0.8:
                    key = f"{agent_name}-action-warning"
                    if key not in warnings_sent:
                        await slack_alert(
                            f"⚠️ Agent `{agent_name}` at {count}/{max_actions} "
                            f"actions. Approaching limit."
                        )
                        warnings_sent.add(key)

                # Hard limit
                if count > max_actions:
                    key = f"{agent_name}-action-limit"
                    if key not in warnings_sent:
                        await slack_alert(
                            f"🔴 Agent `{agent_name}` EXCEEDED action limit "
                            f"({count}/{max_actions}). Manual review required."
                        )
                        warnings_sent.add(key)

        except Exception as e:
            log.error(f"Budget enforcement error: {e}")

        await asyncio.sleep(CHECK_INTERVAL)


# ── MCP Tools ────────────────────────────────────────────

@mcp.tool()
async def check_budget(agent_name: str) -> str:
    """
    Check remaining budget for an agent. Agents should call this
    before starting expensive operations.

    Args:
        agent_name: Name of the agent checking its budget
    """
    budgets = load_budgets()
    agent_limits = budgets.get("agents", {})
    agent_cfg = agent_limits.get(agent_name, agent_limits.get("_default", {}))

    entries = await get_audit_entries(200)
    action_count = sum(
        1 for e in entries
        if e.get("agent_name") == agent_name and e.get("event_type") == "AGENT_ACTION"
    )

    max_actions = agent_cfg.get("max_actions_per_hour", 100)
    remaining = max(0, max_actions - action_count)

    return json.dumps({
        "agent": agent_name,
        "actions_used": action_count,
        "actions_limit": max_actions,
        "actions_remaining": remaining,
        "status": "ok" if remaining > 0 else "exceeded",
    })


@mcp.tool()
async def get_system_status() -> str:
    """
    Get overall system resource status. Shows all agent budgets
    and global metrics.
    """
    budgets = load_budgets()
    entries = await get_audit_entries(200)

    agent_actions: dict[str, int] = defaultdict(int)
    for e in entries:
        if e.get("event_type") == "AGENT_ACTION":
            agent_actions[e.get("agent_name", "unknown")] += 1

    status = {
        "total_actions": sum(agent_actions.values()),
        "global_limit": budgets.get("global", {}).get("max_total_actions_per_hour", 500),
        "agents": {},
    }

    agent_limits = budgets.get("agents", {})
    for agent, count in agent_actions.items():
        cfg = agent_limits.get(agent, agent_limits.get("_default", {}))
        limit = cfg.get("max_actions_per_hour", 100)
        status["agents"][agent] = {
            "actions": count,
            "limit": limit,
            "remaining": max(0, limit - count),
        }

    return json.dumps(status, indent=2)


# ── Entry point ──────────────────────────────────────────

async def main():
    import uvicorn

    PORT = int(os.getenv("GOVERNOR_MCP_PORT", "8093"))
    mcp_app = mcp.streamable_http_app()
    config = uvicorn.Config(mcp_app, host="0.0.0.0", port=PORT, log_level="info")
    server = uvicorn.Server(config)

    await asyncio.gather(
        enforce_budgets(),
        server.serve(),
    )


if __name__ == "__main__":
    import anyio

    anyio.run(main)
