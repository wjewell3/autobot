"""
codegen-mcp — test runner + microservice deployer for codegen-agent.

MCP Tools:
  run_test_suite      — run pytest against generated code in an ephemeral K8s Job
  deploy_microservice — deploy a generated MCP server (ConfigMap + Deployment + Service + RemoteMCPServer)
  lock_service        — write a human-approved lock record to shared-state
  get_lock_status     — check lock status for a compiled service

Port: 8100 (env CODEGEN_MCP_PORT)
Namespace: kagent (env NAMESPACE)
Auth: in-cluster ServiceAccount token
"""

import asyncio
import json
import logging
import os
import re
import sys
import uuid
from datetime import datetime, timezone

import httpx
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stdout)
log = logging.getLogger("codegen-mcp")

PORT = int(os.environ.get("CODEGEN_MCP_PORT", "8100"))
NAMESPACE = os.environ.get("NAMESPACE", "kagent")
SHARED_STATE_URL = os.environ.get("SHARED_STATE_URL", "http://shared-state.kagent.svc.cluster.local:8097")

mcp = FastMCP(
    "codegen-mcp",
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)


# ── K8s API helpers ──────────────────────────────────────────────────────────

def _k8s_auth() -> tuple[str, str]:
    token_path = "/var/run/secrets/kubernetes.io/serviceaccount/token"
    ca_path = "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"
    with open(token_path) as f:
        token = f.read().strip()
    return token, ca_path


async def k8s_json(method: str, path: str, body: dict = None) -> dict:
    """Call K8s API endpoint that returns JSON."""
    token, ca = _k8s_auth()
    url = f"https://kubernetes.default.svc{path}"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    async with httpx.AsyncClient(verify=ca, timeout=30) as client:
        fn = getattr(client, method.lower())
        resp = await (fn(url, headers=headers, json=body) if body else fn(url, headers=headers))
    if resp.status_code not in (200, 201, 202):
        raise RuntimeError(f"K8s {resp.status_code} {method} {path}: {resp.text[:400]}")
    return resp.json()


async def k8s_text(path: str) -> str:
    """GET K8s endpoint that returns plain text (e.g. pod logs)."""
    token, ca = _k8s_auth()
    url = f"https://kubernetes.default.svc{path}"
    async with httpx.AsyncClient(verify=ca, timeout=30) as client:
        resp = await client.get(url, headers={"Authorization": f"Bearer {token}"})
    return resp.text


async def k8s_apply(body: dict) -> dict:
    """Create resource; update if it already exists (server-side apply pattern)."""
    kind = body["kind"]
    name = body["metadata"]["name"]
    ns = body["metadata"].get("namespace", NAMESPACE)
    base: dict[str, str] = {
        "ConfigMap": f"/api/v1/namespaces/{ns}/configmaps",
        "Deployment": f"/apis/apps/v1/namespaces/{ns}/deployments",
        "Service": f"/api/v1/namespaces/{ns}/services",
        "Job": f"/apis/batch/v1/namespaces/{ns}/jobs",
        "RemoteMCPServer": f"/apis/kagent.dev/v1alpha2/namespaces/{ns}/remotemcpservers",
    }
    collection_path = base[kind]
    try:
        return await k8s_json("POST", collection_path, body)
    except RuntimeError as e:
        if "already exists" in str(e):
            # On update we need to preserve resourceVersion for ConfigMap/Deployment
            existing = await k8s_json("GET", f"{collection_path}/{name}")
            rv = existing.get("metadata", {}).get("resourceVersion")
            if rv:
                body.setdefault("metadata", {})["resourceVersion"] = rv
            return await k8s_json("PUT", f"{collection_path}/{name}", body)
        raise


async def k8s_delete_silent(kind: str, name: str, extra_params: str = "") -> None:
    ns_map: dict[str, str] = {
        "ConfigMap": f"/api/v1/namespaces/{NAMESPACE}/configmaps/{name}",
        "Job": f"/apis/batch/v1/namespaces/{NAMESPACE}/jobs/{name}",
    }
    path = ns_map.get(kind)
    if path:
        try:
            await k8s_json("DELETE", f"{path}?propagationPolicy=Foreground{extra_params}")
        except Exception:
            pass


async def wait_for_job(name: str, timeout: int = 180) -> bool:
    """Poll until Job completes. Returns True=success, False=failed/timeout."""
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        try:
            status = await k8s_json("GET", f"/apis/batch/v1/namespaces/{NAMESPACE}/jobs/{name}")
            for cond in status.get("status", {}).get("conditions", []):
                if cond.get("type") == "Complete" and cond.get("status") == "True":
                    return True
                if cond.get("type") == "Failed" and cond.get("status") == "True":
                    return False
        except Exception:
            pass
        await asyncio.sleep(5)
    return False


# ── MCP Tools ────────────────────────────────────────────────────────────────

@mcp.tool()
async def run_test_suite(
    service_name: str,
    service_code: str,
    test_code: str,
    requirements: str = "",
) -> str:
    """
    Run a pytest test suite against generated service code in an ephemeral K8s Job.

    Mounts service_code as service.py and test_code as test_service.py into the job
    container via ConfigMap. Installs dependencies, runs pytest -v --tb=short, fetches
    stdout, parses passed/failed counts, and cleans up the Job+ConfigMap.

    Args:
        service_name:  Short identifier used in K8s resource names (e.g. "prospecting-mcp").
                       Must be DNS-label safe (lowercase, no spaces).
        service_code:  Full Python source of the service module (imported as `service`).
        test_code:     Full Python source of the pytest file. Import service with:
                       `from service import <function>` since service.py is in the same dir.
        requirements:  Space-separated pip packages needed beyond pytest
                       (e.g. "httpx requests beautifulsoup4").

    Returns:
        JSON: {
          "passed": int,
          "failed": int,
          "total": int,
          "exit_zero": bool,        # True if job pod exited 0
          "output": str,            # Last 4000 chars of pytest stdout
          "iteration_hint": str     # "all_passing" | "improving" | "stuck" | "no_tests_found"
        }
    """
    run_id = str(uuid.uuid4())[:6]
    cm_name = f"cg-test-{service_name}-{run_id}"
    job_name = f"cg-test-{service_name}-{run_id}"

    extra_reqs = " ".join(r.strip() for r in requirements.split() if r.strip())
    pip_cmd = f"pip install pytest {extra_reqs} --quiet 2>&1 | tail -5"
    test_cmd = "cd /tmp && python -m pytest test_service.py -v --tb=short 2>&1"
    shell_cmd = (
        f"cp /code/service.py /tmp/service.py && "
        f"cp /code/test_service.py /tmp/test_service.py && "
        f"{pip_cmd} && {test_cmd}"
    )

    cm = {
        "apiVersion": "v1",
        "kind": "ConfigMap",
        "metadata": {"name": cm_name, "namespace": NAMESPACE},
        "data": {"service.py": service_code, "test_service.py": test_code},
    }
    job = {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {"name": job_name, "namespace": NAMESPACE},
        "spec": {
            "ttlSecondsAfterFinished": 300,
            "backoffLimit": 0,
            "template": {
                "spec": {
                    "restartPolicy": "Never",
                    "containers": [{
                        "name": "runner",
                        "image": "docker.io/python:3.12-slim",
                        "command": ["/bin/sh", "-c"],
                        "args": [shell_cmd],
                        "volumeMounts": [{"mountPath": "/code", "name": "code"}],
                        "resources": {
                            "limits": {"cpu": "500m", "memory": "256Mi"},
                            "requests": {"cpu": "100m", "memory": "128Mi"},
                        },
                    }],
                    "volumes": [{"name": "code", "configMap": {"name": cm_name}}],
                }
            },
        },
    }

    try:
        await k8s_apply(cm)
        await k8s_apply(job)
        succeeded = await wait_for_job(job_name, timeout=180)

        # Fetch pod logs (plain text endpoint — not JSON)
        pods = await k8s_json(
            "GET",
            f"/api/v1/namespaces/{NAMESPACE}/pods?labelSelector=job-name%3D{job_name}",
        )
        logs = ""
        for pod in pods.get("items", []):
            pod_name = pod["metadata"]["name"]
            logs = await k8s_text(
                f"/api/v1/namespaces/{NAMESPACE}/pods/{pod_name}/log"
            )
            break

        # Parse pytest summary line: "3 passed, 1 failed in 0.42s"
        passed = 0
        failed = 0
        m_pass = re.search(r"(\d+) passed", logs)
        m_fail = re.search(r"(\d+) failed", logs)
        m_err = re.search(r"(\d+) error", logs)
        if m_pass:
            passed = int(m_pass.group(1))
        if m_fail:
            failed = int(m_fail.group(1))
        if m_err:
            failed += int(m_err.group(1))
        total = passed + failed

        if total == 0:
            hint = "no_tests_found"
        elif failed == 0:
            hint = "all_passing"
        else:
            hint = "improving" if passed > 0 else "stuck"

        return json.dumps({
            "passed": passed,
            "failed": failed,
            "total": total,
            "exit_zero": succeeded,
            "output": logs[-4000:] if len(logs) > 4000 else logs,
            "iteration_hint": hint,
        })
    except Exception as e:
        log.error(f"run_test_suite error: {e}")
        return json.dumps({"error": str(e), "passed": 0, "failed": 0, "total": 0})
    finally:
        await k8s_delete_silent("Job", job_name)
        await k8s_delete_silent("ConfigMap", cm_name)


@mcp.tool()
async def deploy_microservice(
    name: str,
    code: str,
    port: int,
    requirements: str = "fastapi uvicorn mcp httpx anyio",
    description: str = "",
) -> str:
    """
    Deploy a generated Python MCP microservice to the cluster.

    Creates four K8s resources:
      1. ConfigMap <name>-code — contains server.py
      2. Deployment <name>    — python:3.12-slim, pip install + python /app/server.py
      3. Service <name>       — ClusterIP on <port>
      4. RemoteMCPServer <name> — STREAMABLE_HTTP pointing to http://<name>.kagent.svc.cluster.local:<port>/mcp

    All resources get label codegen-managed=true.
    ONLY call this after receiving HITL approval — never pre-deploy.

    Args:
        name:         DNS-safe resource name (e.g. "prospecting-mcp").
        code:         Full Python source. MUST follow the FastMCP server template
                      (see project_summary.md). Use `anyio.run(uvicorn.Server(config).serve)`.
        port:         Container port. Use next free port from allocation table (8101+).
        requirements: Space-separated pip packages (fastapi uvicorn mcp httpx anyio included).
        description:  Human-readable description for the RemoteMCPServer CR.

    Returns:
        JSON: {
          "name": str,
          "endpoint": str,        # MCP endpoint URL
          "resources": {configmap, deployment, service, remotemcpserver},
          "next_steps": [str]      # Manual steps to complete the integration
        }
    """
    reqs = " ".join(r.strip() for r in requirements.split() if r.strip()) or "fastapi uvicorn mcp httpx anyio"
    label = {"codegen-managed": "true"}
    svc_url = f"http://{name}.{NAMESPACE}.svc.cluster.local:{port}/mcp"

    resources = [
        {
            "apiVersion": "v1",
            "kind": "ConfigMap",
            "metadata": {"name": f"{name}-code", "namespace": NAMESPACE, "labels": label},
            "data": {"server.py": code},
        },
        {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {"name": name, "namespace": NAMESPACE, "labels": label},
            "spec": {
                "replicas": 1,
                "selector": {"matchLabels": {"app": name}},
                "template": {
                    "metadata": {"labels": {"app": name}},
                    "spec": {
                        "containers": [{
                            "name": name,
                            "image": "docker.io/python:3.12-slim",
                            "command": ["/bin/sh", "-c"],
                            "args": [f"pip install {reqs} --quiet && python /app/server.py"],
                            "ports": [{"containerPort": port}],
                            "volumeMounts": [{"mountPath": "/app", "name": "code"}],
                            "resources": {
                                "limits": {"cpu": "200m", "memory": "256Mi"},
                                "requests": {"cpu": "50m", "memory": "128Mi"},
                            },
                        }],
                        "volumes": [{"name": "code", "configMap": {"name": f"{name}-code"}}],
                    },
                },
            },
        },
        {
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": {"name": name, "namespace": NAMESPACE, "labels": label},
            "spec": {
                "selector": {"app": name},
                "ports": [{"port": port, "targetPort": port, "protocol": "TCP"}],
            },
        },
        {
            "apiVersion": "kagent.dev/v1alpha2",
            "kind": "RemoteMCPServer",
            "metadata": {"name": name, "namespace": NAMESPACE, "labels": label},
            "spec": {
                "description": description or (
                    f"Codegen-compiled deterministic microservice replacing LLM "
                    f"calls in {name.replace('-mcp', '-agent')}"
                ),
                "protocol": "STREAMABLE_HTTP",
                "url": svc_url,
            },
        },
    ]

    results: dict[str, str] = {}
    for body in resources:
        key = body["kind"].lower()
        try:
            await k8s_apply(body)
            results[key] = "ok"
        except Exception as e:
            results[key] = f"error: {str(e)[:120]}"

    return json.dumps({
        "name": name,
        "endpoint": svc_url,
        "resources": results,
        "next_steps": [
            f"Update infra/phase1-admission-control/capability-registry.yaml:"
            f" add '{name}/<tool_name>' to allowed_tools for the target agent",
            f"Add TOOL PRIORITY instruction to target agent system message"
            f" and push via github_create_branch + github_push_file + github_create_pr",
            f"Add '{name}' to commander-agent's tool list if needed",
            f"kubectl annotate remotemcpserver {name} -n {NAMESPACE}"
            f" codegen.restart=$(date +%s) --overwrite  # force tool re-discovery",
        ],
    })


@mcp.tool()
async def lock_service(
    agent_name: str,
    version: str,
    approved_by: str,
    notes: str = "",
) -> str:
    """
    Write an immutable lock record to shared-state for a compiled service.

    Locked services are protected — codegen-agent, rd-agent, and hardening-agent
    all check lock status before modifying anything related to that agent.
    Only a human can request a revisit ("revisit <agent-name>" message to codegen-agent).

    Args:
        agent_name:  Target agent name (e.g. "prospecting-agent").
        version:     Git tag or iteration label (e.g. "v4" or "iteration-7").
        approved_by: Human identifier from HITL payload (e.g. "user" or Slack handle).
        notes:       Optional notes from the approval — e.g. feedback incorporated.

    Returns:
        JSON: {"locked": bool, "agent": str, "version": str}
    """
    from mcp.client.streamable_http import streamablehttp_client
    from mcp import ClientSession

    record = json.dumps({
        "status": "locked",
        "version": version,
        "approved_by": approved_by,
        "locked_at": datetime.now(timezone.utc).isoformat(),
        "notes": notes,
    })

    try:
        async with streamablehttp_client(f"{SHARED_STATE_URL}/mcp") as (r, w, _):
            async with ClientSession(r, w) as session:
                await session.initialize()
                await session.call_tool("state_set", {
                    "namespace": "codegen",
                    "key": f"{agent_name}/lock",
                    "value": record,
                })
        return json.dumps({"locked": True, "agent": agent_name, "version": version})
    except Exception as e:
        log.error(f"lock_service error: {e}")
        return json.dumps({"locked": False, "agent": agent_name, "error": str(e)})


@mcp.tool()
async def get_lock_status(agent_name: str) -> str:
    """
    Check whether a compiled service is locked for a given agent.

    Args:
        agent_name: Target agent name (e.g. "prospecting-agent").

    Returns:
        JSON lock record if locked: {"status": "locked", "version": ..., "approved_by": ..., ...}
        {"status": "unlocked"} if no lock exists.
        {"status": "unknown", "error": ...} if shared-state is unreachable.
    """
    from mcp.client.streamable_http import streamablehttp_client
    from mcp import ClientSession

    try:
        async with streamablehttp_client(f"{SHARED_STATE_URL}/mcp") as (r, w, _):
            async with ClientSession(r, w) as session:
                await session.initialize()
                result = await session.call_tool("state_get", {
                    "namespace": "codegen",
                    "key": f"{agent_name}/lock",
                })
                if result.content and result.content[0].text:
                    raw = result.content[0].text.strip()
                    # state_get returns the value directly; it may be JSON-encoded
                    return raw if raw and raw != "null" else json.dumps({"status": "unlocked"})
                return json.dumps({"status": "unlocked"})
    except Exception as e:
        log.error(f"get_lock_status error: {e}")
        return json.dumps({"status": "unknown", "error": str(e)})


# ── Entrypoint ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import anyio
    import uvicorn

    app = mcp.streamable_http_app()
    config = uvicorn.Config(app, host="0.0.0.0", port=PORT, log_level="info")
    anyio.run(uvicorn.Server(config).serve)
