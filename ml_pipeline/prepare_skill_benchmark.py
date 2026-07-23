from __future__ import annotations

import argparse
import json
from pathlib import Path

from supporthr_ml.registry import get_source
from supporthr_ml.skill_benchmark import prepare_skill_benchmark


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Clean a pinned skill-linking benchmark while preserving evaluation-only isolation."
    )
    parser.add_argument("--source-id", required=True)
    parser.add_argument("--input-root", required=True)
    parser.add_argument("--output-dir")
    args = parser.parse_args()
    script_dir = Path(__file__).resolve().parent
    result = prepare_skill_benchmark(
        source=get_source(args.source_id),
        input_root=Path(args.input_root).expanduser().resolve(),
        output_dir=(
            Path(args.output_dir).expanduser().resolve()
            if args.output_dir
            else script_dir / "artifacts" / "benchmarks"
        ),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["report"]["qualityGatePassed"]:
        raise SystemExit("Skill benchmark failed privacy quality gates.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
