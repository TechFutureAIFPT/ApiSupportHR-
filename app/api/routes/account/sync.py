from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_current_user
from app.schemas.account import AnalysisRunDataRequest, AuthenticatedUser, CacheSyncRequest
from app.services.account import cache_service, history_service


router = APIRouter()


@router.post("/sync/cache")
def sync_cache_entry(payload: CacheSyncRequest, current_user: AuthenticatedUser = Depends(get_current_user)):
    cache_service.sync_cache_entry(
        current_user,
        cache_key=payload.cacheKey,
        candidate_data=payload.candidateData,
        jd_hash=payload.jdHash,
        weights_hash=payload.weightsHash,
        filters_hash=payload.filtersHash,
        file_info=payload.fileInfo.model_dump(),
    )
    return {"ok": True}


@router.get("/sync/cache/{cache_key}")
def get_cache_entry(cache_key: str, current_user: AuthenticatedUser = Depends(get_current_user)):
    return cache_service.get_cache_entry(current_user, cache_key)


@router.get("/sync/cache")
def get_all_cache_entries(current_user: AuthenticatedUser = Depends(get_current_user)):
    return cache_service.get_all_user_cache(current_user)


@router.delete("/sync/cache")
def clear_all_cache_entries(current_user: AuthenticatedUser = Depends(get_current_user)):
    cache_service.clear_user_cache(current_user)
    return {"ok": True}


@router.post("/sync/history")
def sync_history_entry(payload: AnalysisRunDataRequest, current_user: AuthenticatedUser = Depends(get_current_user)):
    return {"id": history_service.sync_history_entry(current_user, payload.model_dump())}


@router.get("/sync/history")
def get_synced_history(
    limit_count: int = Query(default=20, ge=1, le=200),
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    return history_service.get_synced_history(current_user, limit_count=limit_count)


@router.get("/sync/stats")
def get_sync_stats(current_user: AuthenticatedUser = Depends(get_current_user)):
    return history_service.get_sync_stats(current_user)
