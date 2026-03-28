"""
shared-state.py — Blackboard pattern for agent coordination.

Agents coordinate via shared state instead of just A2A message passing.
This enables real drift detection (COO can see what PM is doing),
pipeline visibility (any agent can see current leads/builds/emails),
and cross-agent memory without relying on pgvector recall.

State is organized into namespaces:
  - pipeline/<run_id>  — current pipeline execution state
  - leads/             — accumulated lead database
  - config/            — runtime configuration overrides
  - metrics/           — counters and gauges
  - locks/             — distributed coordination locks

MCP Tools:
  - state_get(namespace, key) → read a value
  - state_set(namespace, key, value) → write a value
  - state_list(namespace) → list keys in a namespace
  - state_delete(namespace, key) → remove a key
  - pipeline_status() → current pipeline state summary
  - acquire_lock(name, holder, ttl_seconds) → distributed lock
  - release_lock(name, holder) → release a lock
"""

import asyncio
import json
import logging
import os
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("shared-state")

PORT = int(os.getenv("SHARED_STATE_PORT", "8097"))
PERSIST_PATH = os.getenv("STATE_PERSIST_PATH", "/data/state.json")

mcp = FastMCP(
    "shared-state",
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)


# ── State Store ──────────────────────────────────────────

# In-memory state: namespace → key → {value, updated_at, updated_by}
state: dict[str, dict[str, dict]] = defaultdict(dict)

# Distributed locks: name → {holder, expires_at}
locks: dict[str, dict] = {}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def persist_state():
    """Persist state to disk for crash recovery."""
    try:
        os.makedirs(os.path.dirname(PERSIST_PATH), exist_ok=True)
        # Convert defaultdict to regular dict for serialization
        serializable = {ns: dict(keys) for ns, keys in state.items()}
        with open(PERSIST_PATH, "w") as f:
            json.dump(serializable, f, indent=2, default=str)
    except Exception as e:
        log.error(f"Failed to persist state: {e}")


def load_state():
    """Load state from disk on startup."""
    global state
    try:
        with open(PERSIST_PATH) as f:
            loaded = json.load(f)
        for ns, keys in loaded.items():
            for key, val in keys.items():
                state[ns][key] = val
        log.info(f"Loaded state from disk: {sum(len(v) for v in state.values())} keys across {len(state)} namespaces")
    except (FileNotFoundError, json.JSONDecodeError):
        log.info("No persisted state found, starting fresh")


def cleanup_locks():
    """Remove expired locks."""
    now = time.time()
    expired = [name for name, lock in locks.items() if lock["expires_at"] < now]
    for name in expired:
        log.info(f"Lock expired: {name} (held by {locks[name]['holder']})")
        del locks[name]


# ── MCP Tools ────────────────────────────────────────────

@mcp.tool()
async def state_get(namespace: str, key: str) -> str:
    """
    Read a value from shared state.

    Args:
        namespace: State namespace (e.g. "pipeline/run-123", "leads", "config")
        key: Key within the namespace
    """
    entry = state.get(namespace, {}).get(key)
    if entry is None:
        return json.dumps({"found": False, "namespace": namespace, "key": key})
    return json.dumps({"found": True, "namespace": namespace, "key": key, **entry})


@mcp.tool()
async def state_set(namespace: str, key: str, value: str, updated_by: str = "unknown") -> str:
    """
    Write a value to shared state. Creates or overwrites.

    Args:
        namespace: State namespace (e.g. "pipeline/run-123", "leads", "metrics")
        key: Key within the namespace
        value: Value to store (string or JSON string)
        updated_by: Agent name that set this value
    """
    state[namespace][key] = {
        "value": value,
        "updated_at": _now(),
        "updated_by": updated_by,
    }
    persist_state()
    return json.dumps({"success": True, "namespace": namespace, "key": key})


@mcp.tool()
async def state_list(namespace: str) -> str:
    """
    List all keys in a namespace with metadata.

    Args:
        namespace: State namespace to list
    """
    entries = state.get(namespace, {})
    result = []
    for key, entry in entries.items():
        result.append({
            "key": key,
            "updated_at": entry.get("updated_at"),
            "updated_by": entry.get("updated_by"),
            "value_preview": str(entry.get("value", ""))[:100],
        })
    return json.dumps({
        "namespace": namespace,
        "count": len(result),
        "keys": result,
    }, indent=2)


@mcp.tool()
async def state_delete(namespace: str, key: str) -> str:
    """
    Delete a key from shared state.

    Args:
        namespace: State namespace
        key: Key to delete
    """
    if namespace in state and key in state[namespace]:
        del state[namespace][key]
        persist_state()
        return json.dumps({"deleted": True, "namespace": namespace, "key": key})
    return json.dumps({"deleted": False, "error": "Key not found"})


@mcp.tool()
async def pipeline_status() -> str:
    """
    Get a summary of all active pipeline runs.
    COO/PM/north-star use this for drift detection and progress tracking.
    """
    pipeline_runs = {}
    for ns, keys in state.items():
        if ns.startswith("pipeline/"):
            run_id = ns.split("/", 1)[1]
            pipeline_runs[run_id] = {
                key: {
                    "value": entry.get("value", "")[:200],
                    "updated_at": entry.get("updated_at"),
                    "updated_by": entry.get("updated_by"),
                }
                for key, entry in keys.items()
            }

    # Aggregate metrics
    metrics = {}
    for key, entry in state.get("metrics", {}).items():
        metrics[key] = entry.get("value")

    return json.dumps({
        "active_pipelines": len(pipeline_runs),
        "pipelines": pipeline_runs,
        "metrics": metrics,
    }, indent=2)


@mcp.tool()
async def acquire_lock(name: str, holder: str, ttl_seconds: int = 300) -> str:
    """
    Acquire a distributed lock. Prevents concurrent pipeline steps.

    Args:
        name: Lock name (e.g. "site-builder-github-push")
        holder: Who's acquiring (agent name)
        ttl_seconds: Lock auto-expires after this many seconds (default: 300)
    """
    cleanup_locks()

    if name in locks:
        existing = locks[name]
        return json.dumps({
            "acquired": False,
            "held_by": existing["holder"],
            "expires_at": datetime.fromtimestamp(existing["expires_at"], tz=timezone.utc).isoformat(),
        })

    locks[name] = {
        "holder": holder,
        "expires_at": time.time() + ttl_seconds,
        "acquired_at": _now(),
    }
    return json.dumps({"acquired": True, "name": name, "holder": holder})


@mcp.tool()
async def release_lock(name: str, holder: str) -> str:
    """
    Release a distributed lock.

    Args:
        name: Lock name
        holder: Must match the original acquirer
    """
    if name not in locks:
        return json.dumps({"released": False, "error": "Lock not found"})
    if locks[name]["holder"] != holder:
        return json.dumps({"released": False, "error": f"Lock held by {locks[name]['holder']}, not {holder}"})
    del locks[name]
    return json.dumps({"released": True, "name": name})


# ── Periodic Tasks ────────────────────────────────────────

async def maintenance_loop():
    """Periodic cleanup and persistence."""
    while True:
        cleanup_locks()
        persist_state()
        await asyncio.sleep(60)


# ── Entry point ──────────────────────────────────────────

async def main():
    import uvicorn

    load_state()
    mcp_app = mcp.streamable_http_app()
    config = uvicorn.Config(mcp_app, host="0.0.0.0", port=PORT, log_level="info")
    server = uvicorn.Server(config)

    await asyncio.gather(
        maintenance_loop(),
        server.serve(),
    )


if __name__ == "__main__":
    import anyio
    anyio.run(main)
