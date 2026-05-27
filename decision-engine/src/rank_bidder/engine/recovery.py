"""Recovery — state=PUT_SENT 행만 GET bidAmt reconcile (Story 1.8, D15 (c)).

Story 1.3 측정 결과: PUT 200 즉시 반영. 정상 사이클은 reconcile cost 0 — PUT_SENT 잔존은
오직 응답 누락(타임아웃·5xx·process restart) 케이스. 본 모듈은 그 누락 행만 처리.

sa_client_get은 caller가 주입 — Story 1.9에서 production naver_sa wrapper, 본 모듈은 의존 격리.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable

import structlog

from rank_bidder.db.repositories import cycle_entries, decisions
from rank_bidder.engine import state_machine

log = structlog.get_logger(__name__)


def reconcile_put_sent(
    conn: sqlite3.Connection,
    cycle_id: str,
    sa_client_get: Callable[[str], dict],
) -> dict[str, int]:
    """state=PUT_SENT 행만 조회 → 각 KW에 sa_client_get 호출 → COMMITTED 또는 FAILED 전이.

    Args:
        conn: write_transaction() — state 변경 mutation 포함.
        cycle_id: 대상 사이클.
        sa_client_get: ``(keyword_id) -> {bidAmt: int, ...}`` 함수. 예외 raise 시 FAILED.

    Returns:
        ``{committed: N, failed: N, scanned: N}`` 요약 dict.
    """
    summary = {"committed": 0, "failed": 0, "scanned": 0}
    rows = [e for e in cycle_entries.list_by_cycle(conn, cycle_id) if e.state == "PUT_SENT"]
    summary["scanned"] = len(rows)

    for entry in rows:
        # 예상 new_bid 조회 — 같은 cycle_id 의 가장 최근 decision row.
        kw_decisions = decisions.list_for_cycle(conn, cycle_id)
        expected_bid: int | None = next(
            (d.new_bid for d in reversed(kw_decisions) if d.keyword_id == entry.keyword_id),
            None,
        )
        try:
            response = sa_client_get(entry.keyword_id)
            actual_bid = int(response.get("bidAmt", -1))
        except Exception as exc:  # noqa: BLE001 — 어떤 예외든 FAILED 로
            log.warning(
                "recovery.get_failed",
                cycle_id=cycle_id,
                keyword_id=entry.keyword_id,
                error=str(exc),
            )
            state_machine.transition(conn, cycle_id, entry.keyword_id, "FAILED")
            summary["failed"] += 1
            continue

        if expected_bid is None or actual_bid == expected_bid:
            state_machine.transition(conn, cycle_id, entry.keyword_id, "COMMITTED")
            summary["committed"] += 1
            log.info(
                "recovery.committed",
                cycle_id=cycle_id,
                keyword_id=entry.keyword_id,
                actual_bid=actual_bid,
                expected_bid=expected_bid,
            )
        else:
            state_machine.transition(conn, cycle_id, entry.keyword_id, "FAILED")
            summary["failed"] += 1
            log.warning(
                "recovery.mismatch",
                cycle_id=cycle_id,
                keyword_id=entry.keyword_id,
                actual_bid=actual_bid,
                expected_bid=expected_bid,
            )

    return summary
