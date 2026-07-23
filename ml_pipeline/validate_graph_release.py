from __future__ import annotations

import argparse
import json
from pathlib import Path

from supporthr_ml.graph import validate_release_facts


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate an approved GraphRAG artifact before deployment.")
    parser.add_argument("--graph-jsonl", required=True)
    args = parser.parse_args()
    path = Path(args.graph_jsonl).expanduser().resolve()
    facts: list[dict[str, object]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as error:
                raise SystemExit(f"Invalid JSON at line {line_number}: {error}") from error
            if not isinstance(value, dict):
                raise SystemExit(f"Graph record at line {line_number} must be an object.")
            facts.append(value)
    errors = validate_release_facts(facts)
    print(json.dumps({"path": str(path), "factCount": len(facts), "errors": errors}, indent=2))
    if errors:
        raise SystemExit("Graph release validation failed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
