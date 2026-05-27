"""Keep-alive heartbeat (Story 1.9, D26 채널 5).

systemd timer (5분)가 본 스크립트 호출 → heartbeats row insert.
외부 모니터(UptimeRobot 등)가 최신 inserted_at 으로 시스템 생존 판별.
"""

from __future__ import annotations

import structlog

from rank_bidder.db.connection import write_transaction

log = structlog.get_logger(__name__)


def insert_heartbeat(source: str = "cron") -> int:
    """heartbeats 1행 insert → row id 반환."""
    with write_transaction() as conn:
        cursor = conn.execute(
            "INSERT INTO heartbeats (inserted_at, source) VALUES (datetime('now'), ?)",
            (source,),
        )
        row_id = cursor.lastrowid
    log.info("keep_alive.inserted", id=row_id, source=source)
    return row_id


if __name__ == "__main__":
    import sys

    row_id = insert_heartbeat(source="cron")
    print(f"heartbeat row id: {row_id}")
    sys.exit(0)
