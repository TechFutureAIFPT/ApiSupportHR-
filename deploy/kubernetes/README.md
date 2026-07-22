# SupportHR Kubernetes deployment

This directory contains a Kustomize base plus local and production overlays.

## Runtime shape

- `supporthr-api`: stateless FastAPI pods behind a ClusterIP Service.
- `supporthr-worker`: separate durable-analysis workers consuming the Redis queue.
- Redis: local overlay only. Production should use a managed, highly available Redis service.
- Supabase/PostgreSQL remains the default before migration reconciliation. After cutover, Supabase Auth/PostgreSQL is the system of record; Redis still holds queue payloads, short-lived job state, cache and distributed limits.

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
4. For Supabase cutover, set `SUPABASE_URL`, pooled `DATABASE_URL`, `DATA_ENCRYPTION_KEY`, then change both provider flags only after reconciliation.
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

1. Install K3s on Ubuntu and keep the bundled Traefik ingress controller.
2. Install cert-manager, edit `clusterissuer.example.yaml`, then apply it.
3. Copy `secret.env.example` outside Git, fill it, and create the runtime secret.
4. Create the GHCR pull secret for the private image package.
5. Replace `api.example.com` in `ingress.yaml` and change `newTag` to an immutable `sha-*` image tag.
6. Apply the overlay and wait for the API and worker.

```bash
kubectl create namespace supporthr-oci --dry-run=client -o yaml | kubectl apply -f -
kubectl -n supporthr-oci create secret generic supporthr-backend-secrets --from-env-file=/secure/path/supporthr-secret.env
kubectl -n supporthr-oci create secret docker-registry ghcr-pull --docker-server=ghcr.io --docker-username=YOUR_GITHUB_USER --docker-password="$GHCR_TOKEN"
kubectl apply -f deploy/kubernetes/overlays/oci-free/clusterissuer.example.yaml
kubectl apply -k deploy/kubernetes/overlays/oci-free
kubectl -n supporthr-oci rollout status deployment/supporthr-api
kubectl -n supporthr-oci rollout status deployment/supporthr-worker
```

Roll back an application release without changing Redis data:

```bash
kubectl -n supporthr-oci rollout undo deployment/supporthr-api
kubectl -n supporthr-oci rollout undo deployment/supporthr-worker
```

K3s uses containerd to run the same OCI image produced by Docker Buildx; Docker Engine is not required on the K3s node after the image has been pushed to GHCR.
