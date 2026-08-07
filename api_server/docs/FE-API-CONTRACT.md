# SupportHR FE API Contract

> Tài liệu này là hợp đồng tích hợp dành cho việc thiết kế hoặc sinh code Frontend từ Backend SupportHR.
> Nguồn sự thật kỹ thuật theo thứ tự: code route/schema đang chạy, `/openapi.json`, sau đó mới đến tài liệu này.
> Không tự phát minh endpoint, field hoặc trạng thái ngoài các nguồn trên.

## 1. Mục tiêu

Frontend dùng tài liệu này để:

- xác định chức năng nào đã có API;
- biết API nào public, API nào cần Firebase Bearer ID token;
- dựng đúng workflow upload, phân tích CV, polling job, lịch sử và tài khoản;
- sinh type trực tiếp từ OpenAPI thay vì viết type thủ công;
- xử lý loading, empty, degraded, error và retry nhất quán;
- không đưa Gemini, Google, database hoặc encryption secret vào client.

Tài liệu mô tả 91 operation hiện có:

| Nhóm | Số operation |
| --- | ---: |
| Account | 64 |
| AI/CV/JD | 20 |
| Health | 3 |
| Mobile JD | 2 |
| File extraction | 1 |
| Salary | 1 |
| **Tổng** | **91** |

## 2. Endpoint và biến môi trường Frontend

Production demo hiện tại:

```text
https://backendsupporthr.onrender.com
```

Local:

```text
http://localhost:8000
```

Frontend chỉ lưu base URL:

```env
VITE_API_BASE_URL=https://backendsupporthr.onrender.com
```

Với Expo:

```env
EXPO_PUBLIC_API_URL=https://backendsupporthr.onrender.com
```

Không nối `/api` vào biến môi trường vì các health endpoint nằm ngoài `/api`.

## 3. Rules bắt buộc khi sinh FE

1. Không gọi Gemini, Google Drive API hoặc Cloud Firestore trực tiếp từ FE.
2. Không đưa `GEMINI_API_KEY_*`, Google OAuth secret, `FIREBASE_SERVICE_ACCOUNT_JSON` hoặc `DATA_ENCRYPTION_KEY` vào bundle.
3. Login/refresh session thực hiện bằng Firebase client; backend chỉ nhận Firebase ID token.
4. Mọi route `/api/account/*` và `POST /api/cv/enrich` phải gửi:

   ```http
   Authorization: Bearer <firebase_id_token>
   ```

5. Swagger hiện chưa hiển thị biểu tượng khóa cho custom Bearer dependency. Không được hiểu các route account là public.
6. Sinh TypeScript type từ `/openapi.json`; không duy trì một bộ type API viết tay song song.
7. Backend có cả `snake_case` và alias `camelCase`. Không áp dụng bộ chuyển đổi key toàn cục.
8. Chỉ map dữ liệu sang view model tại boundary của từng feature.
9. `DELETE` màu đỏ trong Swagger chỉ là màu HTTP method, không phải trạng thái lỗi.
10. Dùng `/health/live` để biết process còn chạy và `/health/ready` để biết dependency đã sẵn sàng.
11. Khi `/health/live=200` nhưng `/health/ready=503`, FE có thể cho phép feature public đã kiểm chứng, nhưng phải khóa feature account/persistence.
12. Không tự retry `POST`, `PATCH`, `PUT`, `DELETE` nếu chưa có idempotency contract.
13. Poll analysis job phải dừng khi component unmount, logout, `completed`, `failed` hoặc quá timeout.
14. Mọi thao tác xóa phải có hộp thoại xác nhận và chỉ cập nhật optimistic UI khi API thành công.
15. Kết quả AI là gợi ý hỗ trợ HR, không trình bày như quyết định tuyển dụng tự động.

## 4. Sinh type và cấu trúc API client

Sinh type:

```bash
npx openapi-typescript \
  https://backendsupporthr.onrender.com/openapi.json \
  -o src/api/generated/openapi.ts
```

Cấu trúc gợi ý:

```text
src/
├─ api/
│  ├─ client.ts
│  ├─ errors.ts
│  ├─ auth.ts
│  └─ generated/openapi.ts
├─ features/
│  ├─ analysis/api.ts
│  ├─ files/api.ts
│  ├─ jd/api.ts
│  ├─ account/api.ts
│  ├─ history/api.ts
│  ├─ templates/api.ts
│  ├─ chatbot/api.ts
│  └─ google-drive/api.ts
└─ types/
   └─ view-models.ts
```

API client tối thiểu:

```ts
const API_BASE_URL = String(import.meta.env.VITE_API_BASE_URL || "")
  .trim()
  .replace(/\/+$/, "");

export class ApiError extends Error {
  constructor(
    public status: number,
    public detail: unknown,
    message = `API request failed: ${status}`
  ) {
    super(message);
  }
}

export async function apiFetch<T>(
  path: string,
  init: RequestInit = {},
  accessToken?: string | null
): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("X-Request-Id", crypto.randomUUID());

  if (!(init.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }
  if (accessToken) {
    headers.set("Authorization", `Bearer ${accessToken}`);
  }

  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers
  });

  if (response.status === 204) return undefined as T;

  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    throw new ApiError(response.status, payload?.detail ?? payload);
  }
  return payload as T;
}
```

Backend CORS phải cho phép `X-Request-Id` vì API client dùng header này để truy vết request. Với local FE tại `http://localhost:3000`, preflight có `Access-Control-Request-Headers: x-request-id` phải trả `200`.

## 5. Chuẩn auth

Backend không có endpoint login/register riêng.

Luồng đúng:

```text
FE -> Firebase Authentication login
FE <- session.access_token
FE -> Backend: Authorization Bearer access_token
Backend -> Firebase JWKS: verify token
Backend -> Cloud Firestore: query theo owner_id
```

Frontend phải:

- đọc token mới trước request account;
- refresh session bằng Firebase SDK;
- logout hoặc yêu cầu login lại khi nhận `401`;
- không lưu access token vào source code hoặc log;
- không dùng email/user id từ UI làm nguồn ownership; backend lấy `uid` từ token.

## 6. Bản đồ chức năng FE

| Chức năng FE | API chính |
| --- | --- |
| App boot/degraded state | `/health/live`, `/health/ready` |
| Upload và đọc CV/JD | `/api/files/extract-text` |
| Chuẩn hóa JD | `/api/jd/structure`, `/api/jd/position`, `/api/jd/hard-filters` |
| Chấm nhanh 1–3 CV | `/api/cv/quick-score`, `/api/cv/quick-score-text` |
| Phân tích CV đầy đủ | `/api/analysis/jobs`, `/api/analysis/status/{job_id}` |
| Phân tích đồng bộ cho debug | `/api/cv/analyze-core` |
| Kiểm tra classifier/GraphRAG | `/api/cv/classifier-status`, `/api/cv/graphrag-status` |
| Rubric theo vai trò | `/api/rubrics`, `/api/rubrics/{role_key}` |
| Câu hỏi phỏng vấn | `/api/interview/questions` |
| Chat với snapshot ứng viên | `/api/cv/candidate-chat` |
| Phân tích lương | `/api/salary/analyze` |
| Profile/settings | `/api/account/profile`, `/api/account/settings` |
| Lịch sử và feedback | `/api/account/history*` |
| JD template | `/api/account/jd-templates*` |
| File đã tải | `/api/account/uploaded-files*` |
| Đồng bộ web/mobile | `/api/account/sync/*`, `/api/account/mobile-inbox` |
| Chatbot persistence | `/api/account/chatbot/*` |
| Google Drive | `/api/account/google-drive/*` |
| Notification | `/api/account/notifications*` |
| Gửi email | `/api/account/email/send` |

## 7. Workflow FE chuẩn

### 7.1 Khởi động ứng dụng

```text
GET /health/live
  -> 200: backend reachable
  -> fail: show service unavailable

GET /health/ready
  -> 200: enable all configured features
  -> 503: show degraded banner; disable account/persistence feature
```

Không dùng `GET /health` làm liveness vì endpoint này có thể trả `503` khi dependency chưa sẵn sàng.

### 7.2 Phân tích CV đầy đủ

```text
1. Extract CV/JD text khi cần
2. POST /api/jd/structure
3. POST /api/jd/position
4. POST /api/jd/hard-filters
5. POST /api/analysis/jobs
6. Poll GET /api/analysis/status/{job_id}
7. Khi completed: render result.result
8. Nếu đã login: lưu history/feedback theo workflow sản phẩm
```

Polling gợi ý:

```ts
type JobState = "queued" | "processing" | "completed" | "failed";

export async function waitForAnalysis(
  jobId: string,
  signal: AbortSignal,
  accessToken?: string | null
) {
  const deadline = Date.now() + 10 * 60_000;

  while (Date.now() < deadline) {
    const job = await apiFetch<{
      status: JobState;
      progress: number;
      message: string;
      result?: unknown;
      error?: string | null;
    }>(`/api/analysis/status/${encodeURIComponent(jobId)}`, { signal }, accessToken);

    if (job.status === "completed") return job.result;
    if (job.status === "failed") throw new Error(job.error || "Analysis failed");

    await new Promise((resolve) => setTimeout(resolve, 2000));
  }

  throw new Error("Analysis polling timed out");
}
```

Production nhiều instance phải dùng Redis worker. Render Free hiện dùng `in_process`, vì vậy job có thể mất khi service restart hoặc sleep.

### 7.3 Quick score

Hai lựa chọn:

- có `File`: `POST /api/cv/quick-score` bằng `multipart/form-data`;
- đã có text: `POST /api/cv/quick-score-text` bằng JSON.

Không gọi cả hai cho cùng một CV.

### 7.4 Google Drive

```text
1. GET /api/account/google-drive/status
2. POST /api/account/google-drive/oauth-url
3. Redirect user tới authUrl
4. Nhận code/state ở callback
5. POST /api/account/google-drive/exchange-code
6. GET /api/account/google-drive/files
7. POST /api/account/google-drive/import
```

`session-auth` chỉ dùng khi client đã có Google access token hợp lệ và workflow sản phẩm chọn kết nối theo session.

### 7.5 Settings có optimistic concurrency

```text
GET /api/account/settings
  <- ETag

PATCH /api/account/settings
  -> If-Match: <etag>
```

Xử lý:

- `304`: dùng cache hiện tại;
- `409`: dữ liệu đang bị khóa, đọc `Retry-After`;
- `412`: revision cũ, tải lại dữ liệu trước khi ghi;
- `200`: thay state bằng response server.

## 8. Endpoint catalog: health và AI

### 8.1 Health

| Method | Path | Auth | Mục đích |
| --- | --- | --- | --- |
| GET | `/health/live` | Không | Process HTTP còn sống |
| GET | `/health/ready` | Không | Classifier và dependency runtime sẵn sàng |
| GET | `/health` | Không | Health tổng hợp; có thể trả `503` |

### 8.2 AI, CV, JD và rubric

| Method | Path | Auth | Mục đích |
| --- | --- | --- | --- |
| GET | `/api/rubrics` | Không | Danh sách rubric active |
| GET | `/api/rubrics/{role_key}` | Không | Rubric theo vai trò |
| POST | `/api/gemini-chat` | Tùy chọn | Low-level generate; FE nghiệp vụ không nên gọi trực tiếp |
| POST | `/api/gemini-embed` | Tùy chọn | Low-level embedding; FE nghiệp vụ không nên gọi trực tiếp |
| POST | `/api/jd/structure` | Tùy chọn | Chuẩn hóa JD thành cấu trúc |
| POST | `/api/jd/position` | Tùy chọn | Xác định vị trí tuyển dụng |
| POST | `/api/jd/hard-filters` | Tùy chọn | Trích bộ lọc cứng |
| POST | `/api/cv/analyze-core` | Tùy chọn | Phân tích đồng bộ |
| POST | `/api/cv/analyze-core-async` | Tùy chọn | Tạo analysis job |
| POST | `/api/analysis/jobs` | Tùy chọn | Alias chuẩn để tạo analysis job |
| GET | `/api/analysis/status/{job_id}` | Tùy chọn | Poll trạng thái job |
| GET | `/api/cv/classifier-status` | Không | Trạng thái model classifier |
| GET | `/api/cv/graphrag-status` | Không | Trạng thái GraphRAG |
| POST | `/api/cv/classify-industry` | Tùy chọn | Phân loại ngành CV |
| POST | `/api/cv/refine-profile` | Tùy chọn | Chuẩn hóa tên/học vấn |
| POST | `/api/cv/enrich` | **Bắt buộc** | Enrich ứng viên với dữ liệu thuộc user |
| POST | `/api/cv/quick-score` | Tùy chọn | Chấm nhanh từ file |
| POST | `/api/cv/quick-score-text` | Tùy chọn | Chấm nhanh từ text |
| POST | `/api/cv/candidate-chat` | Tùy chọn | Hỏi đáp theo snapshot ứng viên |
| POST | `/api/interview/questions` | Tùy chọn | Sinh câu hỏi phỏng vấn |

`Tùy chọn` nghĩa là endpoint chạy không cần login, nhưng nếu có Bearer token hợp lệ thì backend có thể lưu audit/history phù hợp.

### 8.3 File, mobile JD và salary

| Method | Path | Auth | Content-Type | Mục đích |
| --- | --- | --- | --- | --- |
| POST | `/api/files/extract-text` | Tùy chọn | `multipart/form-data` | Trích text/OCR |
| POST | `/api/mobile/jd/standardize` | Tùy chọn | `application/json` | Chuẩn hóa JD text cho mobile |
| POST | `/api/mobile/jd/standardize-file` | Tùy chọn | `multipart/form-data` | Chuẩn hóa JD file cho mobile |
| POST | `/api/salary/analyze` | Tùy chọn | `application/json` | Phân tích khoảng lương tham khảo |

## 9. Endpoint catalog: account

Tất cả endpoint trong phần này bắt buộc Bearer token.

### 9.1 Profile

| Method | Path | Mục đích |
| --- | --- | --- |
| GET | `/api/account/profile` | Đọc profile |
| PUT | `/api/account/profile` | Tạo/cập nhật profile |
| PATCH | `/api/account/profile/avatar` | Cập nhật avatar |
| GET | `/api/account/profile/cv-history` | Danh sách CV history của profile |
| POST | `/api/account/profile/cv-history` | Thêm CV history |
| POST | `/api/account/profile/cv-history/cleanup` | Dọn CV history cũ |
| POST | `/api/account/profile/migrate-local` | Import dữ liệu local có kiểm soát |

### 9.2 Settings

| Method | Path | Mục đích |
| --- | --- | --- |
| GET | `/api/account/settings` | Đọc settings và revision |
| PATCH | `/api/account/settings` | Cập nhật settings |
| POST | `/api/account/settings/reset` | Đặt lại settings |

### 9.3 History và feedback

| Method | Path | Mục đích |
| --- | --- | --- |
| GET | `/api/account/history` | Lịch sử gần đây |
| POST | `/api/account/history` | Lưu analysis session |
| GET | `/api/account/history/page` | Keyset pagination |
| GET | `/api/account/history/manual` | Lịch sử snapshot thủ công |
| POST | `/api/account/history/manual-snapshot` | Lưu snapshot thủ công |
| GET | `/api/account/history/feedback` | Danh sách feedback |
| POST | `/api/account/history/feedback` | Lưu feedback |
| GET | `/api/account/history/feedback/stats` | Thống kê feedback |
| DELETE | `/api/account/history/feedback/{feedback_id}` | Xóa feedback |

### 9.4 Đồng bộ cache/history

| Method | Path | Mục đích |
| --- | --- | --- |
| GET | `/api/account/sync/cache` | Đọc toàn bộ cache của user |
| POST | `/api/account/sync/cache` | Upsert cache entry |
| DELETE | `/api/account/sync/cache` | Xóa cache của user |
| GET | `/api/account/sync/cache/{cache_key}` | Đọc một cache entry |
| GET | `/api/account/sync/history` | Đọc lịch sử đồng bộ |
| POST | `/api/account/sync/history` | Lưu lịch sử đồng bộ |
| GET | `/api/account/sync/stats` | Thống kê đồng bộ |

### 9.5 Uploaded files

| Method | Path | Mục đích |
| --- | --- | --- |
| GET | `/api/account/uploaded-files` | Danh sách file |
| POST | `/api/account/uploaded-files` | Lưu metadata file |
| POST | `/api/account/uploaded-files/batch` | Lưu nhiều metadata |
| GET | `/api/account/uploaded-files/page` | Keyset pagination |
| GET | `/api/account/uploaded-files/by-type/{file_type}` | Lọc theo loại |
| GET | `/api/account/uploaded-files/by-session/{session_id}` | Lọc theo session |
| DELETE | `/api/account/uploaded-files/{file_id}` | Xóa file record |
| POST | `/api/account/uploaded-files/{file_id}/touch` | Cập nhật last-used |
| PATCH | `/api/account/uploaded-files/{file_id}/touch` | Alias touch |
| POST | `/api/account/uploaded-files/{file_id}/vectorize` | Vectorize một file |
| GET | `/api/account/uploaded-files/stats` | Thống kê file |
| POST | `/api/account/uploaded-files/vector-index/rebuild` | Rebuild vector index của user |

### 9.6 JD templates

| Method | Path | Mục đích |
| --- | --- | --- |
| GET | `/api/account/jd-templates` | Danh sách template |
| GET | `/api/account/jd-templates/page` | Keyset pagination |
| POST | `/api/account/jd-templates` | Tạo template |
| PATCH | `/api/account/jd-templates/{template_id}` | Cập nhật template |
| DELETE | `/api/account/jd-templates/{template_id}` | Xóa template |
| POST | `/api/account/jd-templates/seed-defaults` | Tạo template mặc định |

### 9.7 Chatbot persistence

| Method | Path | Mục đích |
| --- | --- | --- |
| GET | `/api/account/chatbot/sessions` | Danh sách session |
| POST | `/api/account/chatbot/sessions` | Tạo session |
| GET | `/api/account/chatbot/sessions/{session_id}` | Chi tiết session |
| DELETE | `/api/account/chatbot/sessions/{session_id}` | Xóa session |
| POST | `/api/account/chatbot/sessions/{session_id}/messages` | Thêm messages |
| POST | `/api/account/chatbot/sessions/{session_id}/reply` | Sinh và lưu reply |
| GET | `/api/account/chatbot/recent` | Session gần nhất theo vị trí |
| GET | `/api/account/chatbot/stats` | Thống kê chatbot |

### 9.8 Google Drive

| Method | Path | Mục đích |
| --- | --- | --- |
| GET | `/api/account/google-drive/status` | Trạng thái kết nối |
| POST | `/api/account/google-drive/oauth-url` | Tạo OAuth URL/state |
| POST | `/api/account/google-drive/exchange-code` | Đổi code lấy token |
| POST | `/api/account/google-drive/session-auth` | Kết nối bằng Google session |
| DELETE | `/api/account/google-drive/connection` | Ngắt kết nối |
| GET | `/api/account/google-drive/files` | Danh sách file Drive |
| POST | `/api/account/google-drive/import` | Import và trích text |

### 9.9 Notification, mobile inbox và email

| Method | Path | Mục đích |
| --- | --- | --- |
| GET | `/api/account/notifications` | Danh sách notification |
| POST | `/api/account/notifications/{notification_id}/read` | Đánh dấu đã đọc |
| POST | `/api/account/notifications/read-all` | Đánh dấu tất cả |
| GET | `/api/account/mobile-inbox` | Payload inbox cho mobile |
| POST | `/api/account/email/send` | Gửi email bằng Google OAuth connection lưu phía Backend; FE không truyền Google access token |

## 10. Request mẫu quan trọng

### 10.1 Extract file

```ts
const form = new FormData();
form.append("file", file);
form.append("force_ocr", "false");
form.append("document_type", "cv");

const result = await apiFetch<{ text: string; savedRecordId?: string | null }>(
  "/api/files/extract-text",
  { method: "POST", body: form },
  accessToken
);
```

### 10.2 Tạo analysis job

```json
{
  "jd_text": "Backend Developer requires Python and FastAPI.",
  "weights": {},
  "hard_filters": {},
  "cv_entries": [
    {
      "file_name": "candidate-a.pdf",
      "text": "Extracted CV text",
      "cv_id": "optional-client-id",
      "file_id": "optional-saved-file-id"
    }
  ]
}
```

Response:

```json
{
  "job_id": "uuid",
  "status": "queued",
  "status_url": "/api/analysis/status/uuid"
}
```

### 10.3 Quick score text

```json
{
  "cv_entries": [
    {
      "file_name": "candidate-a.txt",
      "text": "CV text"
    }
  ],
  "jd_text": "Optional JD text",
  "include_extracted_text": false
}
```

Tối đa 3 CV cho một request quick score.

### 10.4 Interview questions

General:

```json
{
  "analysis_data": {},
  "analysis_stats": {},
  "question_type": "general",
  "candidate_data": null
}
```

Specific bắt buộc `candidate_data` là object:

```json
{
  "analysis_data": {},
  "analysis_stats": {
    "jobPosition": "Backend Developer"
  },
  "question_type": "specific",
  "candidate_data": {
    "candidateName": "Candidate A",
    "analysis": {}
  }
}
```

Comparative bắt buộc `candidate_data` là array.

### 10.5 Candidate chat

```json
{
  "candidate_snapshot": {
    "name": "Candidate A",
    "score": 82,
    "strengths": ["Python", "FastAPI"],
    "weaknesses": ["AWS"]
  },
  "message": "Tóm tắt ứng viên này",
  "job_position": "Backend Developer",
  "recruiter_context": null
}
```

## 11. Error contract và UI behavior

| HTTP | Ý nghĩa | FE behavior |
| ---: | --- | --- |
| 200/201/202 | Thành công/đã nhận job | Render data hoặc chuyển sang polling |
| 204 | Thành công không body | Đóng modal, refresh cache |
| 304 | Cache vẫn hợp lệ | Giữ dữ liệu hiện tại |
| 400 | Request nghiệp vụ không hợp lệ | Hiện lỗi gần field/workflow |
| 401 | Thiếu/hỏng token | Refresh session hoặc login lại |
| 403 | Không có quyền | Hiện forbidden, không retry |
| 404 | Không tìm thấy resource | Empty/not-found state |
| 409 | Conflict/lock | Đọc `Retry-After`, tải lại |
| 412 | Revision cũ | Refetch rồi cho user xác nhận |
| 413 | File quá lớn | Hiện giới hạn upload |
| 415 | Loại file không hỗ trợ | Hiện định dạng hợp lệ |
| 422 | Schema validation | Map `detail[]` vào field |
| 429 | Rate limit | Countdown rồi retry có kiểm soát |
| 500 | Lỗi backend | Error boundary + request id nếu có |
| 503 | Dependency chưa ready | Degraded mode, không retry dồn dập |

Hai dạng lỗi phổ biến:

```json
{
  "detail": "Thông báo lỗi"
}
```

```json
{
  "detail": [
    {
      "loc": ["body", "field_name"],
      "msg": "Field required",
      "type": "missing"
    }
  ]
}
```

Không render raw stack trace hoặc raw provider error cho người dùng cuối.

## 12. Pagination, cache và performance

Các route `/page` dùng keyset cursor:

```text
?page_size=50&cursor=<opaque-cursor>&fields=id,name,updatedAt
```

Rules:

- coi cursor là opaque string;
- không tự giải mã hoặc sửa cursor;
- `page_size` tối đa 200;
- dùng `fields` đúng allowlist;
- merge page theo `id`, không theo index;
- dừng khi response không còn next cursor;
- dùng `If-None-Match`/`ETag` cho settings và dữ liệu hỗ trợ cache;
- hủy request cũ khi filter/search thay đổi.

## 13. Trạng thái feature và degraded mode

FE không hard-code rằng một integration luôn sẵn sàng.

| Feature | Cách xác định |
| --- | --- |
| API process | `GET /health/live` |
| Runtime dependency | `GET /health/ready` |
| Classifier | `GET /api/cv/classifier-status` |
| GraphRAG | `GET /api/cv/graphrag-status` |
| Google Drive | `GET /api/account/google-drive/status` sau login |
| Firebase account | Request account thật với Bearer token |

Nếu GraphRAG trả `enabled=false` hoặc `approvedFactCount=0`, không hiển thị badge “GraphRAG active”.

Nếu `/health/ready=503`, không giả lập lịch sử/profile bằng dữ liệu local rồi trình bày như dữ liệu server.

## 14. Checklist nghiệm thu FE được sinh

- [ ] API base URL chỉ đến từ environment.
- [ ] Type được sinh từ OpenAPI.
- [ ] Không có secret backend trong source/bundle.
- [ ] Account request luôn có Bearer token mới.
- [ ] JSON và multipart được gửi đúng `Content-Type`.
- [ ] Không có global casing conversion.
- [ ] Analysis job có polling, timeout, cancel và cleanup.
- [ ] Có loading, empty, error, offline và degraded state.
- [ ] `401`, `409`, `412`, `422`, `429`, `503` có UX riêng.
- [ ] DELETE có xác nhận.
- [ ] Không retry mutation ngoài ý muốn.
- [ ] AI verdict luôn kèm lý do/bằng chứng và thông báo hỗ trợ quyết định.
- [ ] Google OAuth callback kiểm tra `state`.
- [ ] Pagination coi cursor là opaque.
- [ ] Test ít nhất desktop, mobile viewport và keyboard navigation.
- [ ] Contract test dùng `/openapi.json` của đúng environment.

## 15. Bảo trì tài liệu

Khi thêm/xóa/đổi path, auth hoặc schema:

1. cập nhật route/schema backend;
2. kiểm tra `app.openapi()` và `/openapi.json`;
3. cập nhật file này nếu workflow FE thay đổi;
4. sinh lại TypeScript type;
5. chạy contract test và smoke test environment;
6. không sửa tài liệu để che việc runtime chưa sẵn sàng.

Swagger:

```text
https://backendsupporthr.onrender.com/docs
```

OpenAPI:

```text
https://backendsupporthr.onrender.com/openapi.json
```
