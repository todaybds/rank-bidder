"""KW endpoints — Story 2.2 toggle + 2026-05-28 LIST (보라웨어 톤 대시보드 지원).

- `GET /api/v1/keywords` — 리스트 (필터: enabled, site_id, q). 각 KW의 현재 bid +
  목표 순위 + 최근 결정 정보 함께. 대시보드 메인 테이블 fetch.
- `POST /api/v1/keywords/{id}/toggle` — enabled 토글 (Story 2.2).

D5 version counter — `if_match_version` mismatch → 409.
"""

from __future__ import annotations

import re

import structlog
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from rank_bidder.db.connection import get_connection, write_transaction
from rank_bidder.db.models import KeywordUpdate
from rank_bidder.db.repositories import keywords
from rank_bidder.db.version import VersionConflictError

#: decisions.reason에서 estimate 추정가 추출. 두 패턴 모두 매칭:
#: - "[estimate:18830] BID_UP toward estimate 18830 (gap +21.9%)"
#: - "CAP_REACHED at 10000 (estimate 26820 > cap, ...)"
_ESTIMATE_RE = re.compile(r"estimate[:\s]+(\d+)")


def _extract_estimate_from_reason(reason: str | None) -> int | None:
    """결정 사유에서 Naver estimate 추정가 정수 추출. 없으면 None."""
    if not reason:
        return None
    m = _ESTIMATE_RE.search(reason)
    if m:
        try:
            return int(m.group(1))
        except (ValueError, IndexError):
            return None
    return None


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
        ORDER BY d.id DESC LIMIT 1) AS last_reason,
      (SELECT d.decided_at FROM decisions d
        WHERE d.keyword_id = k.id AND d.decision IN ('BID_UP','BID_DOWN')
        ORDER BY d.id DESC LIMIT 1) AS last_put_at,
      (SELECT d.old_bid FROM decisions d
        WHERE d.keyword_id = k.id AND d.decision IN ('BID_UP','BID_DOWN')
        ORDER BY d.id DESC LIMIT 1) AS previous_bid,
      (SELECT m.rank_final FROM measurements m
        WHERE m.keyword_id = k.id
        ORDER BY m.id DESC LIMIT 1) AS rank_observed
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
            "previous_bid": r["previous_bid"],
            "last_decision": r["last_decision"],
            "last_decision_at": r["last_decision_at"],
            "last_reason": r["last_reason"],
            "last_put_at": r["last_put_at"],
            "rank_observed": r["rank_observed"],
            "recommended_cap": _extract_estimate_from_reason(r["last_reason"]),
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


class KeywordPatchRequest(BaseModel):
    """개별 편집 — 부분 업데이트. None이면 보존."""

    target_rank: int | None = Field(default=None, ge=1, le=10)
    bid_cap: int | None = Field(default=None, ge=100, le=100000)
    enabled: bool | None = None
    if_match_version: int = Field(ge=0)


class KeywordPatchResponse(BaseModel):
    id: str
    target_rank: int
    bid_cap: int
    enabled: bool
    version: int


@router.patch("/{keyword_id}", response_model=KeywordPatchResponse)
def patch_keyword(keyword_id: str, req: KeywordPatchRequest) -> KeywordPatchResponse:
    """KW 부분 업데이트 — target_rank/bid_cap/enabled. D5 version mismatch → 409."""
    payload = KeywordUpdate(
        target_rank=req.target_rank,
        bid_cap=req.bid_cap,
        enabled=req.enabled,
    )
    try:
        with write_transaction() as conn:
            updated = keywords.update(
                conn,
                keyword_id,
                payload,
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
        "keywords.patch.applied",
        keyword_id=keyword_id,
        target_rank=req.target_rank,
        bid_cap=req.bid_cap,
        enabled=req.enabled,
        new_version=updated.version,
    )
    return KeywordPatchResponse(
        id=updated.id,
        target_rank=updated.target_rank,
        bid_cap=updated.bid_cap,
        enabled=updated.enabled,
        version=updated.version,
    )


class BulkUpdateRequest(BaseModel):
    """선택 KW 일괄 편집 — version 검증 없음 (보라웨어 패턴: 일괄은 force update).

    field=None → 해당 필드 변경 안 함. 최소 1개 필드 필수.
    """

    keyword_ids: list[str] = Field(min_length=1, max_length=500)
    target_rank: int | None = Field(default=None, ge=1, le=10)
    bid_cap: int | None = Field(default=None, ge=100, le=100000)
    enabled: bool | None = None


class BulkUpdateResponse(BaseModel):
    updated: int
    failed: list[dict]


@router.post("/bulk-update", response_model=BulkUpdateResponse)
def bulk_update(req: BulkUpdateRequest) -> BulkUpdateResponse:
    """선택 KW 일괄 편집 — 각 KW 개별 transaction (1건 실패가 전체 안 막음).

    version mismatch는 force overwrite (보라웨어 일괄 변경 패턴 = 운영자 의도 우선).
    """
    if req.target_rank is None and req.bid_cap is None and req.enabled is None:
        raise HTTPException(
            status_code=400,
            detail={
                "error": {
                    "code": "NO_FIELDS",
                    "message": "최소 1개 필드 (target_rank/bid_cap/enabled)",
                },
            },
        )

    payload = KeywordUpdate(
        target_rank=req.target_rank,
        bid_cap=req.bid_cap,
        enabled=req.enabled,
    )
    updated = 0
    failed: list[dict] = []
    for kw_id in req.keyword_ids:
        try:
            with write_transaction() as conn:
                # current version 가져와서 그걸로 expected — force update.
                current = keywords.get(conn, kw_id)
                if current is None:
                    failed.append({"id": kw_id, "error": "NOT_FOUND"})
                    continue
                keywords.update(conn, kw_id, payload, expected_version=current.version)
                updated += 1
        except Exception as exc:  # noqa: BLE001 — KW 단위 격리
            log.warning("keywords.bulk.kw_failed", keyword_id=kw_id, error=str(exc))
            failed.append({"id": kw_id, "error": str(exc)[:120]})

    log.info(
        "keywords.bulk.applied",
        total=len(req.keyword_ids),
        updated=updated,
        failed=len(failed),
        target_rank=req.target_rank,
        bid_cap=req.bid_cap,
        enabled=req.enabled,
    )
    return BulkUpdateResponse(updated=updated, failed=failed)


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
