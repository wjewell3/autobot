"""
rules-engine.py — Runtime execution of approved hardening rules.

This is the missing piece that makes the hardening loop compound.
The hardening-agent PROPOSES rules. This engine EXECUTES them.

Architecture:
  - Loads approved rules from /etc/rules-engine/rules.yaml (ConfigMap)
  - Exposes MCP tools that agents call BEFORE making decisions
  - If a matching active rule exists → return deterministic answer (skip LLM)
  - If shadow rule exists → return LLM answer but log comparison
  - Tracks rule hit/miss rates for measurement
  - Watches rules file for hot-reload (no restart needed)

Rule lifecycle:
  proposed → shadow → active → retired
  - proposed: visible in get_active_rules, not executed
  - shadow: executed alongside LLM, output compared, logged
  - active: replaces LLM decision entirely
  - retired: no longer matched

MCP Tools:
  - check_rule(agent, action, context) → {matched, rule_id, output} or {matched: false}
  - get_rule_stats() → hit/miss rates per rule
  - reload_rules() → force reload from ConfigMap
"""

import asyncio
import json
import logging
import os
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("rules-engine")

RULES_PATH = os.getenv("RULES_PATH", "/etc/rules-engine/rules.yaml")
PORT = int(os.getenv("RULES_ENGINE_PORT", "8095"))
AUDIT_URL = os.getenv(
    "AUDIT_LOGGER_URL", "http://audit-logger.kagent.svc.cluster.local:8092"
)

mcp = FastMCP(
    "rules-engine",
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)

# ── Rule Store ───────────────────────────────────────────

rules: list[dict] = []
rules_mtime: float = 0.0

# Stats tracking
rule_stats: dict[str, dict[str, int]] = defaultdict(lambda: {
    "hits": 0,
    "misses": 0,
    "shadow_matches": 0,
    "shadow_mismatches": 0,
    "last_hit": None,
})


def load_rules_from_disk() -> list[dict]:
    """Load rules from the YAML file. Returns empty list on error."""
    global rules, rules_mtime
    try:
        p = Path(RULES_PATH)
        if not p.exists():
            log.warning(f"Rules file not found: {RULES_PATH}")
            return []
        mtime = p.stat().st_mtime
        if mtime == rules_mtime:
            return rules  # No change
        with open(RULES_PATH) as f:
            data = yaml.safe_load(f) or {}
        rules = data.get("rules", [])
        rules_mtime = mtime
        active = sum(1 for r in rules if r.get("status") == "active")
        shadow = sum(1 for r in rules if r.get("status") == "shadow")
        log.info(f"Loaded {len(rules)} rules ({active} active, {shadow} shadow)")
        return rules
    except Exception as e:
        log.error(f"Failed to load rules: {e}")
        return rules  # Return last good set


def match_rule(agent: str, action: str, context: dict) -> dict | None:
    """Find the first matching rule for this agent+action+context."""
    for rule in rules:
        status = rule.get("status", "proposed")
        if status not in ("active", "shadow"):
            continue

        # Match by agent + action pattern
        rule_pattern = rule.get("pattern", "")
        if ":" in rule_pattern:
            rule_agent, rule_action = rule_pattern.split(":", 1)
            if rule_agent != agent or rule_action != action:
                continue
        elif rule.get("agent") != agent or rule.get("action") != action:
            continue

        # Optional: match context conditions
        conditions = rule.get("conditions", {})
        if conditions:
            match = True
            for key, expected in conditions.items():
                actual = context.get(key)
                if isinstance(expected, list):
                    if actual not in expected:
                        match = False
                        break
                elif actual != expected:
                    match = False
                    break
            if not match:
                continue

        return rule

    return None


def execute_rule(rule: dict, context: dict) -> dict:
    """Execute a matched rule and return the deterministic output."""
    rule_type = rule.get("rule_type", "deterministic")
    rule_id = rule.get("id", rule.get("pattern", "unknown"))

    if rule_type == "template":
        # Template substitution — replace ${var} with context values
        template = rule.get("template", "")
        output = template
        for key, val in context.items():
            output = output.replace(f"${{{key}}}", str(val))
        return {"output": output, "rule_id": rule_id, "rule_type": "template"}

    elif rule_type == "fixed_response":
        return {
            "output": rule.get("response", ""),
            "rule_id": rule_id,
            "rule_type": "fixed_response",
        }

    elif rule_type == "decision_table":
        # Walk a decision table: list of {conditions: {}, output: "..."}
        for row in rule.get("table", []):
            row_conditions = row.get("conditions", {})
            match = True
            for key, expected in row_conditions.items():
                if context.get(key) != expected:
                    match = False
                    break
            if match:
                return {
                    "output": row.get("output", ""),
                    "rule_id": rule_id,
                    "rule_type": "decision_table",
                }
        return None  # No matching row

    elif rule_type == "deterministic":
        # Generic deterministic — just return the configured output
        return {
            "output": rule.get("output", rule.get("deterministic_action", "")),
            "rule_id": rule_id,
            "rule_type": "deterministic",
        }

    return None


async def write_audit(agent: str, action: str, details: str, severity: str = "info"):
    """Write an audit entry via the audit-logger MCP."""
    try:
        from mcp.client.streamable_http import streamablehttp_client
        from mcp import ClientSession

        async with streamablehttp_client(f"{AUDIT_URL}/mcp") as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                await session.call_tool("write_audit", {
                    "agent_name": "rules-engine",
                    "action": action,
                    "details": details,
                    "severity": severity,
                })
    except Exception as e:
        log.debug(f"Audit write failed: {e}")


# ── MCP Tools ────────────────────────────────────────────

@mcp.tool()
async def check_rule(agent: str, action: str, context: str = "{}") -> str:
    """
    Check if a deterministic rule exists for this agent+action+context.

    Call this BEFORE making an LLM decision. If matched=true, use the
    returned output instead of calling the LLM. This is how the hardening
    loop compounds — approved rules skip the LLM entirely.

    Args:
        agent: Agent name (e.g. "prospecting-agent")
        action: Action being taken (e.g. "classify_lead", "search_query")
        context: JSON string with decision context (e.g. {"niche": "plumbers", "city": "Chattanooga"})

    Returns:
        JSON with {matched, rule_id, status, output} or {matched: false}
    """
    load_rules_from_disk()  # Hot-reload check

    try:
        ctx = json.loads(context) if isinstance(context, str) else context
    except json.JSONDecodeError:
        ctx = {}

    rule = match_rule(agent, action, ctx)

    if rule is None:
        rule_stats["_global"]["misses"] += 1
        return json.dumps({"matched": False})

    status = rule.get("status", "proposed")
    rule_id = rule.get("id", rule.get("pattern", "unknown"))

    result = execute_rule(rule, ctx)
    if result is None:
        rule_stats[rule_id]["misses"] += 1
        return json.dumps({"matched": False})

    if status == "active":
        rule_stats[rule_id]["hits"] += 1
        rule_stats[rule_id]["last_hit"] = datetime.now(timezone.utc).isoformat()

        await write_audit(
            agent, "rule_executed",
            f"Rule '{rule_id}' fired for {agent}:{action}. Output: {str(result.get('output', ''))[:200]}",
        )

        return json.dumps({
            "matched": True,
            "status": "active",
            "rule_id": rule_id,
            "output": result["output"],
            "rule_type": result.get("rule_type", "deterministic"),
            "message": "Use this output instead of LLM decision.",
        })

    elif status == "shadow":
        rule_stats[rule_id]["shadow_matches"] += 1

        await write_audit(
            agent, "rule_shadow",
            f"Shadow rule '{rule_id}' matched for {agent}:{action}. "
            f"Shadow output: {str(result.get('output', ''))[:200]}. "
            f"LLM should still make its own decision — compare later.",
            severity="info",
        )

        return json.dumps({
            "matched": False,  # Shadow = don't replace LLM yet
            "shadow_match": True,
            "shadow_rule_id": rule_id,
            "shadow_output": result["output"],
            "message": "Shadow rule matched. Proceed with LLM decision. Output logged for comparison.",
        })

    return json.dumps({"matched": False})


@mcp.tool()
async def get_rule_stats() -> str:
    """
    Get hit/miss statistics for all rules.
    Use this to measure how much LLM surface has been replaced by deterministic rules.
    """
    load_rules_from_disk()

    active_rules = [r for r in rules if r.get("status") == "active"]
    shadow_rules = [r for r in rules if r.get("status") == "shadow"]

    total_hits = sum(s["hits"] for s in rule_stats.values())
    total_misses = rule_stats["_global"]["misses"]

    stats = {
        "total_rules": len(rules),
        "active_rules": len(active_rules),
        "shadow_rules": len(shadow_rules),
        "total_rule_hits": total_hits,
        "total_rule_misses": total_misses,
        "hit_rate": round(total_hits / max(total_hits + total_misses, 1) * 100, 1),
        "per_rule": {
            rule_id: dict(stats)
            for rule_id, stats in rule_stats.items()
            if rule_id != "_global"
        },
    }
    return json.dumps(stats, indent=2, default=str)


@mcp.tool()
async def reload_rules() -> str:
    """Force reload rules from ConfigMap. Call after updating the rules ConfigMap."""
    global rules_mtime
    rules_mtime = 0.0  # Force reload
    loaded = load_rules_from_disk()
    active = sum(1 for r in loaded if r.get("status") == "active")
    shadow = sum(1 for r in loaded if r.get("status") == "shadow")
    return json.dumps({
        "reloaded": True,
        "total": len(loaded),
        "active": active,
        "shadow": shadow,
    })


@mcp.tool()
async def promote_rule(rule_id: str, new_status: str) -> str:
    """
    Promote a rule's status: proposed → shadow → active, or active → retired.

    This is the lifecycle progression. shadow mode lets you compare rule
    output vs LLM output before going fully deterministic.

    Args:
        rule_id: The rule ID or pattern to promote
        new_status: Target status (shadow, active, retired)
    """
    valid_transitions = {
        "proposed": ["shadow", "active"],
        "shadow": ["active", "retired"],
        "active": ["retired"],
    }

    load_rules_from_disk()

    for rule in rules:
        rid = rule.get("id", rule.get("pattern", ""))
        if rid != rule_id:
            continue

        current = rule.get("status", "proposed")
        if new_status not in valid_transitions.get(current, []):
            return json.dumps({
                "error": f"Invalid transition: {current} → {new_status}. "
                         f"Valid: {valid_transitions.get(current, [])}"
            })

        rule["status"] = new_status

        # Write back to disk
        try:
            data = {"rules": rules}
            with open(RULES_PATH, "w") as f:
                yaml.dump(data, f, default_flow_style=False)

            await write_audit(
                "rules-engine", "rule_promoted",
                f"Rule '{rule_id}' promoted: {current} → {new_status}",
            )

            return json.dumps({
                "success": True,
                "rule_id": rule_id,
                "old_status": current,
                "new_status": new_status,
            })
        except Exception as e:
            return json.dumps({"error": f"Failed to write rules: {e}"})

    return json.dumps({"error": f"Rule '{rule_id}' not found"})


# ── File watcher ─────────────────────────────────────────

async def rules_watcher():
    """Periodically check for rules file changes."""
    while True:
        load_rules_from_disk()
        await asyncio.sleep(30)


# ── Entry point ──────────────────────────────────────────

async def main():
    import uvicorn

    load_rules_from_disk()
    mcp_app = mcp.streamable_http_app()
    config = uvicorn.Config(mcp_app, host="0.0.0.0", port=PORT, log_level="info")
    server = uvicorn.Server(config)

    await asyncio.gather(
        rules_watcher(),
        server.serve(),
    )


if __name__ == "__main__":
    import anyio
    anyio.run(main)
