# Matching And Scoring

## Bức tranh tổng thể

Phần so khớp CV/JD của backend không chỉ dựa vào một lần gọi AI.

Nó là pipeline hai tầng:

1. **AI core analysis**
2. **rule-based enrichment**

Kết quả cuối cùng là sự kết hợp của cả hai tầng này.

## Tầng 1: AI core analysis

Service chính:

```text
app/services/cv_analysis_service.py
```

Backend gửi cho Gemini:

- JD đã chuẩn hóa
- bộ trọng số đánh giá
- hard filters
- text của từng CV

Gemini phải trả về JSON array với mỗi ứng viên có:

- thông tin cơ bản
- `analysis`
- `Tổng điểm`
- `Hạng`
- `Chi tiết`
- `Điểm mạnh CV`
- `Điểm yếu CV`

Đây là điểm nền ban đầu của ứng viên.

## Tầng 2: Rule-based enrichment

Service chính:

```text
app/services/candidate_enrichment_service.py
```

Sau khi AI trả kết quả, backend tiếp tục enrich bằng nhiều lớp logic nội bộ.

## Các lớp enrich đang có

### 1. Debiasing warnings

Backend quét CV và bộ lọc cứng để phát hiện các yếu tố nhạy cảm như:

- giới tính
- tuổi
- tôn giáo
- dân tộc
- hôn nhân
- quê quán
- hình ảnh

Mục đích:

- cảnh báo rủi ro tuyển dụng thiên vị
- không trực tiếp cộng/trừ điểm

### 2. Soft-skill heuristics

Backend đọc CV text và chấm thêm các khía cạnh:

- mức độ chủ động
- khả năng trình bày theo STAR
- độ ổn định và trung thành

Các phần này được suy ra từ:

- động từ hành động
- động từ lãnh đạo
- động từ thụ động
- dấu hiệu có số liệu, kết quả, thành tích
- khoảng thời gian làm việc

### 3. Career velocity

Backend cố gắng suy ra:

- cấp bậc cao nhất
- số lần thăng tiến
- tốc độ thăng tiến
- số tháng trung bình để lên level mới

Sau đó thêm một detail kiểu:

```text
Tiềm năng phát triển (Career Velocity)
```

### 4. Skill Graph

Đây là phần "so khớp kỹ năng" thực sự theo luật.

Luồng hoạt động:

1. Tách skill từ JD
2. Tách skill từ candidate
3. So exact match trước
4. Nếu không exact match thì thử match theo cluster

Ví dụ cluster:

- `frontend-react`
- `backend-python`
- `database`
- `devops`

Ví dụ ý tưởng:

- JD cần `nextjs`
- CV có `react`
- hệ thống có thể xem đây là match chuyển đổi trong cùng họ skill

Kết quả trả về:

- `matchedSkills`
- `unmatchedSkills`
- `transferMatches`
- `familyClusters`
- `matchRate`

### 5. Company tier multiplier

Nếu CV chứa tên công ty uy tín, backend có thể nhân hệ số uy tín.

Hiện có các nhóm:

- `TIER1_GLOBAL`
- `TIER2_GLOBAL`
- `TIER1_VN`
- `TIER2_VN`

Ảnh hưởng:

- tier cao hơn có multiplier lớn hơn
- `Tổng điểm` có thể được tăng

### 6. Dynamic boost

Nếu một tiêu chí nào đó nổi bật mạnh, backend có thể dùng nó để bù một phần cho các tiêu chí còn thiếu.

Ý tưởng:

- tìm các tiêu chí quá mạnh
- tìm các tiêu chí còn hụt
- cộng một lượng boost có kiểm soát

Mục tiêu:

- tránh việc ứng viên rất mạnh ở một chiều nhưng bị "kẹt cứng" vì vài tiêu chí nhỏ

### 7. Embedding similarity bonus

Nếu CV giống các CV mẫu chuẩn cùng ngành, backend cộng thêm điểm bonus.

Phần này được mô tả kỹ hơn trong:

```text
docs/vector-embeddings/README.md
```

## Cách xếp hạng cuối cùng

Sau khi enrich xong, backend gán lại rank:

```text
A nếu score >= 75
B nếu score >= 50
C nếu score < 50
```

Cuối cùng danh sách ứng viên được sort theo:

1. `Tổng điểm` giảm dần
2. `fileName` tăng dần

## Ý nghĩa thực tế

Hệ thống đang kết hợp:

- AI để hiểu ngữ nghĩa CV/JD
- luật cứng để giữ sự ổn định
- heuristic để khai thác thêm tín hiệu từ CV
- semantic similarity để thưởng cho CV giống mẫu tốt

Đây là lý do tại sao hai ứng viên có điểm AI gần nhau vẫn có thể bị đảo thứ hạng sau bước enrich.
