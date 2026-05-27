"""Story 1.8 — recovery.reconcile_put_sent integration."""

from __future__ import annotations

from pathlib import Path

import pytest
from rank_bidder.db.connection import get_connection, write_transaction
from rank_bidder.db.models import (
    DecisionCreate,
    KeywordCreate,
    SiteCreate,
)
from rank_bidder.db.repositories import cycle_entries, decisions, keywords, sites
from rank_bidder.engine import state_machine
from rank_bidder.engine.recovery import reconcile_put_sent

CYCLE_ID = "c-recovery-1"
KW1 = "kw1"
KW2 = "kw2"


@pytest.fixture
def seeded(temp_db: Path) -> str:
    with write_transaction() as conn:
        sites.create(conn, SiteCreate(id="s1", name="Site 1"))
        for kw_id in (KW1, KW2):
            keywords.create(
                conn,
                KeywordCreate(id=kw_id, site_id="s1", term=kw_id, target_rank=1, bid_cap=5000),
            )
    return KW1


def _seed_put_sent(conn, kw_id: str, new_bid: int) -> None:
    """KW를 PLANNED→MEASURED→DECIDED→PUT_SENT 까지 진행 + decisions row 박제."""
    for s in ("PLANNED", "MEASURED", "DECIDED", "PUT_SENT"):
        state_machine.transition(conn, CYCLE_ID, kw_id, s)
    decisions.insert(
        conn,
        DecisionCreate(
            keyword_id=kw_id,
            cycle_id=CYCLE_ID,
            decision="BID_UP",
            old_bid=1000,
            new_bid=new_bid,
        ),
    )


def test_reconcile_matches_expected_bid_commits(seeded: str) -> None:
    with write_transaction() as conn:
        _seed_put_sent(conn, KW1, new_bid=2000)

    def fake_get(kw_id: str) -> dict:
        return {"bidAmt": 2000, "nccKeywordId": kw_id}

    with write_transaction() as conn:
        summary = reconcile_put_sent(conn, CYCLE_ID, fake_get)
    assert summary == {"scanned": 1, "committed": 1, "failed": 0}

    with get_connection() as conn:
        entry = cycle_entries.get(conn, CYCLE_ID, KW1)
    assert entry is not None and entry.state == "COMMITTED"


def test_reconcile_mismatch_marks_failed(seeded: str) -> None:
    with write_transaction() as conn:
        _seed_put_sent(conn, KW1, new_bid=2000)

    def fake_get(kw_id: str) -> dict:
        return {"bidAmt": 1500}  # mismatch

    with write_transaction() as conn:
        summary = reconcile_put_sent(conn, CYCLE_ID, fake_get)
    assert summary["failed"] == 1
    with get_connection() as conn:
        entry = cycle_entries.get(conn, CYCLE_ID, KW1)
    assert entry is not None and entry.state == "FAILED"


def test_reconcile_get_exception_marks_failed(seeded: str) -> None:
    with write_transaction() as conn:
        _seed_put_sent(conn, KW1, new_bid=2000)

    def fake_get(kw_id: str) -> dict:
        raise RuntimeError("naver down")

    with write_transaction() as conn:
        summary = reconcile_put_sent(conn, CYCLE_ID, fake_get)
    assert summary["failed"] == 1
    with get_connection() as conn:
        entry = cycle_entries.get(conn, CYCLE_ID, KW1)
    assert entry is not None and entry.state == "FAILED"


def test_reconcile_only_scans_put_sent(seeded: str) -> None:
    """다른 state 행은 무시 — cost 0 보장."""
    with write_transaction() as conn:
        # KW1 = PUT_SENT, KW2 = COMMITTED (이미 완료, scan 대상 아님)
        _seed_put_sent(conn, KW1, new_bid=2000)
        for s in ("PLANNED", "MEASURED", "DECIDED", "PUT_SENT", "COMMITTED"):
            state_machine.transition(conn, CYCLE_ID, KW2, s)

    calls = []

    def fake_get(kw_id: str) -> dict:
        calls.append(kw_id)
        return {"bidAmt": 2000}

    with write_transaction() as conn:
        summary = reconcile_put_sent(conn, CYCLE_ID, fake_get)
    assert summary["scanned"] == 1
    assert calls == [KW1]  # KW2는 COMMITTED라 GET 호출 안 함
