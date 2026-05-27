"""Story 3.1 — policy_eval: active_policy wrap-around + effective_settings fallback +
cap_streak_started_at D17 reset.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from rank_bidder.db.connection import get_connection, write_transaction
from rank_bidder.db.models import (
    DecisionCreate,
    KeywordCreate,
    PolicyCreate,
    SiteCreate,
)
from rank_bidder.db.repositories import decisions, keywords, policies, sites
from rank_bidder.engine.policy_eval import (
    KST,
    active_policy,
    cap_streak_started_at,
    effective_settings,
    minute_of_week_kst,
)

KST_TZ = KST


def _kst(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    """KST timezone-aware datetime helper."""
    return datetime(year, month, day, hour, minute, tzinfo=KST_TZ)


# ---------------------------------------------------------------------------
# minute_of_week_kst — week origin = Monday 00:00 KST
# ---------------------------------------------------------------------------


def test_minute_of_week_monday_zero() -> None:
    """2026-05-25 is a Monday."""
    assert minute_of_week_kst(_kst(2026, 5, 25, 0, 0)) == 0


def test_minute_of_week_sunday_last_minute() -> None:
    """2026-05-31 23:59 KST = Sunday 23:59 → 10079."""
    assert minute_of_week_kst(_kst(2026, 5, 31, 23, 59)) == 10079


def test_minute_of_week_converts_utc_to_kst() -> None:
    """2026-05-25 00:00 UTC = 2026-05-25 09:00 KST → Monday 540."""
    utc_dt = datetime(2026, 5, 25, 0, 0, tzinfo=UTC)
    assert minute_of_week_kst(utc_dt) == 9 * 60


# ---------------------------------------------------------------------------
# active_policy — match + wrap-around + multi-match resolution
# ---------------------------------------------------------------------------


def test_active_policy_simple_match(temp_db: Path) -> None:
    """Monday 09:00-12:00 정책 → Monday 10:00 lookup 매치."""
    with write_transaction() as conn:
        sites.create(conn, SiteCreate(id="s1", name="Site 1"))
        policies.create(
            conn,
            PolicyCreate(
                scope_type="site",
                scope_id="s1",
                start_minute_of_week=9 * 60,
                duration_minutes=3 * 60,
                target_rank=2,
                bid_cap=5000,
            ),
        )
    with get_connection() as conn:
        result = active_policy(conn, "site", "s1", _kst(2026, 5, 25, 10, 0))
    assert result is not None
    assert result.target_rank == 2


def test_active_policy_no_match_outside_window(temp_db: Path) -> None:
    """Monday 09:00-12:00 정책 → Monday 13:00 lookup 미매치."""
    with write_transaction() as conn:
        sites.create(conn, SiteCreate(id="s1", name="Site 1"))
        policies.create(
            conn,
            PolicyCreate(
                scope_type="site",
                scope_id="s1",
                start_minute_of_week=9 * 60,
                duration_minutes=3 * 60,
                target_rank=2,
                bid_cap=5000,
            ),
        )
    with get_connection() as conn:
        result = active_policy(conn, "site", "s1", _kst(2026, 5, 25, 13, 0))
    assert result is None


def test_active_policy_wraparound_22_to_06(temp_db: Path) -> None:
    """일요일 22:00 ~ 월요일 06:00 (8h, wrap) 정책 → 월요일 02:00 lookup 매치.

    Sunday weekday=6 → start = 6*1440 + 22*60 = 9960.
    duration = 8*60 = 480 → end = 10440 → wrap to 360 (Monday 06:00).
    Monday 02:00 → minute_of_week = 0*1440 + 2*60 = 120. (120 - 9960) % 10080 = 240 < 480 → 매치.
    """
    with write_transaction() as conn:
        sites.create(conn, SiteCreate(id="s1", name="Site 1"))
        policies.create(
            conn,
            PolicyCreate(
                scope_type="site",
                scope_id="s1",
                start_minute_of_week=9960,
                duration_minutes=480,
                target_rank=1,
                bid_cap=20000,
            ),
        )
    with get_connection() as conn:
        # 월요일 02:00 KST
        result = active_policy(conn, "site", "s1", _kst(2026, 5, 25, 2, 0))
    assert result is not None
    assert result.bid_cap == 20000


def test_active_policy_wraparound_end_excluded(temp_db: Path) -> None:
    """Wrap 정책: end_minute(반개구간 [start, start+duration)) 직전은 매치, 직후 미매치."""
    with write_transaction() as conn:
        sites.create(conn, SiteCreate(id="s1", name="Site 1"))
        # 일요일 22:00 + 8h → 월요일 06:00 직전까지
        policies.create(
            conn,
            PolicyCreate(
                scope_type="site",
                scope_id="s1",
                start_minute_of_week=9960,
                duration_minutes=480,
                target_rank=1,
                bid_cap=20000,
            ),
        )
    with get_connection() as conn:
        # 월요일 05:59 KST → 매치
        assert active_policy(conn, "site", "s1", _kst(2026, 5, 25, 5, 59)) is not None
        # 월요일 06:00 KST → 미매치 (반개구간)
        assert active_policy(conn, "site", "s1", _kst(2026, 5, 25, 6, 0)) is None


def test_active_policy_multiple_match_returns_highest_id(temp_db: Path) -> None:
    """D15 r 중복 허용 — 다중 매치 시 가장 최근 등록(highest id) 우선."""
    with write_transaction() as conn:
        sites.create(conn, SiteCreate(id="s1", name="Site 1"))
        p1 = policies.create(
            conn,
            PolicyCreate(
                scope_type="site",
                scope_id="s1",
                start_minute_of_week=0,
                duration_minutes=10080,  # 전 주
                target_rank=5,
                bid_cap=1000,
            ),
        )
        p2 = policies.create(
            conn,
            PolicyCreate(
                scope_type="site",
                scope_id="s1",
                start_minute_of_week=9 * 60,
                duration_minutes=3 * 60,
                target_rank=2,
                bid_cap=8000,
            ),
        )
    with get_connection() as conn:
        result = active_policy(conn, "site", "s1", _kst(2026, 5, 25, 10, 0))
    assert result is not None
    assert result.id == p2.id  # later-created wins
    assert result.target_rank == 2
    _ = p1


# ---------------------------------------------------------------------------
# effective_settings — KW → site → keyword default fallback chain
# ---------------------------------------------------------------------------


def _seed_kw(conn, kw_id: str = "kw1") -> None:
    sites.create(conn, SiteCreate(id="s1", name="Site 1"))
    keywords.create(
        conn,
        KeywordCreate(id=kw_id, site_id="s1", term="t", target_rank=5, bid_cap=2000),
    )


def test_effective_settings_falls_back_to_keyword_default(temp_db: Path) -> None:
    """정책 미정의 → keywords.target_rank/bid_cap 사용."""
    with write_transaction() as conn:
        _seed_kw(conn)
    with get_connection() as conn:
        kw = keywords.get(conn, "kw1")
        eff = effective_settings(conn, kw, _kst(2026, 5, 25, 10, 0))
    assert eff.source == "keyword_default"
    assert eff.target_rank == 5
    assert eff.bid_cap == 2000
    assert eff.policy_id is None


def test_effective_settings_site_policy_wins_over_default(temp_db: Path) -> None:
    """site scope 정책 있으면 KW default 보다 우선."""
    with write_transaction() as conn:
        _seed_kw(conn)
        policies.create(
            conn,
            PolicyCreate(
                scope_type="site",
                scope_id="s1",
                start_minute_of_week=0,
                duration_minutes=10080,
                target_rank=3,
                bid_cap=6000,
            ),
        )
    with get_connection() as conn:
        kw = keywords.get(conn, "kw1")
        eff = effective_settings(conn, kw, _kst(2026, 5, 25, 10, 0))
    assert eff.source == "policy:site"
    assert eff.target_rank == 3
    assert eff.bid_cap == 6000


def test_effective_settings_keyword_policy_wins_over_site(temp_db: Path) -> None:
    """KW scope 정책이 site scope 보다 우선."""
    with write_transaction() as conn:
        _seed_kw(conn)
        policies.create(
            conn,
            PolicyCreate(
                scope_type="site",
                scope_id="s1",
                start_minute_of_week=0,
                duration_minutes=10080,
                target_rank=3,
                bid_cap=6000,
            ),
        )
        policies.create(
            conn,
            PolicyCreate(
                scope_type="keyword",
                scope_id="kw1",
                start_minute_of_week=0,
                duration_minutes=10080,
                target_rank=1,
                bid_cap=9000,
            ),
        )
    with get_connection() as conn:
        kw = keywords.get(conn, "kw1")
        eff = effective_settings(conn, kw, _kst(2026, 5, 25, 10, 0))
    assert eff.source == "policy:keyword"
    assert eff.target_rank == 1
    assert eff.bid_cap == 9000


# ---------------------------------------------------------------------------
# cap_streak_started_at — D17 Cap 도달 타이머 reset
# ---------------------------------------------------------------------------


def test_cap_streak_returns_none_when_last_not_cap(temp_db: Path) -> None:
    """직전 decision이 CAP_REACHED 아니면 streak 없음."""
    with write_transaction() as conn:
        _seed_kw(conn)
        decisions.insert(
            conn,
            DecisionCreate(
                keyword_id="kw1",
                cycle_id="c1",
                decision="HOLD",
                old_bid=1000,
                new_bid=1000,
                bid_cap=5000,
            ),
        )
    with get_connection() as conn:
        assert cap_streak_started_at(conn, "kw1", current_cap=5000) is None


def test_cap_streak_resets_when_cap_changes(temp_db: Path) -> None:
    """D17 핵심: cap이 5000 → 7000 으로 바뀌면 streak이 새 regime 첫 row 부터 시작."""
    with write_transaction() as conn:
        _seed_kw(conn)
        # 과거 cap=5000 streak 2건 — 정책 전환 전.
        decisions.insert(
            conn,
            DecisionCreate(
                keyword_id="kw1",
                cycle_id="c1",
                decision="CAP_REACHED",
                old_bid=5000,
                new_bid=5000,
                bid_cap=5000,
            ),
        )
        decisions.insert(
            conn,
            DecisionCreate(
                keyword_id="kw1",
                cycle_id="c2",
                decision="CAP_REACHED",
                old_bid=5000,
                new_bid=5000,
                bid_cap=5000,
            ),
        )
        # 정책 전환 — cap=7000 첫 CAP_REACHED.
        new_row = decisions.insert(
            conn,
            DecisionCreate(
                keyword_id="kw1",
                cycle_id="c3",
                decision="CAP_REACHED",
                old_bid=7000,
                new_bid=7000,
                bid_cap=7000,
            ),
        )
    with get_connection() as conn:
        started_at = cap_streak_started_at(conn, "kw1", current_cap=7000)
    assert started_at is not None
    # streak 시작 = 신 regime 첫 row (c3) — 과거 cap=5000 streak 포함 안 됨.
    assert started_at == new_row.decided_at


def test_cap_streak_continues_when_cap_unchanged(temp_db: Path) -> None:
    """cap 동일 + 연속 CAP_REACHED → streak이 가장 과거 row 까지 확장."""
    with write_transaction() as conn:
        _seed_kw(conn)
        first = decisions.insert(
            conn,
            DecisionCreate(
                keyword_id="kw1",
                cycle_id="c1",
                decision="CAP_REACHED",
                old_bid=5000,
                new_bid=5000,
                bid_cap=5000,
            ),
        )
        decisions.insert(
            conn,
            DecisionCreate(
                keyword_id="kw1",
                cycle_id="c2",
                decision="CAP_REACHED",
                old_bid=5000,
                new_bid=5000,
                bid_cap=5000,
            ),
        )
        decisions.insert(
            conn,
            DecisionCreate(
                keyword_id="kw1",
                cycle_id="c3",
                decision="CAP_REACHED",
                old_bid=5000,
                new_bid=5000,
                bid_cap=5000,
            ),
        )
    with get_connection() as conn:
        started_at = cap_streak_started_at(conn, "kw1", current_cap=5000)
    assert started_at == first.decided_at


def test_cap_streak_breaks_on_non_cap_decision(temp_db: Path) -> None:
    """중간에 HOLD/BID_UP 끼면 streak 부서짐 — 최근 CAP_REACHED 부터 시작."""
    with write_transaction() as conn:
        _seed_kw(conn)
        decisions.insert(
            conn,
            DecisionCreate(
                keyword_id="kw1",
                cycle_id="c1",
                decision="CAP_REACHED",
                old_bid=5000,
                new_bid=5000,
                bid_cap=5000,
            ),
        )
        decisions.insert(
            conn,
            DecisionCreate(
                keyword_id="kw1",
                cycle_id="c2",
                decision="HOLD",
                old_bid=5000,
                new_bid=5000,
                bid_cap=5000,
            ),
        )
        recent = decisions.insert(
            conn,
            DecisionCreate(
                keyword_id="kw1",
                cycle_id="c3",
                decision="CAP_REACHED",
                old_bid=5000,
                new_bid=5000,
                bid_cap=5000,
            ),
        )
    with get_connection() as conn:
        started_at = cap_streak_started_at(conn, "kw1", current_cap=5000)
    assert started_at == recent.decided_at
