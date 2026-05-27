"""Notification sender — Story 6.1 (FR-22, FR-23).

systemd timer 가 매 분 호출. notifications_log 에서 pending (sent_at IS NULL) +
suppressed_until 만료된 row 를 select → 발송 → sent_at + suppressed_until 갱신.

event_type별 발송 후 억제 윈도우:
  - system_failure              : 1h
  - cap_race                    : 24h
  - cap_reached_sustained       : 24h
  - naver_keyword_deleted       : 24h
  - 기타                         : 1h (보수적)
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta

import structlog

from rank_bidder.db.connection import get_connection, write_transaction
from rank_bidder.db.repositories import notifications
from rank_bidder.notify import smtp_client, templates

log = structlog.get_logger(__name__)

SUPPRESSION_HOURS: dict[str, int] = {
    "system_failure": 1,
    "cap_race": 24,
    "cap_reached_sustained": 24,
    "naver_keyword_deleted": 24,
}
DEFAULT_SUPPRESSION_HOURS = 1


def _suppression_for(event_type: str) -> int:
    return SUPPRESSION_HOURS.get(event_type, DEFAULT_SUPPRESSION_HOURS)


def _list_pending(conn: sqlite3.Connection, now_sqlite: str) -> list[notifications.Notification]:
    """sent_at IS NULL + (suppressed_until IS NULL OR < now) 인 row 를 created_at ASC 로."""
    rows = conn.execute(
        f"SELECT * FROM {notifications.TABLE} "
        f"WHERE sent_at IS NULL AND (suppressed_until IS NULL OR suppressed_until < ?) "
        f"ORDER BY created_at LIMIT 100",
        (now_sqlite,),
    ).fetchall()
    return [notifications._row(r) for r in rows]


def _sqlite_dt(dt: datetime) -> str:
    if dt.tzinfo is not None:
        dt = dt.astimezone(UTC).replace(tzinfo=None)
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def run_once(now: datetime | None = None, *, dry_run: bool | None = None) -> dict[str, int]:
    """매 분 systemd timer 진입점. 1회 호출 = pending row 묶음 발송.

    Args:
        now: 테스트용 시각 주입.
        dry_run: True 강제 시 SMTP 호출 없이 sent_at 만 갱신. None 시 env 기반 (smtp_client.Config).

    Returns:
        {scanned, sent, failed, dry_run}.
    """
    now = now or datetime.now(UTC)
    summary = {"scanned": 0, "sent": 0, "failed": 0, "dry_run": 0}
    now_sqlite = _sqlite_dt(now)
    with get_connection() as conn:
        pending = _list_pending(conn, now_sqlite)
    summary["scanned"] = len(pending)
    if not pending:
        return summary

    cfg = smtp_client.Config.from_env()
    effective_dry = bool(dry_run) or cfg.is_dry_run

    for n in pending:
        subject, body = templates.render(n)
        try:
            smtp_client.send(subject, body, cfg=cfg if not dry_run else None)
        except smtp_client.SMTPSendError as exc:
            log.error("notify.send_failed", notification_id=n.id, error=str(exc))
            summary["failed"] += 1
            continue

        new_suppressed_until = _sqlite_dt(now + timedelta(hours=_suppression_for(n.event_type)))
        with write_transaction() as conn:
            conn.execute(
                f"UPDATE {notifications.TABLE} "
                f"SET sent_at = ?, suppressed_until = ? WHERE id = ?",
                (now_sqlite, new_suppressed_until, n.id),
            )
        if effective_dry:
            summary["dry_run"] += 1
        else:
            summary["sent"] += 1
    return summary


def main() -> int:
    """CLI / systemd 진입점."""
    summary = run_once()
    log.info("notify.sender.completed", **summary)
    print(summary)
    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":
    import sys

    sys.exit(main())
