# Agent Memory Infrastructure

## Architecture

kagent agents use two separate memory systems:

### 1. Active Memory — `spec.declarative.memory` (v1alpha2, USED)

Configured on each Agent via `spec.declarative.memory.modelConfig: copilot-embedding`.

**Flow:**
1. On every request, the agent generates an embedding of the query and searches `/api/memories/search` on the kagent controller (pgvector-backed).
2. Relevant memories are injected into the agent's context as `<MEMORY>` blocks.
3. After the session ends, the agent summarizes and embeds the session content, then writes to `/api/memories/sessions/batch`.

**Storage:** kagent controller's built-in pgvector store (PostgreSQL). Vectors are 768-dimensional (truncated from 1536 with L2 normalization).

**TTL:** 30 days (`ttlDays: 30`).

**Embedding model:** `copilot-embedding` ModelConfig → LiteLLM → `text-embedding-3-small` via GitHub Copilot.

### 2. External Vector DB Memory — Memory CR (v1alpha1, PROVISIONED but SEPARATE)

The `Memory` CRD (v1alpha1) allows pointing agents to an external vector store (Pinecone). This is a **separate feature** from `spec.declarative.memory`.

See `memory-cr.yaml` for the provisioned Pinecone-backed Memory CR (`autobot-memory`).

> **Note:** The Pinecone Secret must be created imperatively (not from git):
> ```bash
> kubectl create secret generic pinecone-api-key \
>   --namespace kagent \
>   --from-literal=api-key="$PINECONE_API_KEY"
> ```

## Files

| File | Purpose |
|------|---------|
| `memory-model-config.yaml` | `copilot-embedding` ModelConfig — embedding model for active memory |
| `memory-cr.yaml` | `autobot-memory` Memory CR (v1alpha1) — Pinecone-backed, separate feature |

## Apply

The `memory-model-config.yaml` is also embedded in the root `deploy.yaml` (section 7). Apply it standalone:

```bash
kubectl apply -f infra/memory/memory-model-config.yaml
```
