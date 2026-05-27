"""Story 1.8 — freeze.is_frozen integration."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from rank_bidder.db.connection import get_connection, write_transaction
from rank_bidder.db.models import KeywordCreate, MeasurementCreate, SiteCreate
from rank_bidder.db.repositories import keywords, measurements, sites
from rank_bidder.engine.freeze import freeze_threshold_seconds, is_frozen

KW_ID = "kw1"


@pytest.fixture
def seeded(temp_db: Path) -> str:
    with write_transaction() as conn:
        sites.create(conn, SiteCreate(id="s1", name="Site 1"))
        keywords.create(
            conn,
            KeywordCreate(id=KW_ID, site_id="s1", term="t", target_rank=1, bid_cap=1000),
        )
    return KW_ID


def test_freeze_formula() -> None:
    # 5분 사이클 → 300*2 + 180 + 30 = 810초
    assert freeze_threshold_seconds(300) == 810
    # 7분(축소) → 420*2 + 180 + 30 = 1050초
    assert freeze_threshold_seconds(420) == 1050


def test_no_measurement_returns_false(seeded: str) -> None:
    """첫 사이클 면제."""
    with get_connection() as conn:
        assert is_frozen(conn, seeded, datetime.now(UTC), cycle_interval_s=300) is False


def test_recent_measurement_not_frozen(seeded: str) -> None:
    with write_transaction() as conn:
        measurements.insert(
            conn,
            MeasurementCreate(keyword_id=seeded, rank_samples=[1], rank_final=1, current_bid=100),
        )
    # 잠시 후 (1초 미만) 조회 — 800초 안이라 not frozen
    with get_connection() as conn:
        assert is_frozen(conn, seeded, datetime.now(UTC), cycle_interval_s=300) is False


def test_stale_measurement_frozen(seeded: str) -> None:
    """staleness > 810초 (5분 사이클 임계) → True. now를 future로 simulate."""
    with write_transaction() as conn:
        measurements.insert(
            conn,
            MeasurementCreate(keyword_id=seeded, rank_samples=[1], rank_final=1, current_bid=100),
        )
    # 1시간 미래 simulation
    future = datetime.now(UTC) + timedelta(hours=1)
    with get_connection() as conn:
        assert is_frozen(conn, seeded, future, cycle_interval_s=300) is True


def test_threshold_extends_with_cycle_interval(seeded: str) -> None:
    """7분 사이클(축소)에선 임계 1050초로 늘어남 — 13분 staleness는 아직 not frozen."""
    with write_transaction() as conn:
        measurements.insert(
            conn,
            MeasurementCreate(keyword_id=seeded, rank_samples=[1], rank_final=1, current_bid=100),
        )
    # 13분 (= 780초) 미래 → 5분 사이클(810)에선 not frozen 경계, 7분(1050)엔 확실히 not frozen
    thirteen_min = datetime.now(UTC) + timedelta(minutes=13)
    with get_connection() as conn:
        assert is_frozen(conn, seeded, thirteen_min, cycle_interval_s=420) is False
