"""KW endpoints — Story 2.2 toggle + 2026-05-28 LIST (보라웨어 톤 대시보드 지원).

- `GET /api/v1/keywords` — 리스트 (필터: enabled, site_id, q). 각 KW의 현재 bid +
  목표 순위 + 최근 결정 정보 함께. 대시보드 메인 테이블 fetch.
- `POST /api/v1/keywords/{id}/toggle` — enabled 토글 (Story 2.2).

D5 version counter — `if_match_version` mismatch → 409.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from rank_bidder.db.connection import get_connection, write_transaction
from rank_bidder.db.models import KeywordUpdate
from rank_bidder.db.repositories import keywords
from rank_bidder.db.version import VersionConflictError

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/v1/keywords", tags=["keywords"])


@router.get("")
def list_keywords(
    enabled: bool | None = Query(default=None, description="None=all, true/false 필터"),
    site_id: str | None = Query(default=None),
    q: str | None = Query(default=None, description="키워드 term 부분 검색"),
    limit: int = Query(default=200, ge=1, le=1000),
) -> dict:
    """KW 리스트 + 현재 bid + 목표 + 최근 결정 (보라웨어 톤 메인 테이블 fetch).

    Returns:
        ``{"items": [...], "count": int}``
        items 각 row:
          ``{id, term, site_id, target_rank, bid_cap, enabled, version,
              current_bid, last_decision, last_decision_at, last_reason}``
        - current_bid: 마지막 decision.new_bid (없으면 None)
        - last_decision: BID_UP/DOWN/HOLD/CAP_REACHED/SKIP_STALE
    """
    sql = """
    SELECT
      k.id, k.term, k.site_id, k.target_rank, k.bid_cap, k.enabled, k.version,
      (SELECT d.new_bid FROM decisions d WHERE d.keyword_id = k.id
        ORDER BY d.id DESC LIMIT 1) AS current_bid,
      (SELECT d.decision FROM decisions d WHERE d.keyword_id = k.id
        ORDER BY d.id DESC LIMIT 1) AS last_decision,
      (SELECT d.decided_at FROM decisions d WHERE d.keyword_id = k.id
        ORDER BY d.id DESC LIMIT 1) AS last_decision_at,
      (SELECT d.reason FROM decisions d WHERE d.keyword_id = k.id
        ORDER BY d.id DESC LIMIT 1) AS last_reason
    FROM keywords k
    WHERE 1=1
    """
    params: list = []
    if enabled is not None:
        sql += " AND k.enabled = ?"
        params.append(1 if enabled else 0)
    if site_id is not None:
        sql += " AND k.site_id = ?"
        params.append(site_id)
    if q is not None:
        sql += " AND k.term LIKE ?"
        params.append(f"%{q}%")
    sql += " ORDER BY k.enabled DESC, k.bid_cap DESC, k.term LIMIT ?"
    params.append(limit)

    with get_connection() as conn:
        rows = conn.execute(sql, params).fetchall()

    items = [
        {
            "id": r["id"],
            "term": r["term"],
            "site_id": r["site_id"],
            "target_rank": r["target_rank"],
            "bid_cap": r["bid_cap"],
            "enabled": bool(r["enabled"]),
            "version": r["version"],
            "current_bid": r["current_bid"],
            "last_decision": r["last_decision"],
            "last_decision_at": r["last_decision_at"],
            "last_reason": r["last_reason"],
        }
        for r in rows
    ]
    return {"items": items, "count": len(items)}


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
