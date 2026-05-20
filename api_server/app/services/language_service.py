from __future__ import annotations

import asyncio
import re
from typing import Any

from app.core.config import get_settings
from app.services.gemini_service import generate_content

try:  # langdetect is intentionally optional at runtime; heuristics stay as fallback.
    from langdetect import DetectorFactory, LangDetectException, detect_langs

    DetectorFactory.seed = 42
except Exception:  # pragma: no cover - dependency fallback
    detect_langs = None
    LangDetectException = Exception


VIETNAMESE_HINTS = {
    "va",
    "la",
    "cho",
    "voi",
    "kinh",
    "nghiem",
    "du",
    "an",
    "quan",
    "ly",
    "phat",
    "trien",
    "nhan",
    "su",
    "ban",
    "hang",
    "truyen",
    "thong",
    "ke",
    "toan",
    "tai",
    "chinh",
}
ENGLISH_HINTS = {
    "the",
    "and",
    "with",
    "for",
    "experience",
    "worked",
    "developed",
    "managed",
    "skills",
    "project",
    "projects",
    "education",
    "employment",
    "team",
    "business",
    "marketing",
    "software",
    "engineer",
    "developer",
    "analysis",
}
VIETNAMESE_DIACRITICS_PATTERN = re.compile(r"[àáảãạăằắẳẵặâầấẩẫậđèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵ]", re.IGNORECASE)


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip())


def _tokenize(value: str) -> list[str]:
    return [
        token
        for token in re.sub(r"[^\w\s-]", " ", (value or "").lower()).split()
        if len(token) > 1
    ]


def detect_language(text: str) -> dict[str, Any]:
    cleaned = _clean_text(text)
    if not cleaned:
        return {"language": "unknown", "confidence": 0.0, "reason": "empty_text"}

    if detect_langs is not None:
        try:
            detections = detect_langs(cleaned[:6000])
            if detections:
                best = detections[0]
                language = "vi" if best.lang == "vi" else "en" if best.lang == "en" else best.lang
                confidence = round(float(best.prob), 2)
                if language in {"vi", "en"} and confidence >= 0.55:
                    return {
                        "language": language,
                        "confidence": confidence,
                        "reason": "langdetect",
                    }
        except LangDetectException:
            pass

    if VIETNAMESE_DIACRITICS_PATTERN.search(cleaned):
        return {"language": "vi", "confidence": 0.99, "reason": "vietnamese_diacritics"}

    tokens = _tokenize(cleaned[:4000])
    if not tokens:
        return {"language": "unknown", "confidence": 0.0, "reason": "no_tokens"}

    vietnamese_score = sum(1 for token in tokens if token in VIETNAMESE_HINTS)
    english_score = sum(1 for token in tokens if token in ENGLISH_HINTS)

    if vietnamese_score >= 3 and vietnamese_score >= english_score:
        confidence = round(min(0.95, 0.55 + vietnamese_score / max(20, len(tokens))), 2)
        return {"language": "vi", "confidence": confidence, "reason": "vietnamese_keyword_match"}

    if english_score >= 3 and english_score > vietnamese_score:
        confidence = round(min(0.95, 0.55 + english_score / max(20, len(tokens))), 2)
        return {"language": "en", "confidence": confidence, "reason": "english_keyword_match"}

    return {"language": "unknown", "confidence": 0.3, "reason": "low_signal"}


def translate_to_vietnamese(text: str) -> str:
    cleaned = _clean_text(text)
    if not cleaned:
        return ""

    settings = get_settings()
    prompt = (
        "Ban la he thong dich CV chuyen nghiep.\n"
        "Nhiem vu: dich noi dung CV tieng Anh sang tieng Viet.\n"
        "Quy tac:\n"
        "- Giu dung y nghia nghiep vu.\n"
        "- Giu nguyen ten cong ty, ten cong nghe, ten chung chi, ten san pham.\n"
        "- Dung tieng Viet tu nhien, ro rang.\n"
        "- Chi tra ve ban dich, khong them ghi chu.\n\n"
        "CV goc:\n"
        f"{cleaned[:12000]}"
    )
    return _clean_text(
        generate_content(
            settings.gemini_default_model,
            prompt,
            {
                "temperature": 0.1,
                "topP": 0.8,
                "topK": 20,
            },
        )
    )


async def translate_to_vietnamese_async(text: str) -> str:
    return await asyncio.to_thread(translate_to_vietnamese, text)


def normalize_cv_text_for_analysis(cv_text: str) -> dict[str, Any]:
    original_text = _clean_text(cv_text)
    detection = detect_language(original_text)
    translated_text = ""
    analysis_text = original_text
    was_translated = False

    if detection["language"] == "en":
        translated_text = translate_to_vietnamese(original_text)
        if translated_text:
            analysis_text = translated_text
            was_translated = True

    return {
        "original_text": original_text,
        "analysis_text": analysis_text,
        "translated_text": translated_text,
        "normalized_vi_text": analysis_text,
        "language": detection["language"],
        "language_confidence": detection["confidence"],
        "language_reason": detection["reason"],
        "was_translated": was_translated,
    }


async def normalize_cv_text_for_analysis_async(cv_text: str) -> dict[str, Any]:
    original_text = _clean_text(cv_text)
    detection = detect_language(original_text)
    translated_text = ""
    analysis_text = original_text
    was_translated = False

    if detection["language"] == "en":
        try:
            translated_text = await translate_to_vietnamese_async(original_text)
        except Exception:
            translated_text = ""
        if translated_text:
            analysis_text = translated_text
            was_translated = True

    return {
        "original_text": original_text,
        "analysis_text": analysis_text,
        "translated_text": translated_text,
        "normalized_vi_text": analysis_text,
        "language": detection["language"],
        "language_confidence": detection["confidence"],
        "language_reason": detection["reason"],
        "was_translated": was_translated,
    }


def build_analysis_text_bundle(payload: dict[str, Any]) -> str:
    analysis_text = _clean_text(str(payload.get("analysis_text") or ""))
    original_text = _clean_text(str(payload.get("original_text") or ""))
    translated_text = _clean_text(str(payload.get("translated_text") or ""))

    if payload.get("was_translated") and translated_text:
        return (
            "Ban dich tieng Viet de phan tich:\n"
            f"{translated_text}\n\n"
            "Ban goc de doi chieu thuat ngu:\n"
            f"{original_text[:6000]}"
        ).strip()

    return analysis_text or original_text
