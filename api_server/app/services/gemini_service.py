from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List

from fastapi import HTTPException
from google import genai
import google.generativeai as genai_legacy

from app.core.config import get_settings


def _camel_to_snake(value: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", value).lower()


def _normalize_config(value: Any) -> Any:
    if isinstance(value, dict):
        normalized: Dict[str, Any] = {}
        for key, inner in value.items():
            normalized_key = _camel_to_snake(key)
            if normalized_key == "response_schema":
                # The schema contains output field names such as candidateName.
                # Do not snake_case nested JSON Schema properties.
                normalized[normalized_key] = inner
            else:
                normalized[normalized_key] = _normalize_config(inner)
        return normalized
    if isinstance(value, list):
        return [_normalize_config(item) for item in value]
    return value


def _is_invalid_key_error(error: Exception) -> bool:
    message = str(error)
    return (
        "API_KEY_INVALID" in message
        or "API key not valid" in message
        or ("400" in message and "INVALID_ARGUMENT" in message)
    )


def _get_keys() -> List[str]:
    settings = get_settings()
    keys = settings.gemini_api_keys
    if not keys:
        raise HTTPException(status_code=500, detail="GEMINI_API_KEY not configured on server")
    return keys


def _fallback_models(model: str) -> Iterable[str]:
    yield model
    if model != "gemini-2.5-flash":
        yield "gemini-2.5-flash"
    if model != "gemini-flash-latest":
        yield "gemini-flash-latest"


def _fallback_embedding_models(model: str) -> Iterable[str]:
    yield model
    if model in {"text-embedding-004", "models/text-embedding-004"}:
        yield "gemini-embedding-001"
    if model != "gemini-embedding-001":
        yield "gemini-embedding-001"


def generate_content(model: str, contents: Any, config: Any = None) -> str:
    keys = _get_keys()
    last_error: Exception | None = None
    normalized_config = _normalize_config(config) if config is not None else None

    for target_model in _fallback_models(model):
        for index, key in enumerate(keys, start=1):
            try:
                client = genai.Client(api_key=key)
                response = client.models.generate_content(
                    model=target_model,
                    contents=contents,
                    config=normalized_config,
                )
                return response.text or ""
            except Exception as error:  # pragma: no cover - network/provider path
                last_error = error
                if _is_invalid_key_error(error):
                    print(f"[Gemini Backend] Key {index}/{len(keys)} invalid or revoked.")
                else:
                    print(f"[Gemini Backend] Model {target_model} with key {index} failed: {error}")

    raise HTTPException(status_code=500, detail=str(last_error or "All Gemini keys and models failed on backend"))


def embed_text(text: str, model: str | None = None) -> List[float]:
    settings = get_settings()
    target_model = model or settings.gemini_embedding_model
    keys = _get_keys()
    last_error: Exception | None = None

    for target_embedding_model in _fallback_embedding_models(target_model):
        for index, key in enumerate(keys, start=1):
            try:
                genai_legacy.configure(api_key=key)
                result = genai_legacy.embed_content(
                    model=target_embedding_model,
                    content=text,
                    task_type="semantic_similarity",
                )
                vector = result.get("embedding", [])
                if not vector:
                    raise ValueError("Embedding API returned an empty vector")
                return [float(value) for value in vector]
            except Exception as error:  # pragma: no cover - network/provider path
                last_error = error
                if _is_invalid_key_error(error):
                    print(f"[Gemini Embed] Key {index}/{len(keys)} invalid or revoked.")
                else:
                    print(f"[Gemini Embed] Model {target_embedding_model} with key {index} failed: {error}")

    raise HTTPException(status_code=500, detail=str(last_error or "All Gemini embedding keys failed on backend"))
