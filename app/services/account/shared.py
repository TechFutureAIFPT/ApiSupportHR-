from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable


def to_millis(value: Any) -> int:
    if isinstance(value, datetime):
        return int(value.timestamp() * 1000)
    if isinstance(value, (int, float)):
        return int(value)
    return 0


def serialize(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: serialize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [serialize(item) for item in value]
    if isinstance(value, datetime):
        return to_millis(value)
    return value


def sorted_docs(docs: Iterable[Any], field_name: str, reverse: bool = True) -> list[Any]:
    return sorted(docs, key=lambda doc: to_millis(doc.to_dict().get(field_name)), reverse=reverse)
