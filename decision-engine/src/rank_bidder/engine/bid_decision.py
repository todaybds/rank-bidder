"""Bid decision engine — pure decision logic (Story 1.8, FR-3+FR-4).

자작 v1 폐기 사유 (b) 재발 방지 — Cap clip 없이 광고비 폭주.
본 모듈은 pure function. DB·API 의존 없음. 호출 측이 결과를 ``decisions.insert``로 persist.

Naver 100원 단위 강제 (V85.55 메모리 — error 3703 회피).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

# Decision 종류 — Story 1.6 decisions.decision CHECK 와 일치.
DecisionType = Literal["BID_UP", "BID_DOWN", "HOLD", "CAP_REACHED", "SKIP_STALE"]

NAVER_BID_UNIT = 100
DEFAULT_STEP_PCT = 0.05


@dataclass(frozen=True)
class DecisionOutcome:
    """결정 결과 — `decisions.insert` payload로 그대로 매핑 가능."""

    decision: DecisionType
    new_bid: int
    old_bid: int
    reason: str


def round_100(x: float) -> int:
    """100원 단위 floor (V85.55: Naver bidAmt는 100원 단위만 허용)."""
    return int(x) // NAVER_BID_UNIT * NAVER_BID_UNIT


def decide(
    *,
    current_rank: int | None,
    target_rank: int,
    current_bid: int,
    bid_cap: int,
    step_pct: float = DEFAULT_STEP_PCT,
) -> DecisionOutcome:
    """Pure 결정 함수 — FR-3 + FR-4.

    Args:
        current_rank: 측정된 현재 순위 (1-base). None이면 측정 실패 → SKIP_STALE.
        target_rank: 목표 순위 [1, 10] (FR-1).
        current_bid: 현재 입찰가 (KRW).
        bid_cap: 상한선 (FR-2, [100, 100_000]).
        step_pct: BID 조정폭 (디폴트 5% — FR-3).

    Returns:
        DecisionOutcome.

    Notes:
        - current == bid_cap AND current > target → CAP_REACHED (BID_UP 불가).
        - BID_UP 결과가 cap 초과 → cap 으로 clip + reason='BID_UP_CAPPED'.
        - BID_DOWN 결과가 100원 미만 → 100원 floor + reason='BID_DOWN_FLOORED'.
    """
    if current_rank is None:
        return DecisionOutcome(
            decision="SKIP_STALE",
            new_bid=current_bid,
            old_bid=current_bid,
            reason="MEASUREMENT_FAILURE",
        )

    if current_rank == target_rank:
        return DecisionOutcome(
            decision="HOLD",
            new_bid=current_bid,
            old_bid=current_bid,
            reason=f"rank {current_rank} == target",
        )

    if current_rank > target_rank:
        # BID_UP 영역
        if current_bid >= bid_cap:
            return DecisionOutcome(
                decision="CAP_REACHED",
                new_bid=current_bid,
                old_bid=current_bid,
                reason=f"CAP_REACHED at {bid_cap} (rank {current_rank} > target {target_rank})",
            )
        candidate = round_100(current_bid * (1 + step_pct))
        if candidate >= bid_cap:
            return DecisionOutcome(
                decision="BID_UP",
                new_bid=round_100(bid_cap),
                old_bid=current_bid,
                reason=f"BID_UP_CAPPED at {bid_cap}",
            )
        return DecisionOutcome(
            decision="BID_UP",
            new_bid=candidate,
            old_bid=current_bid,
            reason=f"rank {current_rank} > target {target_rank}",
        )

    # current_rank < target_rank → BID_DOWN (점진 5%)
    candidate = round_100(current_bid * (1 - step_pct))
    floored = max(candidate, NAVER_BID_UNIT)
    reason = f"rank {current_rank} < target {target_rank}"
    if floored != candidate:
        reason = "BID_DOWN_FLOORED at 100"
    return DecisionOutcome(
        decision="BID_DOWN",
        new_bid=floored,
        old_bid=current_bid,
        reason=reason,
    )
