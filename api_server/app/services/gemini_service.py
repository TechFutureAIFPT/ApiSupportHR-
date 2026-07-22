from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List

from fastapi import HTTPException
try:
    from google import genai
except ImportError:  # pragma: no cover - optional in isolated test envs
    genai = None  # type: ignore[assignment]

from app.core.ai_contract import embedding_prompt
from app.core.config import get_settings


def _camel_to_snake(value: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", value).lower()


def _sanitize_schema_for_gemini(value: Any) -> Any:
    if isinstance(value, dict):
        sanitized: Dict[str, Any] = {}
        for key, inner in value.items():
            if key == "additionalProperties" and isinstance(inner, bool):
                continue
            sanitized[key] = _sanitize_schema_for_gemini(inner)
        return sanitized
    if isinstance(value, list):
        return [_sanitize_schema_for_gemini(item) for item in value]
    return value


def _normalize_config(value: Any) -> Any:
    if isinstance(value, dict):
        normalized: Dict[str, Any] = {}
        for key, inner in value.items():
            if inner is None:
                continue
            normalized_key = _camel_to_snake(key)
            if normalized_key == "response_schema":
                # The schema contains output field names such as candidateName.
                # Do not snake_case nested JSON Schema properties.
                normalized[normalized_key] = _sanitize_schema_for_gemini(inner)
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


def _get_keys(api_keys: Iterable[str] | None = None) -> List[str]:
    if api_keys is not None:
        keys = [value.strip() for value in api_keys if isinstance(value, str) and value.strip()]
        if not keys:
            raise HTTPException(status_code=500, detail="Gemini API key not configured on server")
        return keys

    settings = get_settings()
    keys = settings.gemini_api_keys
    if not keys:
        raise HTTPException(status_code=500, detail="GEMINI_API_KEY not configured on server")
    return keys


def _supports_thinking_config(model_name: str) -> bool:
    return "gemini-2.5" in (model_name or "").lower()


def _config_for_model(config: Any, model_name: str) -> Any:
    if not isinstance(config, dict):
        return config

    normalized_model = (model_name or "").strip().lower()
    if normalized_model.startswith(("gemini-3.6-flash", "gemini-3.5-flash-lite")):
        deprecated_sampling_keys = {"temperature", "top_p", "top_k"}
        return {key: value for key, value in config.items() if key not in deprecated_sampling_keys}
    return dict(config)


def _fallback_models(model: str) -> Iterable[str]:
    seen: set[str] = set()
    for candidate in (model, "gemini-3.6-flash", "gemini-3.5-flash", "gemini-2.5-flash"):
        normalized = (candidate or "").strip()
        if normalized and normalized not in seen:
            seen.add(normalized)
            yield normalized


def generate_content(
    model: str,
    contents: Any,
    config: Any = None,
    api_keys: Iterable[str] | None = None,
) -> str:
    if genai is None:
        raise HTTPException(status_code=500, detail="Google GenAI SDK is not installed on server")

    keys = _get_keys(api_keys)
    last_error: Exception | None = None
    normalized_config = _normalize_config(config) if config is not None else None

    for target_model in _fallback_models(model):
        attempt_config = _config_for_model(normalized_config, target_model)
        if isinstance(attempt_config, dict) and "thinking_config" in attempt_config and not _supports_thinking_config(target_model):
            attempt_config = {key: value for key, value in attempt_config.items() if key != "thinking_config"}

        for index, key in enumerate(keys, start=1):
            try:
                client = genai.Client(api_key=key)
                response = client.models.generate_content(
                    model=target_model,
                    contents=contents,
                    config=attempt_config,
                )
                return response.text or ""
            except Exception as error:  # pragma: no cover - network/provider path
                last_error = error
                if _is_invalid_key_error(error):
                    print(f"[Gemini Backend] Key {index}/{len(keys)} invalid or revoked.")
                else:
                    print(f"[Gemini Backend] Model {target_model} with key {index} failed: {error}")

    raise HTTPException(status_code=500, detail=str(last_error or "All Gemini keys and models failed on backend"))


def _embedding_values(response: Any) -> List[float]:
    embeddings = getattr(response, "embeddings", None) or []
    if embeddings:
        values = getattr(embeddings[0], "values", None) or []
        return [float(value) for value in values]
    embedding = getattr(response, "embedding", None)
    values = getattr(embedding, "values", None) if embedding is not None else None
    return [float(value) for value in (values or [])]


def embed_text(
    text: str,
    model: str | None = None,
    *,
    task: str = "semantic_similarity",
    title: str = "none",
    output_dimensionality: int | None = None,
) -> List[float]:
    if genai is None:
        raise HTTPException(status_code=500, detail="Google GenAI SDK is not installed on server")

    settings = get_settings()
    target_model = model or settings.gemini_embedding_model
    target_dimension = output_dimensionality or settings.gemini_embedding_dimension
    prepared_text = embedding_prompt(text, task=task, title=title)
    keys = _get_keys()
    last_error: Exception | None = None

    for index, key in enumerate(keys, start=1):
        try:
            client = genai.Client(api_key=key)
            response = client.models.embed_content(
                model=target_model,
                contents=prepared_text,
                config={"output_dimensionality": target_dimension},
            )
            vector = _embedding_values(response)
            if len(vector) != target_dimension:
                raise ValueError(
                    f"Embedding dimension mismatch: expected {target_dimension}, received {len(vector)}"
                )
            return vector
        except Exception as error:  # pragma: no cover - network/provider path
            last_error = error
            if _is_invalid_key_error(error):
                print(f"[Gemini Embed] Key {index}/{len(keys)} invalid or revoked.")
            else:
                print(f"[Gemini Embed] Model {target_model} with key {index} failed: {error}")

    raise HTTPException(status_code=500, detail=str(last_error or "All Gemini embedding keys failed on backend"))
