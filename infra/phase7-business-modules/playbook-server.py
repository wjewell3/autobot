"""
playbook-server.py — Business module abstraction layer.

Decouples agents from any specific business model. Instead of hardcoding
"plumbers in Chattanooga" into PM/worker system messages, agents call
this server to get their current playbook configuration.

To switch business models: update playbooks.yaml, change active_playbook.
No agent system messages need to change.

MCP Tools:
  - get_playbook() → returns the full active playbook config
  - get_stage_config(stage) → returns config for a specific pipeline stage
  - list_playbooks() → shows all available playbooks
  - switch_playbook(name) → changes the active playbook (requires HITL)
  - get_niche_rotation() → returns prospecting niche list for current playbook
  - get_qualification_rules() → returns HOT/WARM/COLD definitions
"""

import json
import logging
import os
import sys
from pathlib import Path

import yaml
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("playbook-server")

PLAYBOOKS_PATH = os.getenv("PLAYBOOKS_PATH", "/etc/playbooks/playbooks.yaml")
PORT = int(os.getenv("PLAYBOOK_SERVER_PORT", "8099"))

mcp = FastMCP(
    "playbook-server",
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)


def load_playbooks() -> dict:
    try:
        with open(PLAYBOOKS_PATH) as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        log.error(f"Playbooks file not found: {PLAYBOOKS_PATH}")
        return {}


def get_active() -> dict:
    data = load_playbooks()
    active_name = data.get("active_playbook", "")
    playbooks = data.get("playbooks", {})
    return playbooks.get(active_name, {}), active_name


# ── MCP Tools ────────────────────────────────────────────

@mcp.tool()
async def get_playbook() -> str:
    """
    Get the full active playbook configuration.
    Returns the complete playbook including prospecting rules,
    building config, outreach config, and success metrics.
    """
    playbook, name = get_active()
    if not playbook:
        return json.dumps({"error": "No active playbook configured"})
    return json.dumps({
        "active_playbook": name,
        "config": playbook,
    }, indent=2)


@mcp.tool()
async def get_stage_config(stage: str) -> str:
    """
    Get configuration for a specific pipeline stage.

    Args:
        stage: One of "prospecting", "building", "outreach", "metrics"
    """
    playbook, name = get_active()
    if not playbook:
        return json.dumps({"error": "No active playbook configured"})
    config = playbook.get(stage)
    if not config:
        available = [k for k in playbook.keys() if k not in ("name", "description", "version", "default_market")]
        return json.dumps({"error": f"Stage '{stage}' not found. Available: {available}"})
    return json.dumps({
        "playbook": name,
        "stage": stage,
        "default_market": playbook.get("default_market", {}),
        "config": config,
    }, indent=2)


@mcp.tool()
async def list_playbooks() -> str:
    """List all available playbooks with name, description, and active status."""
    data = load_playbooks()
    active_name = data.get("active_playbook", "")
    playbooks = data.get("playbooks", {})
    result = []
    for key, pb in playbooks.items():
        result.append({
            "id": key,
            "name": pb.get("name", key),
            "description": pb.get("description", ""),
            "version": pb.get("version", "0.0"),
            "active": key == active_name,
        })
    return json.dumps(result, indent=2)


@mcp.tool()
async def switch_playbook(name: str) -> str:
    """
    Switch the active playbook. Requires updating the ConfigMap.
    Returns the new playbook config for verification.

    NOTE: This only returns what WOULD change. The actual switch requires
    updating the ConfigMap and restarting. Use this to preview before switching.

    Args:
        name: Playbook ID to switch to (e.g. "saas-landing-pages")
    """
    data = load_playbooks()
    playbooks = data.get("playbooks", {})
    if name not in playbooks:
        available = list(playbooks.keys())
        return json.dumps({"error": f"Playbook '{name}' not found. Available: {available}"})

    new_playbook = playbooks[name]
    return json.dumps({
        "action": "switch_playbook",
        "from": data.get("active_playbook", ""),
        "to": name,
        "new_config": new_playbook,
        "instructions": (
            "To apply: update playbooks.yaml active_playbook field, "
            "recreate the ConfigMap, and restart the playbook-server pod."
        ),
    }, indent=2)


@mcp.tool()
async def get_niche_rotation() -> str:
    """
    Get the niche rotation list for the current playbook's prospecting stage.
    PM-agent calls this instead of hardcoding niches.
    """
    playbook, name = get_active()
    prospecting = playbook.get("prospecting", {})
    return json.dumps({
        "playbook": name,
        "niches": prospecting.get("niche_rotation", []),
        "max_niches_before_block": prospecting.get("max_niches_before_block", 3),
        "min_leads_to_proceed": prospecting.get("min_leads_to_proceed", 1),
    }, indent=2)


@mcp.tool()
async def get_qualification_rules() -> str:
    """
    Get HOT/WARM/COLD qualification rules for the current playbook.
    Prospecting-agent calls this instead of hardcoding classification logic.
    """
    playbook, name = get_active()
    prospecting = playbook.get("prospecting", {})
    return json.dumps({
        "playbook": name,
        "qualification": prospecting.get("qualification", {}),
        "search_strategy": prospecting.get("search_strategy", ""),
        "method": prospecting.get("method", ""),
    }, indent=2)


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
