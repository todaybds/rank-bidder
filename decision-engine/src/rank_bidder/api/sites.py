"""POST /api/v1/sites/{id}/toggle (Story 2.3) — confirm 2단계."""

from __future__ import annotations

import structlog
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from rank_bidder.db.connection import get_connection, write_transaction
from rank_bidder.db.models import SiteUpdate
from rank_bidder.db.repositories import campaigns as campaigns_repo
from rank_bidder.db.repositories import sites as sites_repo
from rank_bidder.db.version import VersionConflictError

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/v1/sites", tags=["sites"])


class SiteToggleRequest(BaseModel):
    enabled: bool
    if_match_version: int = Field(ge=0)
    confirm: bool = False


class SiteTogglePreview(BaseModel):
    affected_keyword_count: int
    next: str


class SiteToggleApplied(BaseModel):
    id: str
    enabled: bool
    version: int
    affected_keyword_count: int


@router.post("/{site_id}/toggle")
def toggle_site(site_id: str, req: SiteToggleRequest):
    """confirm=false면 affected_keyword_count preview + next 안내. true면 적용."""
    with get_connection() as conn:
        site = sites_repo.get(conn, site_id)
        if site is None:
            raise HTTPException(
                status_code=404,
                detail={"error": {"code": "SITE_NOT_FOUND", "site_id": site_id}},
            )
        affected = campaigns_repo.count_keywords_for_site(conn, site_id)

    # Preview only — UI 확인 단계
    if not req.confirm:
        if affected == 0:
            return {"affected_keyword_count": 0, "result": "no-op"}
        return SiteTogglePreview(
            affected_keyword_count=affected,
            next="send confirm=true to apply",
        )

    # Apply
    try:
        with write_transaction() as conn:
            updated = sites_repo.update(
                conn,
                site_id,
                SiteUpdate(enabled=req.enabled),
                expected_version=req.if_match_version,
            )
    except VersionConflictError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "error": {
                    "code": "VERSION_MISMATCH",
                    "expected_version": req.if_match_version,
                    "current_version": exc.current_version,
                }
            },
        ) from exc

    log.info(
        "sites.toggle.applied",
        site_id=site_id,
        enabled=req.enabled,
        affected=affected,
    )
    return SiteToggleApplied(
        id=updated.id,
        enabled=updated.enabled,
        version=updated.version,
        affected_keyword_count=affected,
    )
