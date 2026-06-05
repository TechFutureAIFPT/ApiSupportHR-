from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class GeminiGenerateRequest(BaseModel):
    model: str
    contents: Any
    config: Optional[Dict[str, Any]] = None


class GeminiGenerateResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    text: str
    saved_record_id: str | None = Field(default=None, alias="savedRecordId")


class GeminiEmbedRequest(BaseModel):
    text: str = Field(min_length=1)
    model: Optional[str] = None


class GeminiEmbedResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    vector: List[float]
    saved_record_id: str | None = Field(default=None, alias="savedRecordId")
