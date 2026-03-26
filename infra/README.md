# Autobot Safety Infrastructure

Deterministic guardrails that cannot be bypassed by prompt injection, jailbreaks, or LLM reasoning. Each phase builds on the last.

```
┌──────────────────────────────────────────────────────────────┐
│  Phase 1: ADMISSION CONTROL (Kubernetes webhook)             │
│  Blocks rogue agent creation at the API server level.        │
│  ┌────────────────────────────────────────────────────────┐  │
│  │  Phase 2: AUDIT LOGGER (K8s watch + MCP)               │  │
│  │  Independent trail of every agent create/update/delete  │  │
│  │  ┌──────────────────────────────────────────────────┐  │  │
│  │  │  Phase 3: RESOURCE GOVERNOR (budget enforcement)  │  │  │
│  │  │  Token/action caps — alerts + hard limits         │  │  │
│  │  │  ┌────────────────────────────────────────────┐  │  │  │
│  │  │  │  Phase 4: HARDENING LOOP (pattern → rule)  │  │  │  │
│  │  │  │  Shrinks LLM surface over time             │  │  │  │
│  │  │  └────────────────────────────────────────────┘  │  │  │
│  │  └──────────────────────────────────────────────────┘  │  │
│  └────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────┘
```

## Quick Start

```bash
cd infra/
chmod +x bootstrap.sh
./bootstrap.sh          # Deploy all 4 phases
./bootstrap.sh validate # Verify everything works
```

## Phases

### Phase 1: Admission Control
**What:** A Kubernetes ValidatingAdmissionWebhook that intercepts every Agent CR create/update.

**Why:** Your commander has `k8s_apply_manifest` — it can create agents with arbitrary tools. Without this, a hallucinated system prompt could spawn an agent with `gmail_send_email` that bypasses HITL. The webhook makes that **impossible at the API server level**.

**Enforces:**
- Agents must be listed in the capability registry
- Each agent can only have explicitly granted tools
- `gmail_send_email` is globally forbidden (agents must use `gmail_request_approval`)
- Agents with MCP tools must have the `hitl-reviewed: true` label (only settable via kubectl by a human)
- Max agent count cap (default: 20)

**Files:**
| File | Purpose |
|------|---------|
| `policy-server.py` | FastAPI webhook that validates Agent CRs |
| `capability-registry.yaml` | Allowlist of agents and their permitted tools |
| `setup-certs.sh` | Generates TLS certs (K8s webhooks require HTTPS) |
| `deploy.yaml` | Deployment + Service + RBAC + WebhookConfig |
| `validate.sh` | Smoke tests (including dry-run blocked agent) |

**To add a new agent:** Edit `capability-registry.yaml`, run `./bootstrap.sh 1`.

### Phase 2: Audit Logger
**What:** Watches Agent CRs via K8s watch API and logs every change. Also provides MCP tools so agents can write structured audit entries.

**Why:** You need visibility before increasing autonomy. This gives you a complete, independent record of everything that happens — not reliant on Slack or any agent's self-reporting.

**Outputs:**
- `kubectl logs -l app=audit-logger` — real-time in stdout
- `/audit/audit.jsonl` inside the pod — structured JSONL
- Slack `#audit-log` channel (if configured)

**MCP Tools (available to agents):**
- `write_audit` — structured entry (agent, action, details, severity)
- `get_recent_audit` — fetch last N entries

**Files:**
| File | Purpose |
|------|---------|
| `audit-logger.py` | K8s watcher + MCP server |
| `deploy.yaml` | Deployment + RBAC + RemoteMCPServer registration |
| `validate.sh` | Checks pod, MCP registration, watch activity |

### Phase 3: Resource Governor
**What:** Monitors agent action frequency via the audit log and enforces per-agent and global budget limits.

**Why:** Without this, a looping agent could burn through API tokens or spam external services. Budget limits are defined in `budgets.yaml` — deterministic, not prompt-based.

**Enforces:**
- Per-agent max actions per hour (configurable per agent)
- Global total action cap across all agents
- Slack alerts at 80% threshold
- Critical alerts when hard limits are exceeded

**MCP Tools:**
- `check_budget` — agent checks its remaining budget before expensive ops
- `get_system_status` — overall resource status across all agents

**Files:**
| File | Purpose |
|------|---------|
| `resource-governor.py` | Budget enforcement loop + MCP server |
| `budgets.yaml` | Per-agent and global limits |
| `deploy.yaml` | Deployment + RemoteMCPServer registration |
| `validate.sh` | Checks pod, MCP registration, enforcement loop |

### Phase 4: Hardening Loop
**What:** Analyzes audit log patterns and proposes deterministic rules to replace repetitive LLM decisions.

**Why:** This is the compounding mechanism from the project vision. Over time, the LLM surface shrinks and the deterministic surface grows → lower cost, lower latency, higher reliability.

**How it works:**
1. Reads audit entries every 5 minutes
2. Groups by (agent, action) pairs
3. When a pattern exceeds threshold (default: 10 occurrences), proposes a rule
4. Posts to Slack `#hardening-proposals`
5. Human approves → rule added to `rules.yaml` → deterministic

**v1 is intentionally simple** — frequency counting only. No ML, no embeddings. Start the compounding early with a dumb v1.

**MCP Tools:**
- `get_patterns` — current decision patterns across agents
- `get_active_rules` — approved hardening rules

**Files:**
| File | Purpose |
|------|---------|
| `hardening-agent.py` | Pattern analyzer + MCP server |
| `rules.yaml` | Approved deterministic rules |
| `deploy.yaml` | Deployment + RemoteMCPServer registration |
| `validate.sh` | Checks pod, MCP registration, analysis loop |

## Operations

### Deploy individual phases
```bash
./bootstrap.sh 1        # Phase 1 only
./bootstrap.sh 2 4      # Phases 2 through 4
```

### Update the capability registry
```bash
# Edit the file:
vim phase1-admission-control/capability-registry.yaml

# Push to cluster:
./bootstrap.sh 1
```

### Update budgets
```bash
vim phase3-resource-governor/budgets.yaml
./bootstrap.sh 3
```

### Check what the webhook is doing
```bash
kubectl logs -n kagent -l app=agent-policy-server --tail=20
```

### Check audit trail
```bash
kubectl logs -n kagent -l app=audit-logger --tail=50
```

### Full teardown
```bash
./bootstrap.sh teardown
```

## Architecture

```
                    ┌─────────────────────┐
                    │   K8s API Server    │
                    └────────┬────────────┘
                             │ Agent CR create/update
                             ▼
                    ┌─────────────────────┐
                    │  Admission Webhook  │ ← Phase 1 (BLOCKS invalid agents)
                    │  (policy-server)    │
                    └────────┬────────────┘
                             │ allowed
                             ▼
                    ┌─────────────────────┐
                    │    Agent Runs       │
                    │  (kagent runtime)   │
                    └─┬──────┬──────┬─────┘
                      │      │      │
           ┌──────────┘      │      └──────────┐
           ▼                 ▼                  ▼
   ┌──────────────┐  ┌──────────────┐  ┌──────────────┐
   │ Audit Logger │  │   Resource   │  │  Hardening   │
   │   (watch +   │  │   Governor   │  │    Loop      │
   │   MCP tools) │  │  (budgets)   │  │  (patterns)  │
   └──────────────┘  └──────────────┘  └──────────────┘
     Phase 2            Phase 3           Phase 4
         │                  │                 │
         └──────────────────┼─────────────────┘
                            ▼
                    ┌─────────────────────┐
                    │   Slack Channels    │
                    │  #audit-log         │
                    │  #hardening-props   │
                    │  #hitl-approvals    │
                    └─────────────────────┘
```

## What This Prevents

| Attack Vector | Mitigation |
|---|---|
| Commander spawns agent with `gmail_send_email` | Webhook blocks — tool is globally forbidden |
| Commander spawns unlisted agent | Webhook blocks — not in capability registry |
| Agent gets tools it shouldn't have | Webhook blocks — per-agent allowlist |
| LLM creates agent without HITL label | Webhook blocks — label required for MCP agents |
| Runaway agent spamming tool calls | Governor alerts at 80%, critical alert at limit |
| Agent acts without audit trail | Watcher logs all CR changes independently |
| Repetitive LLM decisions waste tokens | Hardening loop proposes deterministic replacements |
| Prompt injection overrides safety rules | Webhook is deterministic — not LLM-based, not prompt-based |
