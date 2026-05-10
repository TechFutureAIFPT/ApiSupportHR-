from __future__ import annotations

import os
from functools import lru_cache
from typing import List

from dotenv import load_dotenv


load_dotenv()


class Settings:
    def __init__(self) -> None:
        self.app_name = os.getenv("APP_NAME", "SupportHR Backend")
        self.frontend_origin = os.getenv("FRONTEND_ORIGIN", "http://localhost:3000")
        self.gemini_default_model = os.getenv("GEMINI_MODEL", "gemini-flash-latest")
        self.gemini_embedding_model = os.getenv("GEMINI_EMBEDDING_MODEL", "text-embedding-004")

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


@lru_cache
def get_settings() -> Settings:
    return Settings()
