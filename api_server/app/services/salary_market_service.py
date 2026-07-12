from __future__ import annotations

import unicodedata
from typing import Any

import httpx

from app.core.config import get_settings


_LOCATION_MAP = {
    "ha noi": "Hanoi",
    "hanoi": "Hanoi",
    "hai phong": "Hai Phong",
    "haiphong": "Hai Phong",
    "da nang": "Da Nang",
    "danang": "Da Nang",
    "thanh pho ho chi minh": "Ho Chi Minh City",
    "ho chi minh": "Ho Chi Minh City",
    "hcm": "Ho Chi Minh City",
    "saigon": "Ho Chi Minh City",
    "sai gon": "Ho Chi Minh City",
}


def _strip_diacritics(value: str) -> str:
    normalized = unicodedata.normalize("NFD", value or "")
    return "".join(char for char in normalized if unicodedata.category(char) != "Mn").lower()


def normalize_job_title(title: str) -> str:
    return _strip_diacritics(title).strip()


def normalize_location(location: str | None) -> str:
    if not location:
        return "Vietnam"
    normalized = _strip_diacritics(location).strip()
    return _LOCATION_MAP.get(normalized, "Vietnam")


def get_experience_level(years: float | None) -> dict[str, str]:
    if years is None:
        return {"years": "ALL", "level": "All Levels"}
    if years <= 1:
        return {"years": "0-1", "level": "Junior"}
    if years <= 4:
        return {"years": "2-4", "level": "Mid"}
    if years <= 7:
        return {"years": "5-7", "level": "Senior"}
    return {"years": "8+", "level": "Lead"}


def fetch_market_salary(job_title: str, location: str, years_of_experience: str) -> dict[str, Any] | None:
    """Gọi RapidAPI job-salary-data server-side. Key không bao giờ lộ ra client."""
    api_key = get_settings().rapidapi_key
    if not api_key:
        return None

    try:
        response = httpx.get(
            "https://job-salary-data.p.rapidapi.com/job-salary",
            params={
                "job_title": job_title,
                "location": location,
                "location_type": "ANY",
                "years_of_experience": years_of_experience,
            },
            headers={
                "x-rapidapi-key": api_key,
                "x-rapidapi-host": "job-salary-data.p.rapidapi.com",
            },
            timeout=8.0,
        )
        response.raise_for_status()
        payload = response.json()
    except Exception as error:  # pragma: no cover - network path
        print(f"[Salary Market] RapidAPI request failed: {error}")
        return None

    if payload.get("status") != "OK":
        return None
    data = payload.get("data")
    if not isinstance(data, list) or not data:
        return None

    primary = data[0]
    multiplier = 1
    currency = primary.get("salary_currency")
    if currency and currency != "VND":
        multiplier = 25000

    median = float(primary.get("median_salary") or 0) * multiplier
    if median <= 0:
        return None

    return {
        "p25": float(primary.get("p25_salary") or 0) * multiplier,
        "median": median,
        "p75": float(primary.get("p75_salary") or 0) * multiplier,
        "currency": "VND",
        "period": primary.get("salary_period") or "MONTHLY",
    }


def estimate_salary_fallback(
    job_title: str,
    location: str,
    years_of_experience: float | None,
) -> dict[str, Any]:
    """Ước tính nội bộ khi RapidAPI không khả dụng — port từ salaryAnalysisService.ts."""
    title_lower = (job_title or "").lower()

    base_min, base_median, base_max = 8.0, 15.0, 25.0

    if any(kw in title_lower for kw in ("senior", "lead", "architect")):
        base_min, base_median, base_max = 25.0, 40.0, 60.0
    elif any(kw in title_lower for kw in ("manager", "director")):
        base_min, base_median, base_max = 30.0, 50.0, 80.0
    elif any(kw in title_lower for kw in ("junior", "fresher")):
        base_min, base_median, base_max = 6.0, 10.0, 15.0
    elif "mid" in title_lower or (years_of_experience is not None and 2 <= years_of_experience <= 4):
        base_min, base_median, base_max = 12.0, 20.0, 30.0

    premium_tech = ("ai", "ml", "machine learning", "blockchain", "devops", "cloud", "architect")
    if any(tech in title_lower for tech in premium_tech):
        base_min *= 1.3
        base_median *= 1.3
        base_max *= 1.3

    if "Ho Chi Minh" in location or "Hanoi" in location:
        base_min *= 1.1
        base_median *= 1.1
        base_max *= 1.1

    if years_of_experience is not None:
        exp_multiplier = 1 + (years_of_experience * 0.08)
        base_min *= exp_multiplier
        base_median *= exp_multiplier
        base_max *= exp_multiplier

    return {
        "p25": round(base_min * 1_000_000),
        "median": round(base_median * 1_000_000),
        "p75": round(base_max * 1_000_000),
        "currency": "VND",
        "period": "MONTHLY",
    }
