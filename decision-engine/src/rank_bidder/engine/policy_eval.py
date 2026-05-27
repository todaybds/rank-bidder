"""Multi-time policy evaluator — Story 3.1, FR-7.

활성 정책 lookup + KW/site fallback chain + KST minute_of_week 계산.
D17 transition (Cap timer reset on policy transition) 은 본 모듈이 직접 다루지 않는다 —
호출자(cycle_full)가 직전 cycle의 effective bid_cap과 비교해서 결정.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone

from rank_bidder.db.models import MINUTES_PER_WEEK, Keyword, Policy
from rank_bidder.db.repositories import policies as policies_repo

KST = timezone(timedelta(hours=9))


@dataclass(frozen=True)
class EffectiveSettings:
    """현재 사이클에 적용될 target_rank + bid_cap + 출처.

    source ∈ {'policy:keyword', 'policy:site', 'keyword_default'}.
    policy_id 는 source='policy:*' 일 때만 의미 — fallback 시 None.
    """

    target_rank: int
    bid_cap: int
    source: str
    policy_id: int | None


def minute_of_week_kst(now: datetime) -> int:
    """KST 기준 minute_of_week (Monday 00:00 = 0, Sunday 23:59 = 10079).

    Naive datetime은 UTC로 간주 — DB ``datetime('now')`` 와 동일 convention.
    """
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    kst = now.astimezone(KST)
    return kst.weekday() * 1440 + kst.hour * 60 + kst.minute


def active_policy(
    conn: sqlite3.Connection,
    scope_type: str,
    scope_id: str,
    now: datetime,
) -> Policy | None:
    """(scope_type, scope_id) 의 현재 활성 정책 1개. 없으면 None.

    Wrap-around 처리: end = start + duration이 10080을 넘으면 modular 비교.
    중복 매치 (D15 r 허용) 시 가장 최근 등록(highest ``id``)을 선택 — 운영자 최신 의도 우선.
    """
    m = minute_of_week_kst(now)
    candidates: list[Policy] = []
    for p in policies_repo.list_by_scope(conn, scope_type, scope_id):
        offset = (m - p.start_minute_of_week) % MINUTES_PER_WEEK
        if offset < p.duration_minutes:
            candidates.append(p)
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.id)


def cap_streak_started_at(
    conn: sqlite3.Connection,
    keyword_id: str,
    current_cap: int,
) -> datetime | None:
    """현재 cap regime 의 CAP_REACHED 연속 streak 시작 시각 (Story 3.1 D17 helper).

    decisions를 최신 → 과거 순으로 walk. 직전 row가 CAP_REACHED + 같은 cap 이면 streak.
    cap이 다르거나 CAP_REACHED가 아닌 row를 만나면 break.

    Returns:
        streak 첫 row의 decided_at — 없으면 None (=직전 결정이 CAP_REACHED 아니거나 cap 다름).

    Story 3.2의 'cap_reached + 1h 지속' alert가 이 함수로 지속 시간 계산.
    """
    from rank_bidder.db.repositories import decisions as decisions_repo

    rows = decisions_repo.list_for_keyword(conn, keyword_id, limit=200)
    if not rows or rows[0].decision != "CAP_REACHED" or rows[0].bid_cap != current_cap:
        return None
    started_at = rows[0].decided_at
    for r in rows[1:]:
        if r.decision != "CAP_REACHED" or r.bid_cap != current_cap:
            break
        started_at = r.decided_at
    return started_at


def effective_settings(
    conn: sqlite3.Connection,
    keyword: Keyword,
    now: datetime,
) -> EffectiveSettings:
    """KW → site → keyword default fallback 체인으로 (target_rank, bid_cap) 결정.

    cycle_full 이 매 사이클 KW 처리 시 호출. 정책 미정의 KW는 keywords.target_rank /
    keywords.bid_cap 그대로 사용 (Story 3.1 AC3).
    """
    kw_policy = active_policy(conn, "keyword", keyword.id, now)
    if kw_policy is not None:
        return EffectiveSettings(
            target_rank=kw_policy.target_rank,
            bid_cap=kw_policy.bid_cap,
            source="policy:keyword",
            policy_id=kw_policy.id,
        )
    site_policy = active_policy(conn, "site", keyword.site_id, now)
    if site_policy is not None:
        return EffectiveSettings(
            target_rank=site_policy.target_rank,
            bid_cap=site_policy.bid_cap,
            source="policy:site",
            policy_id=site_policy.id,
        )
    return EffectiveSettings(
        target_rank=keyword.target_rank,
        bid_cap=keyword.bid_cap,
        source="keyword_default",
        policy_id=None,
    )
