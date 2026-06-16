from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class SavedRecordMixin(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    saved_record_id: str | None = Field(default=None, alias="savedRecordId")


class JdStructureRequest(BaseModel):
    raw_text: str = Field(min_length=1)


class JdStructureResponse(SavedRecordMixin):
    structured_text: str


class JdPositionRequest(BaseModel):
    jd_text: str = Field(min_length=1)


class JdPositionResponse(SavedRecordMixin):
    job_position: str


class JdHardFiltersRequest(BaseModel):
    jd_text: str = Field(min_length=1)


class JdHardFiltersResponse(SavedRecordMixin):
    filters: Dict[str, Any]


class InterviewQuestionsRequest(BaseModel):
    analysis_data: Dict[str, Any]
    analysis_stats: Dict[str, Any]
    question_type: Literal["general", "specific", "comparative"]
    candidate_data: Optional[Any] = None


class InterviewQuestionsResponse(SavedRecordMixin):
    question_sets: List[Dict[str, Any]]
