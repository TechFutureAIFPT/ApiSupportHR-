from __future__ import annotations

import base64
import json
from typing import Any, Iterable

from fastapi import HTTPException, status
from pydantic import BaseModel, Field, ValidationError, field_validator


class CursorToken(BaseModel):
    sort_at: str = Field(alias="sortAt")
    document_id: str = Field(alias="id")


class FieldSelection(BaseModel):
    fields: list[str]

    @field_validator("fields")
    @classmethod
    def unique_non_empty_fields(cls, value: list[str]) -> list[str]:
        result = list(dict.fromkeys(item.strip() for item in value if item.strip()))
        if not result:
            raise ValueError("At least one response field is required.")
        return result


class CursorPageResponse(BaseModel):
    items: list[dict[str, Any]] = Field(default_factory=list)
    next_cursor: str | None = Field(default=None, alias="nextCursor")
    has_more: bool = Field(default=False, alias="hasMore")
    page_size: int = Field(alias="pageSize")

    model_config = {"populate_by_name": True}


def encode_cursor(sort_at: str, document_id: str) -> str:
    payload = CursorToken(sortAt=sort_at, id=document_id).model_dump(by_alias=True)
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_cursor(value: str | None) -> CursorToken | None:
    if not value:
        return None
    try:
        padded = value + "=" * (-len(value) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
        return CursorToken.model_validate(payload)
    except (ValueError, TypeError, json.JSONDecodeError, ValidationError) as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="cursor is invalid or expired",
        ) from error


def parse_field_selection(
    raw_fields: str | None,
    *,
    allowed_fields: Iterable[str],
    default_fields: Iterable[str],
) -> list[str]:
    allowed = set(allowed_fields)
    requested = [item.strip() for item in (raw_fields or "").split(",") if item.strip()]
    try:
        selection = FieldSelection(fields=requested or list(default_fields)).fields
    except ValidationError as error:
        raise HTTPException(status_code=422, detail="fields must contain at least one field") from error
    unknown = sorted(set(selection) - allowed)
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"message": "Unsupported field selection", "unknownFields": unknown},
        )
    return selection
