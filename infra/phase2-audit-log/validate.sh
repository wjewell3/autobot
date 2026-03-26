#!/usr/bin/env bash
# validate.sh — Verify Phase 2 audit logger is working.
set -euo pipefail

NAMESPACE="kagent"
RED='\033[0;31m'; GREEN='\033[0;32m'; NC='\033[0m'
pass() { echo -e "${GREEN}  ✓ $1${NC}"; }
fail() { echo -e "${RED}  ✗ $1${NC}"; FAILURES=$((FAILURES + 1)); }
FAILURES=0

echo "═══ Phase 2: Audit Logger Validation ═══"
echo ""

# 1. Pod is running
echo "1. Audit logger pod status..."
POD_STATUS=$(kubectl get pods -n "$NAMESPACE" -l app=audit-logger -o jsonpath='{.items[0].status.phase}' 2>/dev/null || echo "NotFound")
if [[ "$POD_STATUS" == "Running" ]]; then
  pass "Audit logger pod is Running"
else
  fail "Audit logger pod is not running (status: $POD_STATUS)"
fi

# 2. MCP server is registered
echo "2. RemoteMCPServer registration..."
if kubectl get remotemcpservers -n "$NAMESPACE" audit-logger &>/dev/null; then
  pass "audit-logger RemoteMCPServer exists"
else
  fail "audit-logger RemoteMCPServer not found"
fi

# 3. Check logs for watch activity
echo "3. Checking for watch activity in logs..."
LOG_OUTPUT=$(kubectl logs -n "$NAMESPACE" -l app=audit-logger --tail=20 2>/dev/null || echo "")
if echo "$LOG_OUTPUT" | grep -qi "AUDIT\|watcher\|Starting"; then
  pass "Audit logger is actively watching"
else
  fail "No watch activity detected in logs"
fi

echo ""
echo "═══════════════════════════════════════════════"
if [[ $FAILURES -eq 0 ]]; then
  echo -e "${GREEN}Phase 2 validation PASSED${NC}"
  exit 0
else
  echo -e "${RED}Phase 2 validation FAILED ($FAILURES failures)${NC}"
  exit 1
fi
