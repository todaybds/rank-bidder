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
    """100원 단위 floor, 최소 NAVER_BID_UNIT 보장 (V85.55: Naver bidAmt는 100원 단위 + 최저 100원).

    2026-05-27 code-review CRITICAL C3 fix: 입력 x < 100 시 0 산출 / 음수 입력 시 더 negative
    floor 산출하는 Python floor-div semantic이 BID_UP 경로에서 NaverInvalidRequest(3703) 또는
    영구 0 loop 유발. 안전망 = 최소 100원 floor + 음수는 ValueError.
    """
    if x < 0:
        raise ValueError(f"round_100 input must be non-negative, got {x}")
    floored = int(x) // NAVER_BID_UNIT * NAVER_BID_UNIT
    return max(NAVER_BID_UNIT, floored)


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

    # 2026-05-27 code-review CRITICAL C5 fix: cap mid-cycle 인하 시 current_bid > bid_cap이면
    # 5% 감산만으론 over-cap 유지 (3-4 사이클 동안 운영자 인하 의도 무시 = 의도 안 한 광고비).
    # HOLD/CAP_REACHED 어느 분기든 진입 전에 즉시 cap clip-down.
    effective_cap = round_100(bid_cap)
    if current_bid > effective_cap:
        return DecisionOutcome(
            decision="BID_DOWN",
            new_bid=effective_cap,
            old_bid=current_bid,
            reason=f"CAP_CLIP_DOWN ({current_bid} > cap {bid_cap} → {effective_cap})",
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
        if current_bid >= effective_cap:
            return DecisionOutcome(
                decision="CAP_REACHED",
                new_bid=current_bid,
                old_bid=current_bid,
                reason=f"CAP_REACHED at {effective_cap} (rank {current_rank} > target {target_rank})",
            )
        candidate = round_100(current_bid * (1 + step_pct))
        if candidate >= effective_cap:
            # CRITICAL C4 fix: reason은 실제 effective_cap 표시 (이전엔 bid_cap 원본 입력만 표시 →
            # 5050 같은 non-100-multiple 입력 시 실제 송신 5000과 reason 5050 불일치).
            return DecisionOutcome(
                decision="BID_UP",
                new_bid=effective_cap,
                old_bid=current_bid,
                reason=f"BID_UP_CAPPED at {effective_cap} (cap input {bid_cap})",
            )
        return DecisionOutcome(
            decision="BID_UP",
            new_bid=candidate,
            old_bid=current_bid,
            reason=f"rank {current_rank} > target {target_rank}",
        )

    # current_rank < target_rank → BID_DOWN (점진 5%)
    candidate = round_100(current_bid * (1 - step_pct))
    reason = f"rank {current_rank} < target {target_rank}"
    if candidate == NAVER_BID_UNIT and int(current_bid * (1 - step_pct)) < NAVER_BID_UNIT:
        reason = "BID_DOWN_FLOORED at 100"
    return DecisionOutcome(
        decision="BID_DOWN",
        new_bid=candidate,
        old_bid=current_bid,
        reason=reason,
    )
