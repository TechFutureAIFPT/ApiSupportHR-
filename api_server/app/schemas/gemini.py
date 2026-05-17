from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class GeminiGenerateRequest(BaseModel):
    model: str
    contents: Any
    config: Optional[Dict[str, Any]] = None


class GeminiGenerateResponse(BaseModel):
    text: str


class GeminiEmbedRequest(BaseModel):
    text: str = Field(min_length=1)
    model: Optional[str] = None


class GeminiEmbedResponse(BaseModel):
    vector: List[float]
