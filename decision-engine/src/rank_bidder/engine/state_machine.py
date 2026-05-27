"""State machine — cycle_entries 전이 enforcement (Story 1.7, I1·I6).

Transition map:
    PLANNED   → MEASURED, FAILED
    MEASURED  → DECIDED, FAILED
    DECIDED   → PUT_SENT, COMMITTED, FAILED      (HOLD/SKIP 결정 시 DECIDED → COMMITTED 직행)
    PUT_SENT  → COMMITTED, FAILED                (I1: 그 외 불가)
    COMMITTED → (terminal)
    FAILED    → (terminal)

PUT_SENT 직전 final guard (I6): site.enabled AND keyword.enabled 재확인 — false면 거절.
"""

from __future__ import annotations

import sqlite3

import structlog

from rank_bidder.db.models import CycleEntryCreate
from rank_bidder.db.repositories import cycle_entries, keywords, sites
from rank_bidder.engine.exceptions import (
    FinalGuardFailedError,
    InvalidTransitionError,
)

log = structlog.get_logger(__name__)

#: 허용된 전이 — frozenset 값 비교로 빠른 검증.
TRANSITIONS: dict[str, frozenset[str]] = {
    "PLANNED": frozenset({"MEASURED", "FAILED"}),
    "MEASURED": frozenset({"DECIDED", "FAILED"}),
    "DECIDED": frozenset({"PUT_SENT", "COMMITTED", "FAILED"}),
    "PUT_SENT": frozenset({"COMMITTED", "FAILED"}),  # I1
    "COMMITTED": frozenset(),  # terminal
    "FAILED": frozenset(),  # terminal
}

ALL_STATES: frozenset[str] = frozenset(TRANSITIONS) | {"PLANNED"}


def _ensure_valid(from_state: str, to_state: str, cycle_id: str, keyword_id: str) -> None:
    """전이 합법성 검증. 위반 시 InvalidTransitionError + structlog 기록."""
    allowed = TRANSITIONS.get(from_state, frozenset())
    if to_state not in allowed:
        log.warning(
            "state_machine.invalid_transition",
            cycle_id=cycle_id,
            keyword_id=keyword_id,
            from_state=from_state,
            to_state=to_state,
            allowed=sorted(allowed),
        )
        raise InvalidTransitionError(cycle_id, keyword_id, from_state, to_state)


def _final_guard(conn: sqlite3.Connection, cycle_id: str, keyword_id: str) -> None:
    """I6: PUT_SENT 직전 site.enabled AND keyword.enabled 재확인.

    실패 시:
    1. cycle_entries.upsert(state=FAILED) 자동 (호출자가 reason은 decisions 테이블에 별도 기록)
    2. FinalGuardFailedError raise — 호출자가 잡아서 D15 cycle 진행 종료
    """
    kw = keywords.get(conn, keyword_id)
    if kw is None:
        cycle_entries.upsert(
            conn, CycleEntryCreate(cycle_id=cycle_id, keyword_id=keyword_id, state="FAILED")
        )
        raise FinalGuardFailedError(cycle_id, keyword_id, reason="KEYWORD_DELETED")
    if not kw.enabled:
        cycle_entries.upsert(
            conn, CycleEntryCreate(cycle_id=cycle_id, keyword_id=keyword_id, state="FAILED")
        )
        raise FinalGuardFailedError(cycle_id, keyword_id, reason="DISABLED_DURING_CYCLE")
    site = sites.get(conn, kw.site_id)
    if site is None:
        cycle_entries.upsert(
            conn, CycleEntryCreate(cycle_id=cycle_id, keyword_id=keyword_id, state="FAILED")
        )
        raise FinalGuardFailedError(cycle_id, keyword_id, reason="SITE_DELETED")
    if not site.enabled:
        cycle_entries.upsert(
            conn, CycleEntryCreate(cycle_id=cycle_id, keyword_id=keyword_id, state="FAILED")
        )
        raise FinalGuardFailedError(cycle_id, keyword_id, reason="DISABLED_DURING_CYCLE")


def transition(
    conn: sqlite3.Connection,
    cycle_id: str,
    keyword_id: str,
    to_state: str,
) -> None:
    """Cycle entry state 전이 — 합법성 + final guard 검증 후 upsert.

    Args:
        conn: write_transaction() 안에서 호출 권장 (mutation).
        cycle_id, keyword_id: cycle_entries PK.
        to_state: 목표 state (6값 중 하나).

    Raises:
        InvalidTransitionError: 정의 안 된 전이 시도.
        FinalGuardFailedError: target=PUT_SENT인데 site/keyword 비활성화. (state는 FAILED로 자동 갱신)
        ValueError: to_state가 ALL_STATES 외.
    """
    if to_state not in ALL_STATES:
        raise ValueError(f"unknown state {to_state!r}; must be in {sorted(ALL_STATES)}")

    existing = cycle_entries.get(conn, cycle_id, keyword_id)
    from_state = existing.state if existing is not None else "PLANNED"

    # 신규 row면 PLANNED로 진입 — 그 외엔 from_state 기반 합법성 검증.
    if existing is None:
        if to_state != "PLANNED":
            raise InvalidTransitionError(cycle_id, keyword_id, "(new)", to_state)
    else:
        _ensure_valid(from_state, to_state, cycle_id, keyword_id)

    # I6 final guard — PUT_SENT 진입 시에만.
    if to_state == "PUT_SENT":
        _final_guard(conn, cycle_id, keyword_id)

    cycle_entries.upsert(
        conn, CycleEntryCreate(cycle_id=cycle_id, keyword_id=keyword_id, state=to_state)
    )
    log.info(
        "state_machine.transition",
        cycle_id=cycle_id,
        keyword_id=keyword_id,
        from_state=from_state,
        to_state=to_state,
    )
