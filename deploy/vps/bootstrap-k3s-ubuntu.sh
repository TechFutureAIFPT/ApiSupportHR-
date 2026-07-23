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
k3s_channel="${K3S_CHANNEL:-stable}"
k3s_version="${K3S_VERSION:-}"
cert_manager_version="${CERT_MANAGER_VERSION:-v1.19.6}"
kube_group="supporthr-k3s"

if [[ -z "${admin_user}" || "${admin_user}" == "root" || ! "${admin_user}" =~ ^[a-z_][a-z0-9_-]*$ ]] || ! id "${admin_user}" >/dev/null 2>&1; then
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
if [[ ! "${k3s_channel}" =~ ^[A-Za-z0-9._-]+$ ]]; then
  echo "K3S_CHANNEL has an invalid format." >&2
  exit 1
fi
if [[ -n "${k3s_version}" && ! "${k3s_version}" =~ ^v[0-9]+\.[0-9]+\.[0-9]+\+k3s[0-9]+$ ]]; then
  echo "K3S_VERSION must look like v1.36.1+k3s1." >&2
  exit 1
fi
if [[ ! "${cert_manager_version}" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "CERT_MANAGER_VERSION must look like v1.19.6." >&2
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y ca-certificates curl fail2ban ufw unattended-upgrades
systemctl enable --now unattended-upgrades
systemctl enable --now fail2ban

if ! getent group "${kube_group}" >/dev/null; then
  groupadd --system "${kube_group}"
fi
usermod -aG "${kube_group}" "${admin_user}"

install -d -m 0755 /etc/rancher/k3s
cat > /etc/rancher/k3s/config.yaml <<EOF
write-kubeconfig-mode: "0640"
write-kubeconfig-group: "${kube_group}"
secrets-encryption: true
node-label:
  - "supporthr.io/runtime=production"
EOF

if command -v k3s >/dev/null 2>&1; then
  systemctl restart k3s
elif [[ -n "${k3s_version}" ]]; then
  curl -sfL https://get.k3s.io | INSTALL_K3S_VERSION="${k3s_version}" sh -
else
  curl -sfL https://get.k3s.io | INSTALL_K3S_CHANNEL="${k3s_channel}" sh -
fi

k3s kubectl wait --for=condition=Ready nodes --all --timeout=240s
k3s kubectl wait --for=condition=Available deployment/traefik -n kube-system --timeout=240s
k3s kubectl wait --for=condition=Available deployment/metrics-server -n kube-system --timeout=240s

cert_manager_manifest="https://github.com/cert-manager/cert-manager/releases/download/${cert_manager_version}/cert-manager.yaml"
k3s kubectl apply -f "${cert_manager_manifest}"
k3s kubectl rollout status deployment/cert-manager -n cert-manager --timeout=300s
k3s kubectl rollout status deployment/cert-manager-cainjector -n cert-manager --timeout=300s
k3s kubectl rollout status deployment/cert-manager-webhook -n cert-manager --timeout=300s

cat > /etc/ssh/sshd_config.d/99-supporthr-hardening.conf <<EOF
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin no
MaxAuthTries 3
AllowUsers ${admin_user}
Port ${ssh_port}
EOF
sshd -t
systemctl reload ssh

install -d -m 0750 -o "${admin_user}" -g "${admin_user}" /opt/supporthr/backend
install -d -m 0750 -o "${admin_user}" -g "${admin_user}" /opt/supporthr/shared

ufw default deny incoming
ufw default allow outgoing
ufw allow "${ssh_port}/tcp"
ufw allow 80/tcp
ufw allow 443/tcp
ufw allow from 10.42.0.0/16 to any
ufw allow from 10.43.0.0/16 to any
ufw --force enable

echo "K3s bootstrap complete."
echo "Reconnect SSH so ${admin_user} receives ${kube_group} group access."
echo "Allow TCP ${ssh_port}, 80 and 443 in the cloud firewall. Do not expose 6379, 6443 or 8000 publicly."
