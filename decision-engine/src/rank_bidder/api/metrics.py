"""GET /api/v1/metrics/dashboard — Story 4.2 5위젯 단일 endpoint.

위젯별 error isolation: 한 위젯 실패가 endpoint 전체를 500으로 만들지 않음.
각 위젯 query는 ``repositories.metrics``에서 widget-isolated dict 반환.

응답 200 OK + 각 위젯 dict 안에 ``error`` 키가 있으면 프론트가 그 위젯만 "데이터 없음" 표시.
"""

from __future__ import annotations

from datetime import datetime, timezone

import structlog
from fastapi import APIRouter

from rank_bidder.db.connection import get_connection
from rank_bidder.db.repositories import metrics as metrics_repo

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/v1/metrics", tags=["metrics"])

#: KST = UTC+9 — 모든 시각은 KST 변환 후 ISO 문자열로 반환 (AC9).
_KST_OFFSET_HOURS = 9


def _now_kst_iso() -> str:
    """현재 KST 시각 ISO8601 (+09:00 표기)."""
    from datetime import timedelta

    kst = timezone(offset=timedelta(hours=_KST_OFFSET_HOURS))
    return datetime.now(tz=kst).isoformat(timespec="seconds")


@router.get("/dashboard")
def get_dashboard() -> dict:
    """Story 4.2 — 5위젯 데이터 1번 fetch.

    Returns:
        dict — 위젯 5개. 각 위젯 dict가 ``error`` 키 가지면 프론트에서 격리 처리.
        ``generated_at`` 응답 시각 (KST).
    """
    with get_connection() as conn:
        conn.row_factory = _ensure_row_factory(conn)
        widgets = {
            "generated_at": _now_kst_iso(),
            "hit_rate_24h": metrics_repo.hit_rate_24h(conn),
            "current_serp_vs_target": metrics_repo.current_serp_vs_target(conn),
            "system_failures_24h": metrics_repo.system_failures_24h(conn),
            "movers_top5": metrics_repo.movers_top5(conn),
            "spend_cum": metrics_repo.spend_cum(conn),
        }
    return widgets


def _ensure_row_factory(conn):  # type: ignore[no-untyped-def]
    """Row factory가 sqlite3.Row인지 확인 (Decision Engine 표준 — dict-access).

    get_connection은 이미 Row factory를 박제하지만, 명시 가드.
    """
    import sqlite3

    if conn.row_factory is not sqlite3.Row:
        conn.row_factory = sqlite3.Row
    return conn.row_factory
