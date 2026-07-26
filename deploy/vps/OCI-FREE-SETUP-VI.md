# Thiết lập SupportHR trên OCI/VPS bằng K3s

Mục tiêu production:

```text
GitHub -> Docker image trên GHCR -> K3s/containerd trên VPS
                                  -> API + worker + Redis PVC
                                  -> Traefik + Let's Encrypt
```

Docker chỉ dùng để build image trong GitHub Actions. VPS chạy K3s, không chạy Docker Compose song song.

## 1. Tạo VPS

Chọn Ubuntu LTS mới, kiến trúc ARM64 hoặc AMD64. Với một API, một worker và Redis, nên có tối thiểu:

- 2 CPU.
- 8 GB RAM; 12 GB phù hợp hơn cho worker AI.
- 40-50 GB boot disk.
- Public IPv4 cố định.
- SSH bằng key, không dùng mật khẩu.

Nếu dùng OCI Free Tier, luôn kiểm tra lại nhãn Free-eligible, quota và giới hạn tại thời điểm tạo máy. Free Tier không phải cam kết uptime.

## 2. Firewall và DNS

Mở trong cloud firewall/security list:

| Nguồn | Giao thức | Cổng | Mục đích |
| --- | --- | --- | --- |
| IP quản trị hoặc GitHub Actions | TCP | `22` | SSH bằng key |
| `0.0.0.0/0` | TCP | `80` | HTTP/ACME |
| `0.0.0.0/0` | TCP | `443` | HTTPS |

Không mở `6379`, `6443` hoặc `8000` ra Internet.

Tạo bản ghi `A`, ví dụ:

```text
backend.supporthr-tf.com.vn -> PUBLIC_VPS_IP
```

Đặt TTL `300` trong giai đoạn cutover.

## 3. Bootstrap K3s

Từ PowerShell hoặc terminal tại `Software/Web/BE`:

```bash
scp -i /path/to/private-key -r deploy/vps ubuntu@YOUR_VPS_IP:/tmp/supporthr-vps
ssh -i /path/to/private-key ubuntu@YOUR_VPS_IP \
  "sudo bash /tmp/supporthr-vps/bootstrap-k3s-ubuntu.sh"
```

Bootstrap thực hiện:

- Cài K3s stable, Traefik và Metrics Server.
- Cài cert-manager `v1.19.6`.
- Bật mã hóa Kubernetes Secrets at rest.
- Cấu hình kubeconfig chỉ cho nhóm `supporthr-k3s`.
- Tắt SSH password/root login.
- Bật Fail2ban, unattended upgrades và UFW.
- Cho phép Pod/Service CIDR nội bộ của K3s.

Ngắt SSH và kết nối lại một lần sau bootstrap để quyền nhóm có hiệu lực.

## 4. Nạp runtime secret

Trên VPS:

```bash
cp /tmp/supporthr-vps/k3s-secret.env.example /opt/supporthr/shared/supporthr-secret.env
chmod 600 /opt/supporthr/shared/supporthr-secret.env
nano /opt/supporthr/shared/supporthr-secret.env
bash /tmp/supporthr-vps/prepare-k3s-secrets.sh
```

Điền Firebase, Gemini và Google OAuth thật. Không gửi nội dung file này qua chat hoặc commit lên Git.

Script sẽ hỏi:

- GitHub username.
- Classic PAT chỉ có quyền `read:packages`.

Token dùng để tạo `ghcr-pull` trong Kubernetes, không được ghi vào repo.

## 5. Cấu hình GitHub

Tạo GitHub environment `production`.

Secrets:

- `VPS_HOST`
- `VPS_USER=ubuntu`
- `VPS_PORT`, có thể bỏ trống để dùng `22`
- `VPS_SSH_KEY`
- `VPS_KNOWN_HOSTS`

Variables:

- `API_DOMAIN=backend.supporthr-tf.com.vn`
- `ACME_EMAIL=your-email@example.com`
- `ENABLE_K3S_DEPLOY=true`

Chỉ bật `ENABLE_K3S_DEPLOY` sau khi DNS đã trỏ đúng, K3s hoạt động và hai secret `supporthr-backend-secrets`, `ghcr-pull` đã tồn tại.

## 6. Deploy

Push thay đổi backend lên `main`. Workflow build tạo image đa kiến trúc và workflow deploy đưa đúng tag bất biến `sha-*` lên VPS.

Theo dõi trên VPS:

```bash
kubectl -n supporthr-oci get pods,service,ingress,pvc
kubectl -n supporthr-oci rollout status deployment/supporthr-api
kubectl -n supporthr-oci rollout status deployment/supporthr-worker
curl -f https://backend.supporthr-tf.com.vn/health/live
curl -f https://backend.supporthr-tf.com.vn/health/ready
```

Rollback thủ công:

```bash
cd /opt/supporthr/backend
bash deploy/vps/rollback-k3s.sh
```

Deploy tự rollback API và worker nếu rollout hoặc public health gate thất bại. Redis PVC không bị thay đổi khi rollback image.

## 7. Gate trước khi xóa Render

Chỉ xóa Render sau khi:

- HTTPS và chứng chỉ hợp lệ.
- `/health/live` và `/health/ready` thành công.
- Đăng nhập, profile, history và JD template hoạt động.
- Upload/OCR, chatbot, feedback và GraphRAG hoạt động.
- Async analysis được worker xử lý.
- Redis còn hoạt động sau khi restart pod.
- Đã thử rollback.
- Frontend và Android đã đổi API URL sang domain VPS.

Nguồn đối chiếu:

- [K3s Quick Start](https://docs.k3s.io/quick-start)
- [K3s requirements](https://docs.k3s.io/installation/requirements)
- [cert-manager installation](https://cert-manager.io/v1.19-docs/installation/kubectl/)
- [GitHub Container Registry authentication](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry)
