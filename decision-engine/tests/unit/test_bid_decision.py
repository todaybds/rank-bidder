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
    # 2026-05-28 BID_UP_NOOP fix: 1000*1.05=1050 → round_100=1000 → NOOP → +100원 강제.
    # 사용자 발견 ("일부만 작동"): 100원/1000원 같은 작은 bid가 매 cycle 헛돌던 silent bug.
    # 이제 최소 NAVER_BID_UNIT(100원)씩 인상 보장.
    assert r.new_bid == 1100


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


# 2026-05-27 code-review CRITICAL fixes ----------------------------


def test_round_100_negative_raises() -> None:
    """CRITICAL C3: 음수 입력은 silently 더 negative 결과 → ValueError로 차단."""
    with pytest.raises(ValueError, match="non-negative"):
        round_100(-50)


def test_round_100_below_min_floors_to_100() -> None:
    """CRITICAL C3: x < NAVER_BID_UNIT → 100원 floor (이전엔 0 산출 + BID_UP 경로에서 3703 유발)."""
    assert round_100(50) == 100
    assert round_100(99.99) == 100
    assert round_100(0) == 100


def test_over_cap_clip_down_immediate() -> None:
    """CRITICAL C5: cap 인하 후 current_bid > bid_cap이면 즉시 cap으로 clip-down.
    이전엔 5% 감산만 → 3-4 사이클 동안 over-cap 유지 = 운영자 인하 의도 무시."""
    r = decide(current_rank=2, target_rank=2, current_bid=6000, bid_cap=5000)
    assert r.decision == "BID_DOWN"
    assert r.new_bid == 5000
    assert "CAP_CLIP_DOWN" in r.reason


def test_over_cap_clip_down_even_when_rank_under_target() -> None:
    """rank < target이어도 over-cap이면 BID_DOWN 5% 감산이 아니라 즉시 cap clip-down."""
    r = decide(current_rank=1, target_rank=3, current_bid=6000, bid_cap=5000)
    assert r.decision == "BID_DOWN"
    assert r.new_bid == 5000  # 6000 * 0.95 = 5700 (여전히 over-cap)이 아니라 5000으로 즉시


def test_bid_up_capped_reason_shows_effective_cap() -> None:
    """CRITICAL C4: reason에 round_100(bid_cap) effective_cap 표시 — 5050 같은 non-100-multiple 입력
    시 실제 송신값과 reason 불일치 차단."""
    r = decide(current_rank=5, target_rank=2, current_bid=4900, bid_cap=5050)
    assert r.decision == "BID_UP"
    assert r.new_bid == 5000  # round_100(5050) = 5000
    assert "5000" in r.reason  # effective_cap
    assert "5050" in r.reason  # 원본 입력 추적
