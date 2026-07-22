from __future__ import annotations

import copy
from typing import Any

from app.core.ai_contract import DEFAULT_RUBRIC_VERSION
from app.services.role_profile_service import ROLE_PROFILES, get_role_profile, resolve_role_profile


BASE_CRITERIA = (
    ("job_fit", "Phù hợp trực tiếp với JD", 20.0),
    ("role_skills", "Kỹ năng chuyên môn theo vị trí", 35.0),
    ("experience", "Kinh nghiệm và mức độ sở hữu công việc", 20.0),
    ("impact", "Dự án, kết quả và bằng chứng định lượng", 10.0),
    ("education", "Học vấn và chứng chỉ liên quan", 5.0),
    ("soft_skills", "Kỹ năng phối hợp và độ tin cậy hồ sơ", 10.0),
)


def _split_weight(total: float, count: int) -> list[float]:
    if count <= 0:
        return []
    base = round(total / count, 2)
    values = [base] * count
    values[-1] = round(total - sum(values[:-1]), 2)
    return values


def _role_skill_children(role_key: str) -> list[dict[str, Any]]:
    profile = get_role_profile(role_key)
    requirements = [
        *list(profile.get("coreRequirements") or []),
        *list(profile.get("secondaryRequirements") or []),
    ]
    if not requirements:
        return []
    child_weights = _split_weight(35.0, len(requirements))
    return [
        {
            "key": str(requirement.get("key") or f"skill_{index}"),
            "name": str(requirement.get("label") or "Kỹ năng chuyên môn"),
            "weight": child_weights[index],
            "description": "Chỉ chấm khi CV có bằng chứng trực tiếp; không suy diễn từ chức danh.",
        }
        for index, requirement in enumerate(requirements)
    ]


def build_default_rubric(role_key: str, *, version: str = DEFAULT_RUBRIC_VERSION) -> dict[str, Any]:
    profile = get_role_profile(role_key)
    resolved_role_key = str(profile.get("roleKey") or "generic")
    weights: dict[str, Any] = {}
    for key, name, weight in BASE_CRITERIA:
        criterion: dict[str, Any] = {"name": name, "weight": weight}
        if key == "role_skills":
            children = _role_skill_children(resolved_role_key)
            if children:
                criterion["children"] = children
                criterion.pop("weight", None)
        weights[key] = criterion
    return {
        "rubricVersion": version,
        "roleKey": resolved_role_key,
        "roleLabel": str(profile.get("label") or "General Specialist"),
        "totalWeight": 100.0,
        "weights": weights,
    }


def _criterion_weight(criterion: Any) -> float:
    if not isinstance(criterion, dict):
        return 0.0
    children = criterion.get("children")
    if isinstance(children, list) and children:
        return sum(
            float(child.get("weight") or 0.0)
            for child in children
            if isinstance(child, dict)
        )
    return float(criterion.get("weight") or 0.0)


def validate_weights(weights: dict[str, Any]) -> float:
    if not isinstance(weights, dict) or not weights:
        raise ValueError("Scoring weights must contain at least one criterion.")
    total = sum(_criterion_weight(criterion) for criterion in weights.values())
    if abs(total - 100.0) > 0.05:
        raise ValueError(f"Scoring weights must total 100; received {round(total, 2)}.")
    for key, criterion in weights.items():
        if not isinstance(criterion, dict) or not str(criterion.get("name") or "").strip():
            raise ValueError(f"Scoring criterion '{key}' must include a name.")
        if _criterion_weight(criterion) <= 0:
            raise ValueError(f"Scoring criterion '{key}' must have a positive weight.")
    return round(total, 2)


def _weight_diff(defaults: dict[str, Any], override: dict[str, Any]) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    for key in sorted(set(defaults) | set(override)):
        default_value = round(_criterion_weight(defaults.get(key)), 2)
        override_value = round(_criterion_weight(override.get(key)), 2)
        if default_value != override_value:
            changes.append({
                "criterionKey": key,
                "defaultWeight": default_value,
                "effectiveWeight": override_value,
                "delta": round(override_value - default_value, 2),
            })
    return changes


def resolve_scoring_rubric(
    *,
    jd_text: str,
    hard_filters: dict[str, Any],
    requested_weights: dict[str, Any] | None,
    rubric_version: str,
) -> dict[str, Any]:
    role_profile = resolve_role_profile(jd_text=jd_text, hard_filters=hard_filters)
    role_key = str(role_profile.get("roleKey") or "generic")
    default_rubric = build_default_rubric(role_key, version=rubric_version)
    default_weights = default_rubric["weights"]
    if not requested_weights:
        return {**default_rubric, "source": "role_template", "overrideDiff": []}

    effective = copy.deepcopy(requested_weights)
    validate_weights(effective)
    return {
        **default_rubric,
        "weights": effective,
        "source": "recruiter_override",
        "overrideDiff": _weight_diff(default_weights, effective),
    }


def list_rubrics(*, version: str = DEFAULT_RUBRIC_VERSION) -> list[dict[str, Any]]:
    return [
        build_default_rubric(role_key, version=version)
        for role_key in ROLE_PROFILES
        if role_key != "generic"
    ]
