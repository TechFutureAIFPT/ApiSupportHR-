from __future__ import annotations

import os
from functools import lru_cache
from typing import List

from dotenv import load_dotenv

from app.core.ai_contract import (
    DEFAULT_EMBEDDING_DIMENSION,
    DEFAULT_EMBEDDING_MODEL,
    DEFAULT_RUBRIC_VERSION,
    DEFAULT_VECTOR_INDEX_VERSION,
)


load_dotenv()

DEFAULT_WEB_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "https://www.supporthr-tf.com.vn",
    "https://supporthr-tf.com.vn",
]


class Settings:
    def __init__(self) -> None:
        def _float_env(name: str, default: float) -> float:
            try:
                return float(os.getenv(name, str(default)))
            except (TypeError, ValueError):
                return default

        self.app_name = os.getenv("APP_NAME", "SupportHR Backend")
        self.maintenance_mode = os.getenv("MAINTENANCE_MODE", "0").strip().lower() in {"1", "true", "yes", "on"}
        self.database_url = os.getenv("DATABASE_URL", "").strip()
        self.supabase_url = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
        self.supabase_jwt_audience = os.getenv("SUPABASE_JWT_AUDIENCE", "authenticated").strip() or "authenticated"
        self.supabase_jwt_issuer = (
            os.getenv("SUPABASE_JWT_ISSUER", "").strip()
            or (f"{self.supabase_url}/auth/v1" if self.supabase_url else "")
        )
        self.supabase_jwks_url = (
            os.getenv("SUPABASE_JWKS_URL", "").strip()
            or (f"{self.supabase_url}/auth/v1/.well-known/jwks.json" if self.supabase_url else "")
        )
        self.frontend_origin = os.getenv("FRONTEND_ORIGIN", "https://www.supporthr-tf.com.vn")
        self.gemini_default_model = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")
        self.gemini_cv_analysis_model = (
            os.getenv("GEMINI_CV_ANALYSIS_MODEL", "gemini-3.6-flash").strip()
            or self.gemini_default_model
        )
        self.quick_cv_gemini_model = (
            os.getenv("QUICK_CV_GEMINI_MODEL", "gemini-3.6-flash").strip()
            or self.gemini_cv_analysis_model
        )
        self.mobile_jd_gemini_model = (
            os.getenv("MOBILE_JD_GEMINI_MODEL", "gemini-3.6-flash").strip()
            or self.gemini_default_model
        )
        self.gemini_thinking_budget = int(os.getenv("GEMINI_THINKING_BUDGET", "8000"))
        raw_embedding_model = os.getenv("GEMINI_EMBEDDING_MODEL", "").strip()
        retired_embedding_models = {
            "",
            "text-embedding-004",
            "models/text-embedding-004",
            "gemini-embedding-001",
            "models/gemini-embedding-001",
        }
        self.gemini_embedding_model = (
            DEFAULT_EMBEDDING_MODEL if raw_embedding_model in retired_embedding_models else raw_embedding_model
        )
        self.gemini_embedding_dimension = max(
            128,
            min(2048, int(_float_env("GEMINI_EMBEDDING_DIMENSION", DEFAULT_EMBEDDING_DIMENSION))),
        )
        self.vector_index_version = (
            os.getenv("VECTOR_INDEX_VERSION", DEFAULT_VECTOR_INDEX_VERSION).strip()
            or DEFAULT_VECTOR_INDEX_VERSION
        )
        self.google_api_key = os.getenv("GOOGLE_API_KEY", "")
        self.google_picker_api_key = os.getenv("GOOGLE_PICKER_API_KEY", "")
        self.google_cloud_vision_api_key = os.getenv("GOOGLE_CLOUD_VISION_API_KEY", "")
        self.rapidapi_key = os.getenv("RAPIDAPI_KEY", "").strip()
        self.google_oauth_client_id = os.getenv("GOOGLE_OAUTH_CLIENT_ID", "")
        self.google_oauth_client_secret = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET", "")
        self.google_oauth_redirect_uri = os.getenv("GOOGLE_OAUTH_REDIRECT_URI", "")
        raw_drive_origins = os.getenv("GOOGLE_DRIVE_ALLOWED_ORIGINS", "").strip()
        self.vector_store_collection = (
            os.getenv("VECTOR_STORE_COLLECTION", "vectorLibraryRecords").strip()
            or "vectorLibraryRecords"
        )
        self.approved_exemplars_collection = (
            os.getenv("APPROVED_EXEMPLARS_COLLECTION", "approvedExemplars").strip()
            or "approvedExemplars"
        )
        self.rubric_version = (
            os.getenv("RUBRIC_VERSION", DEFAULT_RUBRIC_VERSION).strip()
            or DEFAULT_RUBRIC_VERSION
        )
        raw_classifier_mode = os.getenv("LOCAL_CLASSIFIER_MODE", "local").strip().lower()
        if raw_classifier_mode not in {"local", "remote", "auto"}:
            raw_classifier_mode = "local"
        self.local_classifier_mode = raw_classifier_mode
        self.local_classifier_remote_classify_url = os.getenv("LOCAL_CLASSIFIER_REMOTE_CLASSIFY_URL", "").strip()
        self.local_classifier_remote_status_url = os.getenv("LOCAL_CLASSIFIER_REMOTE_STATUS_URL", "").strip()
        self.local_classifier_remote_timeout_seconds = _float_env("LOCAL_CLASSIFIER_REMOTE_TIMEOUT_SECONDS", 10.0)
        self.local_classifier_confidence_threshold = _float_env("LOCAL_CLASSIFIER_CONFIDENCE_THRESHOLD", 0.60)
        self.rag_similarity_threshold = _float_env("RAG_SIMILARITY_THRESHOLD", 0.75)
        self.rag_max_exemplars = max(1, int(_float_env("RAG_MAX_EXEMPLARS", 2)))
        self.rag_candidate_limit = max(10, min(500, int(_float_env("RAG_CANDIDATE_LIMIT", 100))))
        self.ai_preprocess_concurrency = max(1, min(8, int(_float_env("AI_PREPROCESS_CONCURRENCY", 4))))
        self.require_classifier_ready = os.getenv("REQUIRE_CLASSIFIER_READY", "1").strip().lower() in {
            "1", "true", "yes", "on"
        }
        self.redis_url = os.getenv("REDIS_URL", "").strip()
        self.redis_internal_url = os.getenv("REDIS_INTERNAL_URL", "").strip()
        raw_analysis_job_mode = os.getenv("ANALYSIS_JOB_MODE", "in_process").strip().lower()
        if raw_analysis_job_mode not in {"in_process", "redis", "auto"}:
            raw_analysis_job_mode = "in_process"
        self.analysis_job_mode = raw_analysis_job_mode
        self.analysis_job_queue_key = (
            os.getenv("ANALYSIS_JOB_QUEUE_KEY", "supporthr:analysis:stream").strip()
            or "supporthr:analysis:stream"
        )
        self.analysis_job_consumer_group = (
            os.getenv("ANALYSIS_JOB_CONSUMER_GROUP", "supporthr-workers").strip()
            or "supporthr-workers"
        )
        self.analysis_job_reclaim_idle_seconds = max(
            60,
            int(os.getenv("ANALYSIS_JOB_RECLAIM_IDLE_SECONDS", "3600")),
        )
        self.analysis_job_stream_max_length = max(
            1000,
            int(os.getenv("ANALYSIS_JOB_STREAM_MAX_LENGTH", "10000")),
        )
        self.analysis_job_result_ttl_seconds = max(
            300,
            int(os.getenv("ANALYSIS_JOB_RESULT_TTL_SECONDS", "86400")),
        )
        self.analysis_job_lease_seconds = max(
            300,
            int(os.getenv("ANALYSIS_JOB_LEASE_SECONDS", "3600")),
        )
        self.analysis_job_max_concurrency_per_user = max(
            1,
            int(os.getenv("ANALYSIS_JOB_MAX_CONCURRENCY_PER_USER", "3")),
        )
        self.account_cache_ttl_seconds = max(15, int(os.getenv("ACCOUNT_CACHE_TTL_SECONDS", "120")))
        self.mobile_inbox_cache_ttl_seconds = max(15, int(os.getenv("MOBILE_INBOX_CACHE_TTL_SECONDS", "60")))
        self.template_cache_ttl_seconds = max(30, int(os.getenv("TEMPLATE_CACHE_TTL_SECONDS", "300")))
        self.sync_cache_ttl_seconds = max(30, int(os.getenv("SYNC_CACHE_TTL_SECONDS", "300")))
        self.upload_file_size_limit_mb = max(1, int(os.getenv("UPLOAD_FILE_SIZE_LIMIT_MB", "15")))
        self.allowed_upload_extensions = [
            value.strip().lower()
            for value in os.getenv("ALLOWED_UPLOAD_EXTENSIONS", ".pdf,.docx,.txt,.csv,.png,.jpg,.jpeg,.webp").split(",")
            if value.strip()
        ]
        self.allowed_upload_mime_types = [
            value.strip().lower()
            for value in os.getenv(
                "ALLOWED_UPLOAD_MIME_TYPES",
                "application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/plain,text/csv,application/csv,image/png,image/jpeg,image/webp"
            ).split(",")
            if value.strip()
        ]
        default_drive_origins = list(dict.fromkeys([self.frontend_origin, *DEFAULT_WEB_ORIGINS]))
        if raw_drive_origins:
            self.google_drive_allowed_origins = list(
                dict.fromkeys(
                    value.strip()
                    for value in raw_drive_origins.split(",")
                    if value.strip()
                )
            )
        else:
            self.google_drive_allowed_origins = default_drive_origins

    @property
    def gemini_api_keys(self) -> List[str]:
        raw = [
            os.getenv("GEMINI_API_KEY_1"),
            os.getenv("GEMINI_API_KEY_2"),
            os.getenv("GEMINI_API_KEY"),
        ]
        keys = [value.strip() for value in raw if isinstance(value, str) and value.strip()]
        seen: set[str] = set()
        unique: List[str] = []
        for key in keys:
            if key in seen:
                continue
            seen.add(key)
            unique.append(key)
        return unique

    @property
    def quick_cv_gemini_api_keys(self) -> List[str]:
        raw = [
            os.getenv("QUICK_CV_GEMINI_API_KEY"),
            os.getenv("QUICK_CV_GEMINI_API_KEY_1"),
            os.getenv("QUICK_CV_GEMINI_API_KEY_2"),
        ]
        keys = [value.strip() for value in raw if isinstance(value, str) and value.strip()]
        seen: set[str] = set()
        unique: List[str] = []
        for key in [*keys, *self.gemini_api_keys]:
            if key in seen:
                continue
            seen.add(key)
            unique.append(key)
        return unique

    @property
    def mobile_jd_gemini_api_keys(self) -> List[str]:
        raw = [
            os.getenv("MOBILE_JD_GEMINI_API_KEY"),
        ]
        keys = [value.strip() for value in raw if isinstance(value, str) and value.strip()]
        seen: set[str] = set()
        unique: List[str] = []
        for key in [*keys, *self.gemini_api_keys]:
            if key in seen:
                continue
            seen.add(key)
            unique.append(key)
        return unique

    @property
    def redis_connection_url(self) -> str:
        return self.redis_internal_url or self.redis_url


@lru_cache
def get_settings() -> Settings:
    return Settings()
