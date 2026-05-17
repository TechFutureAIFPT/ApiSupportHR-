# AI Workflows

## Tổng quan

Backend đang có nhiều workflow AI khác nhau, không chỉ một endpoint chat đơn giản.

Các workflow này nằm chủ yếu ở:

- `workflow_service.py`
- `cv_analysis_service.py`
- `candidate_refinement_service.py`
- `candidate_enrichment_service.py`
- `gemini_service.py`

## Các endpoint AI chính

### Gemini cơ bản

- `POST /api/gemini-chat`
- `POST /api/gemini-embed`

Mục đích:

- chat/generate nội dung tự do
- tạo embedding cho text

### JD workflow

- `POST /api/jd/structure`
- `POST /api/jd/position`
- `POST /api/jd/hard-filters`

### Interview workflow

- `POST /api/interview/questions`

### CV workflow

- `POST /api/cv/analyze-core`
- `POST /api/cv/refine-profile`
- `POST /api/cv/enrich`

## Từng workflow đang làm gì

### 1. `jd/structure`

Mục tiêu:

- dọn một JD thô
- giữ lại đúng 3 phần chính

Output chuẩn hóa:

- `MucDichCongViec`
- `MoTaCongViec`
- `YeuCauCongViec`

Model phải trả JSON, sau đó backend format lại thành text có section rõ ràng.

### 2. `jd/position`

Mục tiêu:

- lấy chính xác tên vị trí tuyển dụng

Backend tiếp tục:

- cắt ký tự thừa
- bỏ label như `Job Title`, `Position`, `Chuc danh`
- giới hạn độ dài hợp lý

### 3. `jd/hard-filters`

Mục tiêu:

- trích bộ lọc cứng từ JD
- chuẩn hóa về danh sách giá trị mà frontend/backend hiểu được

Các field chính:

- `location`
- `minExp`
- `seniority`
- `education`
- `language`
- `languageLevel`
- `certificates`
- `workFormat`
- `contractType`
- `industry`

Backend còn có bước validate và map alias, ví dụ:

- `HCM` -> `Thanh pho Ho Chi Minh`
- `WFH` -> `Remote`
- `Fresher` -> `Junior`

### 4. `cv/analyze-core`

Mục tiêu:

- lấy JD, weights, hard filters và text của nhiều CV
- yêu cầu Gemini chấm từng CV
- trả về JSON cấu trúc chuẩn cho frontend

Đây là lớp phân tích nền đầu tiên trước khi enrich.

### 5. `cv/refine-profile`

Mục tiêu:

- xác thực và chuẩn hóa thông tin học vấn
- phục hồi tên ứng viên nếu text CV bị lỗi OCR hoặc nhiễu

Output chính:

- `standardized_education`
- `validation_note`
- `warnings`
- `refined_name`

Luồng này hữu ích khi:

- CV bị lỗi template kiểu TopCV, VietnamWorks, JobStreet chen vào tên trường
- phần Education bị lẫn format
- tên ứng viên bị OCR lỗi hoặc dính ký tự rác

### 6. `cv/enrich`

Mục tiêu:

- bổ sung logic chấm điểm nội bộ sau khi AI core analysis xong

Bao gồm:

- skill graph
- debiasing warnings
- soft skills
- career velocity
- company tier
- dynamic boost
- embedding similarity

### 7. `interview/questions`

Mục tiêu:

- sinh bộ câu hỏi phỏng vấn bằng tiếng Việt

Hệ thống đang support 3 kiểu:

- `general`
- `specific`
- `comparative`

Tức là có thể:

- hỏi chung theo cả batch ứng viên
- hỏi riêng cho một ứng viên
- hỏi để so sánh giữa nhiều ứng viên

## Cách backend gọi Gemini

`gemini_service.py` đang làm wrapper chung:

- xoay vòng qua nhiều API key
- fallback model nếu model chính lỗi
- normalize config keys từ camelCase sang snake_case
- ném `HTTPException` khi tất cả key/model đều fail

## Ý nghĩa kiến trúc

Backend đang tách workflow khá rõ:

- route chỉ nhận request và trả response
- service chứa prompt + business logic
- Gemini wrapper xử lý chuyện key/model/fallback

Cách tách này giúp:

- dễ thay prompt
- dễ kiểm soát lỗi provider
- dễ gắn thêm luật nội bộ sau bước AI
