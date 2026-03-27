# Autobot Project Summary
> Last updated: March 27, 2026

## Vision
A self-managing agentic software company with a pre-architected org structure. You provide high-level direction — the agent org executes, self-governs, and gets more reliable over time via a hardening loop.

---

## Current Stack
| Layer | Tool | Cost |
|---|---|---|
| AI model | GitHub Copilot (gpt-4.1) | $10/mo (already paying) |
| LLM proxy | LiteLLM | Free |
| Agent runtime | kagent 0.7.23 | Free |
| Kubernetes | Oracle OKE (ARM) | Free forever |
| Compute | VM.Standard.A1.Flex (4 OCPU / 24GB RAM) | Free forever |
| Event triggers | Khook | Free (built from source) |
| Agent memory | kagent pgvector (built-in) | Free |
| Embedding | LiteLLM → text-embedding-3-small (GitHub Copilot) | $0 extra |
| Public tunnel | Localtonet (ct0nsvobr7.localto.net) | Free (persistent URL) |
| CORS proxy | nginx in-cluster | Free |
| K8s API proxy | kubectl proxy in-cluster | Free |
| Dashboard | Vercel (autobot-chi-tawny.vercel.app) | Free |

---

## Target Agent Org Structure

### C-Suite Agents
| Agent | Role | Status |
|---|---|---|
| **CEO** | Holds original vision, never touches execution, ultimate source of truth for "why". Scope anchor. | ✅ deployed |
| **COO** | Drift detector. Continuously compares current work against original intent. Scope watcher. | ✅ deployed |
| **CFO** | Watches token limits, context windows, cluster resources, action budgets. READ-ONLY monitor. | ✅ deployed + tested |
| **CSO** | HITL-gated enforcer. AUDIT / ENFORCE / EXECUTE modes. Registry governance. | ✅ deployed + tested |
| **PM** | Breaks work into tasks, sequences them, manages dependencies, handles blockers. | ✅ deployed |
| **Hardening Agent** | Watches patterns across all agents. Progressively converts repetitive LLM decisions into deterministic rules. **v1 deployed — analyzing patterns every 5 min, creates PRs via github-mcp.** | ✅ deployed |

> **Commander refactor note:** The current commander is doing too much — CEO + COO + PM + router simultaneously. As C-suite agents are added, commander should become a thin protocol dispatcher: it knows how to reach agents and manages A2A mechanics, but has zero opinion about *what* to do. All intent lives in CEO, all sequencing lives in PM. Plan this refactor before scaling worker agents.

### Worker Agents (narrow, single-purpose, no awareness of bigger picture)
- Prospecting agent — scrapes Google Maps / LinkedIn for business targets ✅ deployed
- Site builder agent — creates demo GitHub Pages websites for prospects ✅ deployed + tested (created live site)
- Outreach agent — sends cold emails via Gmail MCP (next)
- Follow-up agent — nurtures leads until conversion

---

## Capability Layer Architecture

### MCP Servers
| Server | Purpose | Status |
|---|---|---|
| `kagent-tool-server` | K8s ops (spawn/kill/modify agents) | ✅ Running + Accepted |
| `gmail-tool-server` | Email outreach | ✅ Running + Accepted |
| `search-tool-server` | Web search + business prospecting via SearXNG + Overpass API | ✅ Running + Accepted |
| `github-tool-server` | Repo create/push/enable Pages + branch/PR creation (7 tools) | ✅ Running + Accepted |
| `audit-logger` | Independent audit trail — watches Agent CRs, MCP tools: `write_audit`, `get_recent_audit` | ✅ Running + Accepted |
| `hardening-agent` | Pattern analysis + rule proposals — MCP tools: `get_patterns`, `get_active_rules` | ✅ Running + Accepted |
| `hitl-tool-server` | Slack HITL approvals — `request_approval` + `post_notification` MCP tools, posts to #hitl-approvals with ✅/❌ buttons, severity-based timeouts | ✅ Running + Accepted |
| `resource-governor` | Per-agent + global action budget enforcement — `check_budget`, `get_system_status` | ✅ Running + Accepted |
| `kagent-grafana-mcp` | Metrics (intentionally disabled) | ❌ Disabled in helm |

### Skills (instructional only — different risk profile from MCP servers)
- Build a **private tiered skills repo**:
  - Tier 1: Verified vendor skills
  - Tier 2: Custom built
  - Tier 3: Adapted public skills (never pull directly from skills.sh into production)
- CSO agent governs MCP registry and skills registry separately

---

## Python MCP Server Template

Every new Python MCP server in this cluster must use this pattern. Deviating from it causes either import errors, wrong bind address, or DNS rebinding rejections from kagent.

```python
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

# DNS rebinding protection must be explicitly disabled for in-cluster MCP servers.
# kagent sends Host: <service-name>.<namespace>:<port> which fails the default allowlist.
# This is safe — Flannel overlay is not exposed to DNS rebinding attacks.
mcp = FastMCP("your_mcp_name", transport_security=TransportSecuritySettings(
    enable_dns_rebinding_protection=False
))

# ... tool definitions ...

if __name__ == "__main__":
    import uvicorn, anyio
    app = mcp.streamable_http_app()
    config = uvicorn.Config(app, host="0.0.0.0", port=PORT, log_level="info")
    anyio.run(uvicorn.Server(config).serve)
```

**Why each part matters:**
- `transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False)` — kagent's host header (`service.namespace:port`) fails the MCP SDK's default DNS rebinding check. Disable it for all in-cluster servers.
- `host="0.0.0.0"` — FastMCP's `mcp.run()` doesn't accept `host`/`port` kwargs. Pass them directly to uvicorn.
- `FASTMCP_HOST` / `FASTMCP_PORT` env vars — these appear in the Settings source but are **not read** by the installed version. Set host/port in code, not env vars.
- `anyio.run(server.serve)` — `uvicorn.run()` with a pre-instantiated app exits immediately. Use `anyio.run` to keep it alive (matches FastMCP's own internal pattern).

**Deployment command** (in container args):
```bash
pip install fastapi uvicorn mcp httpx --quiet && python /app/server.py
```
Pin `mcp` version if stability is critical: `mcp==<version>`. The SDK changes import paths between minor versions.

### MCP Client SDK Pattern (Server-to-Server Calls)

When one MCP server needs to call tools on another MCP server (e.g., hardening-agent calling audit-logger or github-mcp), use the MCP client SDK — **not** raw `httpx.post()`. Raw HTTP POST to `/mcp` returns 406/400 because Streamable HTTP requires proper session negotiation.

```python
from mcp.client.streamable_http import streamablehttp_client
from mcp import ClientSession

async def call_mcp_tool(server_url: str, tool_name: str, arguments: dict) -> dict:
    async with streamablehttp_client(f"{server_url}/mcp") as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(tool_name, arguments)
            if result.content:
                return result.content[0].text
    return None
```

**Why:** Streamable HTTP uses session IDs, protocol negotiation, and specific `Accept` headers. The MCP client SDK handles all of this. Raw `httpx.post` with JSON-RPC payloads will fail with 406 (wrong Accept header) or 400 (missing session).

**Pip dependency:** Add `mcp` to the container's pip install (it includes both client and server).

**After deploying**, verify with:
```bash
kubectl logs -n kagent deployment/<name> --tail=10
# Must show: Uvicorn running on http://0.0.0.0:<port>
kubectl get remotemcpservers -n kagent
# Must show: ACCEPTED: True
```

---

## Communication Layer — Slack as Nervous System

Use Slack as the message bus rather than direct agent-to-agent API calls:

| Channel | Purpose |
|---|---|
| `#hitl-approvals` | Single approval interface for all HITL escalations |
| `#agent-commander` | Commander activity feed |
| `#agent-workers` | Worker agent output |
| `#hardening-proposals` | Hardening agent proposes new deterministic rules |
| `#inter-agent` | Agent-to-agent communication log |
| `#audit-log` | Independent audit store (do NOT rely on Slack for this) |

### HITL Escalation Message Format
Every escalation includes:
- Original task context
- What triggered the pause
- Proposed action
- Consequence severity
- Inline approve / reject / escalate / ask buttons

### Tiered Escalation
- No response in X minutes → escalate to secondary reviewer or fail safe
- Google Calendar MCP for deadline-aware escalations

### Slack Implementation Rules
- Each agent has its own Slack identity (human-readable comms)
- Use Events API for listening — never poll channel history
- Queue outbound messages: max 1 message/second/channel
- Maintain independent audit log — don't rely on Slack's API

> **Build order note:** Build a minimal Slack HITL skeleton *before or in parallel with* the first autonomous worker agents. You don't want search + outreach running without a reliable approval channel. Even a single working approve/reject button in `#hitl-approvals` is enough to start. Autonomy and oversight should scale together.

---

## Safety Architecture — Three Concentric Layers

```
┌─────────────────────────────────────────────────┐
│  OUTER: Deterministic hard stops                │
│  Schema validation, forbidden API lists,        │
│  step count limits, cost caps                   │
│  (No LLM involved — cannot be reasoned around)  │
│                                                 │
│  ┌───────────────────────────────────────────┐  │
│  │  MIDDLE: CSO + COO agents                 │  │
│  │  Semantic drift detection                 │  │
│  │  Security review, permission enforcement  │  │
│  │  (LLM-based, evaluative not generative)   │  │
│  │                                           │  │
│  │  ┌─────────────────────────────────────┐  │  │
│  │  │  INNER: Worker agents               │  │  │
│  │  │  Minimum necessary MCP access       │  │  │
│  │  │  Approved skills only               │  │  │
│  │  │  No awareness of bigger picture     │  │  │
│  │  └─────────────────────────────────────┘  │  │
│  └───────────────────────────────────────────┘  │
└─────────────────────────────────────────────────┘
```

---

## The Hardening Loop (Core Compounding Mechanism)

```
Hardening agent monitors decision patterns across all agents
    ↓
High frequency, low variance decisions → proposed as deterministic rules
    ↓
Rules run in shadow mode alongside LLM decisions
    ↓
Human reviews proposals in #hardening-proposals
    ↓
Approved rules replace LLM decisions
    ↓
LLM surface shrinks, deterministic surface grows
    ↓
Cost ↓, Latency ↓, Reliability ↑ (compounds over time)
```

> **Prioritize early:** Even a dumb v1 of the hardening loop — just posting "I saw this decision made 10 times this week, should I codify it?" to `#hardening-proposals` — starts building the muscle before you have full infrastructure. Get it running early so the compounding starts sooner.
>
> **Status (March 25, 2026):** v1 is deployed. The hardening-agent reads audit entries via MCP client SDK from audit-logger, counts (agent, action) frequencies, and when patterns exceed the threshold (default: 10), creates a branch + pushes a proposal YAML + opens a PR via github-mcp, then posts to Slack if configured. Tools: `get_patterns`, `get_active_rules`. Analysis interval: 5 min.

---

## Infrastructure

### OCI / OKE
- **Region:** `us-ashburn-1`
- **Tenancy/User/Cluster OCIDs:** stored in `~/.oci/config` and `~/.kube/config`
- **Node:** `10.0.10.201` (private subnet, no public IP)
- **Node shape:** `VM.Standard.A1.Flex` — 4 OCPU, 24GB RAM, Oracle Linux 8 ARM64
- **K8s version:** `v1.34.2`
- **CNI:** Flannel Overlay
- **Node subnet:** `oke-nodesubnet-quick-cluster1-*-regional` (private, 10.0.10.0/24)
- **API endpoint subnet:** `oke-k8sApiEndpoint-subnet-quick-cluster1-*-regional` (public, 10.0.0.0/28)

### OCI Auth
- Config: `~/.oci/config`
- Key file: `~/.oci/oci_api_key.pem`
- No passphrase on key — do NOT set `pass_phrase` in config or kubectl breaks

### kubectl
```bash
oci ce cluster create-kubeconfig \
  --cluster-id <your-cluster-ocid> \
  --file $HOME/.kube/config \
  --region us-ashburn-1 \
  --token-version 2.0.0 \
  --kube-endpoint PUBLIC_ENDPOINT
```

---

## Kubernetes Setup

### Namespace
```bash
kubectl create namespace kagent
```

### Secrets (created imperatively — never in files)
```bash
kubectl create secret generic kagent-openai \
  --namespace kagent \
  --from-literal=OPENAI_API_KEY=anything

kubectl create secret generic copilot-api-key \
  --namespace kagent \
  --from-literal=key=anything

kubectl create secret generic localtonet-token \
  --namespace kagent \
  --from-literal=token=<your-localtonet-token>
```

### kagent Installation
```bash
helm install kagent-crds \
  oci://ghcr.io/kagent-dev/kagent/helm/kagent-crds \
  --namespace kagent

helm install kagent \
  oci://ghcr.io/kagent-dev/kagent/helm/kagent \
  --namespace kagent \
  --set ui.service.type=NodePort \
  --set grafana-mcp.enabled=false
```

### ModelConfig
```bash
kubectl apply -f - <<EOF
apiVersion: kagent.dev/v1alpha2
kind: ModelConfig
metadata:
  name: default-model-config
  namespace: kagent
spec:
  apiKeySecret: kagent-openai
  apiKeySecretKey: OPENAI_API_KEY
  model: gpt-4.1
  provider: OpenAI
  openAI:
    baseUrl: http://litellm-service.kagent.svc.cluster.local:4000
EOF
```

---

## Key Deployments (deploy.yaml)

### LiteLLM
- Image: `ghcr.io/berriai/litellm:main-latest`
- Config: `github_copilot/gpt-4.1` + `github_copilot/text-embedding-3-small`
- Memory: requests 512Mi, limits **1.5Gi** (needs this or OOMKilled)
- Token stored on node hostPath: `/home/opc/.config/litellm/github_copilot`
- First run requires device auth: watch logs → go to https://github.com/login/device

### Agent Memory (pgvector)
- All 8 agents configured with `spec.declarative.memory: {modelConfig: copilot-embedding, ttlDays: 30}`
- **`copilot-embedding` ModelConfig** → LiteLLM → `text-embedding-3-small` (GitHub Copilot)
- **Storage:** kagent controller's built-in pgvector store — 768-dim vectors (truncated + L2-normalized from 1536)
- **Search:** each request embeds the query → `/api/memories/search` on kagent controller — matching memories injected as `<MEMORY>` blocks
- **Save:** async background task after session end → `/api/memories/sessions/batch`; LLM-summarized before embedding
- **Verified end-to-end (2026-03-27):** cross-session recall confirmed — stored "OMEGA / Q2 launch" in session 1, recalled in a completely new session (different contextId) ✅
- **Note:** The `Memory` CR (v1alpha1) with Pinecone is a separate, independent feature from `spec.declarative.memory`. Active memory uses kagent's pgvector — Pinecone is provisioned but unused. See `infra/memory/README.md`.

### CORS Proxy (nginx)
- Listens on port 8081
- Routes `/apis/` → kubectl-proxy:8888
- Routes `/api/a2a/` → kagent-controller:8083
- Run with custom config: `nginx -g "daemon off;" -c /etc/nginx/nginx-cors.conf`

### kubectl-proxy
- Exposes Kubernetes API on port 8888
- Uses `kagent-controller` service account

### Localtonet Tunnel
- Persistent URL: `ct0nsvobr7.localto.net`
- Routes to cors-proxy ClusterIP on port 8081
- ARM64 binary via initContainer (Docker image is x86 only)
- Requires: `DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=1`
- Must send `localtonet-skip-warning: true` header in all proxy requests

---

## Khook — Event-Driven Autonomy

### Install (ARM64 — must build from source)
```bash
# 1. Add GitHub Actions workflow to build ARM64 image
# See .github/workflows/build-khook.yml in repo
# Trigger manually: Actions → Build khook ARM64 → Run workflow
# Image published to: ghcr.io/wjewell3/khook:latest

# 2. Install via Helm
TMP_DIR="$(mktemp -d)"
git clone --depth 1 https://github.com/kagent-dev/khook.git "$TMP_DIR/khook"
cd "$TMP_DIR/khook"
make helm-version
helm install khook-crds ./helm/khook-crds --namespace kagent --create-namespace
helm install khook ./helm/khook --namespace kagent
kubectl set image deployment/khook -n kagent manager=ghcr.io/wjewell3/khook:latest
kubectl set env -n kagent deploy/khook \
  KAGENT_API_URL=http://kagent-controller.kagent.svc.cluster.local:8083 \
  KAGENT_USER_ID=admin@kagent.dev
cd - && rm -rf "$TMP_DIR"
```

### Supported Event Types
`pod-restart` | `pod-pending` | `oom-kill` | `probe-failed` | `node-not-ready`

### Hooks Deployed
- **agent-self-heal** — commander auto-fixes crashed/OOM agents
- **agent-registry-sync** — commander patches itself when cluster state changes

---

## Agent Army (agent_army.yaml)

All agents use `kagent.dev/v1alpha2` with `type: Declarative` (capital D).

Key schema notes:
- `spec.type: Declarative` (not lowercase)
- `spec.declarative.systemMessage` (not `systemPrompt`)
- A2A tools: `type: Agent` with `agent.name/namespace/kind/apiGroup`

### Current Agents (live as of 2026-03-26)
| Agent | Role | Status |
|---|---|---|
| `commander-agent` | Thin router — dispatches to C-suite + HITL_RESUME routing | ✅ |
| `ceo-agent` | Vision/strategy — no tools, pure reasoning | ✅ |
| `coo-agent` | Ops oversight — audit read + Slack notifications | ✅ |
| `cso-agent` | Security enforcement — AUDIT/ENFORCE/EXECUTE modes, HITL-gated | ✅ |
| `cfo-agent` | Token limits, context windows, cluster resources, action budgets (READ-ONLY) | ✅ |
| `pm-agent` | Project manager — backlog, triage, delegates to workers | ✅ |
| `prospecting-agent` | Finds local businesses needing websites | ✅ |
| `site-builder-agent` | Creates demo GitHub Pages sites for prospects | ✅ |

**Legacy demo agents deleted by CSO on 2026-03-26:** number-agent-1/2/3, sum-agent, researcher-agent, critic-agent, writer-agent, publisher-agent, send-email-test

### Commander Capabilities
- Fetches live agent list at start of every conversation
- Resolves colloquial agent references (no hardcoding needed)
- Patches itself after creating/deleting agents
- Reports chain results in exact format: `<agent-name> picked: X` / `final sum: X`

---

## Dashboard (Vercel)

- **URL:** https://autobot-chi-tawny.vercel.app
- **Repo:** https://github.com/wjewell3/autobot
- **Features:** Live agent diagram, agent list, metrics panel, commander chat
- **Polls:** Kubernetes API every 3 seconds via Vercel serverless proxy
- **Chat:** Talks to commander-agent via A2A protocol

### Architecture
```
Browser → Vercel (autobot-chi-tawny.vercel.app)
            ↓ /api/proxy → kubectl-proxy → k8s API (agent list)
            ↓ /api/chat  → localtonet → cors-proxy → kagent-controller A2A
```

### Key Files
| File | Purpose |
|---|---|
| `agent-viz/src/App.jsx` | React dashboard with chat + diagram |
| `api/proxy.js` | Vercel proxy → localtonet (adds skip-warning header) |
| `api/chat.js` | Vercel A2A chat proxy (kind: "text" not type: "text") |
| `vercel.json` | Build config + rewrites |
| `deploy.yaml` | LiteLLM + nginx + kubectl-proxy + localtonet manifests |
| `agent_army.yaml` | Agent definitions |
| `infra/phase1-admission-control/policy-server.py` | Admission webhook — enforce mode, forbidden_tools with allowed_tools override |
| `infra/phase1-admission-control/capability-registry.yaml` | Per-agent tool/agent-call permissions, HITL label enforcement |
| `infra/phase3-resource-governor/budgets.yaml` | Per-agent + global action budget limits |
| `agents/cfo-agent.yaml` | CFO agent — token limits, cluster resources, action budgets |
| `agents/site-builder-agent.yaml` | Site builder — creates GitHub Pages demo sites |
| `infra/phase2-audit-log/audit-logger.py` | K8s Agent CR watcher + MCP audit tools |
| `infra/phase2-audit-log/deploy.yaml` | Audit logger deployment + RBAC + RemoteMCPServer |
| `infra/phase4-hardening-loop/hardening-agent.py` | Pattern analyzer + github-mcp PR flow |
| `infra/phase4-hardening-loop/deploy.yaml` | Hardening agent deployment + RemoteMCPServer |
| `infra/github-mcp-update/server.py` | Updated github-mcp with 7 tools (branch + PR) |
| `.github/workflows/build-khook.yml` | ARM64 khook builder |
| `.github/workflows/deploy.yml` | GitHub Pages deploy (legacy) |

---

## Known Issues / Gotchas
- LiteLLM needs **1.5Gi memory limit** or OOMKills
- Node subnet is private — no public IP on node directly
- LiteLLM Copilot token requires device auth on first run
- All images need `docker.io/` prefix on Oracle Linux 8
- Localtonet ARM64 binary needs `DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=1`
- Localtonet sends warning page — always include `localtonet-skip-warning: true` header
- kagent Agent CRD is `v1alpha2` with `type: Declarative` (capital D)
- Sessions CRD returns 403 — not in kagent 0.7.23, safely ignored
- Do NOT set `pass_phrase` in `[DEFAULT]` OCI config profile
- khook has no published ARM64 image — must build via GitHub Actions
- kagent UI returns 502 on API endpoints — use kubectl-proxy instead
- **MCP SDK breaks imports between minor versions** — `StreamableHTTPSessionManager` moved; use the FastMCP template above instead of manual Starlette wiring
- **`FASTMCP_HOST`/`FASTMCP_PORT` env vars are not read** by the installed SDK version despite appearing in source — set host/port directly in uvicorn.Config
- **`mcp.run()` does not accept `host`/`port` kwargs** — bypass it with `anyio.run(uvicorn.Server(config).serve)`
- **kagent rejects MCP servers with DNS rebinding protection enabled** — always set `enable_dns_rebinding_protection=False` for in-cluster servers
- **ConfigMap updates are cached in running pods** — `kubectl rollout restart` is not always sufficient; use `kubectl delete pod -l app=<name>` to force a clean mount
- **Raw httpx POST to MCP Streamable HTTP endpoints fails** — returns 406 or 400. Use the MCP client SDK (`streamablehttp_client` + `ClientSession`) for server-to-server tool calls. See MCP Client SDK Pattern above.
- **`spec.declarative.memory` (v1alpha2) ≠ Memory CR (v1alpha1)** — these are two separate features. `spec.declarative.memory` uses kagent's own pgvector backend (the working one). The `Memory` CRD is for external vector stores (e.g. Pinecone) and is a different, independent system. Configuring a Memory CR does NOT affect agent memory unless the agent explicitly references it.
- **A2A message parts use `kind` not `type`** — `{"kind":"text","text":"..."}` is correct. `{"type":"text"}` returns "unsupported part kind". Correct A2A path: `POST /api/a2a/<namespace>/<agent-name>/` (trailing slash required). Auth: `x-api-secret` header from `nginx-cors` ConfigMap.
- **RemoteMCPServer CRD requires both `protocol` and `url`** — omitting either causes kagent to silently ignore the server. Always include `protocol: STREAMABLE_HTTP` and `url: http://<service>.<namespace>.svc.cluster.local:<port>/mcp`
- **deploy.yaml must not contain empty ConfigMap stubs** — a `data: {}` ConfigMap in deploy.yaml will overwrite a ConfigMap previously loaded via `kubectl create configmap --from-file`. Put a comment with the load command instead.
- **kagent RemoteMCPServer re-discovery** — after restarting an MCP pod, kagent may cache the old tool list. Force re-discovery with `kubectl annotate remotemcpserver <name> -n kagent retry=$(date +%s) --overwrite`

---

## Next Steps (In Priority Order)

### Immediate
- [x] **Switch Phase 1 webhook to `enforcement_mode: enforce`** — ✅ done 2026-03-26. Registry clean, all 8 agents passing.
- [x] **Real Slack button test** — ✅ fully verified 2026-03-27. Both paths confirmed end-to-end:
  - **Deny path:** CSO enforce → `request_approval` → Slack post → user clicked ❌ → Vercel `hitl.js` sig verify → commander → CSO EXECUTE → `write_audit` (REMEDIATION_REJECTED) ✅
  - **Approve path:** CSO flagged `test-delete-me` legacy agent → user clicked ✅ → Vercel → commander → CSO EXECUTE → `k8s_delete_resource` (agent deleted) → `write_audit` ✅
- [ ] Set `SLACK_PROPOSALS_CHANNEL_ID` on hardening-agent and `SLACK_AUDIT_CHANNEL_ID` on audit-logger (both currently `value: ""` — need channel IDs from user)

### Next Capability: Outreach Agent
- [x] **`site-builder-agent`** — ✅ deployed + tested 2026-03-26. Created live GitHub Pages site (wjewell3/test-plumbing-demo). PM-agent has A2A tool to delegate to it.
- [ ] **`outreach-agent`** — next unlock. Sends HITL-gated cold emails with the demo site URL.
  - Tools: gmail_request_approval, gmail_check_approval, audit-logger
  - Every send requires HITL approval (high severity)
  - Wire PM → prospecting-agent → site-builder-agent → outreach-agent as the full pipeline

### Agent Org Build-Out
- [x] CEO agent — vision/strategy, no tools
- [x] COO agent — ops oversight, audit read + Slack
- [x] CSO agent — HITL-gated enforcement, AUDIT/ENFORCE/EXECUTE modes ✅ fully tested 2026-03-26
- [x] PM agent — backlog management, delegates to prospecting-agent
- [x] Commander → thin router with HITL_RESUME routing
- [x] Hardening agent — deployed, analyzing patterns every 5 min, creates PRs via github-mcp
- [x] CFO agent — ✅ deployed + tested 2026-03-26. Monitors token limits, cluster resources, action budgets. Uses resource-governor MCP tools.

### Safety
- [x] Phase 1: Admission control webhook — deployed, **`enforce` mode** ✅ 2026-03-26
- [x] Phase 2: Audit logger — deployed, watches Agent CRs, MCP tools available
- [x] Phase 3: Resource governor — deployed (MCP running at :8093)
- [x] Phase 4: Hardening loop — deployed, reads audit log, proposes rules via GitHub PRs
- [x] HITL pipeline — CSO audit→enforce→approval→execute fully working end-to-end (both approve ✅ and deny ❌ paths verified via real Slack buttons 2026-03-27)
- [x] **Phase 1 `enforcement_mode: enforce`** — ✅ flipped 2026-03-26, all agents passing
- [x] **`require_hitl_label_for_mcp: true`** — ✅ enabled 2026-03-26. All 8 agents labeled `hitl-reviewed=true`. Unlabeled agents with MCP tools are rejected.
- [x] **forbidden_tools override** — policy-server.py updated to allow explicit `allowed_tools` overrides for forbidden tools (needed for khook auto-synced tools on commander)
- [ ] Install Calico CNI for NetworkPolicy enforcement (Flannel doesn't enforce)

### Infrastructure
- [x] github-mcp updated with `github_create_branch` + `github_create_pr` tools (7 total)
- [x] api/hitl.js — 5 bugs fixed: `tasks/send`→`message/send`, `type`→`kind`, added messageId, correct URL path with namespace, added `X-API-Secret`
- [ ] Clean up `infra/hardening-bot/` scaffold (superseded by hardening-agent + github-mcp)
- [ ] Pin image digests for all MCP server containers
- [x] **Enable kagent memory on all agents** — ✅ done 2026-03-27. All 8 agents using `copilot-embedding` ModelConfig (`text-embedding-3-small` via LiteLLM). pgvector-backed, 30-day TTL. Cross-session recall verified.
- [ ] Add business metrics to dashboard (leads found, emails sent, revenue)
- [ ] Get a real domain for persistent tunnel (optional but recommended)