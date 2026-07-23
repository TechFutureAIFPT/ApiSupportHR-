from __future__ import annotations

import argparse
import json
from pathlib import Path

from supporthr_ml.dataset_pipeline import prepare_csv_dataset
from supporthr_ml.registry import get_source


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Normalize, redact, audit, deduplicate, and curate one registered CSV dataset."
    )
    parser.add_argument("--source-id", required=True)
    parser.add_argument("--input-csv", required=True)
    parser.add_argument("--intended-use", required=True)
    parser.add_argument("--text-column")
    parser.add_argument("--label-column")
    parser.add_argument("--id-column")
    parser.add_argument("--output-dir")
    parser.add_argument("--min-chars", type=int, default=80)
    parser.add_argument("--max-chars", type=int, default=120_000)
    parser.add_argument("--near-duplicate-hamming", type=int, default=3)
    args = parser.parse_args()

    script_dir = Path(__file__).resolve().parent
    output_dir = Path(args.output_dir).resolve() if args.output_dir else script_dir / "artifacts" / "data"
    result = prepare_csv_dataset(
        csv_path=Path(args.input_csv),
        source=get_source(args.source_id),
        output_dir=output_dir,
        intended_use=args.intended_use,
        text_column=args.text_column,
        label_column=args.label_column,
        id_column=args.id_column,
        min_chars=max(1, args.min_chars),
        max_chars=max(args.min_chars, args.max_chars),
        max_near_duplicate_hamming=max(0, min(12, args.near_duplicate_hamming)),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["report"]["qualityGatePassed"]:
        raise SystemExit("Dataset failed the configured privacy/quality release gate.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
