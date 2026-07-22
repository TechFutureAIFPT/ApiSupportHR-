# File Extraction And OCR

## Mục tiêu

Backend có một service chuyên để đổi file đầu vào thành text sạch, phục vụ cho các bước phân tích JD và CV.

Service chính:

```text
app/services/file_extraction_service.py
```

API chính:

```text
POST /api/files/extract-text
```

## Các loại file đang hỗ trợ

- PDF
- DOCX
- ảnh (`image/*`)
- TXT
- CSV

Nếu file không thuộc các loại trên thì backend sẽ báo lỗi `Unsupported file format`.

## Giới hạn hiện tại

- dung lượng tối đa: `15MB`

## Luồng xử lý theo từng loại file

### 1. PDF

Backend làm theo hai bước:

#### Bước A: thử lấy text layer

PDF được mở bằng `PyMuPDF (fitz)` và backend gọi:

```python
page.get_text("text")
```

Nếu text layer đủ dài và đủ "có nghĩa" thì dùng luôn.

#### Bước B: fallback OCR

Nếu:

- PDF không có text layer tốt
- hoặc frontend bật `force_ocr = true`

thì backend:

- render tối đa `3` trang đầu thành ảnh PNG
- gửi từng ảnh vào Gemini Vision
- ghép text OCR lại

Mục tiêu là xử lý các CV/JD scan hoặc PDF ảnh.

### 2. DOCX

Backend dùng `python-docx` để lấy:

- toàn bộ paragraph
- toàn bộ text trong table

Text từ table sẽ được nối kiểu:

```text
cell1 | cell2 | cell3
```

### 3. Ảnh

Backend gửi trực tiếp bytes ảnh vào Gemini Vision để OCR.

Prompt OCR được tách theo loại tài liệu:

- `cv`
- `jd`

Điều này giúp model ưu tiên đúng các vùng thông tin quan trọng.

### 4. TXT và CSV

Backend thử decode theo thứ tự:

- `utf-8`
- `utf-8-sig`
- `latin-1`

## Gemini Vision đang được dùng thế nào

Model OCR hiện tại:

```text
gemini-3.6-flash
```

Prompt OCR yêu cầu:

- giữ line breaks
- giữ bullet, numbering
- cố gắng giữ structure bảng
- chỉ sửa lỗi OCR khi ý nghĩa đã rõ
- trả về plain text

## Làm sạch text sau trích xuất

Sau khi lấy text, backend tiếp tục:

- chuẩn hóa line break
- bỏ tab, non-breaking space
- thu gọn khoảng trắng
- sửa một số lỗi OCR đơn giản

Nếu text sau làm sạch rỗng, backend coi như trích xuất thất bại.

## Các tham số quan trọng

- `force_ocr`: ép OCR kể cả khi PDF có text layer
- `document_type`: nhận `cv` hoặc `jd`

Ý nghĩa:

- `cv`: prompt sẽ ưu tiên tên, email, kinh nghiệm, kỹ năng
- `jd`: prompt sẽ ưu tiên tiêu đề, yêu cầu, kỹ năng, lương, địa điểm

## Ý nghĩa nghiệp vụ

Đây là tầng nền của toàn bộ hệ thống.

Nếu bước trích xuất text không tốt thì:

- phân tích CV sai
- trích hard filters sai
- so khớp kỹ năng sai
- ranking cuối cùng cũng sai theo
