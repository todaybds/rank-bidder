"""Story 1.6 — measurements repository."""

from __future__ import annotations

from pathlib import Path

import pytest
from rank_bidder.db.connection import get_connection, write_transaction
from rank_bidder.db.models import KeywordCreate, MeasurementCreate, SiteCreate
from rank_bidder.db.repositories import keywords, measurements, sites


@pytest.fixture
def seeded_kw(temp_db: Path) -> str:
    with write_transaction() as conn:
        sites.create(conn, SiteCreate(id="s1", name="Site 1"))
        keywords.create(
            conn,
            KeywordCreate(id="kw1", site_id="s1", term="t", target_rank=1, bid_cap=1000),
        )
    return "kw1"


def test_insert_then_get(seeded_kw: str) -> None:
    with write_transaction() as conn:
        m = measurements.insert(
            conn,
            MeasurementCreate(
                keyword_id=seeded_kw,
                rank_samples=[1, None, 1, 2, 1],
                rank_final=1,
                current_bid=300,
            ),
        )
    assert m.id > 0
    assert m.rank_samples == [1, None, 1, 2, 1]
    assert m.rank_final == 1

    with get_connection() as conn:
        again = measurements.get(conn, m.id)
    assert again is not None
    assert again.rank_samples == [1, None, 1, 2, 1]


def test_latest_for_keyword_returns_most_recent(seeded_kw: str) -> None:
    with write_transaction() as conn:
        measurements.insert(
            conn,
            MeasurementCreate(
                keyword_id=seeded_kw, rank_samples=[3, 3], rank_final=3, current_bid=200
            ),
        )
        latest = measurements.insert(
            conn,
            MeasurementCreate(
                keyword_id=seeded_kw, rank_samples=[2, 2], rank_final=2, current_bid=250
            ),
        )
    with get_connection() as conn:
        got = measurements.latest_for_keyword(conn, seeded_kw)
    assert got is not None
    assert got.id == latest.id
    assert got.rank_final == 2


def test_list_for_keyword_respects_limit(seeded_kw: str) -> None:
    with write_transaction() as conn:
        for i in range(5):
            measurements.insert(
                conn,
                MeasurementCreate(
                    keyword_id=seeded_kw,
                    rank_samples=[i + 1],
                    rank_final=i + 1,
                    current_bid=100 + i * 10,
                ),
            )
    with get_connection() as conn:
        rows = measurements.list_for_keyword(conn, seeded_kw, limit=3)
    assert len(rows) == 3
    # DESC 정렬이라 가장 최근(rank_final=5) 가 첫 행
    assert rows[0].rank_final == 5


def test_empty_rank_samples_rejected() -> None:
    with pytest.raises(ValueError):
        MeasurementCreate(keyword_id="kw1", rank_samples=[], current_bid=100)
