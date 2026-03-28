#!/bin/bash
# ── Deploy Phase 5-9 Infrastructure ─────────────────────
#
# Deploys all new structural + verification infrastructure:
#   Phase 5: Rules Engine (makes hardening loop execute at runtime)
#   Phase 6: Eval Harness (measures quality before/after changes)
#   Phase 7: Business Module / Playbook Server (decouples from PoC)
#   Phase 8: Shared State Server (blackboard for agent coordination)
#   Phase 9: Adversarial Tester (proves governance works)
#
# Prerequisites: Phases 1-4 already deployed.
# Run from repo root: bash infra/deploy-phases-5-9.sh

set -euo pipefail
NAMESPACE="kagent"

echo "=== Phase 5: Rules Engine ==="
kubectl create configmap rules-engine-code \
  --from-file=server.py=infra/phase5-rules-engine/rules-engine.py \
  --namespace "$NAMESPACE" --dry-run=client -o yaml | kubectl apply -f -
kubectl create configmap rules-engine-rules \
  --from-file=rules.yaml=infra/phase5-rules-engine/rules.yaml \
  --namespace "$NAMESPACE" --dry-run=client -o yaml | kubectl apply -f -
kubectl apply -f infra/phase5-rules-engine/deploy.yaml
echo "  ✓ Rules engine deployed (port 8095)"

echo ""
echo "=== Phase 6: Eval Harness ==="
kubectl create configmap eval-harness-code \
  --from-file=server.py=infra/phase6-eval-harness/eval-harness.py \
  --namespace "$NAMESPACE" --dry-run=client -o yaml | kubectl apply -f -
kubectl create configmap eval-harness-cases \
  --from-file=cases.yaml=infra/phase6-eval-harness/cases.yaml \
  --namespace "$NAMESPACE" --dry-run=client -o yaml | kubectl apply -f -
kubectl apply -f infra/phase6-eval-harness/deploy.yaml
echo "  ✓ Eval harness deployed (port 8096)"

echo ""
echo "=== Phase 7: Business Module / Playbook Server ==="
kubectl create configmap playbook-server-code \
  --from-file=server.py=infra/phase7-business-modules/playbook-server.py \
  --namespace "$NAMESPACE" --dry-run=client -o yaml | kubectl apply -f -
kubectl create configmap business-playbooks \
  --from-file=playbooks.yaml=infra/phase7-business-modules/playbooks.yaml \
  --namespace "$NAMESPACE" --dry-run=client -o yaml | kubectl apply -f -
kubectl apply -f infra/phase7-business-modules/deploy.yaml
echo "  ✓ Playbook server deployed (port 8099)"

echo ""
echo "=== Phase 8: Shared State Server ==="
kubectl create configmap shared-state-code \
  --from-file=server.py=infra/phase8-shared-state/shared-state.py \
  --namespace "$NAMESPACE" --dry-run=client -o yaml | kubectl apply -f -
kubectl apply -f infra/phase8-shared-state/deploy.yaml
echo "  ✓ Shared state server deployed (port 8097)"

echo ""
echo "=== Phase 9: Adversarial Tester ==="
kubectl create configmap adversarial-tester-code \
  --from-file=server.py=infra/phase9-adversarial-testing/adversarial-tester.py \
  --namespace "$NAMESPACE" --dry-run=client -o yaml | kubectl apply -f -
kubectl create configmap adversarial-tests \
  --from-file=tests.yaml=infra/phase9-adversarial-testing/tests.yaml \
  --namespace "$NAMESPACE" --dry-run=client -o yaml | kubectl apply -f -
kubectl apply -f infra/phase9-adversarial-testing/deploy.yaml
echo "  ✓ Adversarial tester deployed (port 8098)"

echo ""
echo "=== Updating Capability Registry ==="
kubectl create configmap capability-registry \
  --from-file=capability-registry.yaml=infra/phase1-admission-control/capability-registry.yaml \
  -n "$NAMESPACE" --dry-run=client -o yaml | kubectl apply -f -
kubectl rollout restart deployment/agent-policy-server -n "$NAMESPACE"
kubectl rollout status deployment/agent-policy-server -n "$NAMESPACE" --timeout=60s
echo "  ✓ Capability registry updated (webhook ready)"

echo ""
echo "=== Updating Agent YAMLs (tools wiring) ==="
kubectl apply -f agents/pm-agent.yaml
kubectl apply -f agents/rd-agent.yaml
kubectl apply -f agents/north-star-agent.yaml
echo "  ✓ Agents updated with new tool references"

echo ""
echo "=== Verifying Deployments ==="
sleep 5
echo "Pods:"
kubectl get pods -n "$NAMESPACE" -l "app in (rules-engine,eval-harness,playbook-server,shared-state,adversarial-tester)" --no-headers
echo ""
echo "RemoteMCPServers:"
kubectl get remotemcpservers -n "$NAMESPACE" | grep -E "rules-engine|eval-harness|playbook-server|shared-state|adversarial-tester" || echo "  (may take a moment to register)"

echo ""
echo "=== All Phase 5-9 infrastructure deployed ==="
echo ""
echo "New MCP Servers:"
echo "  rules-engine       :8095  — Executes approved hardening rules at runtime"
echo "  eval-harness       :8096  — Measures agent quality before/after changes"
echo "  playbook-server    :8099  — Business playbook config for pipeline agents"
echo "  shared-state       :8097  — Blackboard for agent coordination"
echo "  adversarial-tester :8098  — Feeds bad inputs to prove governance works"
echo ""
echo ""
echo "=== Setting Eval Baselines ==="
kubectl delete job set-eval-baselines -n "$NAMESPACE" 2>/dev/null || true
kubectl apply -f infra/phase6-eval-harness/set-baselines-job.yaml
echo "  ✓ Baseline job started (kubectl logs job/set-eval-baselines -n kagent -f)"

echo ""
echo "=== Deploying Adversarial Sweep CronJob ==="
kubectl apply -f infra/phase9-adversarial-testing/adversarial-cronjob.yaml
echo "  ✓ Adversarial sweep scheduled (Mondays 3am UTC)"
echo "  ✓ Manual trigger: kubectl create job adversarial-sweep-manual --from=cronjob/adversarial-sweep -n kagent"

echo ""
echo "=== All Phase 5-9 infrastructure deployed ==="
echo ""
echo "Automated:"
echo "  rules-engine       :8095  — active/shadow rules execute automatically per agent call"
echo "  playbook-server    :8099  — pm-agent reads config on every pipeline run"
echo "  shared-state       :8097  — pm-agent writes pipeline state automatically"
echo "  eval baselines     job    — capturing now (watch: kubectl logs job/set-eval-baselines -n kagent -f)"
echo "  adversarial sweep  cron   — runs weekly Mondays 3am UTC, posts to #agent-workers"
echo ""
echo "One-time after baseline job completes:"
echo "  Approve first hardening rules: edit infra/phase5-rules-engine/rules.yaml, set status: shadow"
echo "  Re-run baselines anytime: kubectl delete job set-eval-baselines -n kagent && kubectl apply -f ..."
