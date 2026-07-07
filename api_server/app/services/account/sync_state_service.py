from __future__ import annotations

import time
import uuid
from typing import Literal

from app.repositories.firestore import account_repository as repo
from app.schemas.account import AuthenticatedUser


SyncSource = Literal["history", "feedback", "template", "cache"]


def touch_user_sync_state(
    user: AuthenticatedUser,
    source: SyncSource,
    *,
    latest_revision: str | None = None,
) -> str:
    revision = latest_revision or f"{source}:{uuid.uuid4().hex[:16]}"
    repo.user_sync_state().document(user.uid).set(
        {
            "uid": user.uid,
            "email": user.email,
            "latestRevision": revision,
            "lastUpdatedAt": int(time.time() * 1000),
            "lastSource": source,
        },
        merge=True,
    )
    return revision
