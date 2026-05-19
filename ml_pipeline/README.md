# ML Pipeline Workspace

Thu muc `ml_pipeline/` la workspace duy nhat cho phan ML cua backend.

## Cau truc

```text
BE/
├── api_server/
│   └── app/
│       └── models/
└── ml_pipeline/
    ├── .gitignore
    ├── README.md
    ├── requirements.txt
    ├── artifacts/
    ├── data/
    │   └── raw/
    └── scripts/
        ├── seed_exemplars.py
        └── train_classifier.py
```

## Cai thu vien

Chay tu thu muc `BE/ml_pipeline`:

```bash
pip install -r requirements.txt
```

## Train local classifier

```bash
python scripts/train_classifier.py
```

Mac dinh script se:
- uu tien doc `data/raw/kaggle-nlp-classification/Resume/Resume.csv`
- fallback sang folder text neu ban truyen `--text-dir`
- luu model sang `../api_server/app/models/text_classifier_model.pkl` neu repo day du
- dong thoi luu report sang `artifacts/classification_report.txt`

Vi du:

```bash
python scripts/train_classifier.py ^
  --dataset-csv "data/raw/kaggle-nlp-classification/Resume/Resume.csv" ^
  --model-output "artifacts/text_classifier_model.pkl" ^
  --report-output "artifacts/classification_report.txt"
```

## Seed exemplars

```bash
python scripts/seed_exemplars.py --dry-run --limit 5
```

Neu can gan embedding:

```bash
python scripts/seed_exemplars.py --with-embeddings
```

Script se tim dataset trong:
- `ml_pipeline/data/raw/kaggle-job-resume-fit`
- `ml_pipeline/data/kaggle-job-resume-fit`

## Sau khi train

- Model local trong workspace: `ml_pipeline/artifacts/text_classifier_model.pkl`
- Model backend su dung: `api_server/app/models/text_classifier_model.pkl`
- Report danh gia: `ml_pipeline/artifacts/classification_report.txt`

Neu ban train ngay trong repo nay, script co the tu ghi model vao `api_server/app/models/` de backend dung ngay.
