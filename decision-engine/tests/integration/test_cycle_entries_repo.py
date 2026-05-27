"""Story 1.6 — cycle_entries repository CRUD."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from rank_bidder.db.connection import get_connection, write_transaction
from rank_bidder.db.models import CycleEntryCreate, KeywordCreate, SiteCreate
from rank_bidder.db.repositories import cycle_entries, keywords, sites


@pytest.fixture
def seeded_kw(temp_db: Path) -> str:
    with write_transaction() as conn:
        sites.create(conn, SiteCreate(id="s1", name="Site 1"))
        keywords.create(
            conn,
            KeywordCreate(id="kw1", site_id="s1", term="t", target_rank=1, bid_cap=1000),
        )
    return "kw1"


def test_upsert_insert_then_update_state(seeded_kw: str) -> None:
    with write_transaction() as conn:
        first = cycle_entries.upsert(
            conn, CycleEntryCreate(cycle_id="c1", keyword_id=seeded_kw, state="PLANNED")
        )
    assert first.state == "PLANNED"
    assert isinstance(first.created_at, datetime)

    with write_transaction() as conn:
        second = cycle_entries.upsert(
            conn, CycleEntryCreate(cycle_id="c1", keyword_id=seeded_kw, state="PUT_SENT")
        )
    assert second.state == "PUT_SENT"
    # 같은 PK라 created_at 유지, updated_at만 변경
    assert second.created_at <= second.updated_at


def test_get_returns_none_for_missing(temp_db: Path) -> None:
    with get_connection() as conn:
        assert cycle_entries.get(conn, "no", "such") is None


def test_list_active_filters_planned_and_put_sent(seeded_kw: str) -> None:
    with write_transaction() as conn:
        cycle_entries.upsert(
            conn, CycleEntryCreate(cycle_id="c1", keyword_id=seeded_kw, state="PLANNED")
        )
        # 다른 cycle/kw 추가 — DECIDED는 active 아님
        keywords.create(
            conn,
            KeywordCreate(id="kw2", site_id="s1", term="t2", target_rank=2, bid_cap=2000),
        )
        cycle_entries.upsert(
            conn, CycleEntryCreate(cycle_id="c1", keyword_id="kw2", state="DECIDED")
        )
        cycle_entries.upsert(
            conn, CycleEntryCreate(cycle_id="c2", keyword_id=seeded_kw, state="PUT_SENT")
        )
        cycle_entries.upsert(
            conn, CycleEntryCreate(cycle_id="c0", keyword_id=seeded_kw, state="COMMITTED")
        )

    with get_connection() as conn:
        active = cycle_entries.list_active(conn)
    states = sorted(e.state for e in active)
    # PLANNED + PUT_SENT 만 (DECIDED, COMMITTED 제외)
    assert states == ["PLANNED", "PUT_SENT"]


def test_invalid_state_rejected_at_pydantic(seeded_kw: str) -> None:
    with pytest.raises(ValueError, match=r"state must be in"):
        CycleEntryCreate(cycle_id="c1", keyword_id=seeded_kw, state="UNKNOWN")


def test_db_check_constraint_blocks_invalid_state(seeded_kw: str) -> None:
    """Pydantic 우회 시 DB CHECK 가 잡음 (방어망 2중 검증)."""
    import sqlite3

    with write_transaction() as conn, pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO cycle_entries (cycle_id, keyword_id, state, created_at, updated_at) "
            "VALUES ('c-bad', ?, 'BOGUS', datetime('now'), datetime('now'))",
            (seeded_kw,),
        )
