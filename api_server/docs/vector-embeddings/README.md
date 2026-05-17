# Vector Embeddings

## Kết luận ngắn gọn

Hiện tại backend **chưa dùng một vector database thật** như Pinecone, Milvus, Weaviate, pgvector hay Elasticsearch dense vector.

Thay vào đó, hệ thống đang làm theo kiểu:

1. tạo embedding cho CV bằng Gemini
2. nạp một thư viện embedding mẫu từ file JSON
3. tính cosine similarity trực tiếp trong Python
4. lấy top match để cộng điểm bonus

Nói cách khác: đây là một **vector library đọc từ file**, chưa phải **vector DB**.

## Nguồn embedding của ứng viên

Backend gọi:

```python
embed_text(text, model)
```

Luồng thực tế:

- service `candidate_enrichment_service` truyền model legacy `text-embedding-004`
- `gemini_service` tự fallback sang `gemini-embedding-001` nếu cần
- kết quả là một vector số thực `List[float]`

Text được embed là:

- CV text đã được cắt gọn
- tối đa khoảng `6000` ký tự sau khi normalize whitespace

## Nguồn embedding thư viện mẫu

Backend tìm file theo pattern:

```text
frontend/public/data/{industry}-embeddings.json
```

Ví dụ:

- `it-embeddings.json`
- `sales-embeddings.json`
- `marketing-embeddings.json`

Mỗi file được kỳ vọng có dạng gần giống:

```json
{
  "records": [
    {
      "id": "sample-1",
      "name": "Candidate A",
      "role": "Backend Developer",
      "relativePath": "data/cv-001.txt",
      "vector": [0.12, -0.04, 0.98]
    }
  ]
}
```

## Cách tính giống nhau

Backend dùng:

```text
cosine similarity
```

Các bước:

1. Embed CV hiện tại
2. Lặp qua toàn bộ record trong file JSON
3. Tính cosine similarity giữa vector CV và vector mẫu
4. Sắp xếp giảm dần
5. Lấy top `3`
6. Tính `averageSimilarity`
7. Đổi similarity thành `bonusPoints`

## Quy tắc đổi similarity thành điểm thưởng

```text
>= 0.88  -> +5.0
>= 0.83  -> +3.5
>= 0.78  -> +2.0
>= 0.72  -> +1.0
<  0.72  -> +0.0
```

## Điều kiện để phần này chạy

Backend chỉ chạy khi:

- phát hiện được industry phù hợp từ CV/JD/filter
- file embeddings của industry đó tồn tại
- gọi embedding thành công

Nếu thiếu một trong các điều kiện trên thì:

- hệ thống bỏ qua embedding bonus
- không crash pipeline chính

## Tình trạng hiện tại của repo

Trong workspace hiện tại, mình không thấy thư mục:

```text
frontend/public/data
```

Điều đó có nghĩa là ở trạng thái local hiện tại:

- code support tính năng embedding similarity
- nhưng dữ liệu thư viện mẫu đang chưa có trong repo này
- kết quả thực tế nhiều khả năng sẽ không có `embeddingInsights`

## Tối ưu nhỏ đang có

Backend dùng:

```python
@lru_cache(maxsize=4)
```

để cache nội dung các file embeddings đã nạp, tránh đọc lại file JSON nhiều lần.

## Ý nghĩa nghiệp vụ

Mục tiêu của phần này là:

- so CV hiện tại với các CV mẫu "đẹp" cùng ngành
- nếu tương đồng cao thì cộng thêm điểm bonus
- coi như một lớp tham chiếu chất lượng dựa trên semantic similarity

## Nếu sau này muốn nâng cấp thành vector DB thật

Bạn có thể giữ nguyên ý tưởng nghiệp vụ, chỉ thay tầng lưu và truy vấn:

- thay file JSON bằng `pgvector`, Pinecone hoặc Qdrant
- thay vòng lặp Python bằng truy vấn top-k nearest neighbors
- vẫn giữ công thức cộng bonus hiện tại nếu muốn
