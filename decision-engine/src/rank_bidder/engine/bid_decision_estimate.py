"""Estimate-driven bid decision (2026-05-28).

SERP 스크래핑이 Naver IP 차단으로 막힌 상황 대안. Naver 공식 ``/estimate/
average-position-bid/keyword`` API로 "target_rank 도달에 필요한 추정 bid"를 받고,
현재 bid와 비교해서 BID_UP/DOWN/HOLD 결정. SERP rank 측정 불필요.

특성:
- ✅ Naver 공식 API라 차단 무관 (광고비 0)
- ✅ 결정 안정성 — 통계 기반 estimate (실시간 SERP 변동 흡수 안 함)
- ⚠️ 실시간 rank 모니터링 불가 (대시보드 위젯 2 "SERP vs 목표"는 의미 잃음)
- ⚠️ Naver estimate API 자체가 None 반환 시 SKIP_STALE 처리

기존 ``bid_decision.decide`` 안전 박제 그대로 유지:
- ``round_100`` 100원 단위 floor + 음수 ValueError
- ``effective_cap = round_100(bid_cap)`` cap 정규화
- ``current_bid > effective_cap`` → 즉시 BID_DOWN cap clip
- ``current_bid >= effective_cap`` AND BID_UP 영역 → CAP_REACHED
- ``BID_UP`` 결과 over-cap → cap clip + BID_UP_CAPPED
- ``BID_DOWN`` floor → 100원 + BID_DOWN_FLOORED
"""

from __future__ import annotations

from rank_bidder.engine.bid_decision import (
    DEFAULT_STEP_PCT,
    NAVER_BID_UNIT,
    DecisionOutcome,
    round_100,
)


def decide_by_estimate(
    *,
    estimate_bid: int | None,
    target_rank: int,
    current_bid: int,
    bid_cap: int,
    step_pct: float = DEFAULT_STEP_PCT,
    deadband_pct: float = 0.03,
) -> DecisionOutcome:
    """Pure 결정 함수 — estimate API 응답 기반.

    Args:
        estimate_bid: Naver estimate API 응답 (target_rank 도달 추정가). None이면 SKIP_STALE.
        target_rank: 목표 순위 [1, 10] — 로그/reason 표시용.
        current_bid: 현재 입찰가 (KRW, ≥ 0).
        bid_cap: 상한선 (FR-2).
        step_pct: BID 점진 조정폭 (디폴트 5%). estimate에 한 번에 맞추지 않고 점진 — 안전.
        deadband_pct: HOLD 영역 (디폴트 3%). |gap_pct| < deadband → HOLD (oscillation 차단).

    Returns:
        DecisionOutcome.

    Notes:
        - estimate_bid > bid_cap AND current_bid >= cap → CAP_REACHED (target 도달 불가).
        - current_bid > effective_cap → 즉시 BID_DOWN clip (운영자 cap 인하 즉시 반영).
        - estimate API None → SKIP_STALE (caller가 PUT skip).
    """
    # 1. cap clip-down — 운영자 mid-cycle cap 인하 즉시 반영.
    effective_cap = round_100(bid_cap)
    if current_bid > effective_cap:
        return DecisionOutcome(
            decision="BID_DOWN",
            new_bid=effective_cap,
            old_bid=current_bid,
            reason=f"CAP_CLIP_DOWN ({current_bid} > cap {bid_cap} → {effective_cap})",
        )

    # 2. estimate API 응답 부재 → SKIP_STALE.
    if estimate_bid is None:
        return DecisionOutcome(
            decision="SKIP_STALE",
            new_bid=current_bid,
            old_bid=current_bid,
            reason="ESTIMATE_UNAVAILABLE (target_rank unreachable or API None)",
        )

    # 3. estimate API가 cap을 초과하는 bid 권고 → target 도달 불가 (CAP_REACHED).
    if estimate_bid > effective_cap and current_bid >= effective_cap:
        return DecisionOutcome(
            decision="CAP_REACHED",
            new_bid=current_bid,
            old_bid=current_bid,
            reason=(
                f"CAP_REACHED at {effective_cap} "
                f"(estimate {estimate_bid} > cap, target_rank {target_rank} unreachable)"
            ),
        )

    # 4. estimate vs current 비교 — deadband 안이면 HOLD.
    # current_bid 0 방어 (이론상 발생 안 하지만 안전 가드).
    base = max(current_bid, NAVER_BID_UNIT)
    gap = estimate_bid - current_bid
    gap_pct = gap / base

    if abs(gap_pct) < deadband_pct:
        return DecisionOutcome(
            decision="HOLD",
            new_bid=current_bid,
            old_bid=current_bid,
            reason=(
                f"HOLD (current {current_bid} ≈ estimate {estimate_bid}, "
                f"gap {gap_pct * 100:.1f}% < deadband {deadband_pct * 100:.1f}%)"
            ),
        )

    if gap > 0:
        # current < estimate → BID_UP towards estimate, 5% 점진.
        if current_bid >= effective_cap:
            return DecisionOutcome(
                decision="CAP_REACHED",
                new_bid=current_bid,
                old_bid=current_bid,
                reason=f"CAP_REACHED at {effective_cap} (estimate {estimate_bid} > current)",
            )
        candidate = round_100(current_bid * (1 + step_pct))
        # estimate 자체를 초과하지 않게 cap
        if candidate > estimate_bid:
            candidate = round_100(estimate_bid)
        if candidate >= effective_cap:
            return DecisionOutcome(
                decision="BID_UP",
                new_bid=effective_cap,
                old_bid=current_bid,
                reason=f"BID_UP_CAPPED at {effective_cap} (estimate {estimate_bid}, cap input {bid_cap})",
            )
        return DecisionOutcome(
            decision="BID_UP",
            new_bid=candidate,
            old_bid=current_bid,
            reason=f"BID_UP toward estimate {estimate_bid} (gap +{gap_pct * 100:.1f}%)",
        )

    # gap < 0 → current > estimate → BID_DOWN, 5% 점진.
    candidate = round_100(current_bid * (1 - step_pct))
    # estimate 미만으로 가지 않게 floor
    if candidate < estimate_bid:
        candidate = round_100(estimate_bid)
    reason = f"BID_DOWN toward estimate {estimate_bid} (gap {gap_pct * 100:.1f}%)"
    if candidate == NAVER_BID_UNIT and int(current_bid * (1 - step_pct)) < NAVER_BID_UNIT:
        reason = "BID_DOWN_FLOORED at 100"
    return DecisionOutcome(
        decision="BID_DOWN",
        new_bid=candidate,
        old_bid=current_bid,
        reason=reason,
    )
