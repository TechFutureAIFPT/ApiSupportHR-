# Tạo OCI Always Free cho SupportHR

Mục tiêu là một VM ARM64 tự chạy Docker Compose, không dùng Render. Cấu hình dưới đây nằm trong giới hạn Always Free hiện hành: tổng 2 OCPU và 12 GB RAM cho Ampere A1 trong home region.

## 1. Tạo tài khoản và mạng

1. Đăng nhập OCI Console. Không bấm **Upgrade** nếu muốn giữ tài khoản Free Tier.
2. Always Free chỉ áp dụng trong **home region**. Nếu đang tạo tài khoản mới, chọn region gần người dùng và có dung lượng A1; Singapore thường phù hợp với Việt Nam nhưng có thể hết capacity.
3. Mở **Networking → Virtual Cloud Networks → Start VCN Wizard**.
4. Chọn **Create VCN with Internet Connectivity** và hoàn tất wizard.

OCI thường yêu cầu số điện thoại và thẻ để xác minh. Thẻ không bị tính tiền nếu tài khoản không upgrade và chỉ dùng tài nguyên có nhãn **Always Free-eligible**.

## 2. Tạo VM

Mở **Compute → Instances → Create instance** và đặt:

- Name: `supporthr-api-01`.
- Image: bản Ubuntu LTS ARM64 mới nhất có nhãn **Always Free-eligible**.
- Shape: `VM.Standard.A1.Flex`.
- OCPU: `2`.
- Memory: `12 GB`.
- Networking: VCN vừa tạo, public subnet và bật **Automatically assign a public IPv4 address**.
- Boot volume: giữ mặc định khoảng `50 GB`, bật in-transit encryption, không thêm paid block volume.
- SSH: dùng **Generate a key pair** hoặc upload public key OpenSSH của bạn.

Nếu OCI tạo key, tải cả private/public key ngay khi màn hình cho phép. Private key không thể tải lại sau đó. Lưu private key trên máy, ví dụ:

```text
C:\Users\Admin\.ssh\supporthr_oci.key
```

Không gửi nội dung private key, Supabase password hoặc Gemini key qua chat/Git.

## 3. Mở cổng trong OCI VCN

Trong subnet/security list của VM, thêm stateful ingress:

| Source | Protocol | Destination port | Mục đích |
| --- | --- | --- | --- |
| `0.0.0.0/0` | TCP | `22` | GitHub Actions SSH; máy chỉ cho key, tắt password/root và có Fail2ban |
| `0.0.0.0/0` | TCP | `80` | Caddy nhận HTTP/Let's Encrypt |
| `0.0.0.0/0` | TCP | `443` | HTTPS |
| `0.0.0.0/0` | UDP | `443` | HTTP/3 |

Không mở `6379`, `8000` hoặc cổng PostgreSQL ra Internet.

## 4. Kết nối lần đầu và bootstrap

Từ PowerShell tại `D:\Support HR\Software\Web\BE`:

```powershell
scp -i C:\Users\Admin\.ssh\supporthr_oci.key -r deploy/vps ubuntu@YOUR_VPS_IP:/tmp/supporthr-vps
ssh -i C:\Users\Admin\.ssh\supporthr_oci.key ubuntu@YOUR_VPS_IP "sudo bash /tmp/supporthr-vps/bootstrap-ubuntu.sh"
```

Ngắt SSH rồi kết nối lại để quyền nhóm Docker có hiệu lực. Bootstrap cài Docker/Compose, UFW, Fail2ban, security updates và watchdog tự phục hồi container.

## 5. Nạp runtime secret và GHCR

Trên VM:

```bash
echo "$GHCR_TOKEN" | docker login ghcr.io -u YOUR_GITHUB_USER --password-stdin
cp /tmp/supporthr-vps/runtime.env.example /opt/supporthr/shared/runtime.env
chmod 600 /opt/supporthr/shared/runtime.env
nano /opt/supporthr/shared/runtime.env
```

PAT dùng cho `GHCR_TOKEN` chỉ cần quyền đọc package. Điền toàn bộ placeholder Supabase, Gemini, OAuth, domain và email ACME; không commit file này.

## 6. DNS và GitHub Actions

1. Tạo bản ghi A riêng `backend.supporthr-tf.com.vn` trỏ tới public IP, TTL `300`. Bản ghi riêng sẽ thay wildcard Vercel cho đúng subdomain này.
2. Xác minh SSH host fingerprint ngoài luồng, rồi lưu dòng known-host vào GitHub secret `VPS_KNOWN_HOSTS`.
3. Tạo GitHub environment `production` với `VPS_HOST`, `VPS_USER=ubuntu`, `VPS_SSH_KEY`, `VPS_KNOWN_HOSTS` và tùy chọn `VPS_PORT`.
4. Chỉ sau khi các bước trên xong mới tạo repository variable `ENABLE_VPS_DEPLOY=true`.
5. Chạy workflow **Deploy backend to self-hosted VPS** lần đầu với image mặc định `:main`.

## 7. Gate trước khi tắt Render

Chỉ chuyển FE sang `https://backend.supporthr-tf.com.vn` và xóa Render sau khi đạt đủ:

- `/health/live` và `/health/ready` trả thành công qua HTTPS.
- Đăng nhập Supabase, profile, history và JD template hoạt động.
- Upload/OCR, chatbot, feedback và async analysis hoạt động.
- Worker xử lý job; Redis AOF còn dữ liệu sau restart.
- Rollback image cũ đã thử thành công.

## Giới hạn miễn phí cần biết

OCI Always Free không phải SLA 24/7. Oracle nêu rõ VM Always Free nhàn rỗi trong bảy ngày có thể bị thu hồi nếu cả CPU, network và memory đều dưới ngưỡng của họ. Không tạo tải giả để né chính sách; nếu hệ thống cần cam kết uptime thật, phải dùng gói trả phí hoặc thêm node/nhà cung cấp dự phòng.

Nguồn đối chiếu: [OCI Always Free Resources](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm), [OCI Creating an Instance](https://docs.oracle.com/en-us/iaas/Content/Compute/Tasks/launchinginstance.htm), [Docker Engine on Ubuntu](https://docs.docker.com/engine/install/ubuntu/) và [GitHub deployment environments](https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/manage-environments).
