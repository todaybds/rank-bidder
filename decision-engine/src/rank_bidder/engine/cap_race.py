"""Cap race detector + cap_reached_sustained alert (Story 3.2, D27/FR-23).

evaluate_site — 같은 site_id 에서 1h 윈도우 내 CAP_REACHED KW 2+ → 'cap_race' notifications_log row.
evaluate_keyword_sustained — 단일 KW CAP_REACHED + 1h 지속 → 'cap_reached_sustained' row.

둘 다 24h suppression (suppressed_until = now + 24h, related_ids 내 scope_key 매치로 재발 차단).
실제 이메일 발송은 Epic 6 SMTP — 본 모듈은 row insert만.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta

from rank_bidder.db.models import Keyword
from rank_bidder.db.repositories import keywords as keywords_repo
from rank_bidder.db.repositories import notifications
from rank_bidder.engine.policy_eval import cap_streak_started_at, effective_settings

CAP_RACE_WINDOW = timedelta(hours=1)
SUSTAINED_THRESHOLD = timedelta(hours=1)
SUPPRESSION = timedelta(hours=24)
RACE_EVENT = "cap_race"
SUSTAINED_EVENT = "cap_reached_sustained"


def _sqlite_dt(dt: datetime) -> str:
    """UTC datetime → SQLite ``datetime('now')`` 호환 'YYYY-MM-DD HH:MM:SS' (naive UTC)."""
    if dt.tzinfo is not None:
        dt = dt.astimezone(UTC).replace(tzinfo=None)
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def evaluate_site(
    conn: sqlite3.Connection,
    site_id: str,
    now: datetime,
) -> int | None:
    """같은 site에서 1h 윈도우 내 CAP_REACHED KW 2+ → cap_race row insert (24h suppress).

    Returns:
        새로 insert 된 notifications_log row id. 미발화 (조건 불충족 또는 suppressed) 시 None.
    """
    cutoff = now - CAP_RACE_WINDOW
    cutoff_sqlite = _sqlite_dt(cutoff)
    now_sqlite = _sqlite_dt(now)

    rows = conn.execute(
        """
        SELECT DISTINCT d.keyword_id
        FROM decisions d
        JOIN keywords k ON k.id = d.keyword_id
        WHERE k.site_id = ? AND d.decision = 'CAP_REACHED' AND d.decided_at >= ?
        """,
        (site_id, cutoff_sqlite),
    ).fetchall()
    cap_kw_ids = [r["keyword_id"] for r in rows]
    if len(cap_kw_ids) < 2:
        return None

    if notifications.find_active_suppression(conn, RACE_EVENT, site_id, now_sqlite) is not None:
        return None

    suppressed_until = _sqlite_dt(now + SUPPRESSION)
    n = notifications.insert(
        conn,
        event_type=RACE_EVENT,
        related_ids=[site_id, *sorted(cap_kw_ids)],
        payload={
            "site_id": site_id,
            "keyword_ids": sorted(cap_kw_ids),
            "count": len(cap_kw_ids),
            "window_hours": 1,
        },
        suppressed_until=suppressed_until,
    )
    return n.id


def evaluate_keyword_sustained(
    conn: sqlite3.Connection,
    keyword: Keyword,
    now: datetime,
) -> int | None:
    """단일 KW가 현재 cap regime 에서 CAP_REACHED 를 1h 이상 유지 → cap_reached_sustained insert.

    D17 cap timer reset: cap_streak_started_at 가 효과 cap 변경 시 자동 break.
    """
    eff = effective_settings(conn, keyword, now)
    started_at = cap_streak_started_at(conn, keyword.id, current_cap=eff.bid_cap)
    if started_at is None:
        return None
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=UTC)
    duration = now.astimezone(UTC) - started_at
    if duration < SUSTAINED_THRESHOLD:
        return None

    now_sqlite = _sqlite_dt(now)
    if (
        notifications.find_active_suppression(conn, SUSTAINED_EVENT, keyword.id, now_sqlite)
        is not None
    ):
        return None

    suppressed_until = _sqlite_dt(now + SUPPRESSION)
    n = notifications.insert(
        conn,
        event_type=SUSTAINED_EVENT,
        related_ids=[keyword.id],
        payload={
            "keyword_id": keyword.id,
            "site_id": keyword.site_id,
            "bid_cap": eff.bid_cap,
            "started_at": started_at.isoformat(),
            "duration_seconds": int(duration.total_seconds()),
        },
        suppressed_until=suppressed_until,
    )
    return n.id


def evaluate_all_for_cycle(conn: sqlite3.Connection, now: datetime) -> dict[str, int]:
    """사이클 종료 직전 호출 — enabled KW 전체 + distinct site_id 평가.

    Returns:
        summary {sustained_fired, race_fired, sites_scanned, kws_scanned}.
    """
    summary = {"sustained_fired": 0, "race_fired": 0, "sites_scanned": 0, "kws_scanned": 0}
    enabled = keywords_repo.list_keywords(conn, enabled=True)
    summary["kws_scanned"] = len(enabled)
    for kw in enabled:
        if evaluate_keyword_sustained(conn, kw, now) is not None:
            summary["sustained_fired"] += 1
    sites = sorted({kw.site_id for kw in enabled})
    summary["sites_scanned"] = len(sites)
    for sid in sites:
        if evaluate_site(conn, sid, now) is not None:
            summary["race_fired"] += 1
    return summary
