#!/usr/bin/env bash
# set-outreach-phase.sh — Toggle outreach-agent between TESTING and PRODUCTION modes.
#
# Usage:
#   ./scripts/set-outreach-phase.sh testing      # emails go to jewell.will@gmail.com
#   ./scripts/set-outreach-phase.sh production   # emails go to actual prospect addresses
#
# What this does:
#   1. Updates ACTIVE_PHASE in agents/outreach-agent.yaml
#   2. Applies the updated agent to the cluster
#   3. Updates a tracking ConfigMap (outreach-phase-config) so other agents can read current phase
#   4. Deletes the outreach-agent pod to force a system message reload

set -euo pipefail

PHASE="${1:-}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
AGENT_YAML="$REPO_ROOT/agents/outreach-agent.yaml"
NAMESPACE="kagent"
TEST_RECIPIENT="jewell.will@gmail.com"

usage() {
  echo "Usage: $0 [testing|production]"
  echo ""
  echo "  testing     All emails go to $TEST_RECIPIENT (safe for development)"
  echo "  production  Emails go to actual prospect email addresses (LIVE — real people)"
  exit 1
}

if [[ "$PHASE" != "testing" && "$PHASE" != "production" ]]; then
  usage
fi

PHASE_UPPER="${PHASE^^}"  # testing → TESTING

echo "→ Switching outreach-agent to phase: $PHASE_UPPER"

# 1. Update ACTIVE_PHASE line in the agent YAML
if ! grep -q "## ACTIVE_PHASE:" "$AGENT_YAML"; then
  echo "ERROR: Could not find '## ACTIVE_PHASE:' in $AGENT_YAML"
  exit 1
fi

# Use sed to replace the phase line in-place
sed -i "s/^      ## ACTIVE_PHASE: .*/      ## ACTIVE_PHASE: $PHASE_UPPER/" "$AGENT_YAML"

echo "  ✓ Updated ACTIVE_PHASE in agents/outreach-agent.yaml"

# 2. Apply updated agent to the cluster
echo "→ Applying agent to cluster..."
kubectl apply -f "$AGENT_YAML"
echo "  ✓ Agent applied"

# 3. Update (or create) the tracking ConfigMap
echo "→ Updating phase ConfigMap..."
kubectl create configmap outreach-phase-config \
  --namespace "$NAMESPACE" \
  --from-literal=mode="$PHASE" \
  --from-literal=test_recipient="$TEST_RECIPIENT" \
  --dry-run=client -o yaml | kubectl apply -f -
echo "  ✓ ConfigMap outreach-phase-config updated (mode=$PHASE)"

# 4. Force pod restart so the new system message is loaded
echo "→ Restarting outreach-agent pod..."
kubectl delete pod -l app=outreach-agent -n "$NAMESPACE" --ignore-not-found
echo "  ✓ Pod restarted"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  outreach-agent is now in: $PHASE_UPPER mode"
if [[ "$PHASE" == "testing" ]]; then
  echo "  All emails → $TEST_RECIPIENT"
  echo "  Subjects will be prefixed with [TEST]"
else
  echo "  ⚠️  PRODUCTION MODE — emails go to REAL prospect addresses"
  echo "  Ensure HITL approvals are being monitored in Slack"
fi
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
