# Autobot Project Summary
> Last updated: March 20, 2026

## Goal
Build an autonomous AI agent army running on free infrastructure, powered by GitHub Copilot (gpt-4.1), capable of finding and executing business opportunities. Live dashboard at https://autobot-chi-tawny.vercel.app

---

## Stack
| Layer | Tool | Cost |
|---|---|---|
| AI model | GitHub Copilot (gpt-4.1) | $10/mo (already paying) |
| LLM proxy | LiteLLM | Free |
| Agent runtime | kagent 0.7.23 | Free |
| Kubernetes | Oracle OKE (ARM) | Free forever |
| Compute | VM.Standard.A1.Flex (4 OCPU / 24GB RAM) | Free forever |
| Public tunnel | Localtonet (ct0nsvobr7.localto.net) | Free (persistent URL) |
| CORS proxy | nginx in-cluster | Free |
| K8s API proxy | kubectl proxy in-cluster | Free |
| Dashboard | Vercel (autobot-chi-tawny.vercel.app) | Free |

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
- **LB subnet:** `oke-svclbsubnet-quick-cluster1-*-regional` (public, 10.0.20.0/24) — not used

### OCI Auth
- Config: `~/.oci/config`
- Key file: `~/.oci/oci_api_key.pem`
- Fingerprint: stored in `~/.oci/config` under `[DEFAULT]`
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
# kagent OpenAI secret (routes to LiteLLM, value doesn't matter)
kubectl create secret generic kagent-openai \
  --namespace kagent \
  --from-literal=OPENAI_API_KEY=anything

# Dummy API key for ModelConfig
kubectl create secret generic copilot-api-key \
  --namespace kagent \
  --from-literal=key=anything

# Localtonet auth token
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
- Config: `github_copilot/gpt-4.1` model
- Memory: requests 512Mi, limits **1.5Gi** (needs this or OOMKilled)
- Token stored on node hostPath: `/home/opc/.config/litellm/github_copilot`
- Mounted via hostPath (not PVC — saves OCI block storage quota)
- **First run requires device auth:** watch logs for device code → go to https://github.com/login/device
- Token persists across pod restarts via hostPath

### CORS Proxy (nginx)
- Proxies requests from public internet to kubectl-proxy
- Adds `Access-Control-Allow-Origin: *` headers
- Listens on port 8081
- Config mounted via ConfigMap at `/etc/nginx/nginx-cors.conf`
- Run with: `nginx -g "daemon off;" -c /etc/nginx/nginx-cors.conf`

### kubectl-proxy
- Exposes Kubernetes API internally on port 8888
- Uses `kagent-controller` service account
- Image: `docker.io/bitnami/kubectl:latest`
- Allows dashboard to read Agent CRDs directly

### Localtonet Tunnel
- Provides persistent public URL: `ct0nsvobr7.localto.net`
- Routes to cors-proxy ClusterIP on port 8081
- ARM64 binary downloaded via initContainer (Docker image is x86 only)
- Requires env var: `DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=1`
- Image: `docker.io/ubuntu:22.04` with binary at `/app/localtonet`

### Cloudflared (replaced by localtonet)
- Was used for quick tunnel — URL changed on every restart
- Replaced by localtonet for persistent URL
- Can be deleted: `kubectl delete deployment cloudflared -n kagent`

---

## Agent Army (agent_army.yaml)

All agents use `kagent.dev/v1alpha2` with `type: Declarative` (capital D).

Key schema notes:
- `spec.type: Declarative` (not lowercase)
- `spec.declarative.systemMessage` (not `systemPrompt`)
- `spec.declarative.modelConfig` references ModelConfig name
- A2A tools use `type: Agent` with `agent.name/namespace/kind/apiGroup`

### Agents Deployed
| Agent | Role |
|---|---|
| `commander-agent` | Orchestrates the chain, has all others as tools |
| `number-agent-1` | Picks number, passes to agent 2 |
| `number-agent-2` | Picks number, passes to agent 3 |
| `number-agent-3` | Picks number, passes to sum-agent |
| `sum-agent` | Calculates final sum, ends chain |

### Deploy
```bash
kubectl apply -f ~/Documents/autobot/agent_army.yaml
kubectl get agents -n kagent
```

### Trigger Commander Autonomously
```bash
kubectl apply -f - <<EOF
apiVersion: kagent.dev/v1alpha1
kind: Task
metadata:
  name: number-chain
  namespace: kagent
spec:
  agent:
    name: commander-agent
    namespace: kagent
  prompt: "Start the number chain. Activate all agents autonomously."
EOF
```

---

## Dashboard (Vercel)

- **URL:** https://autobot-chi-tawny.vercel.app
- **Repo:** https://github.com/wjewell3/autobot
- **Auto-deploys** from GitHub on every push to `main`
- **Polls** Kubernetes API every 3 seconds via Vercel serverless proxy
- **GitHub Pages** also configured at https://wjewell3.github.io/autobot/ (legacy)

### Architecture
```
Browser → Vercel (autobot-chi-tawny.vercel.app)
            ↓ /api/proxy serverless function
          Localtonet (ct0nsvobr7.localto.net)
            ↓ tunnel into private cluster
          nginx cors-proxy (port 8081)
            ↓ proxy_pass
          kubectl-proxy (port 8888)
            ↓ k8s API
          Agent CRDs in kagent namespace
```

### Vercel Proxy (api/proxy.js)
- ES module format (`export default`) — package.json has `"type": "module"`
- Must include `localtonet-skip-warning: true` header or gets HTML warning page
- Routes all `/api/proxy/*` requests to localtonet

---

## Key Files
| File | Location | Purpose |
|---|---|---|
| `deploy.yaml` | `~/Documents/autobot/` | LiteLLM + CORS proxy + kubectl-proxy + localtonet k8s manifests |
| `agent_army.yaml` | `~/Documents/autobot/` | Number chain agent definitions |
| `autonomous_bot.py` | `~/Documents/autobot/` | Local Python agent (LiteLLM proxy) |
| `config.yaml` | `~/Documents/autobot/` | LiteLLM config for local use |
| `api/proxy.js` | `~/Documents/autobot/` | Vercel serverless CORS proxy |
| `vercel.json` | `~/Documents/autobot/` | Vercel build config |
| `agent-viz/src/App.jsx` | `~/Documents/autobot/` | React dashboard |
| `agent-viz/vite.config.js` | `~/Documents/autobot/` | Vite config (base: '/') |
| `~/.oci/config` | local | OCI CLI auth config |
| `~/.kube/config` | local | kubectl config |

---

## Known Issues / Gotchas
- LiteLLM needs **1.5Gi memory limit** or it OOMKills on startup
- Node subnet is **private** — no public IP possible directly on node
- LiteLLM Copilot token requires **device auth on first run** — watch pod logs
- Token stored on node hostPath — survives pod restarts, zero storage cost
- All images need `docker.io/` prefix on Oracle Linux 8 (short name enforcement)
- Localtonet ARM64 binary needs `DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=1`
- Localtonet shows warning page to first visitors — proxy must send `localtonet-skip-warning: true` header
- kagent grafana-mcp pod always errors (bad image) — safe to ignore or delete
- kagent Agent CRD is `v1alpha2` with `type: Declarative` (capital D)
- `spec.declarative.systemMessage` not `spec.systemPrompt`
- Sessions CRD returns 403 — not available in kagent 0.7.23, safely ignored
- OCI auth: do NOT set `pass_phrase` in `[DEFAULT]` config profile

---

## Next Steps
- [ ] Test number chain running autonomously via commander-agent
- [ ] Verify A2A agent delegation works in kagent 0.7.23
- [ ] Build prospecting agent (scrape Google Maps for businesses)
- [ ] Build outreach agent (Gmail MCP integration)
- [ ] Build site builder agent (GitHub Copilot generates sites)
- [ ] Add business metrics to dashboard (leads found, emails sent, revenue)
- [ ] Add agent spawn UI to dashboard (create new minions from browser)
- [ ] Get a real domain for more reliable tunnel (optional)