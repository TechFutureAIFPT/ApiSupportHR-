#!/usr/bin/env bash
set -Eeuo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
namespace="${SUPPORTHR_NAMESPACE:-supporthr-oci}"
current_file="${repo_dir}/deploy/vps/.current-k3s-image"
previous_file="${repo_dir}/deploy/vps/.previous-k3s-image"
image_ref="${SUPPORTHR_IMAGE_REF:-}"
api_domain="${API_DOMAIN:-}"
acme_email="${ACME_EMAIL:-}"

if [[ ! "${image_ref}" =~ ^ghcr\.io/techfutureaifpt/supporthr-backend:sha-[0-9a-f]{12}$ ]]; then
  echo "SUPPORTHR_IMAGE_REF must be an immutable SupportHR sha-* GHCR tag." >&2
  exit 1
fi
if [[ ! "${api_domain}" =~ ^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)+$ || ! "${api_domain}" =~ [a-z] ]]; then
  echo "API_DOMAIN must be a lowercase DNS hostname." >&2
  exit 1
fi
if [[ ! "${acme_email}" =~ ^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$ ]]; then
  echo "ACME_EMAIL has an invalid format." >&2
  exit 1
fi
kubectl auth can-i patch deployments -n "${namespace}" | grep -Fxq yes
kubectl create namespace "${namespace}" --dry-run=client -o yaml | kubectl apply -f -
kubectl -n "${namespace}" get secret supporthr-backend-secrets >/dev/null
kubectl -n "${namespace}" get secret ghcr-pull >/dev/null

previous_image=""
if [[ -s "${current_file}" ]]; then
  previous_image="$(<"${current_file}")"
else
  previous_image="$(kubectl -n "${namespace}" get deployment supporthr-api \
    -o jsonpath='{.spec.template.spec.containers[?(@.name=="api")].image}' 2>/dev/null || true)"
fi
if [[ -n "${previous_image}" && "${previous_image}" != "${image_ref}" ]]; then
  printf '%s\n' "${previous_image}" > "${previous_file}"
fi

work_dir="$(mktemp -d)"
cleanup() {
  rm -rf -- "${work_dir:?}"
}
trap cleanup EXIT

cp -R "${repo_dir}/deploy/kubernetes" "${work_dir}/kubernetes"
image_tag="${image_ref##*:}"
sed -i "s/newTag: replace-with-release-tag/newTag: ${image_tag}/" \
  "${work_dir}/kubernetes/overlays/oci-free/kustomization.yaml"
sed -i "s/api\.example\.com/${api_domain}/g" \
  "${work_dir}/kubernetes/overlays/oci-free/ingress.yaml"
sed "s/admin@example\.com/${acme_email}/" \
  "${work_dir}/kubernetes/overlays/oci-free/clusterissuer.example.yaml" \
  > "${work_dir}/clusterissuer.yaml"
if grep -Eq 'replace-with-release-tag|api\.example\.com|admin@example\.com' \
  "${work_dir}/kubernetes/overlays/oci-free/kustomization.yaml" \
  "${work_dir}/kubernetes/overlays/oci-free/ingress.yaml" \
  "${work_dir}/clusterissuer.yaml"; then
  echo "A production K3s placeholder remained after rendering." >&2
  exit 1
fi
kubectl kustomize "${work_dir}/kubernetes/overlays/oci-free" >/dev/null

rollback_on_error() {
  exit_code=$?
  trap - ERR
  echo "K3s deployment failed. Collecting safe diagnostics." >&2
  kubectl -n "${namespace}" get pods,deployments,statefulsets,ingress -o wide >&2 || true
  kubectl -n "${namespace}" get events --sort-by=.lastTimestamp | tail -n 40 >&2 || true
  if [[ -n "${previous_image}" && "${previous_image}" =~ ^ghcr\.io/techfutureaifpt/supporthr-backend:sha-[0-9a-f]{12}$ ]]; then
    echo "Rolling back API and worker to ${previous_image}." >&2
    kubectl -n "${namespace}" set image deployment/supporthr-api api="${previous_image}" >&2 || true
    kubectl -n "${namespace}" set image deployment/supporthr-worker worker="${previous_image}" >&2 || true
    kubectl -n "${namespace}" rollout status deployment/supporthr-api --timeout=600s >&2 || true
    kubectl -n "${namespace}" rollout status deployment/supporthr-worker --timeout=900s >&2 || true
    printf '%s\n' "${previous_image}" > "${current_file}"
  fi
  exit "${exit_code}"
}
trap rollback_on_error ERR

kubectl rollout status deployment/cert-manager -n cert-manager --timeout=300s
kubectl rollout status deployment/cert-manager-webhook -n cert-manager --timeout=300s
kubectl apply -f "${work_dir}/clusterissuer.yaml"
kubectl apply -k "${work_dir}/kubernetes/overlays/oci-free"

kubectl -n "${namespace}" rollout status statefulset/redis --timeout=300s
kubectl -n "${namespace}" rollout status deployment/supporthr-api --timeout=600s
kubectl -n "${namespace}" rollout status deployment/supporthr-worker --timeout=900s
kubectl -n "${namespace}" wait --for=condition=Ready pods --all --timeout=300s

curl --fail --silent --show-error --retry 12 --retry-delay 5 --retry-all-errors \
  "https://${api_domain}/health/live" >/dev/null
curl --fail --silent --show-error --retry 12 --retry-delay 5 --retry-all-errors \
  "https://${api_domain}/health/ready" >/dev/null

printf '%s\n' "${image_ref}" > "${current_file}"
trap - ERR
echo "SupportHR K3s release ${image_ref} is healthy at https://${api_domain}."
