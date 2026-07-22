# Legacy source fields for Mobile features

Tài liệu này dùng để tạo collection/field thủ công trong Firebase trước khi nối logic lưu dữ liệu.

## 1. `mobileQuickCvAnalyses`

Lưu lịch sử chấm CV nhanh trên app mobile.

```json
{
  "uid": "firebase-user-uid",
  "email": "hr@example.com",
  "feature": "quick_cv",
  "createdAt": "serverTimestamp",
  "updatedAt": "serverTimestamp",
  "timestamp": 1717300000000,

  "jdTitle": "Backend Developer",
  "jdText": "JD dùng để chấm CV, nếu có",
  "targetRole": "Backend Developer",

  "source": {
    "surface": "mobile_app",
    "inputMode": "file_upload",
    "fileCount": 3
  },

  "summary": {
    "totalCandidates": 3,
    "averageScore": 72,
    "gradeCount": {
      "A": 1,
      "B": 1,
      "C": 1
    },
    "bestCandidateName": "Nguyễn Văn A",
    "bestScore": 88
  },

  "items": [
    {
      "id": "candidate-local-id",
      "fileName": "cv-nguyen-van-a.pdf",
      "candidateName": "Nguyễn Văn A",
      "avatarUrl": "https://example.com/candidates/nguyen-van-a.jpg",
      "targetRole": "Backend Developer",
      "score": 88,
      "rank": "A",
      "summary": "Ứng viên phù hợp tốt với JD.",
      "strengths": ["Python", "FastAPI", "PostgreSQL"],
      "weaknesses": ["Chưa thấy kinh nghiệm cloud rõ ràng"],
      "improvements": ["Cần hỏi thêm về triển khai production"],
      "matchedKeywords": ["FastAPI", "SQL", "REST API"],
      "missingKeywords": ["AWS"],
      "warnings": []
    }
  ],

  "model": "gemini-3.6-flash",
  "usageNote": "Quick CV score from mobile"
}
```

### Field bắt buộc

- `uid`
- `email`
- `feature`
- `createdAt`
- `timestamp`
- `summary.totalCandidates`
- `items`

### Field nên index

- `uid`
- `timestamp`
- `feature`

Query thường dùng:

- `where uid == currentUser.uid`
- `orderBy timestamp desc`

---

## 2. `mobileJDStandardizations`

Lưu lịch sử chuẩn hóa JD trên app mobile.

```json
{
  "uid": "firebase-user-uid",
  "email": "hr@example.com",
  "feature": "jd_standardizer",
  "createdAt": "serverTimestamp",
  "updatedAt": "serverTimestamp",
  "timestamp": 1717300000000,

  "input": {
    "inputMode": "text",
    "sourceFileName": "",
    "rawJD": "JD gốc hoặc text trích xuất từ file",
    "targetPlatform": "topcv",
    "supplementalFields": {
      "companyName": "Hipo Tools",
      "salary": "15-25 triệu",
      "location": "Hà Nội",
      "workingTime": "Thứ 2 - Thứ 6",
      "benefits": "BHXH, thưởng KPI, đào tạo",
      "applicationInfo": "Gửi CV về hr@company.com",
      "notes": "Ưu tiên ứng viên có kinh nghiệm SaaS"
    }
  },

  "result": {
    "score": 86,
    "source": "ai",
    "generatedAt": "2026-06-03T10:00:00Z",
    "platform": {
      "name": "TopCV",
      "url": "https://www.topcv.vn/"
    },
    "platformUrl": "https://www.topcv.vn/",
    "missingSections": [
      {
        "key": "salary",
        "label": "Mức lương",
        "reason": "JD chưa nêu khoảng lương.",
        "priority": "high"
      }
    ],
    "weakPoints": [
      {
        "label": "Yêu cầu còn chung chung",
        "detail": "Cần tách kỹ năng bắt buộc và kỹ năng ưu tiên."
      }
    ],
    "suggestions": [
      {
        "label": "Bổ sung quyền lợi",
        "detail": "Nên thêm bảo hiểm, đào tạo, lộ trình thăng tiến."
      }
    ],
    "normalizedJD": {
      "title": "Backend Developer",
      "overview": "Mô tả ngắn về vị trí.",
      "responsibilities": ["Xây dựng API", "Tối ưu database"],
      "requirements": ["Từ 2 năm kinh nghiệm backend", "Biết FastAPI"],
      "benefits": ["BHXH", "Thưởng KPI"],
      "workingTime": "Thứ 2 - Thứ 6",
      "location": "Hà Nội",
      "salary": "15-25 triệu",
      "applicationInfo": "Gửi CV về hr@company.com",
      "keywords": ["Backend", "FastAPI", "PostgreSQL"]
    }
  },

  "template": {
    "eligible": true,
    "saved": false,
    "templateId": "",
    "savedAt": null
  }
}
```

### Field bắt buộc

- `uid`
- `email`
- `feature`
- `createdAt`
- `timestamp`
- `input.targetPlatform`
- `result.score`
- `result.normalizedJD`
- `template.eligible`

### Field nên index

- `uid`
- `timestamp`
- `feature`
- `template.saved`

Query thường dùng:

- `where uid == currentUser.uid`
- `orderBy timestamp desc`
- lọc thêm `template.saved == true` nếu cần xem các JD đã tạo mẫu

---

## 3. `userJDTemplates`

Collection này đã có trong backend. Dùng để lưu mẫu JD chính thức sau khi người dùng bấm **Tạo mẫu JD**.

```json
{
  "uid": "firebase-user-uid",
  "name": "Backend Developer",
  "category": "Chuẩn hóa JD",
  "jobPosition": "Backend Developer",
  "jdText": "Nội dung JD hoàn chỉnh đã chuẩn hóa",
  "hardFilters": {
    "generatedFrom": "jd-standardizer",
    "platform": "TopCV",
    "source": "ai",
    "score": 86,
    "location": "Hà Nội",
    "salary": "15-25 triệu"
  },
  "createdAt": "serverTimestamp",
  "updatedAt": "serverTimestamp"
}
```

### Field bắt buộc

- `uid`
- `name`
- `category`
- `jobPosition`
- `jdText`
- `hardFilters`
- `createdAt`
- `updatedAt`

---

## Gợi ý collection tối thiểu nên tạo trước

Nếu cần làm nhanh trong Firebase, tạo 3 collection:

1. `mobileQuickCvAnalyses`
2. `mobileJDStandardizations`
3. `userJDTemplates`

`userJDTemplates` đã được backend dùng sẵn. Hai collection `mobileQuickCvAnalyses` và `mobileJDStandardizations` là nơi nên lưu lịch sử riêng của mobile để sau này xem lại nhanh, thống kê, hoặc đồng bộ thông báo.
