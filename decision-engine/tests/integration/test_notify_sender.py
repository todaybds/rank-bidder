"""Story 6.1 — notify sender (templates + suppression + send + mark sent)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
from rank_bidder.db.connection import get_connection, write_transaction
from rank_bidder.db.repositories import notifications
from rank_bidder.notify import sender, smtp_client, templates


@pytest.fixture
def dry_run_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """SMTP env 미설정 → dry_run."""
    for v in ("NOTIFY_SMTP_HOST", "NOTIFY_SMTP_USER", "NOTIFY_SMTP_PASS", "NOTIFY_TO"):
        monkeypatch.delenv(v, raising=False)


# ---------------------------------------------------------------------------
# templates
# ---------------------------------------------------------------------------


def test_template_naver_keyword_deleted(temp_db: Path) -> None:
    with write_transaction() as conn:
        n = notifications.insert(
            conn,
            event_type="naver_keyword_deleted",
            related_ids=["kw-A", "kw-B"],
            payload={"cycle_id": "c1", "count": 2},
        )
    subject, body = templates.render(n)
    assert "Naver" in subject
    assert "kw-A" in body
    assert "c1" in body


def test_template_cap_race(temp_db: Path) -> None:
    with write_transaction() as conn:
        n = notifications.insert(
            conn,
            event_type="cap_race",
            related_ids=["s1", "kw1", "kw2"],
            payload={"site_id": "s1", "keyword_ids": ["kw1", "kw2"], "count": 2},
        )
    subject, body = templates.render(n)
    assert "s1" in subject
    assert "kw1" in body
    assert "kw2" in body


def test_template_cap_reached_sustained(temp_db: Path) -> None:
    with write_transaction() as conn:
        n = notifications.insert(
            conn,
            event_type="cap_reached_sustained",
            related_ids=["kw1"],
            payload={
                "keyword_id": "kw1",
                "site_id": "s1",
                "bid_cap": 7000,
                "started_at": "2026-05-27T10:00:00Z",
                "duration_seconds": 7200,
            },
        )
    subject, body = templates.render(n)
    assert "kw1" in subject
    assert "₩7,000" in body or "7,000" in body
    assert "2.0h" in body


def test_template_generic_fallback(temp_db: Path) -> None:
    with write_transaction() as conn:
        n = notifications.insert(
            conn,
            event_type="bogus_event",
            related_ids=["x"],
            payload={"foo": "bar"},
        )
    subject, body = templates.render(n)
    assert "bogus_event" in body


# ---------------------------------------------------------------------------
# sender.run_once
# ---------------------------------------------------------------------------


def test_run_once_no_pending(temp_db: Path, dry_run_env: None) -> None:
    summary = sender.run_once()
    assert summary["scanned"] == 0
    assert summary["sent"] == 0


def test_dry_run_marks_sent_at(temp_db: Path, dry_run_env: None) -> None:
    """SMTP env 없으면 실제 발송 안 함, 그래도 sent_at 박힘."""
    with write_transaction() as conn:
        n = notifications.insert(
            conn,
            event_type="naver_keyword_deleted",
            related_ids=["kw1"],
            payload={"cycle_id": "c1", "count": 1},
        )
    summary = sender.run_once()
    assert summary["scanned"] == 1
    assert summary["dry_run"] == 1
    with get_connection() as conn:
        got = notifications.get(conn, n.id)
    assert got is not None
    assert got.sent_at is not None
    assert got.suppressed_until is not None


def test_send_calls_smtp_when_configured(temp_db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """SMTP env 설정 시 send 호출됨 (mock 으로 확인)."""
    monkeypatch.setenv("NOTIFY_SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("NOTIFY_SMTP_PORT", "587")
    monkeypatch.setenv("NOTIFY_TO", "alert@example.com")
    monkeypatch.setenv("NOTIFY_FROM", "bot@example.com")

    with write_transaction() as conn:
        notifications.insert(
            conn,
            event_type="naver_keyword_deleted",
            related_ids=["kw1"],
            payload={"cycle_id": "c1", "count": 1},
        )

    with patch("rank_bidder.notify.sender.smtp_client.send", return_value=True) as mock_send:
        summary = sender.run_once()
    assert summary["sent"] == 1
    assert mock_send.call_count == 1


def test_failed_send_does_not_mark_sent(temp_db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """SMTP 실패 시 sent_at 안 박힘 → 다음 분 재시도 가능."""
    monkeypatch.setenv("NOTIFY_SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("NOTIFY_TO", "alert@example.com")

    with write_transaction() as conn:
        n = notifications.insert(
            conn,
            event_type="naver_keyword_deleted",
            related_ids=["kw1"],
            payload={"cycle_id": "c1", "count": 1},
        )

    with patch(
        "rank_bidder.notify.sender.smtp_client.send",
        side_effect=smtp_client.SMTPSendError("connection refused"),
    ):
        summary = sender.run_once()
    assert summary["failed"] == 1
    with get_connection() as conn:
        got = notifications.get(conn, n.id)
    assert got is not None
    assert got.sent_at is None  # 재시도 가능


def test_suppression_window_per_event_type(temp_db: Path, dry_run_env: None) -> None:
    """system_failure 1h vs cap_race 24h — 발송 후 suppressed_until 차이 확인."""
    now = datetime(2026, 5, 27, 12, 0, tzinfo=UTC)
    with write_transaction() as conn:
        sys_n = notifications.insert(
            conn,
            event_type="system_failure",
            related_ids=["host"],
            payload={"x": 1},
        )
        race_n = notifications.insert(
            conn,
            event_type="cap_race",
            related_ids=["s1"],
            payload={"x": 1},
        )
    sender.run_once(now=now)
    with get_connection() as conn:
        sys_got = notifications.get(conn, sys_n.id)
        race_got = notifications.get(conn, race_n.id)
    # system_failure → +1h, cap_race → +24h
    assert sys_got.suppressed_until == (now + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
    assert race_got.suppressed_until == (now + timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")


def test_skips_actively_suppressed_rows(temp_db: Path, dry_run_env: None) -> None:
    """suppressed_until > now 인 row 는 sent_at 안 박힘."""
    future = "2099-01-01 00:00:00"
    with write_transaction() as conn:
        n = notifications.insert(
            conn,
            event_type="cap_race",
            related_ids=["s1"],
            payload={"x": 1},
            suppressed_until=future,
        )
    summary = sender.run_once()
    assert summary["scanned"] == 0
    with get_connection() as conn:
        got = notifications.get(conn, n.id)
    assert got.sent_at is None
