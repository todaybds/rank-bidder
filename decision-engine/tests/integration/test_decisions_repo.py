"""Story 1.6 — decisions repository."""

from __future__ import annotations

from pathlib import Path

import pytest
from rank_bidder.db.connection import get_connection, write_transaction
from rank_bidder.db.models import DecisionCreate, KeywordCreate, SiteCreate
from rank_bidder.db.repositories import decisions, keywords, sites


@pytest.fixture
def seeded_kw(temp_db: Path) -> str:
    with write_transaction() as conn:
        sites.create(conn, SiteCreate(id="s1", name="Site 1"))
        keywords.create(
            conn,
            KeywordCreate(id="kw1", site_id="s1", term="t", target_rank=2, bid_cap=5000),
        )
    return "kw1"


def test_insert_then_get(seeded_kw: str) -> None:
    with write_transaction() as conn:
        d = decisions.insert(
            conn,
            DecisionCreate(
                keyword_id=seeded_kw,
                cycle_id="c1",
                decision="BID_UP",
                old_bid=300,
                new_bid=350,
                rank_observed=3,
                reason="current 3 > target 2",
            ),
        )
    assert d.id > 0
    assert d.decision == "BID_UP"
    assert d.old_bid == 300
    assert d.new_bid == 350


def test_invalid_decision_rejected_pydantic() -> None:
    with pytest.raises(ValueError, match=r"decision must be in"):
        DecisionCreate(
            keyword_id="kw1",
            cycle_id="c1",
            decision="FOOBAR",
            old_bid=0,
            new_bid=0,
        )


def test_list_for_keyword_orders_desc(seeded_kw: str) -> None:
    with write_transaction() as conn:
        for i, dec in enumerate(["HOLD", "BID_UP", "BID_DOWN"]):
            decisions.insert(
                conn,
                DecisionCreate(
                    keyword_id=seeded_kw,
                    cycle_id=f"c{i}",
                    decision=dec,
                    old_bid=100,
                    new_bid=100 + i,
                ),
            )
    with get_connection() as conn:
        rows = decisions.list_for_keyword(conn, seeded_kw)
    assert len(rows) == 3
    # DESC라 마지막 insert (BID_DOWN) 가 첫 행
    assert rows[0].decision == "BID_DOWN"


def test_list_for_cycle_filters(seeded_kw: str) -> None:
    with write_transaction() as conn:
        # 같은 cycle 2건 + 다른 cycle 1건
        decisions.insert(
            conn,
            DecisionCreate(
                keyword_id=seeded_kw, cycle_id="c1", decision="HOLD", old_bid=100, new_bid=100
            ),
        )
        decisions.insert(
            conn,
            DecisionCreate(
                keyword_id=seeded_kw, cycle_id="c1", decision="BID_UP", old_bid=100, new_bid=110
            ),
        )
        decisions.insert(
            conn,
            DecisionCreate(
                keyword_id=seeded_kw, cycle_id="c2", decision="HOLD", old_bid=110, new_bid=110
            ),
        )
    with get_connection() as conn:
        c1_rows = decisions.list_for_cycle(conn, "c1")
        c2_rows = decisions.list_for_cycle(conn, "c2")
    assert len(c1_rows) == 2
    assert len(c2_rows) == 1


def test_db_check_constraint_blocks_invalid_decision(seeded_kw: str) -> None:
    import sqlite3

    with write_transaction() as conn, pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO decisions (keyword_id, cycle_id, decided_at, decision, old_bid, new_bid) "
            "VALUES (?, 'c-bad', datetime('now'), 'BOGUS', 0, 0)",
            (seeded_kw,),
        )
