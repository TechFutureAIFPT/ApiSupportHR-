#!/usr/bin/env bash
set -Eeuo pipefail

namespace="${SUPPORTHR_NAMESPACE:-supporthr-oci}"
runtime_env="${SUPPORTHR_RUNTIME_ENV:-/opt/supporthr/shared/supporthr-secret.env}"

if [[ ! -f "${runtime_env}" ]]; then
  echo "Missing ${runtime_env}." >&2
  echo "Copy deploy/vps/k3s-secret.env.example there and fill every production value." >&2
  exit 1
fi
if grep -Eq 'replace-me|replace-with-|your-project|api\.example\.com' "${runtime_env}"; then
  echo "${runtime_env} still contains placeholder values." >&2
  exit 1
fi

kubectl create namespace "${namespace}" --dry-run=client -o yaml | kubectl apply -f -
kubectl -n "${namespace}" create secret generic supporthr-backend-secrets \
  --from-env-file="${runtime_env}" \
  --dry-run=client -o yaml | kubectl apply -f -

read -r -p "GitHub username for GHCR: " ghcr_username
read -r -s -p "GHCR token with read:packages: " ghcr_token
printf '\n'

if [[ ! "${ghcr_username}" =~ ^[A-Za-z0-9][A-Za-z0-9-]{0,38}$ || -z "${ghcr_token}" ]]; then
  unset ghcr_token
  echo "A valid GitHub username and GHCR token are required for the private image." >&2
  exit 1
fi

docker_config="$(mktemp)"
cleanup() {
  unset ghcr_token registry_auth
  rm -f "${docker_config}"
}
trap cleanup EXIT
chmod 600 "${docker_config}"
registry_auth="$(printf '%s' "${ghcr_username}:${ghcr_token}" | base64 | tr -d '\r\n')"
printf '{"auths":{"ghcr.io":{"auth":"%s"}}}\n' "${registry_auth}" > "${docker_config}"

kubectl -n "${namespace}" create secret generic ghcr-pull \
  --type=kubernetes.io/dockerconfigjson \
  --from-file=.dockerconfigjson="${docker_config}" \
  --dry-run=client -o yaml | kubectl apply -f -
cleanup
trap - EXIT

chmod 600 "${runtime_env}"
echo "Kubernetes runtime and GHCR pull secrets are ready in namespace ${namespace}."
