from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from supporthr_ml.contracts import DEDUPLICATION_VERSION, TEXT_NORMALIZATION_VERSION, sha256_file
from supporthr_ml.dedupe import assign_near_duplicate_groups, content_hash
from supporthr_ml.registry import ensure_use_allowed, get_source
from supporthr_ml.text import normalize_for_model


SCHEMA_VERSION = "supporthr-classifier-manifest-v1"
DEFAULT_MODEL_VERSION = "cv-industry-24-v2"
RANDOM_STATE = 42


def clean_text(value: Any) -> str:
    return normalize_for_model(value)


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
    frame["textHash"] = frame["text"].map(content_hash)

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

    dedupe_records = [
        {"documentId": str(row.textHash), "cleanText": str(row.text)}
        for row in frame.itertuples()
    ]
    groups, near_duplicate_pairs = assign_near_duplicate_groups(dedupe_records)
    frame["entityGroupId"] = frame["textHash"].map(groups)
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
        "nearDuplicatePairs": near_duplicate_pairs,
        "entityGroupCount": int(frame["entityGroupId"].nunique()),
        "datasetFingerprint": hashlib.sha256(fingerprint_payload.encode("utf-8")).hexdigest(),
        "labelDistribution": {str(key): int(value) for key, value in counts.sort_index().items()},
        "textNormalizationVersion": TEXT_NORMALIZATION_VERSION,
        "deduplicationVersion": DEDUPLICATION_VERSION,
    }
    return frame, audit


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit, train, evaluate, and install the SupportHR CV classifier.")
    parser.add_argument("--source-id", required=True)
    parser.add_argument("--dataset-csv", required=True)
    parser.add_argument("--text-column", default="Resume_str")
    parser.add_argument("--label-column", default="Category")
    parser.add_argument("--model-version", default=DEFAULT_MODEL_VERSION)
    parser.add_argument("--dataset-license", help="Dataset license identifier or reviewed internal license record.")
    parser.add_argument("--min-samples", type=int, default=10)
    parser.add_argument("--min-macro-f1", type=float, default=0.70)
    parser.add_argument("--test-size", type=float, default=0.20)
    parser.add_argument("--classifier", choices=("logistic-regression", "linear-svc"), default="linear-svc")
    parser.add_argument("--audit-only", action="store_true")
    parser.add_argument(
        "--output-model-dir",
        help="Write a candidate model outside runtime. Omit to install into api_server/app/models.",
    )
    args = parser.parse_args()

    import joblib
    import sklearn
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import accuracy_score, classification_report, f1_score
    from sklearn.model_selection import StratifiedGroupKFold
    from sklearn.pipeline import Pipeline
    from sklearn.svm import LinearSVC

    script_dir = Path(__file__).resolve().parent
    backend_root = script_dir.parent
    artifacts_dir = script_dir / "artifacts"
    model_dir = (
        Path(args.output_model_dir).expanduser().resolve()
        if args.output_model_dir
        else backend_root / "api_server" / "app" / "models"
    )
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    model_dir.mkdir(parents=True, exist_ok=True)

    dataset_path = Path(args.dataset_csv).expanduser().resolve()
    source = get_source(args.source_id)
    ensure_use_allowed(source, "classifier_training")
    reviewed_license = str(source.get("license") or "").strip()
    if args.dataset_license and args.dataset_license.strip().casefold() != reviewed_license.casefold():
        raise ValueError("--dataset-license does not match the reviewed dataset registry license.")
    pinned_revision = str(source.get("revision") or "").strip().lower()
    source_sha = sha256_file(dataset_path)
    if len(pinned_revision) == 64 and source_sha != pinned_revision:
        raise ValueError(
            f"Dataset checksum does not match registry revision: expected {pinned_revision}, received {source_sha}"
        )

    frame, audit = load_and_audit(
        dataset_path,
        args.text_column,
        args.label_column,
        args.min_samples,
    )
    audit["sourceId"] = source["id"]
    audit["sourceRevision"] = source["revision"]
    audit["license"] = reviewed_license
    (artifacts_dir / "dataset_audit.json").write_text(json.dumps(audit, indent=2), encoding="utf-8")
    print(json.dumps(audit, indent=2))
    if args.audit_only:
        return 0
    if not reviewed_license:
        raise ValueError("The registered dataset requires a reviewed license before model release.")

    if not 0.1 <= args.test_size <= 0.5:
        raise ValueError("--test-size must be between 0.1 and 0.5.")
    split_count = max(2, min(10, round(1 / args.test_size)))
    splitter = StratifiedGroupKFold(n_splits=split_count, shuffle=True, random_state=RANDOM_STATE)
    train_indexes, test_indexes = next(
        splitter.split(frame["text"], frame["label"], groups=frame["entityGroupId"])
    )
    x_train = frame.iloc[train_indexes]["text"]
    y_train = frame.iloc[train_indexes]["label"]
    x_test = frame.iloc[test_indexes]["text"]
    y_test = frame.iloc[test_indexes]["label"]
    train_groups = set(frame.iloc[train_indexes]["entityGroupId"])
    test_groups = set(frame.iloc[test_indexes]["entityGroupId"])
    if train_groups & test_groups:
        raise RuntimeError("Near-duplicate entity groups leaked across train and test.")
    classifier = (
        LinearSVC(class_weight="balanced", random_state=RANDOM_STATE)
        if args.classifier == "linear-svc"
        else LogisticRegression(max_iter=2500, class_weight="balanced", random_state=RANDOM_STATE)
    )
    model = Pipeline([
        (
            "tfidf",
            TfidfVectorizer(
                max_features=20000,
                min_df=2,
                ngram_range=(1, 2),
                stop_words="english",
                sublinear_tf=True,
            ),
        ),
        ("classifier", classifier),
    ])
    model.fit(x_train, y_train)
    predicted = model.predict(x_test)
    metrics = {
        "accuracy": round(float(accuracy_score(y_test, predicted)), 6),
        "macroF1": round(float(f1_score(y_test, predicted, average="macro")), 6),
        "report": classification_report(y_test, predicted, output_dict=True, zero_division=0),
        "split": {
            "strategy": "StratifiedGroupKFold",
            "foldCount": split_count,
            "trainRows": int(len(train_indexes)),
            "testRows": int(len(test_indexes)),
            "groupLeakageCount": 0,
            "randomState": RANDOM_STATE,
        },
        "classifier": args.classifier,
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
        "classifier": args.classifier,
        "pythonVersion": f"{__import__('sys').version_info.major}.{__import__('sys').version_info.minor}",
        "labelCount": len(model.classes_),
        "labels": [str(value) for value in model.classes_],
        "datasetFingerprint": audit["datasetFingerprint"],
        "datasetSourceId": source["id"],
        "datasetRevision": source["revision"],
        "datasetLicense": reviewed_license,
        "dataContract": {
            "textNormalizationVersion": TEXT_NORMALIZATION_VERSION,
            "deduplicationVersion": DEDUPLICATION_VERSION,
            "splitStrategy": "StratifiedGroupKFold",
            "groupLeakageCount": 0,
        },
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
