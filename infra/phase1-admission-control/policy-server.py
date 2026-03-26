"""
policy-server.py — Kubernetes ValidatingAdmissionWebhook for Agent CRs.

Deterministic enforcement layer. No LLM involved — cannot be reasoned around.
Reads allowed agent-tool mappings from /etc/policy/capability-registry.yaml.

Rules enforced:
  1. Agent must be listed in capability registry (or registry allows unlisted)
  2. Agent can only have tools explicitly granted in registry
  3. Globally forbidden tools are blocked regardless of registry
  4. Max agent count enforced (queries API server for current count)
  5. Agents with MCP tools must have hitl-reviewed label

Runs on TLS (required by K8s admission webhooks).
"""

import json
import logging
import os
import ssl

import httpx
import yaml
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("policy-server")

REGISTRY_PATH = "/etc/policy/capability-registry.yaml"
NAMESPACE = os.getenv("WATCH_NAMESPACE", "kagent")
K8S_API = "https://kubernetes.default.svc"
SA_TOKEN_PATH = "/var/run/secrets/kubernetes.io/serviceaccount/token"
SA_CA_PATH = "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"

app = FastAPI()


def load_registry() -> dict:
    with open(REGISTRY_PATH) as f:
        return yaml.safe_load(f)


def get_k8s_headers() -> dict:
    with open(SA_TOKEN_PATH) as f:
        token = f.read().strip()
    return {"Authorization": f"Bearer {token}"}


async def get_agent_count() -> int:
    """Query the K8s API for current agent count in namespace."""
    try:
        async with httpx.AsyncClient(verify=SA_CA_PATH) as client:
            resp = await client.get(
                f"{K8S_API}/apis/kagent.dev/v1alpha2/namespaces/{NAMESPACE}/agents",
                headers=get_k8s_headers(),
                timeout=5,
            )
            resp.raise_for_status()
            items = resp.json().get("items", [])
            return len(items)
    except Exception as e:
        log.error(f"Failed to get agent count: {e}")
        return -1  # fail open on count check if API unreachable


def validate_agent(agent: dict, registry: dict, operation: str) -> tuple[bool, str]:
    """
    Validate an Agent CR against the capability registry.
    Returns (allowed: bool, reason: str).
    """
    agent_name = agent.get("metadata", {}).get("name", "unknown")
    labels = agent.get("metadata", {}).get("labels", {})
    spec = agent.get("spec", {})
    declarative = spec.get("declarative", {})
    tools = declarative.get("tools", [])

    max_agents = registry.get("max_agents", 20)
    allowed_agents = registry.get("allowed_agents", {})
    forbidden_tools = registry.get("forbidden_tools", [])
    require_hitl_label = registry.get("require_hitl_label_for_mcp", True)
    allow_unlisted = registry.get("allow_unlisted_agents", False)

    # ── Rule 1: Agent must be in registry ──
    if not allow_unlisted and agent_name not in allowed_agents:
        return False, (
            f"Agent '{agent_name}' is not in the capability registry. "
            f"Add it to the registry ConfigMap first. "
            f"Registered agents: {list(allowed_agents.keys())}"
        )

    # ── Rule 2: Check tool allowlist ──
    agent_config = allowed_agents.get(agent_name, {})
    allowed_tool_refs = set(agent_config.get("allowed_tools", []))
    allowed_agent_refs = set(agent_config.get("allowed_agent_calls", []))

    for tool in tools:
        tool_type = tool.get("type", "")

        if tool_type == "McpServer":
            mcp = tool.get("mcpServer", {})
            server_name = mcp.get("name", "")
            tool_names = mcp.get("toolNames", [])
            for tn in tool_names:
                ref = f"{server_name}/{tn}"
                if not allow_unlisted and ref not in allowed_tool_refs:
                    return False, (
                        f"Tool '{ref}' is not allowed for agent '{agent_name}'. "
                        f"Allowed: {sorted(allowed_tool_refs)}"
                    )

        elif tool_type == "Agent":
            agent_ref = tool.get("agent", {}).get("name", "")
            if not allow_unlisted and agent_ref not in allowed_agent_refs:
                return False, (
                    f"Agent call to '{agent_ref}' is not allowed for '{agent_name}'. "
                    f"Allowed: {sorted(allowed_agent_refs)}"
                )

    # ── Rule 3: Globally forbidden tools ──
    for tool in tools:
        if tool.get("type") == "McpServer":
            mcp = tool.get("mcpServer", {})
            for tn in mcp.get("toolNames", []):
                if tn in forbidden_tools:
                    return False, (
                        f"Tool '{tn}' is globally forbidden. "
                        f"This tool is blocked by deterministic policy and cannot be "
                        f"assigned to any agent. Contact the operator to update the "
                        f"capability registry."
                    )

    # ── Rule 4: HITL label required for MCP tools ──
    has_mcp = any(t.get("type") == "McpServer" for t in tools)
    if require_hitl_label and has_mcp:
        if labels.get("hitl-reviewed") != "true":
            return False, (
                f"Agent '{agent_name}' has MCP tools but is missing the "
                f"'hitl-reviewed: true' label. Only a human operator can add "
                f"this label via kubectl."
            )

    return True, "OK"


@app.post("/validate")
async def validate(request: Request):
    body = await request.json()
    req = body.get("request", {})
    uid = req.get("uid", "")
    operation = req.get("operation", "")
    agent = req.get("object", {})
    agent_name = agent.get("metadata", {}).get("name", "unknown")

    log.info(f"Admission request: {operation} agent/{agent_name} (uid={uid})")

    # Only validate CREATE and UPDATE
    if operation not in ("CREATE", "UPDATE"):
        return admission_response(uid, True, "Operation not subject to policy")

    registry = load_registry()

    # ── Max agent count (CREATE only) ──
    if operation == "CREATE":
        max_agents = registry.get("max_agents", 20)
        count = await get_agent_count()
        enforcement_mode = registry.get("enforcement_mode", "enforce")
        if count >= 0 and count >= max_agents:
            msg = (
                f"Agent count limit reached ({count}/{max_agents}). "
                f"Delete unused agents before creating new ones."
            )
            if enforcement_mode == "audit":
                log.warning(f"AUDIT-WOULD-DENY {agent_name}: {msg}")
            else:
                log.warning(f"DENIED {agent_name}: {msg}")
                return admission_response(uid, False, msg)

    allowed, reason = validate_agent(agent, registry, operation)
    enforcement_mode = registry.get("enforcement_mode", "enforce")

    if allowed:
        log.info(f"ALLOWED {agent_name}: {reason}")
    else:
        if enforcement_mode == "audit":
            log.warning(f"AUDIT-WOULD-DENY {agent_name}: {reason}")
            allowed = True
            reason = f"[AUDIT MODE] Would deny: {reason}"
        else:
            log.warning(f"DENIED {agent_name}: {reason}")

    return admission_response(uid, allowed, reason)


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


def admission_response(uid: str, allowed: bool, message: str) -> JSONResponse:
    resp = {
        "apiVersion": "admission.k8s.io/v1",
        "kind": "AdmissionReview",
        "response": {
            "uid": uid,
            "allowed": allowed,
        },
    }
    if not allowed:
        resp["response"]["status"] = {"code": 403, "message": message}
    return JSONResponse(resp)


if __name__ == "__main__":
    import uvicorn

    PORT = int(os.getenv("POLICY_SERVER_PORT", "8443"))
    CERT_FILE = "/certs/tls.crt"
    KEY_FILE = "/certs/tls.key"

    # Check if TLS certs exist (they should, created by setup-certs.sh)
    if os.path.exists(CERT_FILE) and os.path.exists(KEY_FILE):
        log.info(f"Starting policy server on :{PORT} with TLS")
        uvicorn.run(
            app,
            host="0.0.0.0",
            port=PORT,
            ssl_certfile=CERT_FILE,
            ssl_keyfile=KEY_FILE,
            log_level="info",
        )
    else:
        log.error(
            f"TLS certs not found at {CERT_FILE} / {KEY_FILE}. "
            f"Run setup-certs.sh first."
        )
        exit(1)
