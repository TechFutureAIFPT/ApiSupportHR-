# Query Cache

## Mục tiêu

Backend có một lớp cache để lưu lại kết quả phân tích ứng viên đã xử lý xong, giúp frontend không phải chạy lại toàn bộ pipeline mỗi lần mở lại phiên làm việc.

Collection được dùng:

```text
syncedAnalysisCache
```

## Cách định danh cache

Mỗi bản ghi cache có:

- `uid`: người dùng sở hữu cache
- `cacheKey`: khóa logic do frontend truyền lên
- document id trong Firestore: `"{uid}_{cacheKey}"`

Điều này có nghĩa là:

- cùng một `cacheKey` nhưng khác user thì không đè nhau
- cùng một user và cùng `cacheKey` thì lần sync sau sẽ ghi đè bản cũ

## Dữ liệu được lưu

Một cache entry gồm các trường chính:

```json
{
  "uid": "...",
  "email": "...",
  "displayName": "...",
  "photoURL": "...",
  "cacheKey": "...",
  "candidateData": {},
  "timestamp": "server timestamp",
  "jdHash": "...",
  "weightsHash": "...",
  "filtersHash": "...",
  "fileInfo": {
    "name": "...",
    "size": 0,
    "lastModified": 0
  },
  "expiresAt": "UTC datetime",
  "lastValidatedAt": "server timestamp"
}
```

Ý nghĩa:

- `candidateData`: payload kết quả chính để frontend dùng lại
- `jdHash`, `weightsHash`, `filtersHash`: dấu vết để frontend/backend biết cache này gắn với JD, trọng số và bộ lọc nào
- `fileInfo`: metadata file nguồn
- `expiresAt`: ngày hết hạn cache

## Chính sách giữ cache

- Mỗi user giữ tối đa `50` cache entry
- Mỗi cache sống `30 ngày`
- Khi ghi mới, backend tự gọi cleanup để xóa các entry cũ hơn
- Khi đọc, nếu entry đã quá hạn thì backend xóa luôn rồi trả `null`

## Các API liên quan

Các route account đang dùng cho cache:

- `POST /api/account/sync/cache`
- `GET /api/account/sync/cache/{cache_key}`
- `GET /api/account/sync/cache`
- `DELETE /api/account/sync/cache`

## Luồng hoạt động

### 1. Sync cache

Frontend gửi kết quả phân tích cùng `cacheKey` lên backend.

Backend:

- tính `expiresAt = now + 30 ngày`
- ghi vào `syncedAnalysisCache`
- gọi cleanup để chỉ giữ lại tối đa 50 bản ghi cho user đó

### 2. Lấy một cache cụ thể

Backend đọc document `uid_cacheKey`.

- nếu không tồn tại: trả `null`
- nếu quá hạn: xóa rồi trả `null`
- nếu hợp lệ: trả `candidateData`

### 3. Lấy toàn bộ cache của user

Backend query toàn bộ document theo `uid`, lọc bản quá hạn rồi trả về:

```json
{
  "cacheKeyA": { "...": "candidateData" },
  "cacheKeyB": { "...": "candidateData" }
}
```

## Điều cần lưu ý

- Logic tạo `cacheKey` hiện không nằm trong backend, backend chỉ nhận và lưu lại.
- Cache này là cache ứng dụng trong Firestore, không phải Redis hay in-memory cache.
- Cache được phân quyền theo `uid`, nên không dùng chung giữa các người dùng.
