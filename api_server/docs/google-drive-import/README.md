# Google Drive Import

## Mục tiêu

Backend cho phép người dùng:

- kết nối tài khoản Google Drive
- duyệt file trong Drive
- import file về backend
- trích text để đưa vào luồng CV/JD

Service chính:

```text
app/services/account/google_drive_service.py
```

## Cơ chế xác thực

Backend đang dùng:

- `OAuth 2.0`
- scope chỉ đọc

Scope hiện tại:

- `openid`
- `email`
- `profile`
- `https://www.googleapis.com/auth/drive.readonly`

## Các endpoint chính

- `GET /api/account/google-drive/status`
- `POST /api/account/google-drive/oauth-url`
- `POST /api/account/google-drive/exchange-code`
- `DELETE /api/account/google-drive/connection`
- `GET /api/account/google-drive/files`
- `POST /api/account/google-drive/import`

## Luồng kết nối OAuth

### Bước 1. Tạo auth URL

Backend:

- kiểm tra `GOOGLE_OAUTH_CLIENT_ID` và `GOOGLE_OAUTH_CLIENT_SECRET`
- resolve `redirectUri`
- kiểm tra origin có nằm trong allowlist hay không
- sinh `state`
- lưu `state` vào PostgreSQL

State hiện có TTL:

```text
10 phút
```

### Bước 2. Exchange code

Khi frontend trả `code` về, backend:

- kiểm tra state còn hợp lệ
- gọi Google token endpoint
- lấy `accessToken`
- lấy `refreshToken` nếu có
- gọi userinfo endpoint
- lưu kết nối vào `googleDriveConnections`

## Làm mới access token

Trước khi gọi Google Drive API, backend kiểm tra:

- token còn hạn không
- nếu gần hết hạn thì refresh bằng `refreshToken`

Nếu không có `refreshToken`, backend yêu cầu user kết nối lại.

## Duyệt file trong Drive

API list file hỗ trợ:

- search theo tên
- duyệt theo folder
- phân trang

Backend gọi:

```text
GET https://www.googleapis.com/drive/v3/files
```

Metadata normalize về các field như:

- `id`
- `name`
- `mimeType`
- `size`
- `modifiedTime`
- `owners`
- `webViewLink`
- `isGoogleWorkspaceFile`

## Import file về backend

Khi import, backend chia ra hai trường hợp:

### 1. File thường

Ví dụ:

- PDF
- DOCX
- ảnh
- CSV

Backend tải bytes trực tiếp bằng `alt=media`.

### 2. Google Workspace file

Ví dụ:

- Google Docs
- Google Sheets
- Google Slides
- Google Drawings

Backend sẽ export trước rồi mới tải:

- Google Docs -> `.docx`
- Google Slides -> `.pdf`
- Google Drawings -> `.png`
- Google Sheets -> `.csv`

## Sau khi tải file xong backend làm gì

Backend gọi lại `extract_text_from_upload(...)` để dùng chung cùng pipeline upload file thường.

Sau đó backend trả về:

- file info
- extracted text
- processing time
- OCR method
- metadata Drive

Nếu bật `persistUploadedFile`, backend còn lưu metadata file vào collection `uploadedFiles`.

## Các kiểm tra an toàn đang có

- kiểm tra origin của `redirectUri`
- kiểm tra `state`
- kiểm tra document kết nối thuộc đúng `uid`
- chỉ dùng scope `drive.readonly`

## Ý nghĩa nghiệp vụ

Phần Google Drive giúp người dùng không cần tải file thủ công xuống máy rồi upload lại.

Đây là một điểm nối rất quan trọng giữa:

- nguồn dữ liệu gốc của người dùng
- pipeline OCR/trích text
- pipeline phân tích CV/JD của hệ thống
