# k8s-kagent-export — Cluster State Snapshot
> Last synced: 2026-03-30

This directory contains a full export of the `kagent` namespace for offline reference.
Use it to reconstruct context on a device without kubectl access.

## Live Cluster State (as of sync date)

### Agents (12 total)
| Name | Role | Tools |
|------|------|-------|
| `commander-agent` | Thin router + HITL_RESUME dispatcher | All A2A + k8s + search + github + gmail (approval only) |
| `ceo-agent` | Vision/strategy | None (pure reasoning) |
| `coo-agent` | Ops oversight | audit-logger/get_recent_audit, hitl-tool-server/post_notification |
| `cso-agent` | Security enforcement (AUDIT/ENFORCE/EXECUTE) | k8s read/delete/patch, audit r/w, HITL request + notify |
| `cfo-agent` | Token limits, cluster resources, action budgets (READ-ONLY) | resource-governor/check_budget/get_system_status, k8s_get_resources |
| `pm-agent` | Project manager / backlog, niche rotation, lead accumulation | audit r/w, HITL, A2A:prospecting-agent, A2A:site-builder-agent, A2A:outreach-agent, shared-state, playbook-server |
| `prospecting-agent` | Finds local businesses needing websites (SearXNG + Overpass) | search_find_businesses, search_web, write_audit, post_notification |
| `site-builder-agent` | Creates demo GitHub Pages sites for prospects | github_create_repo/push_file/enable_pages + k8s + audit + notify |
| `outreach-agent` | Sends HITL-gated cold outreach emails | gmail_send_email, HITL request_approval, audit r/w, post_notification |
| `rd-agent` | R&D: researches best practices, proposes PRs (hourly CronJob) | search_web, github branch/PR, eval compare_eval, hardening get_patterns, audit, HITL notify |
| `north-star-agent` | Trajectory assessor — scores system against project vision (6h CronJob) | search_web, k8s_get_resources, audit r/w, post_notification |
| `codegen-agent` | LLM distillation — compiles repeatable agent tasks into Python microservices | k8s r/w, codegen-mcp (run_test_suite/deploy_microservice/lock_service), eval, audit, HITL, github PR |

### MCP Servers (RemoteMCPServers)
| Name | Port | URL | Accepted |
|------|------|-----|----------|
| `kagent-tool-server` | 8084 | http://kagent-tools.kagent:8084/mcp | ✅ |
| `search-tool-server` | 8086 | http://search-mcp.kagent:8086/mcp | ✅ |
| `github-tool-server` | 8087 | http://github-mcp.kagent.svc.cluster.local:8087/mcp | ✅ |
| `gmail-tool-server` | 8088 | http://gmail-mcp.kagent.svc.cluster.local:8088/mcp | ✅ |
| `hitl-tool-server` | 8091 | http://hitl-tool-server.kagent.svc.cluster.local:8091/mcp | ✅ |
| `audit-logger` | 8092 | http://audit-logger.kagent.svc.cluster.local:8092/mcp | ✅ |
| `resource-governor` | 8093 | http://resource-governor.kagent.svc.cluster.local:8093/mcp | ✅ |
| `hardening-agent` | 8094 | http://hardening-agent.kagent.svc.cluster.local:8094/mcp | ✅ |
| `rules-engine` | 8095 | http://rules-engine.kagent.svc.cluster.local:8095/mcp | ✅ |
| `eval-harness` | 8096 | http://eval-harness.kagent.svc.cluster.local:8096/mcp | ✅ |
| `shared-state` | 8097 | http://shared-state.kagent.svc.cluster.local:8097/mcp | ✅ |
| `adversarial-tester` | 8098 | http://adversarial-tester.kagent.svc.cluster.local:8098/mcp | ✅ |
| `playbook-server` | 8099 | http://playbook-server.kagent.svc.cluster.local:8099/mcp | ✅ |
| `codegen-mcp` | 8100 | http://codegen-mcp.kagent.svc.cluster.local:8100/mcp | ✅ |
| `kagent-grafana-mcp` | 8000 | (disabled) | ❌ |

### CronJobs
| Name | Schedule | Purpose |
|------|----------|---------|
| `rd-evolution-cycle` | `0 * * * *` (hourly) | R&D agent: research + propose improvement PRs |
| `north-star-assessment` | `0 */6 * * *` (every 6h) | North Star agent: score system against project vision |
| `scheduler-cfo-check` | `0 */2 * * *` (every 2h) | CFO agent: monitor token limits + cluster resources |
| `scheduler-coo-status` | `0 */4 * * *` (every 4h) | COO agent: ops oversight check |
| `scheduler-cso-audit` | `0 */6 * * *` (every 6h) | CSO agent: security audit sweep |
| `scheduler-pm-pipeline` | `0 */8 * * *` (every 8h) | PM agent: run full pipeline (prospect → build → outreach) |
| `adversarial-sweep` | `0 3 * * 1` (Monday 3am) | Adversarial tester: full governance stress test |

### Khook Event Hooks
| Hook | Trigger | Handler |
|------|---------|---------|
| `agent-self-heal` | pod-restart, oom-kill, probe-failed | commander-agent auto-fix |
| `agent-registry-sync` | agent create/delete | commander patches itself |

### Key Infrastructure
| Component | Location |
|-----------|----------|
| LiteLLM proxy | `litellm-service.kagent:4000` → `github_copilot/gpt-4.1` + `text-embedding-3-small` |
| nginx cors-proxy | port 8081 — routes `/api/a2a/`, `/apis/`, `/audit-api/`, `/approval/` |
| kubectl-proxy | port 8888 — K8s API |
| OKE Load Balancer | `157.151.243.159:80` → cors-proxy (10 Mbps, OCI free tier) |
| Dashboard | https://autobot1.vercel.app |
| GitHub repo | https://github.com/wjewell3/autobot |
| Admission webhook | `agent-policy-server` — enforcement mode, capability-registry per-agent allowlist |

### Reserved Compiled Service Ports (codegen-agent output)
| Port | Reserved For |
|------|-------------|
| 8101 | `prospecting-mcp` |
| 8102 | `site-builder-mcp` |
| 8103 | `outreach-mcp` |
| 8104 | `pm-mcp` |
| 8105 | `rd-mcp` |
| 8106 | `hardening-mcp` |
| 8107 | `cso-mcp` |
| 8108 | `coo-mcp` |
| 8109 | `cfo-mcp` |

## Files in This Directory
| File | Contents |
|------|----------|
| `agents.kagent.dev.yaml` | All Agent CRDs with full system prompts |
| `remotemcpservers.kagent.dev.yaml` | All RemoteMCPServer registrations |
| `agents.kagent.dev.yaml` | All 12 agent definitions (full YAML with system messages) |
| `remotemcpservers.kagent.dev.yaml` | All 15 RemoteMCPServer definitions |
| `modelconfigs.kagent.dev.yaml` | ModelConfig (gpt-4.1 via LiteLLM, copilot-embedding) |
| `deployments.apps.yaml` | All deployment specs |
| `services.yaml` | All service definitions |
| `configmaps.yaml` | All configmaps (capability-registry, rules, cases, playbooks, adversarial-tests, shared-state, eval-harness-cases, codegen) |
| `cronjobs.batch.yaml` | All 7 CronJob definitions |
| `jobs.batch.yaml` | Completed jobs (eval baseline setter, adversarial sweep runs) |
| `hooks.kagent.dev.yaml` | Khook event hook definitions |
| `roles.rbac.authorization.k8s.io.yaml` | All Roles + ClusterRoles + Bindings |
| `serviceaccounts.yaml` | All ServiceAccounts (incl. codegen-mcp) |
| `pods-status.txt` | `kubectl get pods -n kagent -o wide` snapshot |
| `remotemcpservers-status.txt` | `kubectl get remotemcpservers -n kagent` snapshot |
| `logs/<name>.log` | Last 50 lines from each MCP server pod |

## HITL Pipeline Status (tested 2026-03-27 — both paths verified)
Full end-to-end loop verified:
- **Deny path:** CSO enforce → `request_approval(severity=high)` → Slack #hitl-approvals ❌ → Vercel sig verify → commander → CSO EXECUTE → `write_audit(REMEDIATION_REJECTED)` ✅
- **Approve path:** CSO flagged `test-delete-me` → user clicked ✅ → Vercel → commander → CSO EXECUTE → `k8s_delete_resource` (agent deleted) → `write_audit` ✅

## Vercel API Routes
| Route | Purpose |
|-------|---------|
| `/api/chat.js` | A2A proxy to commander-agent |
| `/api/hitl.js` | Slack webhook receiver → HITL_RESUME to commander (sig verified) |
| `/api/audit.js` | Proxies to audit-logger REST |
| `/api/test.js` | 4 predefined pipeline tests |
| `/api/proxy.js` | K8s API proxy via OKE LB → cors-proxy |

## Safety Infrastructure
| Phase | Status | Mode |
|-------|--------|------|
| Phase 1: Admission webhook | ✅ Deployed | **enforce** (flipped 2026-03-26) |
| Phase 2: Audit logger | ✅ Deployed | active — watches Agent CRs + MCP tools |
| Phase 3: Resource governor | ✅ Deployed | active — per-agent + global budgets |
| Phase 4: Hardening loop | ✅ Deployed | active — L1 freq (threshold=10) + L2 failure (threshold=3) every 5min |
| Phase 5: Rules engine | ✅ Deployed | active — runtime deterministic rule execution |
| Phase 6: Eval harness | ✅ Deployed | active — baselines captured, rd-agent measures before/after PRs |
| Phase 7: Business modules | ✅ Deployed | active — pm-agent reads `local-web-services` playbook |
| Phase 8: Shared state | ✅ Deployed | active — pm-agent writes pipeline state on every run |
| Phase 9: Adversarial testing | ✅ Deployed | active — weekly Monday 3am UTC sweep |
| Phase 10: Codegen (LLM distillation) | ✅ Deployed | active — codegen-agent + codegen-mcp, HITL-gated deployment |

## Cluster Identity
- **Region:** us-ashburn-1
- **Node:** 10.0.10.201 (VM.Standard.A1.Flex — 4 OCPU / 24GB ARM64)
- **K8s version:** v1.34.2
- **CNI:** Flannel Overlay
- **OCI config:** ~/.oci/config (no pass_phrase)
