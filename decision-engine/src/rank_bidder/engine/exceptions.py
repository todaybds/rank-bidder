"""Engine 예외 계층 (Story 1.7)."""

from __future__ import annotations


class EngineError(Exception):
    """Engine 모든 예외 베이스."""


class InvalidTransitionError(EngineError):
    """정의되지 않은 state machine 전이 시도 — I1 등 invariants 위반."""

    def __init__(self, cycle_id: str, keyword_id: str, from_state: str, to_state: str) -> None:
        super().__init__(
            f"Invalid transition for ({cycle_id}, {keyword_id}): {from_state} → {to_state}"
        )
        self.cycle_id = cycle_id
        self.keyword_id = keyword_id
        self.from_state = from_state
        self.to_state = to_state


class FinalGuardFailedError(EngineError):
    """PUT_SENT 직전 final guard 실패 — site 또는 keyword가 cycle 중간에 비활성화됨 (I6)."""

    def __init__(self, cycle_id: str, keyword_id: str, reason: str) -> None:
        super().__init__(f"Final guard failed for ({cycle_id}, {keyword_id}): {reason}")
        self.cycle_id = cycle_id
        self.keyword_id = keyword_id
        self.reason = reason
