from __future__ import annotations

import math
import re
from pathlib import Path
from threading import Lock
from typing import Any

import joblib


MODEL_PATH = Path(__file__).resolve().parents[1] / "models" / "text_classifier_model.pkl"

_model_cache: Any | None = None
_model_error: str | None = None
_model_lock = Lock()


def clean_text(text: str) -> str:
    normalized = str(text).lower()
    normalized = re.sub(r"[^\w\s]+", " ", normalized, flags=re.UNICODE)
    normalized = normalized.replace("_", " ")
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip()


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

    model = _load_model()

    try:
        predicted_label = str(model.predict([cleaned_text])[0])
    except Exception as error:  # pragma: no cover - defensive path for runtime failures
        raise RuntimeError(f"Failed to run local classifier prediction: {error}") from error

    top_predictions = _rank_predictions(model, cleaned_text, top_k=top_k)
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
