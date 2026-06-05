from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ExtractedTextResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    text: str
    saved_record_id: str | None = Field(default=None, alias="savedRecordId")
