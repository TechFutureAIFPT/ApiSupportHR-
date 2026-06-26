from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Mapping


PROMPTS_ROOT = Path(__file__).resolve().parent

ACTIVE_PROMPT_VERSIONS: dict[str, str] = {
    "candidate_refinement/education_validation": "v1",
    "candidate_refinement/refine_name": "v1",
    "cv_analysis/analyze_entries": "v6",
    "file_extraction/ocr_document": "v1",
    "mobile_jd/standardize": "v1",
    "workflow/extract_hard_filters": "v1",
    "workflow/extract_job_position": "v1",
    "workflow/interview_comparative": "v1",
    "workflow/interview_general": "v1",
    "workflow/interview_specific": "v1",
    "workflow/jd_structure": "v1",
}

_PLACEHOLDER_PATTERN = re.compile(r"\[\[\s*([a-zA-Z0-9_]+)\s*\]\]")


class PromptRenderError(ValueError):
    pass


def get_prompt_version(prompt_key: str) -> str:
    version = ACTIVE_PROMPT_VERSIONS.get(prompt_key)
    if not version:
        raise KeyError(f"Prompt '{prompt_key}' is not registered.")
    return version


def get_prompt_path(prompt_key: str, version: str | None = None) -> Path:
    prompt_version = version or get_prompt_version(prompt_key)
    return PROMPTS_ROOT.joinpath(*prompt_key.split("/"), f"{prompt_version}.md")


def load_prompt_template(prompt_key: str, version: str | None = None) -> str:
    path = get_prompt_path(prompt_key, version=version)
    if not path.exists():
        raise FileNotFoundError(f"Prompt file not found: {path}")
    return path.read_text(encoding="utf-8").strip()


def render_prompt(
    prompt_key: str,
    *,
    context: Mapping[str, Any] | None = None,
    version: str | None = None,
) -> str:
    template = load_prompt_template(prompt_key, version=version)
    values = {
        key: "" if value is None else str(value)
        for key, value in (context or {}).items()
    }

    expected_keys = set(_PLACEHOLDER_PATTERN.findall(template))
    missing = sorted(key for key in expected_keys if key not in values)
    if missing:
        raise PromptRenderError(
            f"Prompt '{prompt_key}' is missing required context keys: {', '.join(missing)}"
        )

    def replace(match: re.Match[str]) -> str:
        return values[match.group(1)]

    return _PLACEHOLDER_PATTERN.sub(replace, template).strip()
