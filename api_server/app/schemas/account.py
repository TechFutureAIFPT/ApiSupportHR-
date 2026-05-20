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


class AnalysisFeedbackRequest(BaseModel):
    sessionId: str | None = None
    historyId: str | None = None
    syncHistoryId: str | None = None
    candidateId: str | None = None
    candidateName: str | None = None
    fileName: str | None = None
    jobPosition: str | None = None
    jdHash: str | None = None
    promptKey: str | None = None
    promptVersion: str | None = None
    modelVersion: str | None = None
    action: Literal["like", "dislike", "shortlist", "reject", "interview", "hire", "neutral"]
    aiScore: float | None = None
    finalScore: float | None = None
    isReusableGuidance: bool | None = None
    rank: str | None = None
    reason: str | None = None
    notes: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AnalysisFeedbackResponse(BaseModel):
    id: str
    uid: str
    userEmail: str = ""
    displayName: str = ""
    photoUrl: str = ""
    sessionId: str | None = None
    historyId: str | None = None
    syncHistoryId: str | None = None
    candidateId: str | None = None
    candidateName: str | None = None
    fileName: str | None = None
    jobPosition: str | None = None
    jdHash: str | None = None
    promptKey: str | None = None
    promptVersion: str | None = None
    modelVersion: str | None = None
    action: str
    aiScore: float | None = None
    finalScore: float | None = None
    isReusableGuidance: bool = False
    severity: Literal["low", "medium", "high"] = "low"
    rank: str | None = None
    reason: str | None = None
    notes: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    createdAt: int | None = None
    updatedAt: int | None = None


class AnalysisFeedbackStatsResponse(BaseModel):
    totalFeedback: int = 0
    actionsCount: dict[str, int] = Field(default_factory=dict)
    positiveCount: int = 0
    negativeCount: int = 0
    latestFeedbackAt: int | None = None
    recentEntries: list[AnalysisFeedbackResponse] = Field(default_factory=list)


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


class UserJDTemplateUpdateRequest(BaseModel):
    name: str | None = None
    category: str | None = None
    jobPosition: str | None = None
    jdText: str | None = None
    hardFilters: dict[str, Any] | None = None


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


class GoogleDriveOAuthUrlRequest(BaseModel):
    redirectUri: str | None = None


class GoogleDriveOAuthUrlResponse(BaseModel):
    authUrl: str
    state: str
    redirectUri: str
    scopes: list[str] = Field(default_factory=list)


class GoogleDriveOAuthExchangeRequest(BaseModel):
    code: str
    state: str
    redirectUri: str | None = None


class GoogleDriveConnectionStatusResponse(BaseModel):
    connected: bool = False
    email: str | None = None
    displayName: str | None = None
    photoUrl: str | None = None
    scopes: list[str] = Field(default_factory=list)
    connectedAt: int | None = None
    updatedAt: int | None = None
    expiresAt: int | None = None
    driveUserId: str | None = None


class GoogleDriveFileOwner(BaseModel):
    displayName: str = ""
    emailAddress: str = ""


class GoogleDriveFileItem(BaseModel):
    id: str
    name: str
    mimeType: str
    size: int | None = None
    modifiedTime: str | None = None
    iconLink: str | None = None
    webViewLink: str | None = None
    parents: list[str] = Field(default_factory=list)
    owners: list[GoogleDriveFileOwner] = Field(default_factory=list)
    isGoogleWorkspaceFile: bool = False


class GoogleDriveFilesResponse(BaseModel):
    files: list[GoogleDriveFileItem] = Field(default_factory=list)
    nextPageToken: str | None = None


class GoogleDriveImportRequest(BaseModel):
    fileId: str
    fileType: Literal["cv", "jd"] = "cv"
    forceOcr: bool = False
    analysisSessionId: str | None = None
    candidateName: str | None = None
    jobPosition: str | None = None
    persistUploadedFile: bool = True


class GoogleDriveImportResponse(BaseModel):
    fileId: str
    fileName: str
    mimeType: str
    sourceMimeType: str
    fileSize: int
    extractedText: str
    ocrMethod: str
    processingTimeMs: int
    savedUploadedFileId: str | None = None
    webViewLink: str | None = None
    driveFile: GoogleDriveFileItem | None = None
