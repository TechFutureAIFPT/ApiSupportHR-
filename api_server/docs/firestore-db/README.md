# Firestore DB

## Tổng quan

Backend đang dùng `Firebase Admin SDK` để kết nối `Cloud Firestore`.

Mẫu thiết kế hiện tại là:

- mỗi mảng nghiệp vụ dùng một collection riêng
- gần như mọi bản ghi đều gắn với `uid`
- phần lớn truy vấn là `where("uid", "==", user.uid)`
- sorting thường được làm ở tầng Python sau khi đọc dữ liệu

## Các collection đang dùng

### `users`

Lưu hồ sơ người dùng:

- `uid`
- `email`
- `displayName`
- `avatar`
- `provider`
- `createdAt`
- `updatedAt`

### `cvHistory`

Collection này đang được dùng cho hai kiểu dữ liệu:

- lịch sử CV/JD đơn giản từ profile
- snapshot phân tích đầy đủ từ history service

Các field thường gặp:

- `uid`
- `email` hoặc `userEmail`
- `jdText`, `jdTitle`
- `results`
- `jobPosition`
- `locationRequirement`
- `fullPayload`
- `grades`
- `topCandidates`
- `timestamp`
- `createdAt`

Lưu ý: đây là collection có hơi trộn nhiều kiểu payload, nên khi đọc code sẽ thấy backend phải lọc field để biết document thuộc dạng nào.

### `syncedAnalysisCache`

Lưu cache kết quả phân tích theo `uid + cacheKey`.

### `syncedAnalysisHistory`

Lưu lịch sử đồng bộ của phiên phân tích:

- `analysisData`
- `jobPosition`
- `locationRequirement`
- `totalCandidates`
- `gradesCount`
- `timestamp`

### `uploadedFiles`

Lưu metadata file đã upload hoặc import:

- `fileName`
- `fileType`
- `fileSize`
- `mimeType`
- `fileExtension`
- `ocrMethod`
- `extractedText`
- `extractedTextLength`
- `processingTimeMs`
- `analysisSessionId`
- `candidateName`
- `jobPosition`
- `uploadedAt`

### `userJDTemplates`

Lưu template JD cá nhân:

- `name`
- `category`
- `jobPosition`
- `jdText`
- `hardFilters`
- `createdAt`
- `updatedAt`

### `chatbotSessions`

Lưu hội thoại chatbot theo phiên:

- `jobPosition`
- `totalCandidates`
- `sessionTitle`
- `messages`
- `messageCount`
- `createdAt`
- `updatedAt`
- `lastMessageAt`

### `googleDriveConnections`

Lưu kết nối Google Drive của người dùng:

- `accessToken`
- `refreshToken`
- `expiresAt`
- `scopes`
- `email`
- `displayName`
- `photoUrl`
- `driveUserId`

### `googleDriveOAuthStates`

Lưu state ngắn hạn cho OAuth:

- `uid`
- `redirectUri`
- `createdAt`
- `expiresAt`

### `analysisJobs`

Luu trang thai job phan tich CV bat dong bo:

- `jobId`
- `uid`
- `status`
- `progress`
- `message`
- `result`
- `error`
- `sourceTexts`
- `createdAt`
- `updatedAt`

### `aiRequestHistory`

Luu snapshot cac thao tac AI phu tro khi request co user:

- `operation`
- `request`
- `response`
- `metadata`
- `uid`
- `timestamp`

Dang duoc dung cho Gemini chat/embed, JD structure/position/hard filters, interview questions, refine CV profile, classify industry, va enrich candidates.

### `mobileQuickCvAnalyses`

Luu ket qua quick score CV:

- `request`
- `response`
- `itemCount`
- `model`
- `uid`
- `timestamp`

### `fileExtractions`

Luu ket qua trich xuat text tu file khi request co user:

- `fileName`
- `mimeType`
- `fileSize`
- `documentType`
- `forceOcr`
- `extractedText`
- `extractedTextLength`
- `uid`
- `timestamp`

### `mobileJDStandardizations`

Luu lich su chuan hoa JD mobile:

- `jdText`
- `targetPlatform`
- `supplementalFields`
- `response`
- `sourceFile`
- `score`
- `title`
- `uid`
- `timestamp`

### `CLdl7JGuaOGIuijiDZeG`

Đây là một collection id cố định đang được code gọi là `manual_history`.

Nó được dùng để lưu snapshot dạng "manual history", ví dụ:

- `JD mẫu`
- `Vị trí Lọc JD`
- `Yêu cầu địa điểm`
- `Danh sách CV`
- `Thống kê`
- `weights`
- `hardFilters`
- `updatedAt`

## Pattern dùng chung

### 1. Phân quyền theo user

Gần như service nào cũng:

- query theo `uid`
- sau đó mới cho phép đọc/sửa/xóa

### 2. Dùng `server_timestamp`

Thời gian server chủ yếu được ghi bằng:

```python
firestore.SERVER_TIMESTAMP
```

### 3. Cleanup theo giới hạn số lượng

Nhiều service có cleanup nội bộ:

- cache: tối đa 50
- history: tối đa 100
- uploaded files: tối đa 500
- chatbot sessions: tối đa 100

## Những điểm nên nhớ

- Firestore ở đây đóng vai trò application database chính.
- Hiện chưa có ORM hay repository abstraction phức tạp; repository chủ yếu chỉ trả về collection ref.
- Một số collection đang chứa nhiều shape dữ liệu khác nhau, nên tài liệu này cố ý ghi rõ để tránh hiểu nhầm khi bảo trì.
