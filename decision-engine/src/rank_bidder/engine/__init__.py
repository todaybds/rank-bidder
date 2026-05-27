"""Decision engine — state machine + cycle_id + bid decision + freeze + recovery.

- Story 1.7: state_machine, cycle_id (monotonic UUID v7), exceptions
- Story 1.8: bid_decision, freeze, recovery
"""

from rank_bidder.engine.bid_decision import DecisionOutcome, decide, round_100
from rank_bidder.engine.cycle_id import new_cycle_id
from rank_bidder.engine.exceptions import (
    EngineError,
    FinalGuardFailedError,
    InvalidTransitionError,
)
from rank_bidder.engine.freeze import freeze_threshold_seconds, is_frozen
from rank_bidder.engine.policy_eval import (
    EffectiveSettings,
    active_policy,
    cap_streak_started_at,
    effective_settings,
    minute_of_week_kst,
)
from rank_bidder.engine.recovery import reconcile_put_sent
from rank_bidder.engine.state_machine import ALL_STATES, TRANSITIONS, transition

__all__ = [
    "ALL_STATES",
    "DecisionOutcome",
    "EffectiveSettings",
    "EngineError",
    "FinalGuardFailedError",
    "InvalidTransitionError",
    "TRANSITIONS",
    "active_policy",
    "cap_streak_started_at",
    "decide",
    "effective_settings",
    "freeze_threshold_seconds",
    "is_frozen",
    "minute_of_week_kst",
    "new_cycle_id",
    "reconcile_put_sent",
    "round_100",
    "transition",
]
