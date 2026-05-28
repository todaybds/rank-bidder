"""Unit tests — engine.bid_decision_estimate.decide_by_estimate (2026-05-28).

Naver estimate API 기반 결정 함수 — Naver IP 차단 대응 path.
"""

from __future__ import annotations

from rank_bidder.engine.bid_decision_estimate import decide_by_estimate


def test_estimate_none_returns_skip_stale() -> None:
    """estimate API None → SKIP_STALE (caller PUT skip)."""
    out = decide_by_estimate(estimate_bid=None, target_rank=1, current_bid=5000, bid_cap=10000)
    assert out.decision == "SKIP_STALE"
    assert out.new_bid == 5000
    assert "ESTIMATE_UNAVAILABLE" in out.reason


def test_current_over_cap_returns_cap_clip_down() -> None:
    """운영자 mid-cycle cap 인하 시 current > cap → 즉시 BID_DOWN clip (안전 박제 유지)."""
    out = decide_by_estimate(estimate_bid=3000, target_rank=2, current_bid=8000, bid_cap=5000)
    assert out.decision == "BID_DOWN"
    assert out.new_bid == 5000
    assert "CAP_CLIP_DOWN" in out.reason


def test_estimate_over_cap_and_current_at_cap_returns_cap_reached() -> None:
    """estimate가 cap을 초과 + current가 cap에 도달 → target 도달 불가, CAP_REACHED."""
    out = decide_by_estimate(estimate_bid=20000, target_rank=1, current_bid=10000, bid_cap=10000)
    assert out.decision == "CAP_REACHED"
    assert out.new_bid == 10000
    assert "CAP_REACHED" in out.reason


def test_current_within_deadband_returns_hold() -> None:
    """current ≈ estimate (|gap| < deadband 3%) → HOLD (oscillation 차단)."""
    out = decide_by_estimate(estimate_bid=5100, target_rank=2, current_bid=5000, bid_cap=10000)
    assert out.decision == "HOLD"
    assert out.new_bid == 5000
    assert "HOLD" in out.reason


def test_current_below_estimate_returns_bid_up_step() -> None:
    """current < estimate - deadband → BID_UP 5% 점진."""
    out = decide_by_estimate(estimate_bid=10000, target_rank=1, current_bid=5000, bid_cap=20000)
    assert out.decision == "BID_UP"
    # 5000 * 1.05 = 5250 → round_100 = 5200
    assert out.new_bid == 5200
    assert out.old_bid == 5000


def test_bid_up_candidate_clamped_to_estimate() -> None:
    """5% 인상이 estimate를 넘으면 estimate로 cap."""
    out = decide_by_estimate(estimate_bid=5050, target_rank=2, current_bid=5000, bid_cap=10000)
    # gap = 50/5000 = 1% < deadband 3% → HOLD
    assert out.decision == "HOLD"


def test_bid_up_capped_at_bid_cap() -> None:
    """5% 인상이 cap을 넘으면 cap clip + BID_UP_CAPPED."""
    out = decide_by_estimate(estimate_bid=15000, target_rank=1, current_bid=9800, bid_cap=10000)
    assert out.decision == "BID_UP"
    assert out.new_bid == 10000  # cap clip
    assert "BID_UP_CAPPED" in out.reason


def test_current_above_estimate_returns_bid_down() -> None:
    """current > estimate + deadband → BID_DOWN 5% 점진."""
    out = decide_by_estimate(estimate_bid=3000, target_rank=3, current_bid=5000, bid_cap=10000)
    assert out.decision == "BID_DOWN"
    # 5000 * 0.95 = 4750 → round_100 = 4700
    assert out.new_bid == 4700


def test_bid_down_floored_to_100() -> None:
    """5% 감산이 100원 미만 → 100원 floor + BID_DOWN_FLOORED."""
    out = decide_by_estimate(estimate_bid=50, target_rank=10, current_bid=100, bid_cap=10000)
    assert out.decision == "BID_DOWN"
    assert out.new_bid == 100
    assert "BID_DOWN_FLOORED" in out.reason


def test_bid_down_candidate_clamped_to_estimate() -> None:
    """감산이 estimate 미만으로 가지 않게 floor."""
    out = decide_by_estimate(estimate_bid=4900, target_rank=2, current_bid=5500, bid_cap=10000)
    # gap = -600/5500 = -10.9% > deadband → BID_DOWN
    # 5500*0.95=5225 → round_100=5200, estimate=4900보다 큼 → 5200 채택
    assert out.decision == "BID_DOWN"
    assert out.new_bid == 5200
