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

from rank_bidder.db.connection import get_connection, write_transaction

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
    """파일 SQL 실행 + schema_migrations에 행 추가."""
    sql = path.read_text(encoding="utf-8")
    conn.executescript(sql)
    conn.execute(
        "INSERT INTO schema_migrations(version, applied_at) VALUES (?, datetime('now'))",
        (version,),
    )


def up(migrations_dir: Path = DEFAULT_MIGRATIONS_DIR) -> int:
    """남은 migration을 순차 적용. 적용한 개수 반환."""
    all_migrations = discover_migrations(migrations_dir)
    with write_transaction() as conn:
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
