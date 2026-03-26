"""
audit-logger.py — Independent audit trail for all agent activity.

Watches Agent CRs and logs every create/update/delete with full spec.
Also exposes MCP tools so agents can write structured audit entries.

Writes to:
  - stdout (kubectl logs)
  - /audit/audit.jsonl (persistent volume, one JSON object per line)
  - Slack #audit-log channel (if configured)

This is the "eyes" layer — gives you full visibility before
increasing agent autonomy.
"""

import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timezone

import httpx

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("audit-logger")

NAMESPACE = os.getenv("WATCH_NAMESPACE", "kagent")
K8S_API = "https://kubernetes.default.svc"
SA_TOKEN_PATH = "/var/run/secrets/kubernetes.io/serviceaccount/token"
SA_CA_PATH = "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"
AUDIT_DIR = os.getenv("AUDIT_DIR", "/audit")
AUDIT_FILE = os.path.join(AUDIT_DIR, "audit.jsonl")
SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN", "")
SLACK_AUDIT_CHANNEL = os.getenv("SLACK_AUDIT_CHANNEL_ID", "")

# Also expose as MCP server for agents to write structured audit entries
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

mcp = FastMCP(
    "audit-logger",
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)


def get_k8s_headers() -> dict:
    with open(SA_TOKEN_PATH) as f:
        token = f.read().strip()
    return {"Authorization": f"Bearer {token}"}


def write_audit_entry(entry: dict):
    """Append a JSON audit entry to the log file and stdout."""
    entry["timestamp"] = datetime.now(timezone.utc).isoformat()
    line = json.dumps(entry, default=str)

    # Write to file
    try:
        os.makedirs(AUDIT_DIR, exist_ok=True)
        with open(AUDIT_FILE, "a") as f:
            f.write(line + "\n")
    except Exception as e:
        log.error(f"Failed to write audit file: {e}")

    # Write to stdout (shows in kubectl logs)
    log.info(f"AUDIT: {line}")


async def post_to_slack(entry: dict):
    """Post audit entry to Slack #audit-log channel."""
    if not SLACK_BOT_TOKEN or not SLACK_AUDIT_CHANNEL:
        return

    event_type = entry.get("event_type", "unknown")
    agent_name = entry.get("agent_name", "unknown")
    emoji = {"CREATED": "🟢", "MODIFIED": "🟡", "DELETED": "🔴"}.get(event_type, "⚪")

    text = f"{emoji} *{event_type}* `{agent_name}`"
    if entry.get("changes"):
        text += f"\nChanges: {entry['changes']}"

    try:
        async with httpx.AsyncClient() as client:
            await client.post(
                "https://slack.com/api/chat.postMessage",
                headers={
                    "Authorization": f"Bearer {SLACK_BOT_TOKEN}",
                    "Content-Type": "application/json",
                },
                json={
                    "channel": SLACK_AUDIT_CHANNEL,
                    "blocks": [
                        {
                            "type": "section",
                            "text": {"type": "mrkdwn", "text": text},
                        },
                        {
                            "type": "context",
                            "elements": [
                                {
                                    "type": "mrkdwn",
                                    "text": f"Audit ID: `{entry.get('id', 'n/a')}` | {entry.get('timestamp', '')}",
                                }
                            ],
                        },
                    ],
                },
                timeout=10,
            )
    except Exception as e:
        log.error(f"Failed to post audit to Slack: {e}")


def diff_agents(old_spec: dict, new_spec: dict) -> list[str]:
    """Return list of human-readable changes between two agent specs."""
    changes = []
    old_tools = {
        json.dumps(t, sort_keys=True)
        for t in old_spec.get("declarative", {}).get("tools", [])
    }
    new_tools = {
        json.dumps(t, sort_keys=True)
        for t in new_spec.get("declarative", {}).get("tools", [])
    }

    added_tools = new_tools - old_tools
    removed_tools = old_tools - new_tools
    if added_tools:
        changes.append(f"tools added: {len(added_tools)}")
    if removed_tools:
        changes.append(f"tools removed: {len(removed_tools)}")

    old_msg = old_spec.get("declarative", {}).get("systemMessage", "")
    new_msg = new_spec.get("declarative", {}).get("systemMessage", "")
    if old_msg != new_msg:
        changes.append("systemMessage changed")

    old_desc = old_spec.get("description", "")
    new_desc = new_spec.get("description", "")
    if old_desc != new_desc:
        changes.append(f"description: '{old_desc}' → '{new_desc}'")

    return changes


async def watch_agents():
    """Watch Agent CRs via K8s watch API and log all changes."""
    log.info(f"Starting agent watcher for namespace '{NAMESPACE}'")
    url = (
        f"{K8S_API}/apis/kagent.dev/v1alpha2/namespaces/{NAMESPACE}/agents"
        f"?watch=true"
    )

    # Track last-seen specs to compute diffs on MODIFIED
    last_seen: dict[str, dict] = {}

    while True:
        try:
            async with httpx.AsyncClient(verify=SA_CA_PATH) as client:
                async with client.stream(
                    "GET", url, headers=get_k8s_headers(), timeout=None
                ) as resp:
                    async for line in resp.aiter_lines():
                        if not line.strip():
                            continue
                        try:
                            event = json.loads(line)
                        except json.JSONDecodeError:
                            continue

                        event_type = event.get("type", "UNKNOWN")
                        obj = event.get("object", {})
                        agent_name = obj.get("metadata", {}).get("name", "unknown")
                        spec = obj.get("spec", {})
                        generation = obj.get("metadata", {}).get("generation", 0)

                        entry = {
                            "id": f"{agent_name}-gen{generation}-{event_type.lower()}",
                            "event_type": event_type,
                            "agent_name": agent_name,
                            "generation": generation,
                            "labels": obj.get("metadata", {}).get("labels", {}),
                        }

                        if event_type == "ADDED":
                            entry["tools"] = [
                                summarize_tool(t)
                                for t in spec.get("declarative", {}).get("tools", [])
                            ]
                            last_seen[agent_name] = spec

                        elif event_type == "MODIFIED":
                            old_spec = last_seen.get(agent_name, {})
                            changes = diff_agents(old_spec, spec)
                            entry["changes"] = changes
                            entry["tools"] = [
                                summarize_tool(t)
                                for t in spec.get("declarative", {}).get("tools", [])
                            ]
                            last_seen[agent_name] = spec

                        elif event_type == "DELETED":
                            last_seen.pop(agent_name, None)

                        write_audit_entry(entry)
                        await post_to_slack(entry)

        except Exception as e:
            log.error(f"Watch connection failed: {e}, reconnecting in 5s...")
            await asyncio.sleep(5)


def summarize_tool(tool: dict) -> str:
    """Return a compact string representation of a tool."""
    if tool.get("type") == "McpServer":
        mcp_info = tool.get("mcpServer", {})
        name = mcp_info.get("name", "?")
        tools = mcp_info.get("toolNames", [])
        return f"mcp:{name}/{','.join(tools)}"
    elif tool.get("type") == "Agent":
        return f"a2a:{tool.get('agent', {}).get('name', '?')}"
    return f"unknown:{tool.get('type', '?')}"


# ── MCP Tools (so agents can write audit entries) ────────

@mcp.tool()
async def write_audit(
    agent_name: str,
    action: str,
    details: str,
    severity: str = "info",
) -> str:
    """
    Write a structured audit entry. Use this to log important decisions,
    tool calls, or state changes.

    Args:
        agent_name: Name of the agent writing the entry
        action:     What happened (e.g. "created_repo", "sent_email", "searched_businesses")
        details:    Human-readable description of what was done
        severity:   "info" | "warning" | "error" | "critical"
    """
    entry = {
        "id": f"agent-{agent_name}-{action}-{datetime.now(timezone.utc).strftime('%H%M%S')}",
        "event_type": "AGENT_ACTION",
        "agent_name": agent_name,
        "action": action,
        "details": details,
        "severity": severity,
    }
    write_audit_entry(entry)
    await post_to_slack(entry)
    return f"Audit entry logged: {entry['id']}"


@mcp.tool()
async def get_recent_audit(count: int = 20) -> str:
    """
    Return the most recent audit entries.

    Args:
        count: Number of recent entries to return (max 100)
    """
    count = min(count, 100)
    try:
        with open(AUDIT_FILE) as f:
            lines = f.readlines()
        recent = lines[-count:] if len(lines) > count else lines
        return "\n".join(line.strip() for line in recent)
    except FileNotFoundError:
        return "No audit entries yet."


# ── REST API (for dashboard — no MCP protocol needed) ────

from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route


async def rest_get_entries(request):
    """GET /entries?count=50&offset=0&agent=&type= — return audit entries as JSON."""
    count = min(int(request.query_params.get("count", "50")), 500)
    offset = int(request.query_params.get("offset", "0"))
    agent_filter = request.query_params.get("agent", "")
    type_filter = request.query_params.get("type", "")

    try:
        with open(AUDIT_FILE) as f:
            lines = f.readlines()
    except FileNotFoundError:
        return JSONResponse({"entries": [], "total": 0})

    entries = []
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if agent_filter and entry.get("agent_name", "") != agent_filter:
            continue
        if type_filter and entry.get("event_type", "") != type_filter:
            continue
        entries.append(entry)

    total = len(entries)
    entries = entries[offset:offset + count]
    return JSONResponse({"entries": entries, "total": total})


async def rest_get_stats(request):
    """GET /stats — summary stats for the dashboard."""
    try:
        with open(AUDIT_FILE) as f:
            lines = f.readlines()
    except FileNotFoundError:
        return JSONResponse({"total_entries": 0, "agents": {}, "event_types": {}})

    agents = {}
    event_types = {}
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        agent = entry.get("agent_name", "unknown")
        etype = entry.get("event_type", "unknown")
        agents[agent] = agents.get(agent, 0) + 1
        event_types[etype] = event_types.get(etype, 0) + 1

    return JSONResponse({
        "total_entries": len(lines),
        "agents": agents,
        "event_types": event_types,
    })


async def rest_health(request):
    return JSONResponse({"status": "ok"})


rest_app = Starlette(routes=[
    Route("/entries", rest_get_entries),
    Route("/stats", rest_get_stats),
    Route("/health", rest_health),
])


# ── Entry point ──────────────────────────────────────────

async def main():
    """Run the K8s watcher, MCP server, and REST API concurrently."""
    import uvicorn

    MCP_PORT = int(os.getenv("AUDIT_MCP_PORT", "8092"))
    REST_PORT = int(os.getenv("AUDIT_REST_PORT", "8093"))

    mcp_app = mcp.streamable_http_app()
    mcp_config = uvicorn.Config(mcp_app, host="0.0.0.0", port=MCP_PORT, log_level="info")
    mcp_server = uvicorn.Server(mcp_config)

    rest_config = uvicorn.Config(rest_app, host="0.0.0.0", port=REST_PORT, log_level="info")
    rest_server = uvicorn.Server(rest_config)

    # Run all three concurrently
    await asyncio.gather(
        watch_agents(),
        mcp_server.serve(),
        rest_server.serve(),
    )


if __name__ == "__main__":
    import anyio

    anyio.run(main)
