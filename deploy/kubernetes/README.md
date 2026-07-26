# SupportHR Kubernetes deployment

This directory contains a Kustomize base plus local and production overlays.

## Runtime shape

- `supporthr-api`: stateless FastAPI pods behind a ClusterIP Service.
- `supporthr-worker`: separate durable-analysis workers consuming the Redis queue.
- Redis: local overlay only. Production should use a managed, highly available Redis service.
- Firebase/Firestore remains the default before migration reconciliation. After cutover, Firebase Authentication/Firestore is the system of record; Redis still holds queue payloads, short-lived job state, cache and distributed limits.

## Build the image

From `Software/Web/BE`:

```bash
docker build -t supporthr-backend:local ./api_server
```

Pushes to `main` and `v*` tags also build AMD64/ARM64 images with provenance and SBOM metadata through `.github/workflows/container-image.yml` and publish them to `ghcr.io/techfutureaifpt/supporthr-backend`.

## Generate and validate manifests without a cluster

```bash
kubectl kustomize deploy/kubernetes/overlays/local
kubectl kustomize deploy/kubernetes/overlays/production
kubectl kustomize deploy/kubernetes/overlays/oci-free
```

## Local cluster

Load `supporthr-backend:local` into the local cluster runtime, then:

```bash
kind create cluster --name supporthr
kind load docker-image supporthr-backend:local --name supporthr
kubectl apply -k deploy/kubernetes/overlays/local
kubectl -n supporthr-local rollout status deployment/supporthr-api
kubectl -n supporthr-local rollout status deployment/supporthr-worker
kubectl -n supporthr-local port-forward service/supporthr-api 8000:80
```

The local secret only contains the Redis URL. Add Gemini and the active auth/data provider values before testing AI/account flows.

For functional CPU/memory HPA on kind, install the official Metrics Server and apply the local-only kubelet TLS patch:

```bash
kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/download/v0.8.1/components.yaml
kubectl -n kube-system patch deployment metrics-server --type=strategic --patch-file deploy/kubernetes/local-addons/metrics-server-kind-patch.yaml
kubectl -n kube-system rollout status deployment/metrics-server
kubectl top pods -n supporthr-local
```

`--kubelet-insecure-tls` is only for the local kind certificate. Do not carry that flag into production.

## Production cluster

1. Push an immutable image tag and replace `replace-with-release-tag` in the production overlay.
2. Create `supporthr-backend-secrets` from the real secret manager. Never commit the completed secret YAML.
3. Configure a managed Redis URL in `REDIS_INTERNAL_URL`.
4. Set `FIREBASE_PROJECT_ID`, `FIREBASE_SERVICE_ACCOUNT_JSON`, and `DATA_ENCRYPTION_KEY`, then verify `/health/ready` reports Firebase before routing production traffic.
5. Install Metrics Server so the resource-based HPAs receive CPU/memory metrics.
6. Copy and customize `ingress.example.yaml`, then add it to the production `kustomization.yaml` only after DNS, TLS and ingress class are known.
7. Apply and wait for both rollouts.

```bash
kubectl apply -f deploy/kubernetes/base/secret.example.yaml --dry-run=client
kubectl apply -k deploy/kubernetes/overlays/production
kubectl -n supporthr-production rollout status deployment/supporthr-api
kubectl -n supporthr-production rollout status deployment/supporthr-worker
```

For bursty analysis traffic, CPU/memory HPA is only the baseline. Add KEDA or another external-metrics adapter for Redis queue depth before high-volume production traffic.

## OCI Free single-node K3s

The `oci-free` overlay is sized for a single free ARM64 VM. It keeps one API pod, one worker and a persistent Redis StatefulSet, and intentionally removes HPA/PDB objects that do not improve availability on one node.

The supported production path is automated by:

```bash
sudo bash deploy/vps/bootstrap-k3s-ubuntu.sh
bash deploy/vps/prepare-k3s-secrets.sh
SUPPORTHR_IMAGE_REF=ghcr.io/techfutureaifpt/supporthr-backend:sha-0123456789ab \
  API_DOMAIN=backend.supporthr-tf.com.vn \
  ACME_EMAIL=admin@example.com \
  bash deploy/vps/deploy-k3s.sh
```

`deploy-k3s.sh` works on a temporary Kustomize copy, so the committed overlay keeps placeholders instead of a mutable production tag or domain. It accepts only immutable `sha-*` images, generates the real Ingress and ClusterIssuer, waits for Redis/API/worker plus public HTTPS readiness, and automatically restores the previous API and worker image on failure.

The GitHub workflow `.github/workflows/deploy-vps.yml` uploads and runs the same script after a successful image build. Runtime application secrets are created separately from `/opt/supporthr/shared/supporthr-secret.env` on the VPS and are not rewritten during normal releases; GitHub stores only SSH connection inputs and non-secret domain/email variables.

Manual rollback does not change the Redis PVC:

```bash
bash deploy/vps/rollback-k3s.sh
```

K3s uses containerd to run the same OCI image produced by Docker Buildx; Docker Engine is not required on the K3s node after the image has been pushed to GHCR.
