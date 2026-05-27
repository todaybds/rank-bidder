"""Freeze 판정 — staleness > dynamic threshold (Story 1.8, architecture L317-319).

자작 v1 폐기 사유 (a) 재발 방지 — measurement 없이 결정.

공식 (architecture):
    threshold = (cycle_interval_s × 2) + 매체_lag(180s) + buffer(30s)
    5분 cycle → 13.5분 = 810초
    7분 cycle(축소) → 17.5분 = 1050초

measurement 없으면 False (첫 사이클 면제).
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

import structlog

from rank_bidder.db.repositories import measurements

log = structlog.get_logger(__name__)

MEDIA_LAG_SECONDS = 180  # 매체 lag (Naver SERP 노출 ~3분)
BUFFER_SECONDS = 30


def freeze_threshold_seconds(cycle_interval_s: int) -> int:
    """L317-319 공식 그대로."""
    return cycle_interval_s * 2 + MEDIA_LAG_SECONDS + BUFFER_SECONDS


def is_frozen(
    conn: sqlite3.Connection,
    keyword_id: str,
    now: datetime,
    cycle_interval_s: int,
) -> bool:
    """staleness > threshold 면 True.

    Args:
        conn: 읽기 connection.
        keyword_id: 대상 KW.
        now: 기준 시각 (UTC-aware datetime).
        cycle_interval_s: 현재 사이클 간격(초). 5분=300, 7분(축소)=420.

    Returns:
        True면 freeze (decision 측에서 SKIP_STALE 또는 별도 처리).
        measurement 0건이면 첫 사이클이라 False — 측정 자체가 시작 안 됨.
    """
    latest = measurements.latest_for_keyword(conn, keyword_id)
    if latest is None:
        return False  # 첫 사이클 면제

    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    last_at = latest.measured_at
    if last_at.tzinfo is None:
        last_at = last_at.replace(tzinfo=UTC)

    staleness_s = (now - last_at).total_seconds()
    threshold = freeze_threshold_seconds(cycle_interval_s)
    frozen = staleness_s > threshold
    if frozen:
        log.warning(
            "freeze.staleness_exceeded",
            keyword_id=keyword_id,
            staleness_s=round(staleness_s, 1),
            threshold_s=threshold,
            cycle_interval_s=cycle_interval_s,
        )
    return frozen
