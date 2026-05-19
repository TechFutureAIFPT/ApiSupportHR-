from __future__ import annotations

import json
import math
import re
from pathlib import Path
from threading import Lock
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen

import joblib

from app.core.config import get_settings


MODEL_PATH = Path(__file__).resolve().parents[1] / "models" / "text_classifier_model.pkl"
KNOWN_REMOTE_CLASSIFY_PATH = "/api/cv/classify-industry"
KNOWN_REMOTE_STATUS_PATH = "/api/cv/classifier-status"

_model_cache: Any | None = None
_model_error: str | None = None
_model_lock = Lock()


def clean_text(text: str) -> str:
    normalized = str(text).lower()
    normalized = re.sub(r"[^\w\s]+", " ", normalized, flags=re.UNICODE)
    normalized = normalized.replace("_", " ")
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip()


def _safe_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _classifier_mode() -> str:
    settings = get_settings()
    if settings.local_classifier_mode == "remote":
        return "remote"
    if settings.local_classifier_mode == "auto" and settings.local_classifier_remote_classify_url:
        return "remote"
    return "local"


def _remote_classify_url() -> str:
    settings = get_settings()
    url = settings.local_classifier_remote_classify_url.strip()
    if not url:
        raise RuntimeError(
            "Remote classifier mode is enabled but LOCAL_CLASSIFIER_REMOTE_CLASSIFY_URL is empty."
        )
    return url


def _remote_status_url() -> str:
    settings = get_settings()
    if settings.local_classifier_remote_status_url:
        return settings.local_classifier_remote_status_url

    classify_url = settings.local_classifier_remote_classify_url.strip()
    if not classify_url:
        return ""

    parts = urlsplit(classify_url)
    if parts.path.rstrip("/").endswith(KNOWN_REMOTE_CLASSIFY_PATH):
        status_path = f"{parts.path.rstrip('/')[:-len(KNOWN_REMOTE_CLASSIFY_PATH)]}{KNOWN_REMOTE_STATUS_PATH}"
        return urlunsplit((parts.scheme, parts.netloc, status_path, parts.query, parts.fragment))
    return ""


def _extract_remote_error_message(payload: str) -> str:
    body = payload.strip()
    if not body:
        return ""
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        return body[:240]

    if isinstance(parsed, dict):
        detail = parsed.get("detail")
        if isinstance(detail, str) and detail.strip():
            return detail.strip()
        if detail not in (None, ""):
            return str(detail)
    return body[:240]


def _request_json(url: str, *, method: str, payload: dict[str, Any] | None = None) -> Any:
    settings = get_settings()
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = Request(
        url,
        data=body,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        method=method,
    )
    timeout = max(0.1, float(settings.local_classifier_remote_timeout_seconds))

    try:
        with urlopen(request, timeout=timeout) as response:
            response_body = response.read().decode("utf-8", errors="replace")
    except HTTPError as error:
        error_body = error.read().decode("utf-8", errors="replace")
        detail = _extract_remote_error_message(error_body) or error.reason or "Unknown remote error."
        if error.code == 422:
            raise ValueError(f"Remote classifier rejected the request: {detail}") from error
        if error.code == 503:
            raise FileNotFoundError(f"Remote classifier is unavailable: {detail}") from error
        raise RuntimeError(f"Remote classifier request failed with HTTP {error.code}: {detail}") from error
    except URLError as error:
        reason = getattr(error, "reason", error)
        raise RuntimeError(f"Remote classifier request failed: {reason}") from error
    except TimeoutError as error:
        raise RuntimeError("Remote classifier request timed out.") from error

    try:
        return json.loads(response_body)
    except json.JSONDecodeError as error:
        raise RuntimeError("Remote classifier returned invalid JSON.") from error


def _normalize_top_predictions(raw_predictions: Any) -> list[dict[str, float | None]]:
    normalized: list[dict[str, float | None]] = []
    if not isinstance(raw_predictions, list):
        return normalized

    for item in raw_predictions:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or "").strip()
        if not label:
            continue
        score = _safe_float(item.get("score"))
        normalized.append(
            {
                "label": label,
                "score": round(score, 4) if score is not None else None,
            }
        )
    return normalized


def _normalize_remote_classification(payload: Any, *, source_url: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise RuntimeError("Remote classifier response must be a JSON object.")

    predicted_label = str(
        payload.get("predicted_label") or payload.get("predictedLabel") or ""
    ).strip()
    if not predicted_label:
        raise RuntimeError("Remote classifier response is missing predicted_label.")

    confidence = _safe_float(payload.get("confidence"))
    top_predictions = _normalize_top_predictions(payload.get("top_predictions") or payload.get("topPredictions"))
    model_source = str(payload.get("model_source") or payload.get("modelSource") or source_url).strip() or source_url

    return {
        "predicted_label": predicted_label,
        "confidence": round(confidence, 4) if confidence is not None else None,
        "top_predictions": top_predictions,
        "model_source": model_source,
    }


def _normalize_remote_status(payload: Any, *, source_url: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise RuntimeError("Remote classifier status response must be a JSON object.")

    labels = [
        str(label).strip()
        for label in payload.get("labels", [])
        if str(label).strip()
    ]
    label_count = payload.get("label_count", payload.get("labelCount"))
    try:
        resolved_label_count = int(label_count) if label_count is not None else len(labels)
    except (TypeError, ValueError):
        resolved_label_count = len(labels)

    error_value = payload.get("error")
    error_message = str(error_value).strip() if error_value not in (None, "") else None

    return {
        "ready": bool(payload.get("ready")),
        "model_source": str(payload.get("model_source") or payload.get("modelSource") or source_url).strip() or source_url,
        "label_count": max(resolved_label_count, len(labels)),
        "labels": labels,
        "error": error_message,
    }


def _classify_cv_text_remote(cv_text: str, top_k: int = 3) -> dict[str, Any]:
    payload = _request_json(
        _remote_classify_url(),
        method="POST",
        payload={
            "cv_text": cv_text,
            "top_k": top_k,
        },
    )
    return _normalize_remote_classification(payload, source_url=_remote_classify_url())


def _get_remote_classifier_status() -> dict[str, Any]:
    classify_url = _remote_classify_url()
    status_url = _remote_status_url()
    if not status_url:
        return {
            "ready": True,
            "model_source": classify_url,
            "label_count": 0,
            "labels": [],
            "error": None,
        }

    payload = _request_json(status_url, method="GET")
    return _normalize_remote_status(payload, source_url=status_url)


def _load_model() -> Any:
    global _model_cache, _model_error

    if _model_cache is not None:
        return _model_cache

    with _model_lock:
        if _model_cache is not None:
            return _model_cache

        if not MODEL_PATH.is_file():
            _model_error = f"Local classifier model was not found at: {MODEL_PATH}"
            raise FileNotFoundError(_model_error)

        try:
            _model_cache = joblib.load(MODEL_PATH)
            _model_error = None
        except Exception as error:  # pragma: no cover - defensive path for runtime failures
            _model_error = f"Failed to load local classifier model: {error}"
            raise RuntimeError(_model_error) from error

    return _model_cache


def _softmax(values: list[float]) -> list[float]:
    if not values:
        return []
    max_value = max(values)
    exps = [math.exp(value - max_value) for value in values]
    total = sum(exps)
    if total <= 0:
        return [0.0 for _ in values]
    return [value / total for value in exps]


def _rank_predictions(model: Any, cleaned_text: str, top_k: int) -> list[dict[str, float]]:
    classes = [str(label) for label in getattr(model, "classes_", [])]
    if not classes:
        return []

    if hasattr(model, "predict_proba"):
        probabilities = model.predict_proba([cleaned_text])[0]
        scored = [
            {"label": label, "score": round(float(score), 4)}
            for label, score in zip(classes, probabilities, strict=False)
        ]
    elif hasattr(model, "decision_function"):
        raw_scores = model.decision_function([cleaned_text])
        if hasattr(raw_scores, "tolist"):
            raw_scores = raw_scores.tolist()
        if isinstance(raw_scores, list) and raw_scores and isinstance(raw_scores[0], list):
            raw_scores = raw_scores[0]
        if not isinstance(raw_scores, list):
            raw_scores = [float(raw_scores)]
        probabilities = _softmax([float(value) for value in raw_scores])
        scored = [
            {"label": label, "score": round(float(score), 4)}
            for label, score in zip(classes, probabilities, strict=False)
        ]
    else:
        return []

    return sorted(scored, key=lambda item: item["score"], reverse=True)[:top_k]


def classify_cv_text(cv_text: str, top_k: int = 3) -> dict[str, Any]:
    cleaned_text = clean_text(cv_text)
    if not cleaned_text:
        raise ValueError("CV text is empty after cleaning.")

    if _classifier_mode() == "remote":
        return _classify_cv_text_remote(cleaned_text, top_k=top_k)

    model = _load_model()

    try:
        predicted_label = str(model.predict([cleaned_text])[0])
    except Exception as error:  # pragma: no cover - defensive path for runtime failures
        raise RuntimeError(f"Failed to run local classifier prediction: {error}") from error

    try:
        top_predictions = _rank_predictions(model, cleaned_text, top_k=top_k)
    except Exception:
        # A model can still predict labels even when probability helpers break
        # because of scikit-learn version drift between training and serving.
        top_predictions = []
    confidence = next(
        (prediction["score"] for prediction in top_predictions if prediction["label"] == predicted_label),
        None,
    )

    return {
        "predicted_label": predicted_label,
        "confidence": confidence,
        "top_predictions": top_predictions,
        "model_source": str(MODEL_PATH),
    }


def get_classifier_status() -> dict[str, Any]:
    if _classifier_mode() == "remote":
        try:
            return _get_remote_classifier_status()
        except Exception as error:  # pragma: no cover - defensive path for runtime failures
            return {
                "ready": False,
                "model_source": get_settings().local_classifier_remote_classify_url or "remote",
                "label_count": 0,
                "labels": [],
                "error": str(error),
            }

    if MODEL_PATH.is_file():
        try:
            model = _load_model()
            classes = [str(label) for label in getattr(model, "classes_", [])]
            return {
                "ready": True,
                "model_source": str(MODEL_PATH),
                "label_count": len(classes),
                "labels": classes,
                "error": None,
            }
        except Exception as error:  # pragma: no cover - defensive path for runtime failures
            return {
                "ready": False,
                "model_source": str(MODEL_PATH),
                "label_count": 0,
                "labels": [],
                "error": str(error),
            }

    return {
        "ready": False,
        "model_source": str(MODEL_PATH),
        "label_count": 0,
        "labels": [],
        "error": _model_error or f"Local classifier model was not found at: {MODEL_PATH}",
    }
