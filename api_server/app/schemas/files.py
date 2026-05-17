from __future__ import annotations

from pydantic import BaseModel


class ExtractedTextResponse(BaseModel):
    text: str
