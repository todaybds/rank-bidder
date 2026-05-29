"""Estimate/avgRnk cycle 통합 테스트 (2026-05-29).

run_cycle_estimate → _process_keyword_estimate 배선 검증. 핵심 보장:
1. 측정 순위가 이미 목표 이상(상위)이면 **절대 BID_UP 안 함** (2026-05-28 과입찰 회귀 방어).
2. 측정 순위가 목표보다 하위면 BID_UP + 실제 PUT.
3. avgRnk 신뢰 불가(impCnt<30) → estimate fallback path.

stats/estimate/put 모두 mock (실제 Naver 호출 없음, 돈 안 씀).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from rank_bidder.db.connection import get_connection, write_transaction
from rank_bidder.db.models import DecisionCreate, KeywordCreate, SiteCreate
from rank_bidder.db.repositories import decisions, keywords, sites
from rank_bidder.jobs import cycle_full

SITE_ID = "s1"
KW_ID = "kw1"
ADG_ID = "grp-a001"
PRIOR_BID = 3300


@pytest.fixture(autouse=True)
def _force_estimate_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """본 파일은 estimate/avgRnk closed-loop 경로 검증 — 모드 명시 고정."""
    monkeypatch.setenv("RANKBIDDER_CYCLE_MODE", "estimate")


def _seed(target_rank: int = 2, bid_cap: int = 10000) -> None:
    """site + KW 1개(target_rank/bid_cap) + 직전 decision(current_bid=PRIOR_BID) 박제."""
    with write_transaction() as conn:
        sites.create(conn, SiteCreate(id=SITE_ID, name="Site 1"))
        keywords.create(
            conn,
            KeywordCreate(
                id=KW_ID,
                site_id=SITE_ID,
                term="브레인시티비스타동원",
                target_rank=target_rank,
                bid_cap=bid_cap,
                adgroup_id=ADG_ID,
            ),
        )
        decisions.insert(
            conn,
            DecisionCreate(
                keyword_id=KW_ID,
                cycle_id="c-prev",
                decision="HOLD",
                old_bid=PRIOR_BID,
                new_bid=PRIOR_BID,
                rank_observed=2,
                reason="seed",
                bid_cap=bid_cap,
            ),
        )


def _last_decision() -> dict:
    with get_connection() as conn:
        r = conn.execute(
            "SELECT decision, old_bid, new_bid, rank_observed, reason "
            "FROM decisions WHERE keyword_id = ? ORDER BY id DESC LIMIT 1",
            (KW_ID,),
        ).fetchone()
    assert r is not None
    return dict(r)


def test_already_winning_never_bids_up(temp_db: Path) -> None:
    """측정 avgRnk=1.0(이미 1위), target=2 → BID_UP 절대 금지 (과입찰 회귀 방어 핵심)."""
    _seed(target_rank=2)
    with (
        patch(
            "rank_bidder.jobs.cycle_full.fetch_today_avg_rank",
            return_value=(1.0, 855),
        ),
        # estimate가 cap 초과 추정가를 줘도(과대평가) avgRnk path가 우선이라 무시돼야 함.
        patch("rank_bidder.jobs.cycle_full.average_position_bid", return_value=15000),
        patch("rank_bidder.jobs.cycle_full.sa_put_bid", new=MagicMock()) as mock_put,
    ):
        cycle_full.run_cycle()

    dec = _last_decision()
    assert dec["decision"] != "BID_UP"  # 이미 목표 이상 → 절대 안 올림
    assert dec["new_bid"] <= PRIOR_BID  # 입찰가 인상 없음
    assert dec["rank_observed"] == 1  # 실측 순위 박제
    assert dec["reason"].startswith("[rank:1.0]")
    # cost-save BID_DOWN이면 PUT 1회, HOLD면 0회 — 둘 다 인상 PUT은 아님.
    if dec["decision"] == "BID_DOWN":
        assert mock_put.call_count == 1
        assert mock_put.call_args.args[1] <= PRIOR_BID


def test_worse_than_target_bids_up_and_puts(temp_db: Path) -> None:
    """측정 avgRnk=5.0(목표보다 하위), target=2 → BID_UP 5% + 실제 PUT."""
    _seed(target_rank=2, bid_cap=10000)
    with (
        patch(
            "rank_bidder.jobs.cycle_full.fetch_today_avg_rank",
            return_value=(5.0, 855),
        ),
        patch("rank_bidder.jobs.cycle_full.average_position_bid", return_value=15000),
        patch("rank_bidder.jobs.cycle_full.sa_put_bid", new=MagicMock()) as mock_put,
    ):
        cycle_full.run_cycle()

    dec = _last_decision()
    assert dec["decision"] == "BID_UP"
    assert dec["new_bid"] == 3400  # 3300*1.05=3465 → round_100=3400
    assert dec["rank_observed"] == 5
    assert dec["reason"].startswith("[rank:5.0]")
    assert mock_put.call_count == 1
    assert mock_put.call_args.args[1] == 3400


def test_low_impressions_falls_back_to_estimate(temp_db: Path) -> None:
    """impCnt<30 → avgRnk 신뢰 불가(None) → estimate fallback path 사용."""
    _seed(target_rank=2, bid_cap=10000)
    with (
        # impCnt 부족 → fetch_today_avg_rank가 (None, imp) 반환
        patch(
            "rank_bidder.jobs.cycle_full.fetch_today_avg_rank",
            return_value=(None, 10),
        ),
        patch("rank_bidder.jobs.cycle_full.average_position_bid", return_value=8000),
        patch("rank_bidder.jobs.cycle_full.sa_put_bid", new=MagicMock()) as mock_put,
    ):
        cycle_full.run_cycle()

    dec = _last_decision()
    assert dec["decision"] == "BID_UP"  # estimate 8000 >> current 3300 → 점진 BID_UP
    assert dec["new_bid"] == 3400
    assert dec["rank_observed"] is None  # estimate path → 실측 순위 없음
    assert "[estimate:8000]" in dec["reason"]
    assert mock_put.call_count == 1
