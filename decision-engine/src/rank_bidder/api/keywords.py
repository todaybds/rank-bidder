"""POST /api/v1/keywords/{id}/toggle (Story 2.2).

D5 version counter — `if_match_version` mismatch → 409.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from rank_bidder.db.connection import write_transaction
from rank_bidder.db.models import KeywordUpdate
from rank_bidder.db.repositories import keywords
from rank_bidder.db.version import VersionConflictError

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/v1/keywords", tags=["keywords"])


class ToggleRequest(BaseModel):
    enabled: bool
    if_match_version: int = Field(ge=0)


class ToggleResponse(BaseModel):
    id: str
    enabled: bool
    version: int


@router.post("/{keyword_id}/toggle", response_model=ToggleResponse)
def toggle_keyword(keyword_id: str, req: ToggleRequest) -> ToggleResponse:
    """KW enabled 토글. version mismatch → 409 envelope."""
    try:
        with write_transaction() as conn:
            updated = keywords.update(
                conn,
                keyword_id,
                KeywordUpdate(enabled=req.enabled),
                expected_version=req.if_match_version,
            )
    except VersionConflictError as exc:
        log.warning(
            "keywords.toggle.version_mismatch",
            keyword_id=keyword_id,
            expected=req.if_match_version,
            current=exc.current_version,
        )
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
        "keywords.toggle.applied",
        keyword_id=keyword_id,
        enabled=req.enabled,
        new_version=updated.version,
    )
    return ToggleResponse(id=updated.id, enabled=updated.enabled, version=updated.version)
