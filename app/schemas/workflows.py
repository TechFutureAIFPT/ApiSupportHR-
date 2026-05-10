from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class JdStructureRequest(BaseModel):
    raw_text: str = Field(min_length=1)


class JdStructureResponse(BaseModel):
    structured_text: str


class JdPositionRequest(BaseModel):
    jd_text: str = Field(min_length=1)


class JdPositionResponse(BaseModel):
    job_position: str


class JdHardFiltersRequest(BaseModel):
    jd_text: str = Field(min_length=1)


class JdHardFiltersResponse(BaseModel):
    filters: Dict[str, str]


class InterviewQuestionsRequest(BaseModel):
    analysis_data: Dict[str, Any]
    analysis_stats: Dict[str, Any]
    question_type: Literal["general", "specific", "comparative"]
    candidate_data: Optional[Any] = None


class InterviewQuestionsResponse(BaseModel):
    question_sets: List[Dict[str, Any]]
