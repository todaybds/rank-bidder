"""metrics repository — Story 4.2 dashboard 5위젯 집계 쿼리 (read-only).

각 함수는 widget-isolated dict 반환:
- 성공: 정상 데이터 dict (위젯별 schema)
- 실패: ``{"error": {"code": "...", "message": "..."}}`` (caller가 endpoint 응답에 그대로 포함)

caller(api/metrics.py)는 각 함수를 try/except로 감싸지 않고도 안전한 widget-isolation 가능.
SQL은 모두 SELECT (write_transaction 사용 안 함) → 동시성 안전, GIL/PID 격리 무관.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

import structlog

log = structlog.get_logger(__name__)


def _safe(fn_name: str, fn):  # type: ignore[no-untyped-def]
    """위젯 함수 호출 wrapper — Exception 시 widget-isolated error dict 반환."""
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001 — widget isolation 핵심
        log.warning("metrics.widget_failed", widget=fn_name, error=str(exc))
        return {"error": {"code": "WIDGET_QUERY_FAILED", "message": str(exc)[:200]}}


# ---------- Widget 1: 24h 적중률 ----------


def hit_rate_24h(conn: sqlite3.Connection) -> dict[str, Any]:
    """전체 + 사이트별 24h 적중률.

    적중 = ``decisions.rank_observed == keywords.target_rank`` (사이클 단위).
    ``rank_observed IS NULL`` (SKIP_STALE 등) 행은 분모에서 제외.
    """

    def _query() -> dict[str, Any]:
        overall = conn.execute(
            """
            SELECT
              SUM(CASE WHEN d.rank_observed = k.target_rank THEN 1 ELSE 0 END) AS hit,
              SUM(CASE WHEN d.rank_observed != k.target_rank THEN 1 ELSE 0 END) AS miss
            FROM decisions d
            JOIN keywords k ON k.id = d.keyword_id
            WHERE d.decided_at >= datetime('now', '-1 day')
              AND d.rank_observed IS NOT NULL
            """
        ).fetchone()
        hit = (overall["hit"] or 0) if overall else 0
        miss = (overall["miss"] or 0) if overall else 0
        total = hit + miss
        rate_pct = round(hit * 100.0 / total, 1) if total else 0.0

        by_site_rows = conn.execute(
            """
            SELECT
              k.site_id AS site_id,
              COALESCE(s.name, k.site_id) AS site_name,
              SUM(CASE WHEN d.rank_observed = k.target_rank THEN 1 ELSE 0 END) AS hit,
              SUM(CASE WHEN d.rank_observed != k.target_rank THEN 1 ELSE 0 END) AS miss
            FROM decisions d
            JOIN keywords k ON k.id = d.keyword_id
            LEFT JOIN sites s ON s.id = k.site_id
            WHERE d.decided_at >= datetime('now', '-1 day')
              AND d.rank_observed IS NOT NULL
            GROUP BY k.site_id, s.name
            ORDER BY k.site_id
            """
        ).fetchall()
        by_site = []
        for r in by_site_rows:
            h, m = r["hit"] or 0, r["miss"] or 0
            t = h + m
            by_site.append(
                {
                    "site_id": r["site_id"],
                    "site_name": r["site_name"],
                    "hit": h,
                    "miss": m,
                    "rate_pct": round(h * 100.0 / t, 1) if t else 0.0,
                }
            )

        return {
            "overall": {"hit": hit, "miss": miss, "rate_pct": rate_pct},
            "by_site": by_site,
            "window": "24h",
        }

    return _safe("hit_rate_24h", _query)


# ---------- Widget 2: 현재 SERP vs 목표 ----------


def current_serp_vs_target(conn: sqlite3.Connection) -> list[dict[str, Any]] | dict[str, Any]:
    """enabled KW 전수의 최근 측정 vs target_rank + delta + outlier 플래그.

    ``outlier = abs(delta) >= 3 OR rank_observed IS NULL`` (운영자 시선 우선 강조).
    """

    def _query() -> list[dict[str, Any]]:
        rows = conn.execute(
            """
            SELECT
              k.id AS keyword_id,
              k.term AS term,
              k.target_rank AS target_rank,
              k.site_id AS site_id,
              (SELECT m.rank_final FROM measurements m
                 WHERE m.keyword_id = k.id
                 ORDER BY m.id DESC LIMIT 1) AS rank_observed,
              (SELECT m.measured_at FROM measurements m
                 WHERE m.keyword_id = k.id
                 ORDER BY m.id DESC LIMIT 1) AS measured_at
            FROM keywords k
            WHERE k.enabled = 1
            ORDER BY k.site_id, k.term
            """
        ).fetchall()
        out = []
        for r in rows:
            rank = r["rank_observed"]
            target = r["target_rank"]
            delta = (rank - target) if rank is not None else None
            outlier = (rank is None) or (delta is not None and abs(delta) >= 3)
            out.append(
                {
                    "keyword_id": r["keyword_id"],
                    "term": r["term"],
                    "site_id": r["site_id"],
                    "target_rank": target,
                    "rank_observed": rank,
                    "delta": delta,
                    "outlier": bool(outlier),
                    "measured_at": r["measured_at"],
                }
            )
        return out

    return _safe("current_serp_vs_target", _query)


# ---------- Widget 3: 시스템 장애 24h ----------


def system_failures_24h(conn: sqlite3.Connection) -> list[dict[str, Any]] | dict[str, Any]:
    """notifications_log 최근 24h, 시각 역순 최대 20건."""

    def _query() -> list[dict[str, Any]]:
        rows = conn.execute(
            """
            SELECT id, created_at, event_type, related_ids, payload
            FROM notifications_log
            WHERE created_at >= datetime('now', '-1 day')
            ORDER BY created_at DESC
            LIMIT 20
            """
        ).fetchall()
        out = []
        for r in rows:
            try:
                related = json.loads(r["related_ids"]) if r["related_ids"] else []
            except (json.JSONDecodeError, TypeError):
                related = []
            try:
                payload = json.loads(r["payload"]) if r["payload"] else {}
            except (json.JSONDecodeError, TypeError):
                payload = {}
            # summary 한 줄 — payload에 있으면 우선, 없으면 event_type + count
            summary = (
                payload.get("summary")
                or payload.get("message")
                or f"{r['event_type']} (count={len(related)})"
            )
            out.append(
                {
                    "id": r["id"],
                    "at": r["created_at"],
                    "event_type": r["event_type"],
                    "summary": str(summary)[:200],
                    "related_ids": related[:10],  # 너무 많으면 잘라냄
                }
            )
        return out

    return _safe("system_failures_24h", _query)


# ---------- Widget 4: 변동 Top 5 KW ----------


def movers_top5(conn: sqlite3.Connection) -> list[dict[str, Any]] | dict[str, Any]:
    """최근 24h BID_UP/BID_DOWN 중 변동률 절댓값 Top 5. KW 단위 dedup."""

    def _query() -> list[dict[str, Any]]:
        # KW별 최대 변동률 1건만, 그 중 전체 Top 5.
        # SQLite 3.25+ window function 사용 가능.
        rows = conn.execute(
            """
            WITH ranked AS (
              SELECT
                d.keyword_id,
                k.term,
                k.site_id,
                d.decision,
                d.old_bid,
                d.new_bid,
                d.decided_at,
                ROUND(ABS(d.new_bid - d.old_bid) * 100.0 / d.old_bid, 2) AS delta_pct,
                ROW_NUMBER() OVER (
                  PARTITION BY d.keyword_id
                  ORDER BY ABS(d.new_bid - d.old_bid) * 100.0 / d.old_bid DESC
                ) AS rn
              FROM decisions d
              JOIN keywords k ON k.id = d.keyword_id
              WHERE d.decided_at >= datetime('now', '-1 day')
                AND d.decision IN ('BID_UP', 'BID_DOWN')
                AND d.old_bid > 0
            )
            SELECT keyword_id, term, site_id, decision, old_bid, new_bid, delta_pct, decided_at
            FROM ranked
            WHERE rn = 1
            ORDER BY delta_pct DESC
            LIMIT 5
            """
        ).fetchall()
        return [
            {
                "keyword_id": r["keyword_id"],
                "term": r["term"],
                "site_id": r["site_id"],
                "decision": r["decision"],
                "old_bid": r["old_bid"],
                "new_bid": r["new_bid"],
                "delta_pct": r["delta_pct"],
                "decided_at": r["decided_at"],
            }
            for r in rows
        ]

    return _safe("movers_top5", _query)


# ---------- Widget 5: 광고비 누적 ----------


def spend_cum(conn: sqlite3.Connection) -> dict[str, Any]:
    """Story 4.4 spend_daily 의존. 테이블 없으면 ``available=false``."""

    def _query() -> dict[str, Any]:
        # spend_daily 테이블 존재 확인
        exists = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='spend_daily'"
        ).fetchone()
        if not exists:
            return {
                "available": False,
                "today_krw": None,
                "month_krw": None,
                "by_site": [],
                "note": "Story 4.4 미완 — spend_daily 테이블 없음 (수집 대기)",
            }
        # 4.4 완료 후 활성 (현 시점 도달 안 함)
        today = conn.execute(
            "SELECT SUM(spend_amount) FROM spend_daily WHERE date = date('now', 'localtime')"
        ).fetchone()
        month = conn.execute(
            "SELECT SUM(spend_amount) FROM spend_daily "
            "WHERE date >= date('now', 'start of month', 'localtime')"
        ).fetchone()
        by_site = conn.execute(
            """
            SELECT
              sp.site_id,
              COALESCE(s.name, sp.site_id) AS site_name,
              SUM(CASE WHEN sp.date = date('now','localtime') THEN sp.spend_amount ELSE 0 END) AS today_krw,
              SUM(CASE WHEN sp.date >= date('now','start of month','localtime') THEN sp.spend_amount ELSE 0 END) AS month_krw
            FROM spend_daily sp
            LEFT JOIN sites s ON s.id = sp.site_id
            WHERE sp.site_id IS NOT NULL
            GROUP BY sp.site_id, s.name
            ORDER BY month_krw DESC
            """
        ).fetchall()
        return {
            "available": True,
            "today_krw": (today[0] if today else 0) or 0,
            "month_krw": (month[0] if month else 0) or 0,
            "by_site": [
                {
                    "site_id": r["site_id"],
                    "site_name": r["site_name"],
                    "today_krw": r["today_krw"] or 0,
                    "month_krw": r["month_krw"] or 0,
                }
                for r in by_site
            ],
        }

    return _safe("spend_cum", _query)
