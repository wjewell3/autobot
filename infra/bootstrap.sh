#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════
# bootstrap.sh — Deploy the Autobot safety infrastructure
#
# Deploys 4 phases in order, each building on the last:
#   Phase 1: Admission Control (deterministic agent policy)
#   Phase 2: Audit Logger (independent activity trail)
#   Phase 3: Resource Governor (token/action budgets)
#   Phase 4: Hardening Loop (LLM → deterministic conversion)
#
# Usage:
#   ./bootstrap.sh              # Deploy all phases
#   ./bootstrap.sh 1            # Deploy only phase 1
#   ./bootstrap.sh 2 4          # Deploy phases 2 through 4
#   ./bootstrap.sh validate     # Run all validation checks
#   ./bootstrap.sh teardown     # Remove all infra components
#
# Prerequisites:
#   - kubectl configured and pointing at your OKE cluster
#   - kagent namespace exists with agents already running
#   - openssl available (for TLS cert generation)
#
# This script is idempotent — safe to run multiple times.
# ═══════════════════════════════════════════════════════════

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
NAMESPACE="kagent"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
BOLD='\033[1m'
NC='\033[0m'

info()  { echo -e "${BLUE}[INFO]${NC}  $1"; }
ok()    { echo -e "${GREEN}[OK]${NC}    $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $1"; }
err()   { echo -e "${RED}[ERROR]${NC} $1"; }
header(){ echo -e "\n${BOLD}═══ $1 ═══${NC}\n"; }

# ── Preflight checks ────────────────────────────────────

preflight() {
    info "Running preflight checks..."

    if ! command -v kubectl &>/dev/null; then
        err "kubectl not found in PATH"
        exit 1
    fi

    if ! kubectl get namespace "$NAMESPACE" &>/dev/null; then
        err "Namespace '$NAMESPACE' does not exist"
        exit 1
    fi

    if ! kubectl get crd agents.kagent.dev &>/dev/null; then
        err "kagent CRDs not installed (agents.kagent.dev not found)"
        exit 1
    fi

    AGENT_COUNT=$(kubectl get agents -n "$NAMESPACE" --no-headers 2>/dev/null | wc -l)
    info "Found $AGENT_COUNT existing agents in namespace '$NAMESPACE'"

    if ! command -v openssl &>/dev/null; then
        err "openssl not found — required for Phase 1 TLS certs"
        exit 1
    fi

    ok "Preflight checks passed"
}

# ── Helper: create ConfigMap from file ───────────────────

create_configmap_from_file() {
    local cm_name="$1"
    local key="$2"
    local file_path="$3"

    if [[ ! -f "$file_path" ]]; then
        err "File not found: $file_path"
        return 1
    fi

    info "Creating ConfigMap '$cm_name' from $(basename "$file_path")..."
    kubectl create configmap "$cm_name" \
        --from-file="${key}=${file_path}" \
        --namespace="$NAMESPACE" \
        --dry-run=client -o yaml | kubectl apply -f -
}

# ── Helper: wait for deployment ──────────────────────────

wait_for_deployment() {
    local name="$1"
    local timeout="${2:-120}"

    info "Waiting for deployment '$name' to be ready (timeout: ${timeout}s)..."
    if kubectl rollout status deployment/"$name" \
        -n "$NAMESPACE" --timeout="${timeout}s" 2>/dev/null; then
        ok "Deployment '$name' is ready"
    else
        err "Deployment '$name' did not become ready within ${timeout}s"
        warn "Check logs: kubectl logs -n $NAMESPACE -l app=$name --tail=30"
        return 1
    fi
}

# ── Helper: label existing agents for migration ─────────

label_existing_agents() {
    info "Adding 'hitl-reviewed: true' label to existing agents..."
    local agents
    agents=$(kubectl get agents -n "$NAMESPACE" --no-headers -o custom-columns=":metadata.name" 2>/dev/null)

    for agent in $agents; do
        kubectl label agent "$agent" -n "$NAMESPACE" hitl-reviewed=true --overwrite 2>/dev/null || true
        ok "Labeled $agent"
    done
}

# ═══════════════════════════════════════════════════════════
# PHASE 1: Admission Control
# ═══════════════════════════════════════════════════════════

deploy_phase1() {
    header "Phase 1: Admission Control"
    local phase_dir="${SCRIPT_DIR}/phase1-admission-control"

    # Step 1: Label existing agents BEFORE enabling the webhook.
    # The webhook requires hitl-reviewed=true on agents with MCP tools.
    # Existing agents don't have this label yet — they'd be locked out
    # on any update if we don't label them first.
    label_existing_agents

    # Step 2: Create ConfigMaps from source files
    create_configmap_from_file \
        "agent-policy-server-code" \
        "server.py" \
        "${phase_dir}/policy-server.py"

    create_configmap_from_file \
        "capability-registry" \
        "capability-registry.yaml" \
        "${phase_dir}/capability-registry.yaml"

    # Step 3: Generate TLS certs (idempotent — applies with dry-run)
    info "Generating TLS certificates..."
    bash "${phase_dir}/setup-certs.sh"

    # Step 4: Deploy the policy server + RBAC + service
    # But skip the webhook config initially — let the server start first
    info "Deploying policy server (without webhook)..."
    kubectl apply -f "${phase_dir}/deploy.yaml"

    # Step 5: Wait for the policy server to be ready
    wait_for_deployment "agent-policy-server" 120

    # Step 6: Now inject the CA bundle into the webhook and apply
    local ca_bundle_file="${phase_dir}/ca-bundle.b64"
    if [[ -f "$ca_bundle_file" ]]; then
        local ca_bundle
        ca_bundle=$(cat "$ca_bundle_file")
        info "Patching webhook with CA bundle..."
        kubectl patch validatingwebhookconfiguration agent-policy-webhook \
            --type='json' \
            -p="[{\"op\":\"replace\",\"path\":\"/webhooks/0/clientConfig/caBundle\",\"value\":\"${ca_bundle}\"}]" \
            2>/dev/null || true
    else
        warn "CA bundle file not found — webhook may not work until setup-certs.sh is re-run"
    fi

    ok "Phase 1 deployed"
    echo ""
    info "The admission webhook is now ACTIVE. Agent CRs are validated against"
    info "the capability registry. To test:"
    info "  bash ${phase_dir}/validate.sh"
}

# ═══════════════════════════════════════════════════════════
# PHASE 2: Audit Logger
# ═══════════════════════════════════════════════════════════

deploy_phase2() {
    header "Phase 2: Audit Logger"
    local phase_dir="${SCRIPT_DIR}/phase2-audit-log"

    # Create ConfigMap from source
    create_configmap_from_file \
        "audit-logger-code" \
        "server.py" \
        "${phase_dir}/audit-logger.py"

    # Deploy
    info "Deploying audit logger..."
    kubectl apply -f "${phase_dir}/deploy.yaml"

    wait_for_deployment "audit-logger" 120

    # Update capability registry to allow commander to use audit tools
    # (The registry is already deployed from Phase 1, just needs the tool refs)
    info "Note: To give agents access to audit tools, add 'audit-logger/write_audit'"
    info "      and 'audit-logger/get_recent_audit' to their allowed_tools in the"
    info "      capability registry, then re-run Phase 1 ConfigMap creation."

    ok "Phase 2 deployed"
}

# ═══════════════════════════════════════════════════════════
# PHASE 3: Resource Governor
# ═══════════════════════════════════════════════════════════

deploy_phase3() {
    header "Phase 3: Resource Governor"
    local phase_dir="${SCRIPT_DIR}/phase3-resource-governor"

    # Create ConfigMaps
    create_configmap_from_file \
        "resource-governor-code" \
        "server.py" \
        "${phase_dir}/resource-governor.py"

    create_configmap_from_file \
        "governor-budgets" \
        "budgets.yaml" \
        "${phase_dir}/budgets.yaml"

    # Deploy
    info "Deploying resource governor..."
    kubectl apply -f "${phase_dir}/deploy.yaml"

    wait_for_deployment "resource-governor" 120

    ok "Phase 3 deployed"
}

# ═══════════════════════════════════════════════════════════
# PHASE 4: Hardening Loop
# ═══════════════════════════════════════════════════════════

deploy_phase4() {
    header "Phase 4: Hardening Loop"
    local phase_dir="${SCRIPT_DIR}/phase4-hardening-loop"

    # Create ConfigMaps
    create_configmap_from_file \
        "hardening-agent-code" \
        "server.py" \
        "${phase_dir}/hardening-agent.py"

    create_configmap_from_file \
        "hardening-rules" \
        "rules.yaml" \
        "${phase_dir}/rules.yaml"

    # Deploy
    info "Deploying hardening agent..."
    kubectl apply -f "${phase_dir}/deploy.yaml"

    wait_for_deployment "hardening-agent" 120

    ok "Phase 4 deployed"
}

# ═══════════════════════════════════════════════════════════
# VALIDATE
# ═══════════════════════════════════════════════════════════

validate_all() {
    header "Running All Validations"
    local failures=0

    for phase_dir in "${SCRIPT_DIR}"/phase*/; do
        local validate_script="${phase_dir}validate.sh"
        if [[ -f "$validate_script" ]]; then
            echo ""
            if bash "$validate_script"; then
                ok "$(basename "$phase_dir") passed"
            else
                err "$(basename "$phase_dir") failed"
                failures=$((failures + 1))
            fi
        fi
    done

    echo ""
    if [[ $failures -eq 0 ]]; then
        ok "All validations passed"
    else
        err "$failures phase(s) failed validation"
        exit 1
    fi
}

# ═══════════════════════════════════════════════════════════
# TEARDOWN
# ═══════════════════════════════════════════════════════════

teardown() {
    header "Teardown: Removing Safety Infrastructure"

    warn "This will remove ALL safety infrastructure components."
    warn "Your agents will continue running but WITHOUT policy enforcement."
    echo ""
    read -rp "Are you sure? (type 'yes' to confirm): " confirm
    if [[ "$confirm" != "yes" ]]; then
        info "Teardown cancelled."
        exit 0
    fi

    echo ""

    # Phase 4
    info "Removing Phase 4 (hardening loop)..."
    kubectl delete remotemcpserver hardening-agent -n "$NAMESPACE" 2>/dev/null || true
    kubectl delete deployment hardening-agent -n "$NAMESPACE" 2>/dev/null || true
    kubectl delete service hardening-agent -n "$NAMESPACE" 2>/dev/null || true
    kubectl delete configmap hardening-agent-code hardening-rules -n "$NAMESPACE" 2>/dev/null || true

    # Phase 3
    info "Removing Phase 3 (resource governor)..."
    kubectl delete remotemcpserver resource-governor -n "$NAMESPACE" 2>/dev/null || true
    kubectl delete deployment resource-governor -n "$NAMESPACE" 2>/dev/null || true
    kubectl delete service resource-governor -n "$NAMESPACE" 2>/dev/null || true
    kubectl delete configmap resource-governor-code governor-budgets -n "$NAMESPACE" 2>/dev/null || true

    # Phase 2
    info "Removing Phase 2 (audit logger)..."
    kubectl delete remotemcpserver audit-logger -n "$NAMESPACE" 2>/dev/null || true
    kubectl delete deployment audit-logger -n "$NAMESPACE" 2>/dev/null || true
    kubectl delete service audit-logger -n "$NAMESPACE" 2>/dev/null || true
    kubectl delete configmap audit-logger-code -n "$NAMESPACE" 2>/dev/null || true

    # Phase 1
    info "Removing Phase 1 (admission control)..."
    kubectl delete validatingwebhookconfiguration agent-policy-webhook 2>/dev/null || true
    kubectl delete deployment agent-policy-server -n "$NAMESPACE" 2>/dev/null || true
    kubectl delete service agent-policy-server -n "$NAMESPACE" 2>/dev/null || true
    kubectl delete configmap agent-policy-server-code capability-registry -n "$NAMESPACE" 2>/dev/null || true
    kubectl delete secret agent-policy-tls -n "$NAMESPACE" 2>/dev/null || true
    kubectl delete serviceaccount agent-policy-server -n "$NAMESPACE" 2>/dev/null || true
    kubectl delete role agent-policy-reader -n "$NAMESPACE" 2>/dev/null || true
    kubectl delete rolebinding agent-policy-reader-binding -n "$NAMESPACE" 2>/dev/null || true

    ok "All safety infrastructure removed"
    warn "Agents are now running without policy enforcement!"
}

# ═══════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════

main() {
    echo -e "${BOLD}"
    echo "╔═══════════════════════════════════════════════╗"
    echo "║  Autobot Safety Infrastructure Bootstrap      ║"
    echo "║  4 phases · each builds on the last           ║"
    echo "╚═══════════════════════════════════════════════╝"
    echo -e "${NC}"

    local cmd="${1:-all}"

    case "$cmd" in
        validate)
            validate_all
            ;;
        teardown)
            teardown
            ;;
        all)
            preflight
            deploy_phase1
            deploy_phase2
            deploy_phase3
            deploy_phase4
            echo ""
            header "Deployment Complete"
            info "Run './bootstrap.sh validate' to verify everything is working."
            info "Run './bootstrap.sh teardown' to remove everything."
            ;;
        [1-4])
            local start="$cmd"
            local end="${2:-$start}"
            preflight
            for phase in $(seq "$start" "$end"); do
                "deploy_phase${phase}"
            done
            echo ""
            ok "Phase(s) $start-$end deployed"
            ;;
        *)
            echo "Usage: $0 [all|1|2|3|4|validate|teardown]"
            echo ""
            echo "  all       Deploy all phases (default)"
            echo "  1-4       Deploy specific phase(s): $0 2 4 deploys phases 2-4"
            echo "  validate  Run validation checks on all deployed phases"
            echo "  teardown  Remove all safety infrastructure"
            exit 1
            ;;
    esac
}

main "$@"
