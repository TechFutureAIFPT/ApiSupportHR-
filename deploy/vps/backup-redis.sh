#!/usr/bin/env bash
set -Eeuo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
backup_dir="${repo_dir}/deploy/vps/backups"
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
archive="${backup_dir}/supporthr-redis-${timestamp}.tar.gz"
env_file="${repo_dir}/deploy/vps/runtime.env"
compose_file="${repo_dir}/compose.production.yaml"

mkdir -p "${backup_dir}"
docker compose --env-file "${env_file}" -f "${compose_file}" exec -T redis redis-cli SAVE >/dev/null
docker run --rm \
  -v supporthr-redis-data:/data:ro \
  -v "${backup_dir}:/backup" \
  alpine:3.22 \
  tar -czf "/backup/$(basename "${archive}")" -C /data .

find "${backup_dir}" -type f -name 'supporthr-redis-*.tar.gz' -mtime +14 -delete
echo "Created ${archive}"
