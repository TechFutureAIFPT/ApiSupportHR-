from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import shutil
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import quote
from urllib.request import Request, urlopen

from supporthr_ml.contracts import SOURCE_MANIFEST_SCHEMA_VERSION
from supporthr_ml.registry import ensure_use_allowed, get_source


DEFAULT_PATTERNS = ("*.csv", "*.json", "*.jsonl", "*.parquet", "*.md")
USER_AGENT = "SupportHR-ML-Pipeline/1.0"


def _request_json(url: str) -> Any:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=60) as response:
        return json.load(response)


def _repo_files(repository: str, revision: str) -> list[dict[str, Any]]:
    encoded_revision = quote(revision, safe="")
    url = (
        f"https://huggingface.co/api/datasets/{repository}/tree/{encoded_revision}"
        "?recursive=true&expand=false"
    )
    payload = _request_json(url)
    if not isinstance(payload, list):
        raise RuntimeError("Unexpected Hugging Face repository tree response.")
    return [
        item for item in payload
        if isinstance(item, dict) and item.get("type") == "file" and item.get("path")
    ]


def _safe_target(root: Path, relative_path: str) -> Path:
    pure = PurePosixPath(relative_path)
    if pure.is_absolute() or ".." in pure.parts:
        raise ValueError(f"Unsafe repository path: {relative_path}")
    target = (root / Path(*pure.parts)).resolve()
    if root.resolve() not in target.parents and target != root.resolve():
        raise ValueError(f"Repository path escapes output directory: {relative_path}")
    return target


def _safe_category(value: str) -> Path:
    pure = PurePosixPath(value or "huggingface")
    if pure.is_absolute() or ".." in pure.parts or not pure.parts:
        raise ValueError(f"Unsafe storage category: {value}")
    return Path(*pure.parts)


def _download(url: str, target: Path) -> str:
    target.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=120) as response, target.open("wb") as handle:
        while chunk := response.read(1024 * 1024):
            handle.write(chunk)
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Download a registered Hugging Face dataset at its pinned revision."
    )
    parser.add_argument("--source-id", required=True)
    parser.add_argument("--intended-use", required=True)
    parser.add_argument("--accept-license", required=True)
    parser.add_argument("--output-root")
    parser.add_argument("--pattern", action="append", dest="patterns")
    parser.add_argument("--max-total-mb", type=float, default=512.0)
    parser.add_argument(
        "--allow-quarantine-download",
        action="store_true",
        help="Allow immutable raw acquisition for an audit_only source; never permits training or release.",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    source = get_source(args.source_id)
    status = str(source.get("status") or "")
    if status == "rejected":
        raise SystemExit(f"Dataset {args.source_id} is rejected and cannot be downloaded.")
    if status == "quarantine":
        allowed_uses = {str(item) for item in source.get("intendedUses") or []}
        if (
            not args.allow_quarantine_download
            or args.intended_use != "audit_only"
            or args.intended_use not in allowed_uses
        ):
            raise SystemExit(
                "Quarantined datasets require --allow-quarantine-download and --intended-use audit_only."
            )
    else:
        ensure_use_allowed(source, args.intended_use)
    if source.get("provider") != "Hugging Face":
        raise SystemExit(f"Dataset {args.source_id} is not a Hugging Face source.")
    if args.accept_license.strip().casefold() != str(source.get("license") or "").strip().casefold():
        raise SystemExit("--accept-license must exactly match the reviewed registry license.")

    repository = str(source.get("repository") or "")
    revision = str(source.get("revision") or "")
    if not repository or len(revision) != 40:
        raise SystemExit("Hugging Face repository and pinned 40-character revision are required.")

    patterns = tuple(args.patterns or DEFAULT_PATTERNS)
    repository_files = _repo_files(repository, revision)
    files = [
        item for item in repository_files
        if any(fnmatch.fnmatch(str(item["path"]), pattern) for pattern in patterns)
    ]
    total_size = sum(int(item.get("size") or 0) for item in files)
    if total_size > args.max_total_mb * 1024 * 1024:
        raise SystemExit(
            f"Selected files total {total_size / 1024 / 1024:.1f} MB, above --max-total-mb={args.max_total_mb:.1f}."
        )

    script_dir = Path(__file__).resolve().parent
    output_root = (
        Path(args.output_root).expanduser().resolve()
        if args.output_root
        else script_dir / "data" / "raw" / "huggingface"
    )
    storage_category = _safe_category(str(source.get("storageCategory") or "huggingface"))
    destination = output_root / storage_category / args.source_id / revision
    plan = {
        "sourceId": args.source_id,
        "repository": repository,
        "revision": revision,
        "license": source["license"],
        "status": status,
        "intendedUse": args.intended_use,
        "storageCategory": storage_category.as_posix(),
        "selectedPatterns": list(patterns),
        "repositoryFileCount": len(repository_files),
        "excludedFileCount": len(repository_files) - len(files),
        "fileCount": len(files),
        "totalBytes": total_size,
        "destination": str(destination),
        "files": [{"path": item["path"], "size": int(item.get("size") or 0)} for item in files],
    }
    if args.dry_run:
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return 0

    downloaded: list[dict[str, Any]] = []
    if destination.exists():
        raise SystemExit(f"Destination already exists; refusing to overwrite immutable raw data: {destination}")
    destination.mkdir(parents=True)
    try:
        for item in files:
            relative_path = str(item["path"])
            target = _safe_target(destination, relative_path)
            url = f"https://huggingface.co/datasets/{repository}/resolve/{revision}/{quote(relative_path)}"
            downloaded.append({
                "path": relative_path,
                "size": int(item.get("size") or 0),
                "sha256": _download(url, target),
            })
        manifest = {
            **plan,
            "schemaVersion": SOURCE_MANIFEST_SCHEMA_VERSION,
            "files": downloaded,
        }
        (destination / "source-manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        shutil.rmtree(destination, ignore_errors=True)
        raise
    print(json.dumps({**plan, "downloaded": True}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
