"""SQLite connection module — D4 + D15(h)(j).

모든 write는 ``write_transaction()`` 경유. 직접 ``sqlite3.connect``로 write 금지.
PRAGMA: journal_mode=WAL + synchronous=FULL + busy_timeout=5000 + wal_autocheckpoint=1000 + foreign_keys=ON.
"""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from filelock import FileLock, Timeout

LOCK_TIMEOUT_SECONDS: float = 5.0
BUSY_TIMEOUT_MS: int = 5000
WAL_AUTOCHECKPOINT_PAGES: int = 1000

_REQUIRED_PRAGMAS: dict[str, str | int] = {
    "journal_mode": "wal",
    "synchronous": 2,  # FULL = 2
    "busy_timeout": BUSY_TIMEOUT_MS,
    "wal_autocheckpoint": WAL_AUTOCHECKPOINT_PAGES,
    "foreign_keys": 1,
}

# Module-level mutable DB path: env-driven by default, override via configure() for tests.
_db_path: Path | None = None


class SQLiteBusyError(Exception):
    """File lock 대기 시간 초과 — D15(h) HTTP 503으로 매핑."""


def configure(db_path: Path | None) -> None:
    """테스트/명시적 주입을 위한 DB 경로 설정. env 우선 적용을 override.

    ``None`` 을 전달하면 module-level override 해제 → env 변수로 fallback.
    pytest fixture teardown에서 사용.
    """
    global _db_path
    _db_path = Path(db_path) if db_path is not None else None


def get_db_path() -> Path:
    if _db_path is not None:
        return _db_path
    env_value = os.environ.get("RANKBIDDER_DB_PATH")
    if not env_value:
        raise RuntimeError(
            "RANKBIDDER_DB_PATH 환경변수가 없고 configure()도 호출되지 않았습니다. "
            ".env.example 참고."
        )
    return Path(env_value)


def get_lock_path() -> Path:
    return get_db_path().with_suffix(".lock")


def _apply_pragmas(conn: sqlite3.Connection) -> None:
    """모든 PRAGMA 설정 후 SELECT로 적용 검증. 검증 실패 = RuntimeError."""
    for pragma, expected in _REQUIRED_PRAGMAS.items():
        conn.execute(f"PRAGMA {pragma} = {expected}")
    for pragma, expected in _REQUIRED_PRAGMAS.items():
        row = conn.execute(f"PRAGMA {pragma}").fetchone()
        actual = row[0] if row is not None else None
        if isinstance(expected, str):
            if str(actual).lower() != expected.lower():
                raise RuntimeError(f"PRAGMA {pragma} 적용 실패: expected={expected}, got={actual}")
        else:
            if int(actual) != int(expected):
                raise RuntimeError(f"PRAGMA {pragma} 적용 실패: expected={expected}, got={actual}")


@contextmanager
def get_connection() -> Iterator[sqlite3.Connection]:
    """READ 또는 manual transaction용 connection. WAL 모드라 read는 lock 무관."""
    conn = sqlite3.connect(
        get_db_path(),
        isolation_level=None,
        timeout=LOCK_TIMEOUT_SECONDS,
    )
    conn.row_factory = sqlite3.Row
    try:
        _apply_pragmas(conn)
        yield conn
    finally:
        conn.close()


@contextmanager
def write_transaction() -> Iterator[sqlite3.Connection]:
    """모든 mutation 경로. file lock + BEGIN IMMEDIATE + 자동 commit/rollback.

    lock 5s timeout 초과 시 ``SQLiteBusyError`` raise (D15 h).
    """
    lock = FileLock(str(get_lock_path()), timeout=LOCK_TIMEOUT_SECONDS)
    try:
        lock.acquire()
    except Timeout as exc:
        raise SQLiteBusyError(
            f"File lock 대기 {LOCK_TIMEOUT_SECONDS}s 초과 — 동시 쓰기 경합"
        ) from exc
    try:
        with get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
            except Exception:
                conn.rollback()
                raise
            else:
                conn.commit()
    finally:
        lock.release()
