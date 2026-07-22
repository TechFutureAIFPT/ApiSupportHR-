from __future__ import annotations

import math
import json
import hashlib
import re
from pathlib import Path
from threading import Lock
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import joblib
import sklearn

from app.core.ai_contract import MODEL_ARTIFACT_SCHEMA_VERSION
from app.core.config import get_settings


MODEL_PATH = Path(__file__).resolve().parents[1] / "models" / "text_classifier_model.pkl"
MANIFEST_PATH = MODEL_PATH.with_suffix(".manifest.json")

_model_cache: Any | None = None
_model_error: str | None = None
_model_manifest: dict[str, Any] | None = None
_model_lock = Lock()


def clean_text(text: str) -> str:
    normalized = str(text).lower()
    normalized = re.sub(r"[^\w\s]+", " ", normalized, flags=re.UNICODE)
    normalized = normalized.replace("_", " ")
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_and_validate_manifest() -> dict[str, Any]:
    if not MANIFEST_PATH.is_file():
        raise FileNotFoundError(f"Classifier manifest was not found at: {MANIFEST_PATH}")
    try:
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(f"Classifier manifest is invalid: {error}") from error
    if manifest.get("schemaVersion") != MODEL_ARTIFACT_SCHEMA_VERSION:
        raise RuntimeError("Classifier manifest schema is unsupported.")
    expected_hash = str(manifest.get("sha256") or "").strip().lower()
    actual_hash = _sha256(MODEL_PATH)
    if not expected_hash or actual_hash != expected_hash:
        raise RuntimeError(
            f"Classifier checksum mismatch: expected {expected_hash or 'missing'}, received {actual_hash}"
        )
    required_sklearn = str(manifest.get("frameworkVersion") or "").strip()
    if required_sklearn and sklearn.__version__ != required_sklearn:
        raise RuntimeError(
            f"Classifier requires scikit-learn {required_sklearn}; runtime has {sklearn.__version__}"
        )
    return manifest


def _load_model() -> Any:
    global _model_cache, _model_error, _model_manifest

    if _model_cache is not None:
        return _model_cache

    with _model_lock:
        if _model_cache is not None:
            return _model_cache

        if not MODEL_PATH.is_file():
            _model_error = f"Local classifier model was not found at: {MODEL_PATH}"
            raise FileNotFoundError(_model_error)

        try:
            _model_manifest = _load_and_validate_manifest()
            _model_cache = joblib.load(MODEL_PATH)
            expected_labels = [str(value) for value in (_model_manifest.get("labels") or [])]
            actual_labels = [str(value) for value in getattr(_model_cache, "classes_", [])]
            if expected_labels and actual_labels != expected_labels:
                raise RuntimeError("Classifier labels do not match the artifact manifest.")
            _model_error = None
        except Exception as error:  # pragma: no cover - defensive path for runtime failures
            _model_error = f"Failed to load local classifier model: {error}"
            raise RuntimeError(_model_error) from error

    return _model_cache


def warm_classifier() -> dict[str, Any]:
    """Load and verify the local model once so server readiness is deterministic."""
    return get_classifier_status()


def _round_score(value: Any) -> float | None:
    if not isinstance(value, (int, float)):
        return None
    return round(float(value), 4)


def _derived_remote_status_url(classify_url: str) -> str:
    if "classify-industry" in classify_url:
        return classify_url.replace("classify-industry", "classifier-status")
    return classify_url.rstrip("/") + "/status"


def _http_error_detail(error: HTTPError) -> str:
    try:
        raw = error.read().decode("utf-8", errors="replace")
        payload = json.loads(raw) if raw else {}
        if isinstance(payload, dict):
            detail = payload.get("detail") or payload.get("message") or payload.get("error")
            if detail:
                return str(detail)
        return raw or str(error)
    except Exception:
        return str(error)


def _remote_request(url: str, payload: dict[str, Any] | None, timeout: float) -> dict[str, Any]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"} if data is not None else {},
        method="POST" if data is not None else "GET",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
            parsed = json.loads(body) if body else {}
            return parsed if isinstance(parsed, dict) else {}
    except HTTPError as error:
        detail = _http_error_detail(error)
        if error.code in {404, 503}:
            raise FileNotFoundError(detail) from error
        raise RuntimeError(detail) from error
    except URLError as error:
        raise RuntimeError(str(error)) from error


def _classify_remote(cleaned_text: str, top_k: int) -> dict[str, Any]:
    settings = get_settings()
    if not settings.local_classifier_remote_classify_url:
        raise FileNotFoundError("Remote classifier URL is not configured.")

    payload = {
        "cv_text": cleaned_text,
        "top_k": top_k,
    }
    result = _remote_request(
        settings.local_classifier_remote_classify_url,
        payload,
        settings.local_classifier_remote_timeout_seconds,
    )
    top_predictions = []
    for item in list(result.get("top_predictions") or []):
        if not isinstance(item, dict):
            continue
        top_predictions.append(
            {
                "label": str(item.get("label") or ""),
                "score": _round_score(item.get("score")),
            }
        )

    return {
        "predicted_label": str(result.get("predicted_label") or result.get("label") or "unknown"),
        "confidence": _round_score(result.get("confidence")),
        "top_predictions": top_predictions,
        "model_source": str(result.get("model_source") or "remote://classifier"),
    }


def _remote_status() -> dict[str, Any]:
    settings = get_settings()
    classify_url = settings.local_classifier_remote_classify_url
    status_url = settings.local_classifier_remote_status_url or _derived_remote_status_url(classify_url)
    if not status_url:
        raise FileNotFoundError("Remote classifier status URL is not configured.")
    result = _remote_request(status_url, None, settings.local_classifier_remote_timeout_seconds)
    labels = [str(label) for label in list(result.get("labels") or [])]
    return {
        "ready": bool(result.get("ready")),
        "model_source": str(result.get("model_source") or "remote://classifier"),
        "label_count": int(result.get("label_count") or len(labels)),
        "labels": labels,
        "error": result.get("error"),
    }


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

    settings = get_settings()
    if settings.local_classifier_mode in {"remote", "auto"} and settings.local_classifier_remote_classify_url:
        try:
            return _classify_remote(cleaned_text, top_k)
        except Exception:
            if settings.local_classifier_mode == "remote":
                raise

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
        "model_version": str((_model_manifest or {}).get("modelVersion") or "unknown"),
    }


def get_classifier_status() -> dict[str, Any]:
    settings = get_settings()
    has_remote_status = bool(
        settings.local_classifier_remote_status_url or settings.local_classifier_remote_classify_url
    )
    if settings.local_classifier_mode in {"remote", "auto"} and has_remote_status:
        try:
            return _remote_status()
        except Exception as error:
            if settings.local_classifier_mode == "remote":
                return {
                    "ready": False,
                    "model_source": settings.local_classifier_remote_classify_url,
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
                "model_version": str((_model_manifest or {}).get("modelVersion") or "unknown"),
                "artifact_sha256": str((_model_manifest or {}).get("sha256") or ""),
                "label_count": len(classes),
                "labels": classes,
                "error": None,
            }
        except Exception as error:  # pragma: no cover - defensive path for runtime failures
            return {
                "ready": False,
                "model_source": str(MODEL_PATH),
                "model_version": str((_model_manifest or {}).get("modelVersion") or "unknown"),
                "artifact_sha256": str((_model_manifest or {}).get("sha256") or ""),
                "label_count": 0,
                "labels": [],
                "error": str(error),
            }

    return {
        "ready": False,
        "model_source": str(MODEL_PATH),
        "model_version": "unknown",
        "artifact_sha256": "",
        "label_count": 0,
        "labels": [],
        "error": _model_error or f"Local classifier model was not found at: {MODEL_PATH}",
    }
