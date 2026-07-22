# SupportHR on a free VPS without Render

This is the primary single-server production path. It runs the API, durable worker, Redis and automatic HTTPS with Docker Compose. Supabase remains the external system of record.

## 1. Prepare the server

Use an Ubuntu ARM64 or AMD64 VM with at least 2 vCPU and 8 GB RAM. Point the API domain A/AAAA record to the public IP, then allow inbound TCP 22, 80 and 443 plus UDP 443. Install Docker Engine and the Compose plugin from Docker's official repository.

Clone the backend repository and sign in to GHCR if the package is private:

```bash
echo "$GHCR_TOKEN" | docker login ghcr.io -u YOUR_GITHUB_USER --password-stdin
cp deploy/vps/runtime.env.example deploy/vps/runtime.env
chmod 600 deploy/vps/runtime.env
```

Fill every placeholder in `deploy/vps/runtime.env`. Do not commit this file. For reproducible releases, change `SUPPORTHR_IMAGE_REF` from `:main` to an immutable `:sha-...` tag after the first successful GitHub Actions build.

## 2. Deploy and update

```bash
bash deploy/vps/deploy.sh
```

The deploy script validates configuration, pulls the AMD64/ARM64 image, waits for health checks, verifies public HTTPS and automatically returns to the previous image if startup fails.

Useful operations:

```bash
docker compose --env-file deploy/vps/runtime.env -f compose.production.yaml ps
docker compose --env-file deploy/vps/runtime.env -f compose.production.yaml logs -f --tail=200 backend worker
bash deploy/vps/rollback.sh
```

## 3. Backups

Supabase data must use Supabase backups/PITR. Redis is queue/cache state, but its AOF is persistent and can be archived:

```bash
bash deploy/vps/backup-redis.sh
```

Schedule that command daily with systemd timer or cron and copy the encrypted archives off the VM. The script retains local archives for 14 days.

## 4. Availability limits

Docker services restart automatically after process failure or VM reboot. A single free VM is still one failure domain and cannot provide a real uptime SLA. Keep Supabase backups enabled, monitor `/health/ready`, and use the K3s overlay when moving to a larger/multi-node environment.

Do not delete the old Render service until this endpoint has passed login, profile, history, upload, chatbot, feedback, asynchronous analysis and worker smoke tests. After cutover, change the frontend API URL and remove the Render service.
