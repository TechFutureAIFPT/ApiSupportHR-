from __future__ import annotations

import argparse
import json
from pathlib import Path

from supporthr_ml.graph import build_pending_graph_facts


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build evidence-backed pending graph facts from a curated SupportHR dataset."
    )
    parser.add_argument("--curated-jsonl", required=True)
    parser.add_argument("--skill-aliases")
    parser.add_argument("--output-jsonl")
    parser.add_argument("--report-json")
    parser.add_argument("--min-document-count", type=int, default=3)
    args = parser.parse_args()

    script_dir = Path(__file__).resolve().parent
    curated_path = Path(args.curated_jsonl).expanduser().resolve()
    aliases_path = (
        Path(args.skill_aliases).expanduser().resolve()
        if args.skill_aliases
        else script_dir / "configs" / "skill_aliases.json"
    )
    output_path = (
        Path(args.output_jsonl).expanduser().resolve()
        if args.output_jsonl
        else script_dir / "artifacts" / "graph" / "pending_graph_facts.jsonl"
    )
    report_path = (
        Path(args.report_json).expanduser().resolve()
        if args.report_json
        else script_dir / "artifacts" / "reports" / "graph_candidates.audit.json"
    )
    facts, report = build_pending_graph_facts(
        curated_jsonl=curated_path,
        skill_aliases_path=aliases_path,
        min_document_count=max(2, args.min_document_count),
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="\n") as handle:
        for fact in facts:
            handle.write(json.dumps(fact, ensure_ascii=False, sort_keys=True) + "\n")
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({**report, "output": str(output_path)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
