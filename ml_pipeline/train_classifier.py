from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "supporthr-classifier-manifest-v1"
DEFAULT_MODEL_VERSION = "cv-industry-24-v2"
RANDOM_STATE = 42


def clean_text(value: Any) -> str:
    text = re.sub(r"[^\w\s]+", " ", str(value or "").lower(), flags=re.UNICODE)
    return re.sub(r"\s+", " ", text.replace("_", " ")).strip()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_and_audit(csv_path: Path, text_column: str, label_column: str, min_samples: int):
    import pandas as pd

    frame = pd.read_csv(
        csv_path,
        usecols=[text_column, label_column],
        encoding="utf-8",
        encoding_errors="ignore",
        on_bad_lines="skip",
    ).rename(columns={text_column: "text", label_column: "label"})
    frame["text"] = frame["text"].fillna("").map(clean_text)
    frame["label"] = frame["label"].fillna("").astype(str).str.strip().str.upper()
    frame = frame[(frame["text"] != "") & frame["label"].str.fullmatch(r"[A-Z][A-Z0-9-]{1,63}")].copy()
    raw_valid_rows = int(len(frame))
    frame["textHash"] = frame["text"].map(lambda value: hashlib.sha256(value.encode("utf-8")).hexdigest())

    label_conflicts = frame.groupby("textHash")["label"].nunique()
    conflicting_hashes = set(label_conflicts[label_conflicts > 1].index)
    conflict_rows = int(frame["textHash"].isin(conflicting_hashes).sum())
    frame = frame[~frame["textHash"].isin(conflicting_hashes)].drop_duplicates("textHash").reset_index(drop=True)

    counts = frame["label"].value_counts()
    undersized = {str(label): int(count) for label, count in counts[counts < min_samples].items()}
    if undersized:
        raise ValueError(f"Classes below min_samples={min_samples}: {undersized}")
    if frame["label"].nunique() < 2:
        raise ValueError("Training requires at least two valid labels.")

    fingerprint_payload = "\n".join(sorted(f"{row.textHash}:{row.label}" for row in frame.itertuples()))
    audit = {
        "source": str(csv_path.resolve()),
        "sourceSha256": sha256_file(csv_path),
        "rawValidRows": raw_valid_rows,
        "rowsAfterAudit": int(len(frame)),
        "exactDuplicatesRemoved": raw_valid_rows - conflict_rows - int(len(frame)),
        "labelCount": int(frame["label"].nunique()),
        "labels": sorted(str(value) for value in frame["label"].unique()),
        "conflictingRowsRemoved": conflict_rows,
        "datasetFingerprint": hashlib.sha256(fingerprint_payload.encode("utf-8")).hexdigest(),
        "labelDistribution": {str(key): int(value) for key, value in counts.sort_index().items()},
    }
    return frame, audit


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit, train, evaluate, and install the SupportHR CV classifier.")
    parser.add_argument("--dataset-csv", required=True)
    parser.add_argument("--text-column", default="Resume_str")
    parser.add_argument("--label-column", default="Category")
    parser.add_argument("--model-version", default=DEFAULT_MODEL_VERSION)
    parser.add_argument("--dataset-license", help="Dataset license identifier or reviewed internal license record.")
    parser.add_argument("--min-samples", type=int, default=10)
    parser.add_argument("--min-macro-f1", type=float, default=0.70)
    parser.add_argument("--test-size", type=float, default=0.20)
    parser.add_argument("--audit-only", action="store_true")
    args = parser.parse_args()

    import joblib
    import sklearn
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import accuracy_score, classification_report, f1_score
    from sklearn.model_selection import train_test_split
    from sklearn.pipeline import Pipeline

    script_dir = Path(__file__).resolve().parent
    backend_root = script_dir.parent
    artifacts_dir = script_dir / "artifacts"
    model_dir = backend_root / "api_server" / "app" / "models"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    model_dir.mkdir(parents=True, exist_ok=True)

    frame, audit = load_and_audit(
        Path(args.dataset_csv).expanduser().resolve(),
        args.text_column,
        args.label_column,
        args.min_samples,
    )
    (artifacts_dir / "dataset_audit.json").write_text(json.dumps(audit, indent=2), encoding="utf-8")
    print(json.dumps(audit, indent=2))
    if args.audit_only:
        return 0
    if not str(args.dataset_license or "").strip():
        raise ValueError("--dataset-license is required before a model can be released.")

    x_train, x_test, y_train, y_test = train_test_split(
        frame["text"], frame["label"], test_size=args.test_size, random_state=RANDOM_STATE, stratify=frame["label"]
    )
    model = Pipeline([
        ("tfidf", TfidfVectorizer(max_features=12000, min_df=2, ngram_range=(1, 2), stop_words="english", sublinear_tf=True)),
        ("classifier", LogisticRegression(max_iter=2500, class_weight="balanced", random_state=RANDOM_STATE)),
    ])
    model.fit(x_train, y_train)
    predicted = model.predict(x_test)
    metrics = {
        "accuracy": round(float(accuracy_score(y_test, predicted)), 6),
        "macroF1": round(float(f1_score(y_test, predicted, average="macro")), 6),
        "report": classification_report(y_test, predicted, output_dict=True, zero_division=0),
    }
    (artifacts_dir / "evaluation.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    if metrics["macroF1"] < args.min_macro_f1:
        raise RuntimeError(f"macro-F1 {metrics['macroF1']} is below release gate {args.min_macro_f1}")

    model_path = model_dir / "text_classifier_model.pkl"
    joblib.dump(model, model_path)
    manifest = {
        "schemaVersion": SCHEMA_VERSION,
        "modelVersion": args.model_version,
        "artifact": model_path.name,
        "sha256": sha256_file(model_path),
        "framework": "scikit-learn",
        "frameworkVersion": sklearn.__version__,
        "pythonVersion": f"{__import__('sys').version_info.major}.{__import__('sys').version_info.minor}",
        "labelCount": len(model.classes_),
        "labels": [str(value) for value in model.classes_],
        "datasetFingerprint": audit["datasetFingerprint"],
        "datasetLicense": str(args.dataset_license).strip(),
        "metrics": {"accuracy": metrics["accuracy"], "macroF1": metrics["macroF1"]},
        "createdAt": datetime.now(timezone.utc).isoformat(),
    }
    manifest_path = model_path.with_suffix(".manifest.json")
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Installed model: {model_path}")
    print(f"Installed manifest: {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
