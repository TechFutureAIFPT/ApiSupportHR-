# SupportHR on a free VPS without Render

This is the primary single-server production path. It runs the API, durable worker, Redis and automatic HTTPS with Docker Compose. Supabase remains the external system of record.

For the current OCI Console choices and exact Free Tier limits, follow [OCI-FREE-SETUP-VI.md](OCI-FREE-SETUP-VI.md).

## 1. Prepare the server

Use an Ubuntu ARM64 VM with 2 OCPU and 12 GB RAM for the current OCI A1 Free allowance. Point the API domain A/AAAA record to the public IP, then allow inbound TCP 22, 80 and 443 plus UDP 443 in both the OCI VCN and the VM firewall.

From the local backend repository, copy the bootstrap bundle and run it on the new VM:

```bash
scp -r deploy/vps ubuntu@YOUR_VPS_IP:/tmp/supporthr-vps
ssh ubuntu@YOUR_VPS_IP 'sudo bash /tmp/supporthr-vps/bootstrap-ubuntu.sh'
```

Sign out and reconnect once so the SSH user receives Docker group access. Then authenticate the VM to private GHCR and create the persistent runtime environment:

```bash
echo "$GHCR_TOKEN" | docker login ghcr.io -u YOUR_GITHUB_USER --password-stdin
cp /tmp/supporthr-vps/runtime.env.example /opt/supporthr/shared/runtime.env
chmod 600 /opt/supporthr/shared/runtime.env
```

Fill every placeholder in `/opt/supporthr/shared/runtime.env`. Do not commit this file. The bootstrap installs Docker from Docker's official Ubuntu repository, disables password/root SSH login, enables Fail2ban and unattended security updates, opens only SSH/HTTP/HTTPS and enables the SupportHR health watchdog.

## 2. Deploy and update

Configure the GitHub `production` environment with these secrets:

- `VPS_HOST`: public IP or DNS name.
- `VPS_USER`: non-root SSH user, normally `ubuntu`.
- `VPS_PORT`: optional; defaults to `22`.
- `VPS_SSH_KEY`: private deployment key.
- `VPS_KNOWN_HOSTS`: verified SSH host-key line; do not accept an unverified `ssh-keyscan` result.

Create repository variable `ENABLE_VPS_DEPLOY=true` only after the VM, GHCR login and runtime environment are ready. Run `Deploy backend to self-hosted VPS` once manually with `:main`. Every later successful image build from `main` deploys its immutable `sha-*` tag automatically.

The workflow uploads only deployment manifests/scripts over verified SSH. Secrets stay on the VM. The deploy script validates configuration, pulls the AMD64/ARM64 image, waits for health checks, verifies public HTTPS and automatically returns to the previous image if startup fails.

Useful operations:

```bash
docker compose --env-file deploy/vps/runtime.env -f compose.production.yaml ps
docker compose --env-file deploy/vps/runtime.env -f compose.production.yaml logs -f --tail=200 backend worker
bash deploy/vps/rollback.sh
systemctl status supporthr-health.timer
```

## 3. Backups

Supabase data must use Supabase backups/PITR. Redis is queue/cache state, but its AOF is persistent and can be archived:

```bash
bash deploy/vps/backup-redis.sh
```

Schedule that command daily with systemd timer or cron and copy the encrypted archives off the VM. The script retains local archives for 14 days.

## 4. Availability limits

Docker services restart automatically after process failure or VM reboot. The systemd watchdog checks every two minutes and restarts missing/unhealthy containers. A single free VM is still one failure domain and cannot provide a real uptime SLA. Keep Supabase backups enabled, monitor `/health/ready`, and use the K3s overlay when moving to a larger/multi-node environment.

Do not delete the old Render service until this endpoint has passed login, profile, history, upload, chatbot, feedback, asynchronous analysis and worker smoke tests. After cutover, change the frontend API URL and remove the Render service.
