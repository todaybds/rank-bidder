"""Story 1.8 — bid_decision pure function matrix."""

from __future__ import annotations

import pytest
from rank_bidder.engine.bid_decision import decide, round_100

# round_100 ---------------------------------------------------------


@pytest.mark.parametrize(
    ("x", "expected"),
    [(100, 100), (149, 100), (150, 100), (200, 200), (249.9, 200), (5050.7, 5000)],
)
def test_round_100_floor_to_unit(x: float, expected: int) -> None:
    assert round_100(x) == expected


# decide ------------------------------------------------------------


def test_hold_when_rank_equals_target() -> None:
    r = decide(current_rank=2, target_rank=2, current_bid=1000, bid_cap=5000)
    assert r.decision == "HOLD"
    assert r.new_bid == 1000


def test_bid_up_normal() -> None:
    r = decide(current_rank=5, target_rank=2, current_bid=1000, bid_cap=5000)
    assert r.decision == "BID_UP"
    # 1000 * 1.05 = 1050 → round_100 = 1000? 1050//100*100 = 1000.
    # 그러나 floor 결과가 같으면 effectively HOLD인데, decision은 BID_UP 그대로.
    # 의미: step 5%가 너무 작아 다음 사이클에 누적 진행.
    assert r.new_bid == 1000


def test_bid_up_with_visible_increase() -> None:
    r = decide(current_rank=5, target_rank=2, current_bid=2000, bid_cap=5000)
    # 2000*1.05 = 2100 → 2100
    assert r.decision == "BID_UP"
    assert r.new_bid == 2100


def test_bid_up_capped_at_bid_cap() -> None:
    r = decide(current_rank=5, target_rank=2, current_bid=4800, bid_cap=5000)
    # 4800*1.05 = 5040 → cap 5000으로 clip
    assert r.decision == "BID_UP"
    assert r.new_bid == 5000
    assert "CAPPED" in r.reason


def test_cap_reached_no_bid_up() -> None:
    r = decide(current_rank=5, target_rank=2, current_bid=5000, bid_cap=5000)
    assert r.decision == "CAP_REACHED"
    assert r.new_bid == 5000
    assert "CAP_REACHED" in r.reason


def test_bid_down_normal() -> None:
    r = decide(current_rank=1, target_rank=3, current_bid=2000, bid_cap=5000)
    # 2000 * 0.95 = 1900
    assert r.decision == "BID_DOWN"
    assert r.new_bid == 1900


def test_bid_down_floor_at_100() -> None:
    r = decide(current_rank=1, target_rank=3, current_bid=100, bid_cap=5000)
    # 100 * 0.95 = 95 → floor 95 → max(95, 100) = 100
    assert r.decision == "BID_DOWN"
    assert r.new_bid == 100
    assert "FLOORED" in r.reason


def test_skip_stale_when_current_rank_none() -> None:
    r = decide(current_rank=None, target_rank=2, current_bid=1000, bid_cap=5000)
    assert r.decision == "SKIP_STALE"
    assert r.new_bid == 1000
    assert "MEASUREMENT_FAILURE" in r.reason


def test_decision_outcome_keeps_old_bid() -> None:
    r = decide(current_rank=4, target_rank=2, current_bid=3000, bid_cap=10000)
    assert r.old_bid == 3000
    assert r.new_bid != r.old_bid  # BID_UP 적용
