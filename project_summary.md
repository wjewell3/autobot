# Autobot Project Summary
> Last updated: March 19, 2026

## Goal
Build an autonomous AI agent army running on free infrastructure, powered by GitHub Copilot (gpt-4.1), capable of finding and executing business opportunities. Live dashboard at https://wjewell3.github.io/autobot/

---

## Stack
| Layer | Tool | Cost |
|---|---|---|
| AI model | GitHub Copilot (gpt-4.1) | $10/mo (already paying) |
| LLM proxy | LiteLLM | Free |
| Agent runtime | kagent 0.7.23 | Free |
| Kubernetes | Oracle OKE (ARM) | Free forever |
| Compute | VM.Standard.A1.Flex (4 OCPU / 24GB RAM) | Free forever |
| Public tunnel | Cloudflare Quick Tunnel | Free (URL changes on restart) |
| Dashboard | GitHub Pages | Free |

---

## Infrastructure

### OCI / OKE
- **Tenancy:** `<your-tenancy-ocid>` — find via OCI Console → Profile → Tenancy
- **User:** `<your-user-ocid>` — find via OCI Console → Profile → User
- **Region:** `us-ashburn-1`
- **Cluster:** `<your-cluster-ocid>` — find via OCI Console → OKE → Clusters
- **Node:** `10.0.10.201` (private only, no public IP)
- **Node shape:** `VM.Standard.A1.Flex` — 4 OCPU, 24GB RAM, Oracle Linux 8 ARM64
- **K8s version:** `v1.34.2`
- **CNI:** Flannel Overlay
- **Node subnet:** `oke-nodesubnet-quick-cluster1-*-regional` (private, 10.0.10.0/24)
- **API endpoint subnet:** `oke-k8sApiEndpoint-subnet-quick-cluster1-*-regional` (public, 10.0.0.0/28)
- **LB subnet:** `oke-svclbsubnet-quick-cluster1-*-regional` (public, 10.0.20.0/24) — not used

### OCI Auth
- Config: `~/.oci/config`
- Key file: `~/.oci/oci_api_key.pem`
- Fingerprint: `<your-fingerprint>` — find via OCI Console → Profile → User → API Keys
- No passphrase on key

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
# LiteLLM Copilot token (stored on node hostPath, not secret)
# kagent OpenAI secret (routes to LiteLLM, value doesn't matter)
kubectl create secret generic kagent-openai \
  --namespace kagent \
  --from-literal=OPENAI_API_KEY=anything

# Dummy API key for ModelConfig
kubectl create secret generic copilot-api-key \
  --namespace kagent \
  --from-literal=key=anything
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

### deploy.yaml
Key components deployed via `kubectl apply -f deploy.yaml`:
- **LiteLLM deployment** — image: `ghcr.io/berriai/litellm:main-latest`
  - Config: `github_copilot/gpt-4.1` model
  - Token stored on node hostPath: `/home/opc/.config/litellm/github_copilot`
  - Memory: requests 512Mi, limits 1.5Gi (needs this much or OOMKilled)
- **LiteLLM service** — ClusterIP on port 4000
- **ModelConfig** — `copilot-gpt41`, points at `http://litellm-service.kagent.svc.cluster.local:4000`

### ModelConfig (v1alpha2)
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

### LiteLLM Auth
- GitHub Copilot token stored at `/home/opc/.config/litellm/github_copilot/api-key.json` on the node
- Mounted via hostPath into LiteLLM pod
- First run requires device auth: watch logs for device code, go to https://github.com/login/device
- Token persists across pod restarts via hostPath

### Cloudflare Tunnel (public access)
```bash
# Deploy cloudflared as a pod (quick tunnel, no domain needed)
kubectl apply -f - <<EOF
apiVersion: apps/v1
kind: Deployment
metadata:
  name: cloudflared
  namespace: kagent
spec:
  replicas: 1
  selector:
    matchLabels:
      app: cloudflared
  template:
    metadata:
      labels:
        app: cloudflared
    spec:
      containers:
        - name: cloudflared
          image: docker.io/cloudflare/cloudflared:latest-arm64
          args:
            - tunnel
            - --no-autoupdate
            - --url
            - http://kagent-ui.kagent.svc.cluster.local:8080
          resources:
            requests:
              memory: "64Mi"
              cpu: "100m"
            limits:
              memory: "128Mi"
              cpu: "200m"
EOF
```
- ⚠️ URL changes on every pod restart — get current URL with:
```bash
kubectl logs -n kagent -l app=cloudflared | grep trycloudflare
```

---

## GitHub Repo
- **Repo:** https://github.com/wjewell3/autobot
- **Dashboard:** https://wjewell3.github.io/autobot/
- **Deploy:** GitHub Actions → pushes to `gh-pages` branch automatically on every push to `main`
- **Workflow permissions:** Read and write (required for gh-pages deploy)

---

## Key Files
| File | Location | Purpose |
|---|---|---|
| `deploy.yaml` | `~/Documents/autobot/` | LiteLLM + ModelConfig k8s manifests |
| `agent_army.yaml` | `~/Documents/autobot/` | Number chain agent definitions |
| `autonomous_bot.py` | `~/Documents/autobot/` | Local Python agent (LiteLLM proxy) |
| `config.yaml` | `~/Documents/autobot/` | LiteLLM config for local use |
| `src/App.jsx` | `~/Documents/agent-viz/` | React dashboard deployed to GitHub Pages |
| `~/.oci/config` | local | OCI CLI auth config |
| `~/.kube/config` | local | kubectl config |

---

## Known Issues / Gotchas
- LiteLLM needs **1.5Gi memory** or it OOMKills on startup
- Node subnet is **private** — no public IP possible on node directly
- Cloudflare quick tunnel URL **changes on every pod restart** — update `KAGENT_API` in App.jsx when it does
- OCI auth uses fingerprint `62:cc:...` — if 401 errors appear check `~/.oci/config` DEFAULT profile matches this fingerprint
- `pass_phrase` must not be set in `~/.oci/config` DEFAULT profile or kubectl auth breaks
- kagent grafana-mcp pod will always error (bad image) — safe to ignore or delete
- All images need `docker.io/` prefix on Oracle Linux 8 due to short name enforcement

---

## Next Steps
- [ ] Add CORS headers to kagent API so GitHub Pages dashboard can poll live data
- [ ] Wire up agent_army.yaml agents and test number chain autonomously
- [ ] Build prospecting agent (scrape Google Maps for businesses)
- [ ] Build outreach agent (Gmail MCP integration)
- [ ] Build site builder agent (GitHub Copilot generates sites)
- [ ] Get a real domain for persistent Cloudflare tunnel URL
- [ ] Scale to multiple agent pods for parallel prospecting