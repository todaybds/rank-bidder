"""Migration runner — D2 raw .sql 순번 + schema_migrations 추적.

CLI:
    python -m rank_bidder.db.migrate up
    python -m rank_bidder.db.migrate current
"""

from __future__ import annotations

import argparse
import re
import sqlite3
import sys
import time
from pathlib import Path

import structlog

from rank_bidder.db.connection import get_connection

DEFAULT_MIGRATIONS_DIR: Path = Path(__file__).resolve().parents[3] / "migrations"

_MIGRATION_PATTERN = re.compile(r"^(\d{4})_[a-z0-9_]+\.sql$")
log = structlog.get_logger(__name__)


def discover_migrations(migrations_dir: Path) -> list[tuple[int, Path]]:
    """`NNNN_<snake>.sql` 패턴 파일을 번호 순으로 반환.

    번호가 중복이거나 1부터 시작하는 순차가 아니면 ``ValueError``.
    """
    found: list[tuple[int, Path]] = []
    for path in sorted(migrations_dir.glob("*.sql")):
        match = _MIGRATION_PATTERN.match(path.name)
        if not match:
            continue
        version = int(match.group(1))
        found.append((version, path))

    versions = [v for v, _ in found]
    if len(versions) != len(set(versions)):
        raise ValueError(f"중복 migration 번호: {versions}")
    expected = list(range(1, len(versions) + 1))
    if versions != expected:
        raise ValueError(
            f"비순차 migration: 기대 {expected}, 실제 {versions} — 1부터 빈틈 없이 증가해야 함."
        )
    return found


def current_version(conn: sqlite3.Connection) -> int:
    """``schema_migrations`` 없으면 0, 있으면 ``MAX(version)``."""
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
    ).fetchone()
    if row is None:
        return 0
    row = conn.execute("SELECT COALESCE(MAX(version), 0) AS v FROM schema_migrations").fetchone()
    return int(row["v"])


def apply_migration(conn: sqlite3.Connection, version: int, path: Path) -> None:
    """파일 SQL + schema_migrations INSERT를 1개 atomic script로 실행.

    ``executescript()`` 는 pending transaction 있을 시 implicit COMMIT을 발행하므로
    outer ``write_transaction()`` 의 BEGIN IMMEDIATE를 깨버린다. 따라서 각 migration
    내부에 명시 ``BEGIN IMMEDIATE; ... COMMIT;`` 을 박아 단일 migration 단위로 원자성을
    보장한다 — 중간 실패 시 해당 migration만 rollback, 이전 migration들은 보존.

    ``version`` 은 ``discover_migrations`` regex로 추출된 int이라 f-string 안전.
    """
    sql = path.read_text(encoding="utf-8").rstrip()
    atomic_script = (
        "BEGIN IMMEDIATE;\n"
        f"{sql}\n"
        f"INSERT INTO schema_migrations(version, applied_at) "
        f"VALUES ({version}, datetime('now'));\n"
        "COMMIT;\n"
    )
    conn.executescript(atomic_script)


def up(migrations_dir: Path = DEFAULT_MIGRATIONS_DIR) -> int:
    """남은 migration을 순차 적용. 적용한 개수 반환.

    ``write_transaction()`` 대신 file lock만 직접 acquire 한다 — ``apply_migration``
    의 ``executescript()`` 가 outer transaction을 implicit COMMIT으로 깨기 때문.
    각 migration의 원자성은 ``apply_migration`` 내부 BEGIN IMMEDIATE/COMMIT이 담당.
    """
    from filelock import FileLock, Timeout

    from rank_bidder.db.connection import (
        LOCK_TIMEOUT_SECONDS,
        SQLiteBusyError,
        get_connection,
        get_lock_path,
    )

    all_migrations = discover_migrations(migrations_dir)
    lock = FileLock(str(get_lock_path()), timeout=LOCK_TIMEOUT_SECONDS)
    try:
        lock.acquire()
    except Timeout as exc:
        raise SQLiteBusyError(
            f"File lock 대기 {LOCK_TIMEOUT_SECONDS}s 초과 — migration in progress"
        ) from exc
    try:
        with get_connection() as conn:
            current = current_version(conn)
            pending = [(v, p) for v, p in all_migrations if v > current]
            if not pending:
                log.info("migration.no_pending", current_version=current)
                return 0
            for version, path in pending:
                started = time.perf_counter()
                apply_migration(conn, version, path)
                duration_ms = (time.perf_counter() - started) * 1000
                log.info(
                    "migration.applied",
                    version=version,
                    file=path.name,
                    duration_ms=round(duration_ms, 2),
                )
    finally:
        lock.release()
    return len(pending)


def _print_current(migrations_dir: Path) -> None:
    with get_connection() as conn:
        version = current_version(conn)
    available = discover_migrations(migrations_dir)
    latest = available[-1][0] if available else 0
    print(f"current: {version}")
    print(f"latest:  {latest}")
    print(f"pending: {latest - version}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rank_bidder.db.migrate")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("up", help="apply all pending migrations")
    sub.add_parser("current", help="show current and latest version")
    parser.add_argument(
        "--migrations-dir",
        type=Path,
        default=DEFAULT_MIGRATIONS_DIR,
        help="override migrations directory (default: decision-engine/migrations/)",
    )
    args = parser.parse_args(argv)

    if args.cmd == "up":
        applied = up(args.migrations_dir)
        if applied == 0:
            print("Already at latest version.")
        else:
            print(f"Applied {applied} migration(s).")
        return 0
    if args.cmd == "current":
        _print_current(args.migrations_dir)
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
