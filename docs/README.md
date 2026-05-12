# Tài liệu Backend

Các file trong thư mục `docs` mô tả đúng những gì backend đang làm ở thời điểm hiện tại.

Mỗi thư mục con đại diện cho một mảng chức năng, và mỗi mảng có một file `README.md` riêng:

- `query-cache`: cơ chế cache kết quả phân tích theo người dùng và `cacheKey`
- `firestore-db`: mô hình dữ liệu Firestore, collection nào đang được dùng
- `vector-embeddings`: phần embedding, cosine similarity, và "vector DB" hiện tại
- `matching-scoring`: logic so khớp CV/JD và cộng trừ điểm sau phân tích AI
- `file-extraction-ocr`: luồng upload file, trích xuất text, OCR
- `ai-workflows`: các workflow AI như chuẩn hóa JD, trích bộ lọc cứng, phân tích CV, sinh câu hỏi phỏng vấn
- `google-drive-import`: kết nối OAuth Google Drive, duyệt file, import file và trích text

## Luồng tổng quát của backend

1. Người dùng upload file hoặc import file từ Google Drive.
2. Backend trích text từ PDF, DOCX, ảnh, TXT hoặc CSV.
3. Backend dùng Gemini để phân tích CV theo JD và trọng số.
4. Backend enrich kết quả bằng luật nội bộ:
   - skill graph
   - career velocity
   - soft-skill heuristics
   - company tier
   - embedding similarity
5. Kết quả có thể được lưu vào:
   - cache đồng bộ
   - lịch sử phân tích
   - uploaded files
   - hồ sơ người dùng
   - chatbot sessions

## Cấu trúc tổng thể backend

```text
backend/
├─ app/
│  ├─ api/
│  │  ├─ deps.py
│  │  ├─ routes_account.py
│  │  ├─ routes_ai.py
│  │  └─ routes_files.py
│  ├─ core/
│  │  └─ config.py
│  ├─ integrations/
│  │  └─ firebase_admin.py
│  ├─ repositories/
│  │  └─ firestore/
│  │     └─ account_repository.py
│  ├─ schemas/
│  │  ├─ account.py
│  │  ├─ analysis.py
│  │  ├─ files.py
│  │  ├─ gemini.py
│  │  └─ workflows.py
│  ├─ services/
│  │  ├─ account/
│  │  │  ├─ cache_service.py
│  │  │  ├─ chatbot_service.py
│  │  │  ├─ google_drive_service.py
│  │  │  ├─ history_service.py
│  │  │  ├─ profile_service.py
│  │  │  ├─ shared.py
│  │  │  ├─ template_service.py
│  │  │  └─ uploaded_file_service.py
│  │  ├─ candidate_enrichment_service.py
│  │  ├─ candidate_refinement_service.py
│  │  ├─ cv_analysis_service.py
│  │  ├─ file_extraction_service.py
│  │  ├─ gemini_service.py
│  │  └─ workflow_service.py
│  └─ main.py
├─ docs/
├─ requirements.txt
├─ render.yaml
└─ README.md
```

## Vai trò từng tầng

### `app/main.py`

Điểm vào của ứng dụng:

- khởi tạo `FastAPI`
- cấu hình `CORS`
- mount các router chính

### `app/api`

Tầng route nhận request và trả response.

- `routes_ai.py`: các API AI, JD workflow, CV workflow, interview questions
- `routes_files.py`: upload file và trích text
- `routes_account.py`: profile, cache, history, uploaded files, chatbot, Google Drive
- `deps.py`: lấy user hiện tại từ Firebase token

### `app/core`

Chứa cấu hình dùng chung của hệ thống.

- `config.py`: đọc biến môi trường, model Gemini, Firebase config, Google OAuth config

### `app/integrations`

Tầng kết nối dịch vụ ngoài ở mức thấp.

- `firebase_admin.py`: khởi tạo Firebase Admin, Firestore client, verify token

### `app/repositories`

Tầng truy cập dữ liệu.

- `firestore/account_repository.py`: định nghĩa collection refs và helper CRUD cơ bản cho Firestore

### `app/schemas`

Tầng schema dữ liệu với Pydantic.

- định nghĩa request/response model cho account, AI, file, workflow

### `app/services`

Tầng business logic chính của backend.

- `gemini_service.py`: wrapper gọi Gemini và embedding
- `file_extraction_service.py`: trích text từ PDF, DOCX, ảnh, TXT, CSV
- `cv_analysis_service.py`: chấm CV theo JD bằng AI
- `candidate_refinement_service.py`: refine học vấn và tên ứng viên
- `candidate_enrichment_service.py`: enrich điểm bằng rule, skill graph, embedding similarity
- `workflow_service.py`: chuẩn hóa JD, trích hard filters, tạo câu hỏi phỏng vấn

### `app/services/account`

Nhóm service dành riêng cho dữ liệu cá nhân người dùng:

- `profile_service.py`: hồ sơ người dùng và lịch sử CV cơ bản
- `cache_service.py`: cache kết quả phân tích
- `history_service.py`: lịch sử đồng bộ, snapshot phiên phân tích
- `uploaded_file_service.py`: lưu metadata file đã upload/import
- `template_service.py`: JD templates
- `chatbot_service.py`: chatbot sessions
- `google_drive_service.py`: OAuth Drive, duyệt file, import file
- `shared.py`: helper serialize/sort dùng chung

## Luồng gọi lớp trong backend

Luồng code thường đi theo thứ tự:

```text
Client
-> API Route
-> Dependency Auth (nếu có)
-> Service
-> Repository / Integration
-> Firestore hoặc Google/Gemini
-> Response Schema
-> Client
```

Ví dụ:

- phân tích CV: `routes_ai.py -> cv_analysis_service.py -> gemini_service.py`
- lấy cache user: `routes_account.py -> cache_service.py -> account_repository.py -> Firestore`
- import từ Google Drive: `routes_account.py -> google_drive_service.py -> Google Drive API -> file_extraction_service.py`

## Gợi ý đọc nhanh

- Nếu bạn muốn hiểu cache: đọc `query-cache/README.md`
- Nếu bạn muốn hiểu database: đọc `firestore-db/README.md`
- Nếu bạn muốn hiểu "vector DB" và so khớp embedding: đọc `vector-embeddings/README.md`
- Nếu bạn muốn hiểu cách chấm điểm ứng viên: đọc `matching-scoring/README.md`
- Nếu bạn muốn hiểu luồng import CV/JD: đọc `file-extraction-ocr/README.md` và `google-drive-import/README.md`
- Nếu bạn muốn hiểu các endpoint AI: đọc `ai-workflows/README.md`
