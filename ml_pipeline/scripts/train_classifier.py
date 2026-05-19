from __future__ import annotations

import argparse
import os
import re
import sys
from typing import Iterable

RANDOM_STATE = 42
TEST_SIZE = 0.2
MAX_FEATURES = 5000
MIN_SAMPLES_REQUIRED = 2
COLUMN_TEXT = "Resume_str"
COLUMN_LABEL = "Category"
DEFAULT_MODEL_NAME = "text_classifier_model.pkl"
DEFAULT_REPORT_NAME = "classification_report.txt"


def configure_console_output() -> None:
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace")


def clean_text(text: str) -> str:
    normalized = str(text).lower()
    normalized = re.sub(r"[^\w\s]+", " ", normalized, flags=re.UNICODE)
    normalized = normalized.replace("_", " ")
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Train a CV industry classifier for Support HR."
    )
    parser.add_argument(
        "--dataset-csv",
        default=None,
        help="Optional absolute or relative path to Resume.csv.",
    )
    parser.add_argument(
        "--text-dir",
        default=None,
        help="Optional absolute or relative path to String_Folder dataset.",
    )
    parser.add_argument(
        "--model-output",
        default=None,
        help=(
            "Optional absolute or relative path for the exported .pkl model. "
            "If omitted, the script saves to api_server/app/models when available, "
            "otherwise to ml_pipeline/artifacts."
        ),
    )
    parser.add_argument(
        "--report-output",
        default=None,
        help=(
            "Optional absolute or relative path for the classification report text file. "
            "Defaults to ml_pipeline/artifacts/classification_report.txt."
        ),
    )
    return parser.parse_args()


def iter_text_files(dataset_dir: str) -> Iterable[tuple[str, str]]:
    for label in sorted(os.listdir(dataset_dir)):
        label_dir = os.path.join(dataset_dir, label)
        if not os.path.isdir(label_dir):
            continue

        for file_name in sorted(os.listdir(label_dir)):
            if not file_name.lower().endswith(".txt"):
                continue

            file_path = os.path.join(label_dir, file_name)
            if not os.path.isfile(file_path):
                continue

            yield label, file_path


def validate_dataset(dataset: pd.DataFrame, skipped_items: int = 0) -> pd.DataFrame:
    if dataset.empty:
        raise ValueError("Dataset is empty after cleaning.")

    label_counts = dataset["label"].value_counts()
    invalid_labels = label_counts[label_counts < MIN_SAMPLES_REQUIRED]
    if not invalid_labels.empty:
        details = ", ".join(f"{label}={count}" for label, count in invalid_labels.items())
        raise ValueError(
            "Each class needs at least 2 samples for stratified train/test split. "
            f"Classes with too few samples: {details}"
        )

    print(f"Loaded {len(dataset)} samples across {dataset['label'].nunique()} labels.")
    if skipped_items:
        print(f"Skipped {skipped_items} unreadable or empty samples.")
    print("Label distribution:")
    print(label_counts.sort_index().to_string())
    return dataset


def load_dataset_from_text_folders(dataset_dir: str) -> pd.DataFrame:
    import pandas as pd

    records: list[dict[str, str]] = []
    skipped_files = 0

    for label, file_path in iter_text_files(dataset_dir):
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as file:
                raw_text = file.read()
        except OSError as error:
            print(f"[WARN] Cannot read file: {file_path} -> {error}")
            skipped_files += 1
            continue

        cleaned = clean_text(raw_text)
        if not cleaned:
            skipped_files += 1
            continue

        records.append(
            {
                "label": label,
                "text": cleaned,
                "source_file": file_path,
            }
        )

    if not records:
        raise ValueError(
            "No valid .txt samples were loaded. "
            "Please verify that data/kaggle-nlp-classification/String_Folder contains non-empty text files."
        )

    return validate_dataset(pd.DataFrame(records), skipped_items=skipped_files)


def load_dataset_from_resume_csv(csv_path: str) -> pd.DataFrame:
    import pandas as pd

    try:
        dataset = pd.read_csv(
            csv_path,
            usecols=[COLUMN_TEXT, COLUMN_LABEL],
            encoding="utf-8",
            encoding_errors="ignore",
            on_bad_lines="skip",
        )
    except ValueError as error:
        raise ValueError(
            f"CSV file is missing required columns '{COLUMN_TEXT}' and '{COLUMN_LABEL}': {csv_path}"
        ) from error

    dataset = dataset.rename(columns={COLUMN_TEXT: "text", COLUMN_LABEL: "label"})
    dataset["text"] = dataset["text"].fillna("").map(clean_text)
    dataset["label"] = dataset["label"].fillna("").astype(str).str.strip()
    dataset = dataset[(dataset["text"] != "") & (dataset["label"] != "")]
    dataset = dataset.reset_index(drop=True)
    return validate_dataset(dataset)


def resolve_workspace_dir(script_dir: str) -> str:
    return os.path.abspath(os.path.join(script_dir, ".."))


def resolve_default_paths(workspace_dir: str) -> dict[str, str]:
    repo_root = os.path.abspath(os.path.join(workspace_dir, ".."))
    return {
        "csv_path": os.path.abspath(
            os.path.join(
                workspace_dir,
                "data",
                "raw",
                "kaggle-nlp-classification",
                "Resume",
                "Resume.csv",
            )
        ),
        "text_dir": os.path.abspath(
            os.path.join(workspace_dir, "data", "kaggle-nlp-classification", "String_Folder")
        ),
        "api_model_path": os.path.abspath(
            os.path.join(repo_root, "api_server", "app", "models", DEFAULT_MODEL_NAME)
        ),
        "local_model_path": os.path.abspath(
            os.path.join(workspace_dir, "artifacts", DEFAULT_MODEL_NAME)
        ),
        "report_path": os.path.abspath(
            os.path.join(workspace_dir, "artifacts", DEFAULT_REPORT_NAME)
        ),
    }


def resolve_cli_path(base_dir: str, path_value: str | None) -> str | None:
    if not path_value:
        return None
    if os.path.isabs(path_value):
        return os.path.abspath(path_value)
    return os.path.abspath(os.path.join(base_dir, path_value))


def resolve_dataset_source(
    workspace_dir: str,
    dataset_csv: str | None = None,
    text_dir: str | None = None,
) -> tuple[str, str]:
    defaults = resolve_default_paths(workspace_dir)
    csv_path = resolve_cli_path(workspace_dir, dataset_csv) or defaults["csv_path"]
    if os.path.isfile(csv_path):
        return "csv", csv_path

    text_dir = resolve_cli_path(workspace_dir, text_dir) or defaults["text_dir"]
    if os.path.isdir(text_dir):
        return "txt", text_dir

    raise FileNotFoundError(
        "No supported dataset source was found. "
        "Expected either:\n"
        f"- CSV: {csv_path}\n"
        f"- TXT folders: {text_dir}"
    )


def build_pipeline() -> Pipeline:
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline

    return Pipeline(
        steps=[
            ("tfidf", TfidfVectorizer(max_features=MAX_FEATURES, stop_words="english")),
            ("classifier", LogisticRegression(max_iter=1000, random_state=RANDOM_STATE)),
        ]
    )


def ensure_parent_dir(file_path: str) -> str:
    parent_dir = os.path.dirname(file_path)
    os.makedirs(parent_dir, exist_ok=True)
    return file_path


def resolve_model_output_path(workspace_dir: str, model_output: str | None) -> str:
    defaults = resolve_default_paths(workspace_dir)
    if model_output:
        return ensure_parent_dir(resolve_cli_path(workspace_dir, model_output))

    api_model_parent = os.path.dirname(defaults["api_model_path"])
    if os.path.isdir(os.path.dirname(api_model_parent)):
        return ensure_parent_dir(defaults["api_model_path"])

    return ensure_parent_dir(defaults["local_model_path"])


def resolve_report_output_path(workspace_dir: str, report_output: str | None) -> str:
    defaults = resolve_default_paths(workspace_dir)
    if report_output:
        return ensure_parent_dir(resolve_cli_path(workspace_dir, report_output))
    return ensure_parent_dir(defaults["report_path"])


def save_report(report_output_path: str, report: str) -> None:
    with open(report_output_path, "w", encoding="utf-8") as report_file:
        report_file.write(report.strip())
        report_file.write("\n")


def train_and_export(args: argparse.Namespace) -> tuple[str, str]:
    import joblib
    from sklearn.metrics import classification_report
    from sklearn.model_selection import train_test_split

    script_dir = os.path.dirname(os.path.abspath(__file__))
    workspace_dir = resolve_workspace_dir(script_dir)
    source_type, source_path = resolve_dataset_source(
        workspace_dir,
        dataset_csv=args.dataset_csv,
        text_dir=args.text_dir,
    )
    print(f"Using dataset source [{source_type}]: {source_path}")

    if source_type == "csv":
        dataset = load_dataset_from_resume_csv(source_path)
    else:
        dataset = load_dataset_from_text_folders(source_path)

    x = dataset["text"]
    y = dataset["label"]

    x_train, x_test, y_train, y_test = train_test_split(
        x,
        y,
        test_size=TEST_SIZE,
        random_state=RANDOM_STATE,
        stratify=y,
    )

    model = build_pipeline()
    model.fit(x_train, y_train)

    predictions = model.predict(x_test)
    report = classification_report(y_test, predictions, zero_division=0)
    print("\nClassification report:")
    print(report)

    report_output_path = resolve_report_output_path(workspace_dir, args.report_output)
    save_report(report_output_path, report)

    model_output_path = resolve_model_output_path(workspace_dir, args.model_output)
    joblib.dump(model, model_output_path)
    return model_output_path, report_output_path


def main() -> int:
    try:
        configure_console_output()
        args = parse_args()
        model_path, report_path = train_and_export(args)
        print(f"\nModel exported successfully to: {model_path}")
        print(f"Classification report saved to: {report_path}")
        return 0
    except FileNotFoundError as error:
        print(f"[ERROR] {error}")
        return 1
    except ValueError as error:
        print(f"[ERROR] {error}")
        return 1
    except Exception as error:
        print(f"[ERROR] Unexpected training failure: {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
