from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


TargetPlatform = Literal["generic", "topcv", "vietnamworks", "linkedin", "parse_jd"]


class JDSupplementalFields(BaseModel):
    company_name: str = Field(default="", alias="companyName")
    salary: str = ""
    location: str = ""
    working_time: str = Field(default="", alias="workingTime")
    benefits: str = ""
    application_info: str = Field(default="", alias="applicationInfo")
    notes: str = ""


class JDStandardizeRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    jd_text: str = Field(alias="jdText", min_length=1)
    target_platform: TargetPlatform = Field(default="generic", alias="targetPlatform")
    supplemental_fields: JDSupplementalFields | None = Field(default=None, alias="supplementalFields")


class JDPlatformInfo(BaseModel):
    name: str
    url: str


class JDMissingSection(BaseModel):
    key: str
    label: str
    reason: str
    priority: Literal["high", "medium", "low"] = "medium"


class JDWeakPoint(BaseModel):
    label: str
    detail: str


class JDSuggestion(BaseModel):
    label: str
    detail: str


class NormalizedJD(BaseModel):
    title: str = ""
    overview: str = ""
    responsibilities: list[str] = Field(default_factory=list)
    requirements: list[str] = Field(default_factory=list)
    benefits: list[str] = Field(default_factory=list)
    working_time: str = Field(default="", alias="workingTime")
    location: str = ""
    salary: str = ""
    application_info: str = Field(default="", alias="applicationInfo")
    keywords: list[str] = Field(default_factory=list)


class JDStandardizeResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    score: int
    missing_sections: list[JDMissingSection] = Field(alias="missingSections")
    weak_points: list[JDWeakPoint] = Field(alias="weakPoints")
    suggestions: list[JDSuggestion]
    normalized_jd: NormalizedJD = Field(alias="normalizedJD")
    platform: JDPlatformInfo
    platform_url: str = Field(alias="platformUrl")
    generated_at: str = Field(alias="generatedAt")
    source: Literal["ai", "fallback"] = "fallback"
