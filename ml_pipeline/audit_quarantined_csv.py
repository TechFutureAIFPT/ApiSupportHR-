from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path

from supporthr_ml.contracts import sha256_file
from supporthr_ml.registry import get_source
from supporthr_ml.text import canonical_text_for_hash


def _hash(value: str) -> str:
    return hashlib.sha256(canonical_text_for_hash(value).encode("utf-8")).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Produce a non-PII structural audit for a registered quarantined CSV."
    )
    parser.add_argument("--source-id", required=True)
    parser.add_argument("--input-csv", required=True)
    parser.add_argument("--primary-text-column", required=True)
    parser.add_argument("--paired-text-column")
    parser.add_argument("--label-column")
    parser.add_argument("--output-json")
    args = parser.parse_args()

    source = get_source(args.source_id)
    path = Path(args.input_csv).expanduser().resolve()
    if not path.is_file():
        raise SystemExit(f"CSV not found: {path}")

    total_rows = 0
    malformed_rows = 0
    missing_primary = 0
    missing_paired = 0
    missing_label = 0
    pair_hashes: Counter[str] = Counter()
    primary_hashes: Counter[str] = Counter()
    label_distribution: Counter[str] = Counter()
    with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
        reader = csv.reader(handle)
        headers = next(reader, [])
        normalized_headers = [str(header or "").strip() for header in headers]
        header_lookup = {header: index for index, header in enumerate(normalized_headers) if header}
        required = [args.primary_text_column]
        if args.paired_text_column:
            required.append(args.paired_text_column)
        if args.label_column:
            required.append(args.label_column)
        missing_headers = [column for column in required if column not in header_lookup]
        if missing_headers:
            raise SystemExit(f"Missing required columns: {missing_headers}")

        for row in reader:
            total_rows += 1
            if len(row) != len(headers):
                malformed_rows += 1
            padded = [*row, *([""] * max(0, len(headers) - len(row)))]
            primary = str(padded[header_lookup[args.primary_text_column]] or "")
            paired = (
                str(padded[header_lookup[args.paired_text_column]] or "")
                if args.paired_text_column
                else ""
            )
            label = (
                str(padded[header_lookup[args.label_column]] or "").strip()
                if args.label_column
                else ""
            )
            if not primary.strip():
                missing_primary += 1
            else:
                primary_hashes[_hash(primary)] += 1
            if args.paired_text_column and not paired.strip():
                missing_paired += 1
            if args.label_column:
                if not label:
                    missing_label += 1
                else:
                    label_distribution[label] += 1
            if primary.strip() and (not args.paired_text_column or paired.strip()):
                pair_hashes[_hash(primary + "\x1f" + paired)] += 1

    report = {
        "sourceId": args.source_id,
        "sourceStatus": source.get("status"),
        "releaseAllowed": False,
        "sourcePath": str(path),
        "sourceSha256": sha256_file(path),
        "license": source.get("license"),
        "headerCount": len(headers),
        "emptyHeaderCount": sum(1 for header in normalized_headers if not header),
        "totalRows": total_rows,
        "malformedRowCount": malformed_rows,
        "missingPrimaryTextCount": missing_primary,
        "missingPairedTextCount": missing_paired,
        "missingLabelCount": missing_label,
        "duplicatePrimaryTextRows": sum(count - 1 for count in primary_hashes.values() if count > 1),
        "duplicatePairRows": sum(count - 1 for count in pair_hashes.values() if count > 1),
        "uniquePrimaryTextCount": len(primary_hashes),
        "uniquePairCount": len(pair_hashes),
        "labelCount": len(label_distribution),
        "labelDistribution": dict(sorted(label_distribution.items())),
        "decision": "quarantine",
        "reason": "Registered source is not licensed or validated for training, scoring, or approved exemplars.",
    }
    script_dir = Path(__file__).resolve().parent
    output = (
        Path(args.output_json).expanduser().resolve()
        if args.output_json
        else script_dir / "artifacts" / "data" / "reports" / f"{args.source_id}.structure-audit.json"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
