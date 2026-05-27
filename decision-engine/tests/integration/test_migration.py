"""AC1 + AC7 — 0001_initial.sql 적용 + migration idempotency."""

from __future__ import annotations

from pathlib import Path

import pytest
from rank_bidder.db import configure, get_connection
from rank_bidder.db.migrate import (
    DEFAULT_MIGRATIONS_DIR,
    current_version,
    discover_migrations,
    up,
)


def test_up_creates_three_tables_and_indexes(temp_db: Path) -> None:
    """AC1: schema_migrations + sites + keywords + 2 indexes 생성."""
    with get_connection() as conn:
        tables = {
            row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    assert {"schema_migrations", "sites", "keywords"} <= tables

    with get_connection() as conn:
        indexes = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_%'"
            )
        }
    assert {"idx_keywords_site_id", "idx_keywords_enabled_site_id"} <= indexes


def test_up_records_version_1(temp_db: Path) -> None:
    """AC1: schema_migrations에 version=1 행 박제."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT version, applied_at FROM schema_migrations WHERE version = 1"
        ).fetchone()
    assert row is not None
    assert int(row["version"]) == 1
    assert row["applied_at"]  # ISO 8601 string


def test_up_is_idempotent(temp_db: Path) -> None:
    """AC7: 두 번째 호출은 적용 건수 0."""
    applied = up(DEFAULT_MIGRATIONS_DIR)
    assert applied == 0
    with get_connection() as conn:
        assert current_version(conn) == 1


def test_discover_migrations_rejects_non_sequential(tmp_path: Path) -> None:
    """AC7: 빈틈 있는 번호는 ValueError."""
    (tmp_path / "0001_a.sql").write_text("-- noop")
    (tmp_path / "0003_c.sql").write_text("-- noop")
    with pytest.raises(ValueError, match="비순차"):
        discover_migrations(tmp_path)


def test_discover_migrations_rejects_duplicate(tmp_path: Path) -> None:
    """AC7: 중복 번호는 ValueError."""
    (tmp_path / "0001_a.sql").write_text("-- noop")
    (tmp_path / "0001_b_duplicate.sql").write_text("-- noop")
    with pytest.raises(ValueError, match="중복"):
        discover_migrations(tmp_path)


def test_up_on_empty_db_returns_one(empty_db: Path) -> None:
    """AC1: 0 → 1 적용 시 카운트 1."""
    configure(empty_db)
    applied = up(DEFAULT_MIGRATIONS_DIR)
    assert applied == 1
