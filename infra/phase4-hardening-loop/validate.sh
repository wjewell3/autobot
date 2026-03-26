#!/usr/bin/env bash
set -euo pipefail
NAMESPACE="kagent"
RED='\033[0;31m'; GREEN='\033[0;32m'; NC='\033[0m'
pass() { echo -e "${GREEN}  ✓ $1${NC}"; }
fail() { echo -e "${RED}  ✗ $1${NC}"; FAILURES=$((FAILURES + 1)); }
FAILURES=0

echo "═══ Phase 4: Hardening Loop Validation ═══"
echo ""

echo "1. Hardening agent pod status..."
POD_STATUS=$(kubectl get pods -n "$NAMESPACE" -l app=hardening-agent -o jsonpath='{.items[0].status.phase}' 2>/dev/null || echo "NotFound")
if [[ "$POD_STATUS" == "Running" ]]; then
  pass "Hardening agent pod is Running"
else
  fail "Hardening agent pod is not running (status: $POD_STATUS)"
fi

echo "2. RemoteMCPServer registration..."
if kubectl get remotemcpservers -n "$NAMESPACE" hardening-agent &>/dev/null; then
  pass "hardening-agent RemoteMCPServer exists"
else
  fail "hardening-agent RemoteMCPServer not found"
fi

echo "3. Analysis loop active..."
LOG_OUTPUT=$(kubectl logs -n "$NAMESPACE" -l app=hardening-agent --tail=10 2>/dev/null || echo "")
if echo "$LOG_OUTPUT" | grep -qi "analysis\|hardening\|Starting\|patterns"; then
  pass "Analysis loop is running"
else
  fail "No analysis activity in logs"
fi

echo ""
if [[ $FAILURES -eq 0 ]]; then
  echo -e "${GREEN}Phase 4 validation PASSED${NC}"
else
  echo -e "${RED}Phase 4 validation FAILED ($FAILURES failures)${NC}"
fi
exit $FAILURES
