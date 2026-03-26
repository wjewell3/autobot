#!/usr/bin/env bash
# setup-certs.sh — Generate TLS certs for the admission webhook and
# create the Kubernetes secret. Run this ONCE before deploying.
#
# Usage: ./setup-certs.sh
# Requires: openssl, kubectl (configured for your cluster)

set -euo pipefail

NAMESPACE="${NAMESPACE:-kagent}"
SERVICE="agent-policy-server"
SECRET_NAME="agent-policy-tls"
WEBHOOK_NAME="agent-policy-webhook"
TMPDIR=$(mktemp -d)

echo "==> Generating CA key and cert..."
openssl genrsa -out "${TMPDIR}/ca.key" 2048 2>/dev/null
openssl req -x509 -new -nodes \
  -key "${TMPDIR}/ca.key" \
  -days 3650 \
  -out "${TMPDIR}/ca.crt" \
  -subj "/CN=${SERVICE}-ca" 2>/dev/null

echo "==> Generating server key and CSR..."
openssl genrsa -out "${TMPDIR}/server.key" 2048 2>/dev/null

# SAN config — K8s calls webhook via service DNS
cat > "${TMPDIR}/san.cnf" <<EOF
[req]
req_extensions = v3_req
distinguished_name = req_dn
prompt = no

[req_dn]
CN = ${SERVICE}.${NAMESPACE}.svc

[v3_req]
subjectAltName = @alt_names

[alt_names]
DNS.1 = ${SERVICE}
DNS.2 = ${SERVICE}.${NAMESPACE}
DNS.3 = ${SERVICE}.${NAMESPACE}.svc
DNS.4 = ${SERVICE}.${NAMESPACE}.svc.cluster.local
EOF

openssl req -new -nodes \
  -key "${TMPDIR}/server.key" \
  -out "${TMPDIR}/server.csr" \
  -config "${TMPDIR}/san.cnf" 2>/dev/null

echo "==> Signing server cert with CA..."
openssl x509 -req \
  -in "${TMPDIR}/server.csr" \
  -CA "${TMPDIR}/ca.crt" \
  -CAkey "${TMPDIR}/ca.key" \
  -CAcreateserial \
  -out "${TMPDIR}/server.crt" \
  -days 3650 \
  -extensions v3_req \
  -extfile "${TMPDIR}/san.cnf" 2>/dev/null

echo "==> Creating Kubernetes TLS secret '${SECRET_NAME}' in namespace '${NAMESPACE}'..."
kubectl create secret tls "${SECRET_NAME}" \
  --cert="${TMPDIR}/server.crt" \
  --key="${TMPDIR}/server.key" \
  --namespace="${NAMESPACE}" \
  --dry-run=client -o yaml | kubectl apply -f -

echo "==> Storing CA bundle for webhook configuration..."
CA_BUNDLE=$(base64 -w0 < "${TMPDIR}/ca.crt")

# Write CA bundle to a file so deploy.yaml can read it,
# and also directly patch the webhook if it exists already
echo "${CA_BUNDLE}" > "$(dirname "$0")/ca-bundle.b64"

if kubectl get validatingwebhookconfiguration "${WEBHOOK_NAME}" &>/dev/null; then
  echo "==> Patching existing webhook with CA bundle..."
  kubectl patch validatingwebhookconfiguration "${WEBHOOK_NAME}" \
    --type='json' \
    -p="[{\"op\":\"replace\",\"path\":\"/webhooks/0/clientConfig/caBundle\",\"value\":\"${CA_BUNDLE}\"}]"
fi

echo "==> Cleaning up temp files..."
rm -rf "${TMPDIR}"

echo ""
echo "✅ TLS certs generated and stored in secret '${SECRET_NAME}'"
echo "   CA bundle saved to: $(dirname "$0")/ca-bundle.b64"
echo ""
echo "Next: deploy the policy server and webhook:"
echo "  kubectl apply -f infra/phase1-admission-control/deploy.yaml"
