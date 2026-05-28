"""Story 4.2 — metrics repository 5위젯 query 함수 unit tests.

`temp_db` fixture로 임시 SQLite 박제. write_transaction으로 seed → 5 함수 호출 검증.
widget-isolated error 패턴 (예외 시 dict + error 키)도 검증.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from rank_bidder.db.connection import get_connection, write_transaction
from rank_bidder.db.models import (
    DecisionCreate,
    KeywordCreate,
    MeasurementCreate,
    SiteCreate,
)
from rank_bidder.db.repositories import (
    decisions,
    keywords,
    measurements,
    metrics,
    notifications,
    sites,
)


@pytest.fixture
def seeded_db(temp_db: Path) -> Path:
    """사이트 1 + KW 3 + 측정 + decisions 박제 (24h 안)."""
    with write_transaction() as conn:
        sites.create(conn, SiteCreate(id="s1", name="Site 1"))
        keywords.create(
            conn,
            KeywordCreate(id="kw-A", site_id="s1", term="키워드A", target_rank=1, bid_cap=10000),
        )
        keywords.create(
            conn,
            KeywordCreate(id="kw-B", site_id="s1", term="키워드B", target_rank=2, bid_cap=5000),
        )
        keywords.create(
            conn,
            KeywordCreate(id="kw-C", site_id="s1", term="키워드C", target_rank=3, bid_cap=3000),
        )
        # 측정 박제
        measurements.insert(
            conn,
            MeasurementCreate(
                keyword_id="kw-A", rank_samples=[1, 1, 1], rank_final=1, current_bid=3000
            ),
        )
        measurements.insert(
            conn,
            MeasurementCreate(
                keyword_id="kw-B", rank_samples=[5, 5, 5], rank_final=5, current_bid=2000
            ),
        )
        # kw-C 측정 실패 (rank_final=None)
        measurements.insert(
            conn,
            MeasurementCreate(
                keyword_id="kw-C",
                rank_samples=[None, None, None],
                rank_final=None,
                current_bid=1000,
            ),
        )
        # decisions 박제 — kw-A 적중, kw-B 빗나감, kw-C SKIP_STALE
        decisions.insert(
            conn,
            DecisionCreate(
                keyword_id="kw-A",
                cycle_id="c1",
                decision="HOLD",
                old_bid=3000,
                new_bid=3000,
                rank_observed=1,  # target=1 → 적중
                reason="target hit",
                bid_cap=10000,
            ),
        )
        decisions.insert(
            conn,
            DecisionCreate(
                keyword_id="kw-B",
                cycle_id="c1",
                decision="BID_UP",
                old_bid=1000,
                new_bid=1500,
                rank_observed=5,  # target=2 → 빗나감
                reason="below target",
                bid_cap=5000,
            ),
        )
        decisions.insert(
            conn,
            DecisionCreate(
                keyword_id="kw-C",
                cycle_id="c1",
                decision="SKIP_STALE",
                old_bid=500,
                new_bid=500,
                rank_observed=None,  # SKIP_STALE → 분모 제외
                reason="measurement_failed",
                bid_cap=3000,
            ),
        )
    return temp_db


# ---------- Widget 1: hit_rate_24h ----------


def test_hit_rate_24h_basic(seeded_db: Path) -> None:
    with get_connection() as conn:
        result = metrics.hit_rate_24h(conn)
    assert "error" not in result
    overall = result["overall"]
    # kw-A 적중 1 + kw-B 빗나감 1, kw-C는 분모 제외 (rank_observed IS NULL)
    assert overall["hit"] == 1
    assert overall["miss"] == 1
    assert overall["rate_pct"] == 50.0
    # 사이트별 분포
    by_site = result["by_site"]
    assert len(by_site) == 1
    assert by_site[0]["site_id"] == "s1"
    assert by_site[0]["rate_pct"] == 50.0


def test_hit_rate_24h_empty_db(temp_db: Path) -> None:
    """데이터 없을 때 rate_pct=0.0, by_site=[]."""
    with get_connection() as conn:
        result = metrics.hit_rate_24h(conn)
    assert "error" not in result
    assert result["overall"]["rate_pct"] == 0.0
    assert result["by_site"] == []


# ---------- Widget 2: current_serp_vs_target ----------


def test_current_serp_vs_target_includes_all_enabled_with_outlier_flag(seeded_db: Path) -> None:
    with get_connection() as conn:
        result = metrics.current_serp_vs_target(conn)
    assert isinstance(result, list)
    assert len(result) == 3  # enabled KW 3개
    by_id = {r["keyword_id"]: r for r in result}
    # kw-A: rank=1, target=1, delta=0, outlier=False
    assert by_id["kw-A"]["delta"] == 0
    assert by_id["kw-A"]["outlier"] is False
    # kw-B: rank=5, target=2, delta=3, outlier=True (|delta|>=3)
    assert by_id["kw-B"]["delta"] == 3
    assert by_id["kw-B"]["outlier"] is True
    # kw-C: rank=None, outlier=True (측정 실패)
    assert by_id["kw-C"]["rank_observed"] is None
    assert by_id["kw-C"]["outlier"] is True


# ---------- Widget 3: system_failures_24h ----------


def test_system_failures_24h_returns_recent_events(seeded_db: Path) -> None:
    # 장애 박제
    with write_transaction() as conn:
        notifications.insert(
            conn,
            event_type="naver_keyword_deleted",
            related_ids=["kw-X", "kw-Y"],
            payload={"summary": "2 KWs auto-OFF due to 404"},
        )
    with get_connection() as conn:
        result = metrics.system_failures_24h(conn)
    assert isinstance(result, list)
    assert len(result) == 1
    assert result[0]["event_type"] == "naver_keyword_deleted"
    assert result[0]["related_ids"] == ["kw-X", "kw-Y"]
    assert "2 KWs auto-OFF" in result[0]["summary"]


def test_system_failures_24h_empty(seeded_db: Path) -> None:
    with get_connection() as conn:
        result = metrics.system_failures_24h(conn)
    assert result == []


# ---------- Widget 4: movers_top5 ----------


def test_movers_top5_dedups_by_keyword_and_sorts_by_delta_pct(seeded_db: Path) -> None:
    """같은 KW 여러 변동이면 최대 변동률 1건만, 전체 Top 5."""
    with get_connection() as conn:
        result = metrics.movers_top5(conn)
    assert isinstance(result, list)
    # seeded_db에선 kw-B만 BID_UP/BID_DOWN — 1건
    assert len(result) == 1
    assert result[0]["keyword_id"] == "kw-B"
    assert result[0]["delta_pct"] == 50.0  # 1000→1500 = +50%


def test_movers_top5_empty_when_no_bid_changes(temp_db: Path) -> None:
    with get_connection() as conn:
        result = metrics.movers_top5(conn)
    assert result == []


# ---------- Widget 5: spend_cum ----------


def test_spend_cum_returns_available_true_with_zero_when_no_data(temp_db: Path) -> None:
    """Story 4.4 완료 후 — spend_daily 테이블 존재 + 데이터 0 → available=true + 0원."""
    with get_connection() as conn:
        result = metrics.spend_cum(conn)
    assert result["available"] is True
    assert result["today_krw"] == 0
    assert result["month_krw"] == 0
    assert result["by_site"] == []


# ---------- Widget-isolated error pattern ----------


def test_widget_isolated_error_returns_error_dict_not_raise(temp_db: Path) -> None:
    """repository 함수는 예외 시 dict + error 키 반환 — endpoint 전체를 500으로 만들지 않음."""
    # 일부러 connection 닫아서 exception 유도
    import sqlite3

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.close()
    result = metrics.hit_rate_24h(conn)
    assert "error" in result
    assert result["error"]["code"] == "WIDGET_QUERY_FAILED"
