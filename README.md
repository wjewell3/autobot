# Autobot — Self-Managing Agentic Software Company

A self-managing agentic org running on Oracle OKE (free tier). You provide high-level direction — the agent org executes, self-governs, and gets more reliable over time.

## Quick Links

| Resource | URL |
|----------|-----|
| Dashboard | https://autobot1.vercel.app |
| GitHub repo | https://github.com/wjewell3/autobot |
| Public endpoint | http://157.151.243.159 (OKE Load Balancer, free 10 Mbps) |
| Cluster | OKE `us-ashburn-1` — VM.Standard.A1.Flex (4 OCPU / 24GB ARM64, free forever) |

## Documentation

**All architecture, gotchas, and decisions are in [`project_summary.md`](./project_summary.md).** That is the single source of truth — start there when picking this up from a new computer.

Quick-start for a new machine:
1. Install OCI CLI + `kubectl`
2. Copy `~/.oci/config` and `~/.oci/oci_api_key.pem` from the original machine
3. Run `oci ce cluster create-kubeconfig --cluster-id <clusterOCID> --file $HOME/.kube/config --region us-ashburn-1 --token-version 2.0.0 --kube-endpoint PUBLIC_ENDPOINT`
4. `kubectl get pods -n kagent` — should show ~20+ pods Running

The cluster OCID is in `~/.kube/config` on the original machine (look for `--cluster-id ocid1.cluster...` in the exec args).

## Repo Structure

```
agents/                  # Agent definitions (12 agents, individual YAMLs)
infra/
  phase1-admission-control/  # Admission webhook + capability registry
  phase2-audit-log/          # Audit logger MCP server
  phase3-resource-governor/  # Budget enforcement MCP server
  phase4-hardening-loop/     # Pattern analysis + rule proposals
  phase5-rules-engine/       # Runtime deterministic rule execution
  phase6-eval-harness/       # Agent eval before/after changes
  phase7-business-modules/   # Playbook abstraction (swap business models)
  phase8-shared-state/       # Blackboard pattern for agent coordination
  phase9-adversarial-testing/ # Governance stress tests
  phase10-codegen/           # LLM distillation → Python microservices
  hitl-tool-server/          # Slack HITL approval MCP server
  github-mcp-update/         # Updated github-mcp (branch + PR tools)
  search-mcp/                # Search MCP server (SearXNG + Overpass)
  scheduler/                 # CronJob A2A dispatcher
  memory/                    # Pinecone Memory CR (inactive — see project_summary)
agent-viz/               # React dashboard (deployed via Vercel)
api/                     # Vercel serverless functions (chat, hitl, audit, etc.)
k8s-kagent-export/       # Full cluster snapshot (refresh with kubectl exports)
scripts/                 # Operational scripts (e.g. set-outreach-phase.sh)
deploy.yaml              # Core infra: LiteLLM + nginx + kubectl-proxy + localtonet
project_summary.md       # ← MASTER DOCUMENT — read this first
```

## Agent Fleet (12 agents live)

C-suite: `commander`, `ceo`, `coo`, `cso`, `cfo`, `pm`, `hardening-agent`  
Workers: `prospecting`, `site-builder`, `outreach`, `rd`, `north-star`, `codegen`

## MCP Servers (14 live, 1 disabled)

Ports 8084–8100 in use. Ports 8101–8109 reserved for codegen-agent compiled services.
