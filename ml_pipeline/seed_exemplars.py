from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Iterable


DEFAULT_COLLECTION = "approvedExemplars"
DEFAULT_EMBEDDING_MODEL = "text-embedding-004"
MAX_BATCH_SIZE = 400

CSV_RESUME_COLUMNS = ("resume_text", "resume", "cv_text", "cv", "candidate_resume")
CSV_JD_COLUMNS = ("job_text", "jd_text", "job_description", "jd", "description")
CSV_INDUSTRY_COLUMNS = ("category", "industry", "label", "job_category")
CSV_SENIORITY_COLUMNS = ("seniority", "level", "experience_level", "job_level")


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def console_text(value: Any) -> str:
    return str(value).encode("ascii", errors="backslashreplace").decode("ascii")


def redact_pii(text: str) -> str:
    """Remove obvious PII while keeping useful skill and experience evidence."""
    redacted = str(text or "")
    redacted = re.sub(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b", "[REDACTED_EMAIL]", redacted)
    redacted = re.sub(r"(?:\+?\d[\d\s().-]{7,}\d)", "[REDACTED_PHONE]", redacted)
    redacted = re.sub(r"https?://\S+|www\.\S+", "[REDACTED_URL]", redacted, flags=re.I)
    redacted = re.sub(
        r"(?im)^\s*(name|candidate|full name)\s*[:\-].*$",
        "[REDACTED_NAME]",
        redacted,
    )
    return clean_text(redacted)


def normalize_header(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")


def first_non_empty(row: dict[str, Any], aliases: Iterable[str]) -> str:
    normalized_row = {normalize_header(key): value for key, value in row.items() if key is not None}
    for alias in aliases:
        value = normalized_row.get(normalize_header(alias))
        if value not in (None, ""):
            return str(value)
    return ""


def parse_listish(value: str) -> list[str]:
    value = str(value or "").strip()
    if not value:
        return []
    try:
        parsed = ast.literal_eval(value)
        if isinstance(parsed, list):
            return [str(item).strip() for item in parsed if str(item).strip()]
    except (SyntaxError, ValueError):
        pass
    return [item.strip() for item in re.split(r"[,;|]", value) if item.strip()]


def infer_seniority(*texts: str) -> str:
    text = " ".join(texts).lower()
    if re.search(r"\b(lead|principal|head|director|manager)\b", text):
        return "Lead"
    if re.search(r"\b(senior|sr\.?|5\+?\s*years?|6\+?\s*years?|7\+?\s*years?)\b", text):
        return "Senior"
    if re.search(r"\b(mid|middle|3\+?\s*years?|4\+?\s*years?)\b", text):
        return "Mid-level"
    if re.search(r"\b(intern|internship|fresher|entry[- ]level|graduate)\b", text):
        return "Intern"
    return "Junior"


def build_analysis_json(row: dict[str, Any]) -> dict[str, Any]:
    ai_score = first_non_empty(row, ("ai_match_score", "match_score", "score"))
    string_score = first_non_empty(row, ("skill_string_match_score", "string_match_score"))
    fuzzy_score = first_non_empty(row, ("fuzzy_match_score",))
    required_skills = parse_listish(first_non_empty(row, ("job_required_skills", "required_skills")))
    resume_skills = parse_listish(first_non_empty(row, ("resume_skill_list", "resume_skills")))
    matched_skills = parse_listish(first_non_empty(row, ("ai_matched_skills", "matched_skills")))

    return {
        "source": "kaggle-job-resume-fit",
        "match_score": float(ai_score) if str(ai_score).replace(".", "", 1).isdigit() else None,
        "skill_string_match_score": float(string_score) if str(string_score).replace(".", "", 1).isdigit() else None,
        "fuzzy_match_score": float(fuzzy_score) if str(fuzzy_score).replace(".", "", 1).isdigit() else None,
        "required_skills": required_skills[:40],
        "resume_skills": resume_skills[:40],
        "matched_skills": matched_skills[:40],
    }


def stable_doc_id(*parts: str) -> str:
    payload = "\n".join(parts).encode("utf-8", errors="ignore")
    return hashlib.sha256(payload).hexdigest()[:32]


def candidate_data_dirs(explicit_data_dir: str | None) -> list[Path]:
    if explicit_data_dir:
        return [Path(explicit_data_dir).expanduser().resolve()]

    script_dir = Path(__file__).resolve().parent
    repo_root = script_dir.parent
    return [
        script_dir / "data" / "kaggle-job-resume-fit",
        script_dir / "data" / "raw" / "kaggle-job-resume-fit",
        repo_root / "ai_ml" / "data" / "raw" / "kaggle-job-resume-fit",
        repo_root / "ai_ml" / "data" / "kaggle-job-resume-fit",
    ]


def resolve_data_dir(explicit_data_dir: str | None) -> Path:
    for path in candidate_data_dirs(explicit_data_dir):
        if path.exists():
            return path
    checked = "\n".join(str(path) for path in candidate_data_dirs(explicit_data_dir))
    raise FileNotFoundError(f"Could not find kaggle-job-resume-fit data directory. Checked:\n{checked}")


def read_csv_records(csv_path: Path) -> Iterable[dict[str, Any]]:
    with csv_path.open("r", encoding="utf-8", errors="ignore", newline="") as handle:
        reader = csv.DictReader(handle)
        for row_index, row in enumerate(reader, start=1):
            resume_text = first_non_empty(row, CSV_RESUME_COLUMNS)
            jd_text = first_non_empty(row, CSV_JD_COLUMNS)
            if not resume_text or not jd_text:
                continue

            industry = clean_text(first_non_empty(row, CSV_INDUSTRY_COLUMNS)) or "Unknown"
            seniority = clean_text(first_non_empty(row, CSV_SENIORITY_COLUMNS)) or infer_seniority(resume_text, jd_text)
            source_id = first_non_empty(row, ("id", "ID")) or f"{csv_path.stem}-{row_index}"

            yield {
                "id": stable_doc_id(str(csv_path), source_id, resume_text[:500], jd_text[:500]),
                "industry": industry,
                "seniority": seniority,
                "redacted_cv_text": redact_pii(resume_text),
                "jd_snapshot": clean_text(jd_text),
                "analysis_json": build_analysis_json(row),
                "source_dataset": "kaggle-job-resume-fit",
                "source_file": str(csv_path.name),
                "source_row": row_index,
            }


def read_text_pair_records(data_dir: Path) -> Iterable[dict[str, Any]]:
    text_files = list(data_dir.rglob("*.txt")) + list(data_dir.rglob("*.md"))
    grouped: dict[str, dict[str, Path]] = {}
    for path in text_files:
        normalized_name = normalize_header(path.stem)
        key = re.sub(r"_(resume|cv|job|jd|description)$", "", normalized_name)
        bucket = grouped.setdefault(key, {})
        if re.search(r"(resume|cv)", normalized_name):
            bucket["resume"] = path
        elif re.search(r"(job|jd|description)", normalized_name):
            bucket["jd"] = path

    for key, paths in grouped.items():
        resume_path = paths.get("resume")
        jd_path = paths.get("jd")
        if not resume_path or not jd_path:
            continue
        resume_text = resume_path.read_text(encoding="utf-8", errors="ignore")
        jd_text = jd_path.read_text(encoding="utf-8", errors="ignore")
        if not resume_text.strip() or not jd_text.strip():
            continue
        industry = resume_path.parent.name if resume_path.parent != data_dir else "Unknown"
        seniority = infer_seniority(resume_text, jd_text)
        yield {
            "id": stable_doc_id(str(resume_path), str(jd_path), resume_text[:500], jd_text[:500]),
            "industry": industry,
            "seniority": seniority,
            "redacted_cv_text": redact_pii(resume_text),
            "jd_snapshot": clean_text(jd_text),
            "analysis_json": {"source": "kaggle-job-resume-fit", "pair_key": key},
            "source_dataset": "kaggle-job-resume-fit",
            "source_file": f"{resume_path.name}|{jd_path.name}",
        }


def iter_exemplar_documents(data_dir: Path, limit: int | None = None) -> Iterable[dict[str, Any]]:
    count = 0
    for csv_path in sorted(data_dir.rglob("*.csv")):
        for record in read_csv_records(csv_path):
            yield record
            count += 1
            if limit and count >= limit:
                return

    for record in read_text_pair_records(data_dir):
        yield record
        count += 1
        if limit and count >= limit:
            return


def extract_embedding_values(response: Any) -> list[float]:
    embeddings = getattr(response, "embeddings", None)
    if embeddings:
        values = getattr(embeddings[0], "values", None)
        return [float(value) for value in values or []]
    embedding = getattr(response, "embedding", None)
    values = getattr(embedding, "values", None) if embedding is not None else None
    return [float(value) for value in values or []]


def build_embedding_client() -> Any:
    from google import genai

    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("Set GEMINI_API_KEY or GOOGLE_API_KEY before using --with-embeddings.")
    return genai.Client(api_key=api_key)


def attach_embedding(record: dict[str, Any], client: Any, model: str) -> dict[str, Any]:
    text = f"{record['industry']} | {record['seniority']}\n{record['redacted_cv_text'][:6000]}"
    response = client.models.embed_content(model=model, contents=text)
    vector = extract_embedding_values(response)
    if vector:
        record["embedding"] = vector
        record["embedding_model"] = model
    return record


def seed_firestore(records: Iterable[dict[str, Any]], *, collection: str, project: str | None, dry_run: bool) -> int:
    if dry_run:
        count = 0
        for record in records:
            count += 1
            print(json.dumps({k: v for k, v in record.items() if k != "embedding"}, ensure_ascii=True)[:1200])
        return count

    from google.cloud import firestore

    client = firestore.Client(project=project) if project else firestore.Client()
    batch = client.batch()
    pending = 0
    total = 0

    for record in records:
        doc_id = str(record.pop("id"))
        record["updated_at"] = firestore.SERVER_TIMESTAMP
        batch.set(client.collection(collection).document(doc_id), record, merge=True)
        pending += 1
        total += 1
        if pending >= MAX_BATCH_SIZE:
            batch.commit()
            batch = client.batch()
            pending = 0

    if pending:
        batch.commit()
    return total


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed approvedExemplars from kaggle-job-resume-fit.")
    parser.add_argument("--data-dir", help="Path to kaggle-job-resume-fit directory.")
    parser.add_argument("--collection", default=DEFAULT_COLLECTION)
    parser.add_argument("--project", default=os.getenv("GOOGLE_CLOUD_PROJECT"))
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--with-embeddings", action="store_true")
    parser.add_argument("--embedding-model", default=DEFAULT_EMBEDDING_MODEL)
    args = parser.parse_args()

    data_dir = resolve_data_dir(args.data_dir)
    print(f"Using dataset: {console_text(data_dir)}")

    records = iter_exemplar_documents(data_dir, limit=args.limit)
    if args.with_embeddings:
        client = build_embedding_client()
        records = (attach_embedding(record, client, args.embedding_model) for record in records)

    total = seed_firestore(records, collection=args.collection, project=args.project, dry_run=args.dry_run)
    action = "Prepared" if args.dry_run else "Seeded"
    print(f"{action} {total} exemplar documents into {args.collection}.")


if __name__ == "__main__":
    main()
