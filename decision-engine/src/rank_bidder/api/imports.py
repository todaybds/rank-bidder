"""POST /api/v1/imports — Naver 캠페인 KW 일괄 import (Story 2.1)."""

from __future__ import annotations

import sqlite3

import structlog
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from rank_bidder.db.connection import write_transaction
from rank_bidder.db.models import KeywordCreate
from rank_bidder.db.repositories import keywords, sites
from rank_bidder.naver_sa.campaigns import fetch_campaign_keywords

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/v1", tags=["imports"])

DEFAULT_BID_CAP = 5000
DEFAULT_TARGET_RANK = 1


class ImportRequest(BaseModel):
    campaign_id: str = Field(min_length=1)
    site_id: str = Field(min_length=1)
    target_rank: int = Field(default=DEFAULT_TARGET_RANK, ge=1, le=10)
    bid_cap: int | None = Field(default=None, ge=100, le=100_000)


class ImportError(BaseModel):
    keyword_id: str
    reason: str


class ImportResponse(BaseModel):
    imported: int
    skipped: int
    default_cap_applied: int
    errors: list[ImportError]


@router.post("/imports", response_model=ImportResponse)
def import_campaign_keywords(req: ImportRequest) -> ImportResponse:
    """Naver 캠페인의 ELIGIBLE KW 전체 → keywords 테이블 insert."""
    # site_id 존재 검증 (AC5)
    with write_transaction() as conn:
        site = sites.get(conn, req.site_id)
    if site is None:
        raise HTTPException(
            status_code=400,
            detail={"error": {"code": "SITE_NOT_FOUND", "site_id": req.site_id}},
        )

    # Naver fetch (Story 1.5 client 자동 rate-limit + 백오프)
    try:
        naver_kws = fetch_campaign_keywords(req.campaign_id)
    except Exception as exc:  # noqa: BLE001 — Naver 호출 실패 envelope로 통일
        log.error("imports.naver_fetch_failed", campaign_id=req.campaign_id, error=str(exc))
        raise HTTPException(
            status_code=502,
            detail={"error": {"code": "NAVER_FETCH_FAILED", "message": str(exc)[:200]}},
        ) from exc

    # cap cascade: (1) 명령 → (3) 전역 5000원
    # site 기본값(2)은 sites 테이블에 컬럼 없음 — v2 영역
    effective_cap = req.bid_cap if req.bid_cap is not None else DEFAULT_BID_CAP
    default_cap_applied_count = 0
    imported = 0
    skipped = 0
    errors: list[ImportError] = []

    with write_transaction() as conn:
        for kw in naver_kws:
            kw_id = kw.get("nccKeywordId")
            term = kw.get("keyword")
            if not kw_id or not term:
                continue
            # AC2 — 이미 등록되어 있으면 skip
            existing = keywords.get(conn, kw_id)
            if existing is not None:
                skipped += 1
                continue
            try:
                keywords.create(
                    conn,
                    KeywordCreate(
                        id=kw_id,
                        site_id=req.site_id,
                        term=term,
                        target_rank=req.target_rank,
                        bid_cap=effective_cap,
                        adgroup_id=kw.get("nccAdgroupId"),
                    ),
                )
                imported += 1
                if req.bid_cap is None:
                    default_cap_applied_count += 1
            except sqlite3.IntegrityError as exc:
                errors.append(ImportError(keyword_id=kw_id, reason=f"IntegrityError: {exc}"))
            except Exception as exc:  # noqa: BLE001 — KW 단위 격리 (Epic 1 패턴)
                errors.append(ImportError(keyword_id=kw_id, reason=str(exc)[:200]))

    log.info(
        "imports.completed",
        campaign_id=req.campaign_id,
        imported=imported,
        skipped=skipped,
        default_cap_applied=default_cap_applied_count,
        errors=len(errors),
    )
    return ImportResponse(
        imported=imported,
        skipped=skipped,
        default_cap_applied=default_cap_applied_count,
        errors=errors,
    )
