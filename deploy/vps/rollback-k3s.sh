#!/usr/bin/env bash
set -Eeuo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
namespace="${SUPPORTHR_NAMESPACE:-supporthr-oci}"
previous_file="${repo_dir}/deploy/vps/.previous-k3s-image"
current_file="${repo_dir}/deploy/vps/.current-k3s-image"

if [[ ! -s "${previous_file}" ]]; then
  echo "No previous K3s image has been recorded." >&2
  exit 1
fi

previous_image="$(<"${previous_file}")"
if [[ ! "${previous_image}" =~ ^ghcr\.io/techfutureaifpt/supporthr-backend:sha-[0-9a-f]{12}$ ]]; then
  echo "Recorded rollback image is invalid." >&2
  exit 1
fi

kubectl -n "${namespace}" set image deployment/supporthr-api api="${previous_image}"
kubectl -n "${namespace}" set image deployment/supporthr-worker worker="${previous_image}"
kubectl -n "${namespace}" rollout status deployment/supporthr-api --timeout=600s
kubectl -n "${namespace}" rollout status deployment/supporthr-worker --timeout=900s
printf '%s\n' "${previous_image}" > "${current_file}"
echo "Rolled back SupportHR K3s workloads to ${previous_image}."
