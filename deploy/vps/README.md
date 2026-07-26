# SupportHR on K3s VPS

The primary self-hosted production path is:

```text
GitHub Actions -> Docker Buildx -> immutable GHCR image -> K3s on the VPS
                                                     -> API
                                                     -> analysis worker
                                                     -> persistent Redis
                                                     -> Traefik + cert-manager HTTPS
```

Docker builds the OCI image in CI. K3s uses containerd to run that image, so Docker Engine and Docker Compose do not run beside K3s on the production node. `compose.production.yaml` remains a break-glass fallback only.

## 1. Human prerequisites

Create an Ubuntu VPS and a DNS `A` record such as `backend.supporthr-tf.com.vn` pointing to its public IPv4 address. Allow only:

- SSH TCP port, normally `22`.
- TCP `80` and `443`.
- Do not expose Redis `6379`, Kubernetes API `6443`, or backend `8000`.

Keep the private SSH key, Firebase Admin credentials, Gemini keys and GHCR token out of Git and chat.

## 2. Bootstrap K3s

From the backend repository:

```bash
scp -r deploy/vps ubuntu@YOUR_VPS_IP:/tmp/supporthr-vps
ssh ubuntu@YOUR_VPS_IP 'sudo bash /tmp/supporthr-vps/bootstrap-k3s-ubuntu.sh'
```

The script installs the current K3s stable channel, bundled Traefik and Metrics Server, pinned cert-manager `v1.19.6`, encrypted Kubernetes Secrets at rest, Fail2ban, unattended security updates, SSH hardening and the required UFW rules.

Optional bootstrap overrides:

```bash
sudo K3S_VERSION=v1.36.1+k3s1 \
  CERT_MANAGER_VERSION=v1.19.6 \
  SUPPORTHR_ADMIN_USER=ubuntu \
  SSH_PORT=22 \
  bash /tmp/supporthr-vps/bootstrap-k3s-ubuntu.sh
```

Reconnect SSH once after bootstrap so the deployment account receives access to the root-owned K3s kubeconfig through the `supporthr-k3s` group.

## 3. Create runtime and image-pull secrets

On the VPS:

```bash
cp /tmp/supporthr-vps/k3s-secret.env.example /opt/supporthr/shared/supporthr-secret.env
chmod 600 /opt/supporthr/shared/supporthr-secret.env
nano /opt/supporthr/shared/supporthr-secret.env
bash /tmp/supporthr-vps/prepare-k3s-secrets.sh
```

The script creates:

- `supporthr-backend-secrets` from the root-protected runtime env file.
- `ghcr-pull` after interactively reading a GitHub username and a classic PAT with only `read:packages`.

## 4. Configure GitHub production

Create GitHub environment `production` with:

Secrets:

- `VPS_HOST`
- `VPS_USER`, normally `ubuntu`
- `VPS_PORT`, optional and defaults to `22`
- `VPS_SSH_KEY`
- `VPS_KNOWN_HOSTS`, captured only after verifying the VPS host fingerprint

Variables:

- `API_DOMAIN`, for example `backend.supporthr-tf.com.vn`
- `ACME_EMAIL`
- `ENABLE_K3S_DEPLOY=true`

Keep `ENABLE_K3S_DEPLOY` unset until K3s, DNS, the runtime secret and `ghcr-pull` are ready.

## 5. Automated releases and rollback

Every successful backend image build from `main` triggers `Deploy backend to K3s VPS`. The workflow deploys only the immutable `sha-<12 hex>` image built from that exact revision.

For the first release, run the workflow manually and paste the `ghcr.io/techfutureaifpt/supporthr-backend:sha-...` tag from a successful **Build and publish backend image** run. Manual deployment deliberately has no mutable `main` fallback.

The deployment:

1. Verifies the separately managed runtime and image-pull secrets.
2. Generates the real Ingress hostname and Let's Encrypt ClusterIssuer outside Git.
3. Applies the `oci-free` Kustomize overlay.
4. Waits for Redis, API and worker rollouts.
5. Requires both public `/health/live` and `/health/ready` to pass.
6. Restores the previous API and worker image automatically when a gate fails.

Manual rollback:

```bash
cd /opt/supporthr/backend
bash deploy/vps/rollback-k3s.sh
```

Useful checks:

```bash
kubectl -n supporthr-oci get pods,service,ingress,pvc
kubectl -n supporthr-oci rollout status deployment/supporthr-api
kubectl -n supporthr-oci rollout status deployment/supporthr-worker
kubectl -n supporthr-oci logs deployment/supporthr-api --tail=200
kubectl -n supporthr-oci logs deployment/supporthr-worker --tail=200
```

## 6. Render removal gate

Delete Render only after the K3s endpoint passes:

- HTTPS `/health/live` and `/health/ready`.
- Firebase sign-in, profile, history and JD templates.
- Upload/OCR, chatbot, feedback and GraphRAG.
- Asynchronous analysis completed by the worker.
- Redis persistence after pod restart.
- A tested rollback to the previous immutable image.
- Frontend and Android API URLs switched to the VPS domain.

A single VPS remains one failure domain. Firebase is the system of record; Redis contains queue/cache state and its PVC must not be treated as a database backup.
