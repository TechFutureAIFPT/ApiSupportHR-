#!/usr/bin/env bash
set -Eeuo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
compose_file="${repo_dir}/compose.production.yaml"
env_file="${repo_dir}/deploy/vps/runtime.env"
current_file="${repo_dir}/deploy/vps/.current-image"
previous_file="${repo_dir}/deploy/vps/.previous-image"

cd "${repo_dir}"

if [[ ! -f "${env_file}" ]]; then
  echo "Missing ${env_file}. Copy runtime.env.example and fill all production values." >&2
  exit 1
fi

if grep -Eq '(^|=)(replace-me|replace-with-|.*example\.com)' "${env_file}"; then
  echo "runtime.env still contains placeholder values." >&2
  exit 1
fi

read_env_value() {
  local key="$1"
  sed -n "s/^${key}=//p" "${env_file}" | tail -n 1 | tr -d '\r'
}

SUPPORTHR_IMAGE_REF="$(read_env_value SUPPORTHR_IMAGE_REF)"
API_DOMAIN="$(read_env_value API_DOMAIN)"
ACME_EMAIL="$(read_env_value ACME_EMAIL)"

: "${SUPPORTHR_IMAGE_REF:?SUPPORTHR_IMAGE_REF is required}"
: "${API_DOMAIN:?API_DOMAIN is required}"
: "${ACME_EMAIL:?ACME_EMAIL is required}"

if [[ -f "${current_file}" ]]; then
  cp "${current_file}" "${previous_file}"
fi
printf '%s\n' "${SUPPORTHR_IMAGE_REF}" > "${current_file}"

docker compose --env-file "${env_file}" -f "${compose_file}" config --quiet
docker compose --env-file "${env_file}" -f "${compose_file}" pull

if ! docker compose --env-file "${env_file}" -f "${compose_file}" up -d --remove-orphans --wait --wait-timeout 300; then
  echo "Deployment failed health checks." >&2
  if [[ -s "${previous_file}" ]]; then
    echo "Rolling back to $(<"${previous_file}")" >&2
    export SUPPORTHR_IMAGE_REF="$(<"${previous_file}")"
    docker compose --env-file "${env_file}" -f "${compose_file}" up -d --remove-orphans --wait --wait-timeout 300
    cp "${previous_file}" "${current_file}"
  fi
  exit 1
fi

curl --fail --silent --show-error --retry 6 --retry-delay 5 "https://${API_DOMAIN}/health/live" >/dev/null
docker image prune -f --filter "until=168h" >/dev/null
echo "SupportHR is healthy at https://${API_DOMAIN}"
