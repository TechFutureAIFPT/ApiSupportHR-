#!/usr/bin/env bash
set -Eeuo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run this script with sudo on the new Ubuntu VPS." >&2
  exit 1
fi

# shellcheck disable=SC1091
source /etc/os-release
if [[ "${ID:-}" != "ubuntu" ]]; then
  echo "This bootstrap supports Ubuntu only." >&2
  exit 1
fi

admin_user="${SUPPORTHR_ADMIN_USER:-${SUDO_USER:-}}"
ssh_port="${SSH_PORT:-22}"
if [[ -z "${admin_user}" || "${admin_user}" == "root" ]] || ! id "${admin_user}" >/dev/null 2>&1; then
  echo "Set SUPPORTHR_ADMIN_USER to the non-root SSH account." >&2
  exit 1
fi
if [[ ! "${ssh_port}" =~ ^[0-9]{1,5}$ ]]; then
  echo "SSH_PORT must be numeric." >&2
  exit 1
fi
ssh_port_number=$((10#${ssh_port}))
if ((ssh_port_number < 1 || ssh_port_number > 65535)); then
  echo "SSH_PORT must be between 1 and 65535." >&2
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y ca-certificates curl gnupg ufw unattended-upgrades

install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
docker_codename="${UBUNTU_CODENAME:-${VERSION_CODENAME}}"
printf '%s\n' \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${docker_codename} stable" \
  > /etc/apt/sources.list.d/docker.list

apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
systemctl enable --now docker
systemctl enable --now unattended-upgrades
usermod -aG docker "${admin_user}"

install -d -m 0750 -o "${admin_user}" -g "${admin_user}" /opt/supporthr/backend
install -d -m 0750 -o "${admin_user}" -g "${admin_user}" /opt/supporthr/shared

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
install -m 0644 "${script_dir}/systemd/supporthr-health.service" /etc/systemd/system/supporthr-health.service
install -m 0644 "${script_dir}/systemd/supporthr-health.timer" /etc/systemd/system/supporthr-health.timer
systemctl daemon-reload
systemctl enable --now supporthr-health.timer

ufw default deny incoming
ufw default allow outgoing
ufw allow "${ssh_port}/tcp"
ufw allow 80/tcp
ufw allow 443/tcp
ufw allow 443/udp
ufw --force enable

echo "Bootstrap complete. Sign out and back in so ${admin_user} receives Docker group access."
echo "Also allow TCP ${ssh_port}, TCP 80/443 and UDP 443 in the OCI VCN security list."
