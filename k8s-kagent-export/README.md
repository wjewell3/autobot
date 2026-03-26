# k8s-kagent-export — Cluster State Snapshot
> Last synced: 2026-03-26

This directory contains a full export of the `kagent` namespace for offline reference.
Use it to reconstruct context on a device without kubectl access.

## Live Cluster State (as of sync date)

### Agents (6 total — post-CSO-cleanup)
| Name | Role | Tools |
|------|------|-------|
| commander-agent | Thin router + HITL_RESUME dispatcher | All A2A + k8s + search + github + gmail (approval only) |
| ceo-agent | Vision/strategy | None (pure reasoning) |
| coo-agent | Ops oversight | audit-logger/get_recent_audit, hitl-tool-server/post_notification |
| cso-agent | Security enforcement (AUDIT/ENFORCE/EXECUTE) | k8s read/delete/patch, audit r/w, HITL request + notify |
| pm-agent | Project manager / backlog | audit r/w, HITL, A2A:prospecting-agent |
| prospecting-agent | Finds businesses needing websites | search_find_businesses, search_web, write_audit, post_notification |

### MCP Servers (RemoteMCPServers)
| Name | Port | URL | Status |
|------|------|-----|--------|
| kagent-tool-server | 8084 | http://kagent-tools.kagent:8084/mcp | ✅ Accepted |
| search-tool-server | 8086 | http://search-mcp.kagent:8086/mcp | ✅ Accepted |
| github-tool-server | 8087 | http://github-mcp.kagent.svc.cluster.local:8087/mcp | ✅ Accepted |
| gmail-tool-server | 8088 | http://gmail-mcp.kagent.svc.cluster.local:8088/mcp | ✅ Accepted |
| hitl-tool-server | 8091 | http://hitl-tool-server.kagent.svc.cluster.local:8091/mcp | ✅ Accepted |
| audit-logger | 8092 | http://audit-logger.kagent.svc.cluster.local:8092/mcp | ✅ Accepted |
| resource-governor | 8093 | http://resource-governor.kagent.svc.cluster.local:8093/mcp | ✅ Accepted |
| hardening-agent | 8094 | http://hardening-agent.kagent.svc.cluster.local:8094/mcp | ✅ Accepted |
| kagent-grafana-mcp | 8000 | (disabled) | ❌ |

### Khook Event Hooks
| Hook | Trigger | Handler |
|------|---------|---------|
| agent-self-heal | pod-restart, oom-kill, probe-failed | commander-agent auto-fix |
| agent-registry-sync | agent create/delete | commander patches itself |

### Key Infrastructure
| Component | Location |
|-----------|----------|
| LiteLLM proxy | litellm-service.kagent:4000 → github_copilot/gpt-4.1 |
| nginx cors-proxy | port 8081 — routes /api/a2a/, /apis/, /audit-api/, /approval/ |
| kubectl-proxy | port 8888 — K8s API |
| approval-server | port 8089 — HITL approval state (in-memory) |
| localtonet tunnel | ct0nsvobr7.localto.net → cors-proxy:8081 (tunnel #1975034) |
| Dashboard | https://autobot-chi-tawny.vercel.app |
| GitHub repo | https://github.com/wjewell3/autobot |

## Files in This Directory
| File | Contents |
|------|----------|
| `agents.kagent.dev.yaml` | All Agent CRDs with full system prompts |
| `remotemcpservers.kagent.dev.yaml` | All RemoteMCPServer registrations |
| `modelconfigs.kagent.dev.yaml` | ModelConfig (gpt-4.1 via LiteLLM) |
| `deployments.apps.yaml` | All deployment specs |
| `services.yaml` | All service definitions |
| `configmaps.yaml` | All configmaps (includes capability-registry.yaml) |
| `hooks.kagent.dev.yaml` | Khook event hook definitions |
| `roles.yaml` / `rolebindings.yaml` | RBAC |
| `serviceaccounts.yaml` | Service accounts |

## HITL Pipeline Status (tested 2026-03-26)
Full end-to-end loop verified:
1. CSO ENFORCE message → CSO audits all agents → finds 9 legacy violations
2. CSO calls `request_approval(severity=high)` → Slack #hitl-approvals ✅/❌ buttons posted
3. CSO stops and waits for HITL_RESUME
4. HITL_RESUME(outcome=approved) → commander routes to cso-agent → CSO deletes 9 agents
5. CSO re-audits → Status: CLEAN

## Vercel API Routes
| Route | Purpose |
|-------|---------|
| /api/chat.js | A2A proxy to commander-agent |
| /api/hitl.js | Slack webhook receiver → HITL_RESUME to commander |
| /api/audit.js | Proxies to audit-logger REST |
| /api/test.js | 4 predefined pipeline tests |
| /api/approve.js | Email-based approval handler |

## Safety Infrastructure
| Phase | Status | Mode |
|-------|--------|------|
| Phase 1: Admission webhook | ✅ Deployed | audit (not yet enforce) |
| Phase 2: Audit logger | ✅ Deployed | active |
| Phase 3: Resource governor | ✅ Deployed | active |
| Phase 4: Hardening loop | ✅ Deployed | active (5min interval) |

**Next action:** Flip Phase 1 to `enforcement_mode: enforce` in capability-registry.yaml.
