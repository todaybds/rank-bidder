"""Story 1.7 — state machine transition + final guard tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from rank_bidder.db.connection import get_connection, write_transaction
from rank_bidder.db.models import KeywordCreate, KeywordUpdate, SiteCreate, SiteUpdate
from rank_bidder.db.repositories import cycle_entries, keywords, sites
from rank_bidder.engine import state_machine
from rank_bidder.engine.exceptions import (
    FinalGuardFailedError,
    InvalidTransitionError,
)

CYCLE_ID = "c-test-1"
KW_ID = "kw1"
SITE_ID = "s1"


@pytest.fixture
def seeded(temp_db: Path) -> str:
    with write_transaction() as conn:
        sites.create(conn, SiteCreate(id=SITE_ID, name="Site 1"))
        keywords.create(
            conn,
            KeywordCreate(id=KW_ID, site_id=SITE_ID, term="t", target_rank=1, bid_cap=1000),
        )
    return KW_ID


def _state(cycle_id: str = CYCLE_ID, kw_id: str = KW_ID) -> str | None:
    with get_connection() as conn:
        entry = cycle_entries.get(conn, cycle_id, kw_id)
    return entry.state if entry else None


def test_new_row_must_enter_as_planned(seeded: str) -> None:
    with write_transaction() as conn, pytest.raises(InvalidTransitionError):
        state_machine.transition(conn, CYCLE_ID, seeded, "MEASURED")


def test_happy_path_planned_to_committed(seeded: str) -> None:
    with write_transaction() as conn:
        state_machine.transition(conn, CYCLE_ID, seeded, "PLANNED")
        state_machine.transition(conn, CYCLE_ID, seeded, "MEASURED")
        state_machine.transition(conn, CYCLE_ID, seeded, "DECIDED")
        state_machine.transition(conn, CYCLE_ID, seeded, "PUT_SENT")
        state_machine.transition(conn, CYCLE_ID, seeded, "COMMITTED")
    assert _state() == "COMMITTED"


def test_decided_can_go_committed_directly_hold(seeded: str) -> None:
    """HOLD/SKIP_STALE 결정 시 DECIDED → COMMITTED 직행 (PUT_SENT skip)."""
    with write_transaction() as conn:
        state_machine.transition(conn, CYCLE_ID, seeded, "PLANNED")
        state_machine.transition(conn, CYCLE_ID, seeded, "MEASURED")
        state_machine.transition(conn, CYCLE_ID, seeded, "DECIDED")
        state_machine.transition(conn, CYCLE_ID, seeded, "COMMITTED")
    assert _state() == "COMMITTED"


def test_i1_put_sent_to_measured_invalid(seeded: str) -> None:
    """I1: PUT_SENT 다음은 COMMITTED/FAILED만."""
    with write_transaction() as conn:
        state_machine.transition(conn, CYCLE_ID, seeded, "PLANNED")
        state_machine.transition(conn, CYCLE_ID, seeded, "MEASURED")
        state_machine.transition(conn, CYCLE_ID, seeded, "DECIDED")
        state_machine.transition(conn, CYCLE_ID, seeded, "PUT_SENT")
        with pytest.raises(InvalidTransitionError):
            state_machine.transition(conn, CYCLE_ID, seeded, "MEASURED")


def test_committed_is_terminal(seeded: str) -> None:
    with write_transaction() as conn:
        for s in ("PLANNED", "MEASURED", "DECIDED", "COMMITTED"):
            state_machine.transition(conn, CYCLE_ID, seeded, s)
        with pytest.raises(InvalidTransitionError):
            state_machine.transition(conn, CYCLE_ID, seeded, "PUT_SENT")


def test_failed_is_terminal(seeded: str) -> None:
    with write_transaction() as conn:
        state_machine.transition(conn, CYCLE_ID, seeded, "PLANNED")
        state_machine.transition(conn, CYCLE_ID, seeded, "FAILED")
        with pytest.raises(InvalidTransitionError):
            state_machine.transition(conn, CYCLE_ID, seeded, "MEASURED")


def test_i6_final_guard_blocks_disabled_keyword(seeded: str) -> None:
    """I6: PUT_SENT 진입 직전 keyword.enabled=False → 거절 + state=FAILED."""
    with write_transaction() as conn:
        state_machine.transition(conn, CYCLE_ID, seeded, "PLANNED")
        state_machine.transition(conn, CYCLE_ID, seeded, "MEASURED")
        state_machine.transition(conn, CYCLE_ID, seeded, "DECIDED")
        # cycle 중간에 KW OFF
        kw = keywords.get(conn, seeded)
        assert kw is not None
        keywords.update(conn, seeded, KeywordUpdate(enabled=False), expected_version=kw.version)
        with pytest.raises(FinalGuardFailedError, match="DISABLED_DURING_CYCLE"):
            state_machine.transition(conn, CYCLE_ID, seeded, "PUT_SENT")
    assert _state() == "FAILED"


def test_i6_final_guard_blocks_disabled_site(seeded: str) -> None:
    """I6: site.enabled=False → 거절 + state=FAILED."""
    with write_transaction() as conn:
        state_machine.transition(conn, CYCLE_ID, seeded, "PLANNED")
        state_machine.transition(conn, CYCLE_ID, seeded, "MEASURED")
        state_machine.transition(conn, CYCLE_ID, seeded, "DECIDED")
        s = sites.get(conn, SITE_ID)
        assert s is not None
        sites.update(conn, SITE_ID, SiteUpdate(enabled=False), expected_version=s.version)
        with pytest.raises(FinalGuardFailedError, match="DISABLED_DURING_CYCLE"):
            state_machine.transition(conn, CYCLE_ID, seeded, "PUT_SENT")
    assert _state() == "FAILED"


def test_unknown_state_raises_value_error(seeded: str) -> None:
    with write_transaction() as conn, pytest.raises(ValueError, match="unknown state"):
        state_machine.transition(conn, CYCLE_ID, seeded, "GHOSTSTATE")
