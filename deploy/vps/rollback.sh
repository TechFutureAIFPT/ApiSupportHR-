#!/usr/bin/env bash
set -Eeuo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
env_file="${repo_dir}/deploy/vps/runtime.env"
compose_file="${repo_dir}/compose.production.yaml"
previous_file="${repo_dir}/deploy/vps/.previous-image"
current_file="${repo_dir}/deploy/vps/.current-image"

if [[ ! -s "${previous_file}" ]]; then
  echo "No previous image has been recorded." >&2
  exit 1
fi

cd "${repo_dir}"
export SUPPORTHR_IMAGE_REF="$(<"${previous_file}")"
docker compose --env-file "${env_file}" -f "${compose_file}" pull backend worker
docker compose --env-file "${env_file}" -f "${compose_file}" up -d --remove-orphans --wait --wait-timeout 300
printf '%s\n' "${SUPPORTHR_IMAGE_REF}" > "${current_file}"
echo "Rolled back to ${SUPPORTHR_IMAGE_REF}"
