# Autobot Safety Infrastructure

> **Full documentation is in [`../project_summary.md`](../project_summary.md).** This file covers the quick-start for each phase.

Ten phases of deterministic guardrails. Each builds on the last. Phases 1–4 are the foundation; phases 5–10 add compounding mechanisms.

```
Phase 1: ADMISSION CONTROL    — blocks rogue agents at the K8s API level
Phase 2: AUDIT LOGGER         — independent trail of everything that happens
Phase 3: RESOURCE GOVERNOR    — per-agent + global action budget enforcement
Phase 4: HARDENING LOOP       — converts repeated LLM decisions into rules
Phase 5: RULES ENGINE         — runtime execution of approved deterministic rules
Phase 6: EVAL HARNESS         — measures quality before/after every agent change
Phase 7: BUSINESS MODULES     — playbook abstraction (swap business models)
Phase 8: SHARED STATE         — blackboard for agent coordination + pipeline visibility
Phase 9: ADVERSARIAL TESTING  — stress-tests governance before production finds gaps
Phase 10: CODEGEN             — distills repeatable agent tasks into Python microservices
```

## Deploy

```bash
# Phases 1-4 (bootstrap.sh)
cd infra/
chmod +x bootstrap.sh
./bootstrap.sh          # Deploy all 4 phases
./bootstrap.sh validate # Verify

# Phases 5-9 (deploy-phases-5-9.sh)
./deploy-phases-5-9.sh

# Phase 10 (codegen-mcp)
kubectl apply -f phase10-codegen/deploy.yaml
kubectl apply -f ../agents/codegen-agent.yaml

# hitl-tool-server
kubectl apply -f hitl-tool-server/deploy.yaml
```

## Phase Directories

| Directory | What's inside |
|-----------|--------------|
| `phase1-admission-control/` | `policy-server.py` — webhook; `capability-registry.yaml` — per-agent tool allowlist |
| `phase2-audit-log/` | `audit-logger.py` — K8s watcher + MCP tools (`write_audit`, `get_recent_audit`) |
| `phase3-resource-governor/` | `resource-governor.py`; `budgets.yaml` — per-agent limits |
| `phase4-hardening-loop/` | `hardening-agent.py` — L1 frequency + L2 failure analysis, creates PRs via github-mcp |
| `phase5-rules-engine/` | `rules-engine.py` — runtime rule execution; `rules.yaml` — proposed→shadow→active→retired |
| `phase6-eval-harness/` | `eval-harness.py`; `cases.yaml` — test cases; `set-baselines-job.yaml` — captures baselines on deploy |
| `phase7-business-modules/` | `playbook-server.py`; `playbooks.yaml` — business model configs |
| `phase8-shared-state/` | `shared-state.py` — namespaced key-value blackboard |
| `phase9-adversarial-testing/` | `adversarial-tester.py`; `tests.yaml`; `adversarial-cronjob.yaml` |
| `phase10-codegen/` | `codegen-mcp.py` — test runner + deployer; `deploy.yaml` |
| `hitl-tool-server/` | `deploy.yaml` — Slack HITL MCP server (port 8091) |
| `github-mcp-update/` | `server.py` — github-mcp with branch + PR tools (7 tools total) |
| `search-mcp/` | `server.py` — SearXNG + Overpass API |
| `scheduler/` | `scheduler.py` — CronJob A2A dispatcher for periodic C-suite triggers |
| `memory/` | `memory-cr.yaml` — Pinecone Memory CR (provisioned but **inactive** — agents use kagent's built-in pgvector) |

## Common Operations

```bash
# Check which agents are in the registry
cat phase1-admission-control/capability-registry.yaml

# Force webhook re-read after registry change
kubectl rollout restart deployment/agent-policy-server -n kagent

# Check audit trail
kubectl logs -n kagent -l app=audit-logger --tail=50

# Trigger adversarial sweep manually
kubectl create job adversarial-sweep-manual --from=cronjob/adversarial-sweep -n kagent

# Force MCP server re-discovery after pod restart
kubectl annotate remotemcpserver <name> -n kagent retry=$(date +%s) --overwrite
```

```
