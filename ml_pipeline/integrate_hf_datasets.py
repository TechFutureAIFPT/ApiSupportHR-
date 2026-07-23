from __future__ import annotations

import argparse
import json
from pathlib import Path

from supporthr_ml.contracts import DATASET_ROUTING_REPORT_SCHEMA_VERSION
from supporthr_ml.hf_dataset_adapters import (
    audit_resume_source_equivalence,
    prepare_compatibility_benchmark,
    prepare_job_skill_audit,
)
from supporthr_ml.registry import get_source
from supporthr_ml.skill_benchmark import prepare_skill_benchmark


SOURCE_IDS = (
    "techwolf-skill-techwolf",
    "opensporks-resumes",
    "batuhan-job-skill-set",
    "siddharth-job-compatibility",
)


def _source_root(raw_root: Path, source: dict) -> Path:
    category = Path(*str(source.get("storageCategory") or "huggingface").split("/"))
    return raw_root / category / str(source["id"]) / str(source["revision"])


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audit and route the four pinned Hugging Face datasets into isolated ML contracts."
    )
    parser.add_argument("--raw-root")
    parser.add_argument("--output-dir")
    args = parser.parse_args()

    script_dir = Path(__file__).resolve().parent
    raw_root = (
        Path(args.raw_root).expanduser().resolve()
        if args.raw_root
        else script_dir / "data" / "raw" / "huggingface"
    )
    output_dir = (
        Path(args.output_dir).expanduser().resolve()
        if args.output_dir
        else script_dir / "artifacts" / "hf_integration"
    )

    sources = {source_id: get_source(source_id) for source_id in SOURCE_IDS}
    roots = {source_id: _source_root(raw_root, source) for source_id, source in sources.items()}
    missing = [str(path) for path in roots.values() if not path.is_dir()]
    if missing:
        raise FileNotFoundError(f"Downloaded source roots are missing: {missing}")

    techwolf = prepare_skill_benchmark(
        source=sources["techwolf-skill-techwolf"],
        input_root=roots["techwolf-skill-techwolf"],
        output_dir=output_dir / "skill_extraction",
    )
    resume = audit_resume_source_equivalence(
        source=sources["opensporks-resumes"],
        csv_path=roots["opensporks-resumes"] / "Resume" / "Resume.csv",
        canonical_source=get_source("kaggle-resume-dataset"),
        output_dir=output_dir / "resume_classification",
    )
    job_skill = prepare_job_skill_audit(
        source=sources["batuhan-job-skill-set"],
        parquet_path=roots["batuhan-job-skill-set"] / "data" / "train-00000-of-00001.parquet",
        output_dir=output_dir / "job_skill",
    )
    compatibility = prepare_compatibility_benchmark(
        source=sources["siddharth-job-compatibility"],
        json_path=roots["siddharth-job-compatibility"] / "final_data.json",
        resume_source=sources["opensporks-resumes"],
        resume_csv_path=roots["opensporks-resumes"] / "Resume" / "Resume.csv",
        output_dir=output_dir / "job_compatibility",
    )

    routing = {
        "schemaVersion": DATASET_ROUTING_REPORT_SCHEMA_VERSION,
        "sources": [
            {
                "sourceId": "techwolf-skill-techwolf",
                "role": "esco_skill_linker_benchmark",
                "decision": "evaluation_only",
                **techwolf["report"],
            },
            {
                "sourceId": "opensporks-resumes",
                "role": "cv_industry_classifier_source",
                "decision": resume["report"]["routingDecision"],
                **resume["report"],
            },
            {
                "sourceId": "batuhan-job-skill-set",
                "role": "job_skill_catalog_candidate",
                "decision": job_skill["report"]["routingDecision"],
                **job_skill["report"],
            },
            {
                "sourceId": "siddharth-job-compatibility",
                "role": "cv_jd_prompt_regression_benchmark",
                "decision": compatibility["report"]["routingDecision"],
                **compatibility["report"],
            },
        ],
        "runtimeModelChanged": False,
        "reason": "No new source currently passes both provenance and model-quality release gates.",
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    routing_path = output_dir / "dataset-routing-report.json"
    routing_path.write_text(json.dumps(routing, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"routing": routing, "routingPath": str(routing_path)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
