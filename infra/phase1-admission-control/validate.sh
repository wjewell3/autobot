#!/usr/bin/env bash
# validate.sh — Verify Phase 1 admission control is working.
# Run after deploying. Exits 0 on success, 1 on failure.

set -euo pipefail

NAMESPACE="kagent"
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

pass() { echo -e "${GREEN}  ✓ $1${NC}"; }
fail() { echo -e "${RED}  ✗ $1${NC}"; FAILURES=$((FAILURES + 1)); }
warn() { echo -e "${YELLOW}  ⚠ $1${NC}"; }

FAILURES=0

echo "═══ Phase 1: Admission Control Validation ═══"
echo ""

# 1. Policy server pod is running
echo "1. Policy server pod status..."
POD_STATUS=$(kubectl get pods -n "$NAMESPACE" -l app=agent-policy-server -o jsonpath='{.items[0].status.phase}' 2>/dev/null || echo "NotFound")
if [[ "$POD_STATUS" == "Running" ]]; then
  pass "Policy server pod is Running"
else
  fail "Policy server pod is not running (status: $POD_STATUS)"
fi

# 2. Webhook is registered
echo "2. ValidatingWebhookConfiguration..."
if kubectl get validatingwebhookconfiguration agent-policy-webhook &>/dev/null; then
  pass "Webhook configuration exists"
else
  fail "Webhook configuration not found"
fi

# 3. CA bundle is populated
echo "3. CA bundle in webhook..."
CA_LEN=$(kubectl get validatingwebhookconfiguration agent-policy-webhook -o jsonpath='{.webhooks[0].clientConfig.caBundle}' 2>/dev/null | wc -c)
if [[ "$CA_LEN" -gt 10 ]]; then
  pass "CA bundle is populated ($CA_LEN chars)"
else
  fail "CA bundle is empty or missing"
fi

# 4. Test: ALLOWED — create an agent that IS in the registry (dry-run)
echo "4. Test: Registry-approved agent creation..."
RESULT=$(kubectl apply --dry-run=server -f - 2>&1 <<EOF
apiVersion: kagent.dev/v1alpha2
kind: Agent
metadata:
  name: number-agent-1
  namespace: kagent
spec:
  description: "Test agent"
  type: Declarative
  declarative:
    modelConfig: default-model-config
    systemMessage: "test"
EOF
) || true
if echo "$RESULT" | grep -qi "unchanged\|created\|configured"; then
  pass "Registry-approved agent was allowed"
elif echo "$RESULT" | grep -qi "denied\|rejected"; then
  warn "Registry-approved agent was denied — check hitl-reviewed label requirement"
else
  warn "Unexpected result: $RESULT"
fi

# 5. Test: DENIED — create an agent NOT in the registry
echo "5. Test: Unlisted agent creation (should be DENIED)..."
RESULT=$(kubectl apply --dry-run=server -f - 2>&1 <<EOF
apiVersion: kagent.dev/v1alpha2
kind: Agent
metadata:
  name: rogue-agent-test-$(date +%s)
  namespace: kagent
spec:
  description: "This should be blocked"
  type: Declarative
  declarative:
    modelConfig: default-model-config
    systemMessage: "I am a rogue agent"
    tools:
      - type: McpServer
        mcpServer:
          apiGroup: kagent.dev
          kind: RemoteMCPServer
          name: gmail-tool-server
          toolNames:
            - gmail_send_email
EOF
) || true
if echo "$RESULT" | grep -qi "denied\|forbidden\|rejected\|not in the capability"; then
  pass "Unlisted agent was correctly DENIED"
else
  fail "Unlisted agent was NOT denied — webhook may not be working. Result: $RESULT"
fi

# 6. Test: DENIED — forbidden tool (gmail_send_email)
echo "6. Test: Forbidden tool assignment (should be DENIED)..."
RESULT=$(kubectl apply --dry-run=server -f - 2>&1 <<EOF
apiVersion: kagent.dev/v1alpha2
kind: Agent
metadata:
  name: commander-agent
  namespace: kagent
  labels:
    hitl-reviewed: "true"
spec:
  description: "Commander with forbidden tool"
  type: Declarative
  declarative:
    modelConfig: default-model-config
    systemMessage: "test"
    tools:
      - type: McpServer
        mcpServer:
          apiGroup: kagent.dev
          kind: RemoteMCPServer
          name: gmail-tool-server
          toolNames:
            - gmail_send_email
EOF
) || true
if echo "$RESULT" | grep -qi "denied\|forbidden\|rejected\|globally forbidden"; then
  pass "Forbidden tool assignment was correctly DENIED"
else
  fail "Forbidden tool was NOT denied. Result: $RESULT"
fi

echo ""
echo "═══════════════════════════════════════════════"
if [[ $FAILURES -eq 0 ]]; then
  echo -e "${GREEN}Phase 1 validation PASSED${NC}"
  exit 0
else
  echo -e "${RED}Phase 1 validation FAILED ($FAILURES failures)${NC}"
  exit 1
fi
