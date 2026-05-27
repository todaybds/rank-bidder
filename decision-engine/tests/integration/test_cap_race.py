"""Story 3.2 — cap_race detector + cap_reached_sustained alert + 24h suppression."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from rank_bidder.db.connection import get_connection, write_transaction
from rank_bidder.db.models import (
    DecisionCreate,
    KeywordCreate,
    PolicyCreate,
    SiteCreate,
)
from rank_bidder.db.repositories import decisions, keywords, notifications, policies, sites
from rank_bidder.engine.cap_race import (
    RACE_EVENT,
    SUSTAINED_EVENT,
    _sqlite_dt,
    evaluate_keyword_sustained,
    evaluate_site,
)


def _backdate_decision(conn, decision_id: int, decided_at: datetime) -> None:
    """SQLite `datetime('now')` 자동 박제 우회 — 명시 시각으로 갱신."""
    conn.execute(
        "UPDATE decisions SET decided_at = ? WHERE id = ?",
        (_sqlite_dt(decided_at), decision_id),
    )


def _seed_site_with_kws(conn, site_id: str = "s1", kw_ids: tuple[str, ...] = ("kw1", "kw2")) -> None:
    sites.create(conn, SiteCreate(id=site_id, name="Site"))
    for kid in kw_ids:
        keywords.create(
            conn,
            KeywordCreate(id=kid, site_id=site_id, term=f"t-{kid}", target_rank=2, bid_cap=5000),
        )


def _insert_cap_decision(conn, kw_id: str, cycle_id: str, bid_cap: int = 5000):
    return decisions.insert(
        conn,
        DecisionCreate(
            keyword_id=kw_id,
            cycle_id=cycle_id,
            decision="CAP_REACHED",
            old_bid=bid_cap,
            new_bid=bid_cap,
            bid_cap=bid_cap,
        ),
    )


# ---------------------------------------------------------------------------
# evaluate_site — cap_race detector
# ---------------------------------------------------------------------------


def test_evaluate_site_fires_when_2plus_kws_cap_in_1h(temp_db: Path) -> None:
    now = datetime(2026, 5, 27, 12, 0, tzinfo=UTC)
    with write_transaction() as conn:
        _seed_site_with_kws(conn)
        _insert_cap_decision(conn, "kw1", "c1")
        _insert_cap_decision(conn, "kw2", "c1")
    with write_transaction() as conn:
        notif_id = evaluate_site(conn, "s1", now)
    assert notif_id is not None
    with get_connection() as conn:
        n = notifications.get(conn, notif_id)
    assert n is not None
    assert n.event_type == RACE_EVENT
    assert n.payload["site_id"] == "s1"
    assert n.payload["count"] == 2
    assert set(n.payload["keyword_ids"]) == {"kw1", "kw2"}
    assert n.suppressed_until is not None


def test_evaluate_site_no_fire_with_single_kw(temp_db: Path) -> None:
    now = datetime(2026, 5, 27, 12, 0, tzinfo=UTC)
    with write_transaction() as conn:
        _seed_site_with_kws(conn)
        _insert_cap_decision(conn, "kw1", "c1")
    with write_transaction() as conn:
        result = evaluate_site(conn, "s1", now)
    assert result is None


def test_evaluate_site_excludes_decisions_older_than_1h(temp_db: Path) -> None:
    now = datetime(2026, 5, 27, 12, 0, tzinfo=UTC)
    with write_transaction() as conn:
        _seed_site_with_kws(conn)
        d1 = _insert_cap_decision(conn, "kw1", "c1")
        d2 = _insert_cap_decision(conn, "kw2", "c1")
        # 둘 다 1h + 1min 과거로 backdate → 윈도우 밖.
        old_time = now - timedelta(hours=1, minutes=1)
        _backdate_decision(conn, d1.id, old_time)
        _backdate_decision(conn, d2.id, old_time)
    with write_transaction() as conn:
        result = evaluate_site(conn, "s1", now)
    assert result is None


def test_evaluate_site_suppressed_24h_after_fire(temp_db: Path) -> None:
    """1차 fire 후 24h 미만 시점 재호출 시 추가 row 없음."""
    now = datetime(2026, 5, 27, 12, 0, tzinfo=UTC)
    with write_transaction() as conn:
        _seed_site_with_kws(conn)
        _insert_cap_decision(conn, "kw1", "c1")
        _insert_cap_decision(conn, "kw2", "c1")
    with write_transaction() as conn:
        first = evaluate_site(conn, "s1", now)
    with write_transaction() as conn:
        # 23h 59m 후 재시도
        second = evaluate_site(conn, "s1", now + timedelta(hours=23, minutes=59))
    assert first is not None
    assert second is None


def test_evaluate_site_fires_again_after_suppression_expires(temp_db: Path) -> None:
    """24h + 1min 후 suppression 풀려서 다시 fire."""
    now = datetime(2026, 5, 27, 12, 0, tzinfo=UTC)
    with write_transaction() as conn:
        _seed_site_with_kws(conn)
        _insert_cap_decision(conn, "kw1", "c1")
        _insert_cap_decision(conn, "kw2", "c1")
    with write_transaction() as conn:
        first = evaluate_site(conn, "s1", now)
    with write_transaction() as conn:
        # 새 CAP_REACHED row 추가 (24h 이후 시점 기준 1h 윈도우)
        d3 = _insert_cap_decision(conn, "kw1", "c2")
        d4 = _insert_cap_decision(conn, "kw2", "c2")
        future = now + timedelta(hours=24, minutes=1)
        _backdate_decision(conn, d3.id, future - timedelta(minutes=10))
        _backdate_decision(conn, d4.id, future - timedelta(minutes=10))
        second = evaluate_site(conn, "s1", future)
    assert first is not None
    assert second is not None
    assert first != second


# ---------------------------------------------------------------------------
# evaluate_keyword_sustained — cap_reached_sustained
# ---------------------------------------------------------------------------


def test_sustained_fires_when_streak_at_least_1h(temp_db: Path) -> None:
    now = datetime(2026, 5, 27, 12, 0, tzinfo=UTC)
    with write_transaction() as conn:
        _seed_site_with_kws(conn, kw_ids=("kw1",))
        d1 = _insert_cap_decision(conn, "kw1", "c1")
        # 1h + 1min 과거로 backdate → streak duration ≥ 1h.
        _backdate_decision(conn, d1.id, now - timedelta(hours=1, minutes=1))
    with get_connection() as conn:
        kw = keywords.get(conn, "kw1")
    with write_transaction() as conn:
        notif_id = evaluate_keyword_sustained(conn, kw, now)
    assert notif_id is not None
    with get_connection() as conn:
        n = notifications.get(conn, notif_id)
    assert n is not None
    assert n.event_type == SUSTAINED_EVENT
    assert n.payload["keyword_id"] == "kw1"
    assert n.payload["bid_cap"] == 5000
    assert n.payload["duration_seconds"] >= 3600


def test_sustained_no_fire_when_streak_under_1h(temp_db: Path) -> None:
    now = datetime(2026, 5, 27, 12, 0, tzinfo=UTC)
    with write_transaction() as conn:
        _seed_site_with_kws(conn, kw_ids=("kw1",))
        d1 = _insert_cap_decision(conn, "kw1", "c1")
        _backdate_decision(conn, d1.id, now - timedelta(minutes=30))
    with get_connection() as conn:
        kw = keywords.get(conn, "kw1")
    with write_transaction() as conn:
        result = evaluate_keyword_sustained(conn, kw, now)
    assert result is None


def test_sustained_resets_when_cap_changes_d17(temp_db: Path) -> None:
    """D17 reset 핵심: cap=5000 streak 2h 누적 후 정책으로 cap=8000 전환 시 streak 새로 시작 → 미발화."""
    now = datetime(2026, 5, 27, 12, 0, tzinfo=UTC)
    with write_transaction() as conn:
        _seed_site_with_kws(conn, kw_ids=("kw1",))
        # 과거 cap=5000 streak 2h 누적 (정책 전환 전)
        d_old1 = _insert_cap_decision(conn, "kw1", "c1", bid_cap=5000)
        d_old2 = _insert_cap_decision(conn, "kw1", "c2", bid_cap=5000)
        _backdate_decision(conn, d_old1.id, now - timedelta(hours=2, minutes=10))
        _backdate_decision(conn, d_old2.id, now - timedelta(hours=2))
        # 정책 전환 — cap=8000 로 변경, KW scope policy로 박제.
        policies.create(
            conn,
            PolicyCreate(
                scope_type="keyword",
                scope_id="kw1",
                start_minute_of_week=0,
                duration_minutes=10080,
                target_rank=2,
                bid_cap=8000,
            ),
        )
        # 신 regime 첫 CAP_REACHED (cap=8000) 10분 전.
        d_new = _insert_cap_decision(conn, "kw1", "c3", bid_cap=8000)
        _backdate_decision(conn, d_new.id, now - timedelta(minutes=10))
    with get_connection() as conn:
        kw = keywords.get(conn, "kw1")
    with write_transaction() as conn:
        result = evaluate_keyword_sustained(conn, kw, now)
    # 신 regime streak 10분 < 1h → 미발화 (= D17 reset 확인).
    assert result is None


def test_sustained_suppressed_24h(temp_db: Path) -> None:
    now = datetime(2026, 5, 27, 12, 0, tzinfo=UTC)
    with write_transaction() as conn:
        _seed_site_with_kws(conn, kw_ids=("kw1",))
        d1 = _insert_cap_decision(conn, "kw1", "c1")
        _backdate_decision(conn, d1.id, now - timedelta(hours=1, minutes=10))
    with get_connection() as conn:
        kw = keywords.get(conn, "kw1")
    with write_transaction() as conn:
        first = evaluate_keyword_sustained(conn, kw, now)
    with write_transaction() as conn:
        second = evaluate_keyword_sustained(conn, kw, now + timedelta(hours=12))
    assert first is not None
    assert second is None


# ---------------------------------------------------------------------------
# notifications repo — suppressed_until + find_active_suppression
# ---------------------------------------------------------------------------


def test_insert_with_suppressed_until_roundtrip(temp_db: Path) -> None:
    with write_transaction() as conn:
        n = notifications.insert(
            conn,
            event_type="x",
            related_ids=["a"],
            payload={},
            suppressed_until="2099-01-01 00:00:00",
        )
    assert n.suppressed_until == "2099-01-01 00:00:00"


def test_find_active_suppression_matches_scope_key(temp_db: Path) -> None:
    with write_transaction() as conn:
        notifications.insert(
            conn,
            event_type=RACE_EVENT,
            related_ids=["s1", "kw1", "kw2"],
            payload={},
            suppressed_until="2099-01-01 00:00:00",
        )
    with get_connection() as conn:
        # s1 매치
        assert (
            notifications.find_active_suppression(
                conn, RACE_EVENT, "s1", "2026-05-27 12:00:00"
            )
            is not None
        )
        # 다른 사이트 미매치
        assert (
            notifications.find_active_suppression(
                conn, RACE_EVENT, "s9", "2026-05-27 12:00:00"
            )
            is None
        )


def test_find_active_suppression_ignores_expired(temp_db: Path) -> None:
    with write_transaction() as conn:
        notifications.insert(
            conn,
            event_type=RACE_EVENT,
            related_ids=["s1"],
            payload={},
            suppressed_until="2020-01-01 00:00:00",
        )
    with get_connection() as conn:
        assert (
            notifications.find_active_suppression(
                conn, RACE_EVENT, "s1", "2026-05-27 12:00:00"
            )
            is None
        )
