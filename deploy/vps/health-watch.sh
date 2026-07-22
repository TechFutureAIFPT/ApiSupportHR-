#!/usr/bin/env bash
set -Eeuo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
compose_file="${repo_dir}/compose.production.yaml"
env_file="${repo_dir}/deploy/vps/runtime.env"
lock_file="/tmp/supporthr-health-watch.lock"

if [[ ! -f "${env_file}" ]]; then
  exit 0
fi

exec 9>"${lock_file}"
if ! flock -n 9; then
  exit 0
fi

compose=(docker compose --env-file "${env_file}" -f "${compose_file}")
expected=(redis backend worker caddy)
running="$("${compose[@]}" ps --status running --services 2>/dev/null || true)"
restart=()

for service in "${expected[@]}"; do
  if ! grep -Fxq "${service}" <<<"${running}"; then
    restart+=("${service}")
  fi
done

while IFS= read -r service; do
  [[ -n "${service}" ]] && restart+=("${service}")
done < <("${compose[@]}" ps --status unhealthy --services 2>/dev/null || true)

if ((${#restart[@]} > 0)); then
  mapfile -t restart < <(printf '%s\n' "${restart[@]}" | sort -u)
  "${compose[@]}" restart "${restart[@]}" || "${compose[@]}" up -d "${restart[@]}"
  "${compose[@]}" up -d --remove-orphans --wait --wait-timeout 180
fi

api_domain="$(sed -n 's/^API_DOMAIN=//p' "${env_file}" | tail -n 1 | tr -d '\r')"
if [[ -n "${api_domain}" ]]; then
  curl --fail --silent --show-error --max-time 15 "https://${api_domain}/health/live" >/dev/null
fi
