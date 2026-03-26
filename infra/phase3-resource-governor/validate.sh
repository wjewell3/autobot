#!/usr/bin/env bash
set -euo pipefail
NAMESPACE="kagent"
RED='\033[0;31m'; GREEN='\033[0;32m'; NC='\033[0m'
pass() { echo -e "${GREEN}  ✓ $1${NC}"; }
fail() { echo -e "${RED}  ✗ $1${NC}"; FAILURES=$((FAILURES + 1)); }
FAILURES=0

echo "═══ Phase 3: Resource Governor Validation ═══"
echo ""

echo "1. Resource governor pod status..."
POD_STATUS=$(kubectl get pods -n "$NAMESPACE" -l app=resource-governor -o jsonpath='{.items[0].status.phase}' 2>/dev/null || echo "NotFound")
if [[ "$POD_STATUS" == "Running" ]]; then
  pass "Resource governor pod is Running"
else
  fail "Resource governor pod is not running (status: $POD_STATUS)"
fi

echo "2. RemoteMCPServer registration..."
if kubectl get remotemcpservers -n "$NAMESPACE" resource-governor &>/dev/null; then
  pass "resource-governor RemoteMCPServer exists"
else
  fail "resource-governor RemoteMCPServer not found"
fi

echo "3. Budget enforcement loop active..."
LOG_OUTPUT=$(kubectl logs -n "$NAMESPACE" -l app=resource-governor --tail=10 2>/dev/null || echo "")
if echo "$LOG_OUTPUT" | grep -qi "enforcement\|budget\|Starting"; then
  pass "Budget enforcement loop is running"
else
  fail "No enforcement activity in logs"
fi

echo ""
if [[ $FAILURES -eq 0 ]]; then
  echo -e "${GREEN}Phase 3 validation PASSED${NC}"
else
  echo -e "${RED}Phase 3 validation FAILED ($FAILURES failures)${NC}"
fi
exit $FAILURES
