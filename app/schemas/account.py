from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class AuthenticatedUser(BaseModel):
    uid: str
    email: str = ""
    display_name: str | None = None
    photo_url: str | None = None


class UserProfileUpsertRequest(BaseModel):
    email: str | None = None
    displayName: str | None = None
    avatar: str | None = None
    provider: str | None = None


class UserAvatarUpdateRequest(BaseModel):
    avatar: str


class LocalHistoryMigrationEntry(BaseModel):
    jdText: str = ""
    jdTitle: str = "Vị trí tuyển dụng"
    cvCount: int = 0
    results: list[Any] = Field(default_factory=list)


class LocalDataMigrationRequest(BaseModel):
    avatar: str | None = None
    history: list[LocalHistoryMigrationEntry] = Field(default_factory=list)


class UserCvHistoryCreateRequest(BaseModel):
    email: str | None = None
    jdText: str = ""
    jdTitle: str = "Vị trí tuyển dụng"
    cvCount: int = 0
    results: list[Any] = Field(default_factory=list)


class HistorySaveRequest(BaseModel):
    jdText: str = ""
    jobPosition: str = ""
    locationRequirement: str = ""
    candidates: list[Any] = Field(default_factory=list)
    userEmail: str = ""
    weights: dict[str, Any] = Field(default_factory=dict)
    hardFilters: dict[str, Any] = Field(default_factory=dict)


class AnalysisRunDataRequest(BaseModel):
    timestamp: int | None = None
    job: dict[str, Any] = Field(default_factory=dict)
    candidates: list[Any] = Field(default_factory=list)


class CacheFileInfo(BaseModel):
    name: str = ""
    size: int = 0
    lastModified: int = 0


class CacheSyncRequest(BaseModel):
    cacheKey: str
    candidateData: dict[str, Any]
    jdHash: str = ""
    weightsHash: str = ""
    filtersHash: str = ""
    fileInfo: CacheFileInfo


class UploadedFileCreateRequest(BaseModel):
    fileName: str
    fileType: Literal["cv", "jd"]
    fileSize: int
    mimeType: str
    ocrMethod: str
    extractedText: str
    processingTimeMs: int = 0
    analysisSessionId: str | None = None
    candidateName: str | None = None
    jobPosition: str | None = None


class UploadedFilesBatchRequest(BaseModel):
    files: list[UploadedFileCreateRequest] = Field(default_factory=list)


class UserJDTemplateCreateRequest(BaseModel):
    name: str
    category: str
    jobPosition: str
    jdText: str
    hardFilters: dict[str, Any] = Field(default_factory=dict)


class ChatMessageRecordRequest(BaseModel):
    id: str
    author: Literal["user", "bot"]
    content: str
    timestamp: int
    suggestedCandidateIds: list[str] = Field(default_factory=list)


class ChatbotSessionCreateRequest(BaseModel):
    jobPosition: str
    totalCandidates: int = 0


class ChatbotMessagesRequest(BaseModel):
    messages: list[ChatMessageRecordRequest] = Field(default_factory=list)

