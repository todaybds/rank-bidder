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
        # Story 4.5 추가 후 latest=8 (0008 runtime_config)
        assert current_version(conn) == 8


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


def test_up_on_empty_db_returns_all_pending(empty_db: Path) -> None:
    """AC1: 0 → latest 적용 시 카운트 = 전체 migration 수."""
    configure(empty_db)
    applied = up(DEFAULT_MIGRATIONS_DIR)
    # 0001 + 0002 + 0003 + 0004 + 0005 + 0006 + 0007 + 0008 (Story 4.5 시점)
    assert applied == 8


def test_0003_creates_heartbeats_table(temp_db: Path) -> None:
    """Story 1.9: heartbeats 테이블 + 인덱스."""
    with get_connection() as conn:
        tables = {
            row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        indexes = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_heart%'"
            )
        }
    assert "heartbeats" in tables
    assert "idx_heartbeats_inserted_at" in indexes


def test_0002_creates_cycle_entries_measurements_decisions(temp_db: Path) -> None:
    """Story 1.6 AC1+AC2+AC4+AC5: 3 신규 테이블 + 인덱스 5개."""
    with get_connection() as conn:
        tables = {
            row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        indexes = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_%'"
            )
        }
    assert {"cycle_entries", "measurements", "decisions"} <= tables
    assert {
        "idx_cycle_entries_active",
        "idx_measurements_kw_time",
        "idx_decisions_kw_time",
        "idx_decisions_decided_at",
    } <= indexes


def test_0002_partial_index_filter_recorded(temp_db: Path) -> None:
    """Story 1.6 AC3: idx_cycle_entries_active 가 partial(WHERE 절 포함)."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='index' AND name='idx_cycle_entries_active'"
        ).fetchone()
    assert row is not None
    sql = row["sql"]
    assert "WHERE" in sql
    assert "PUT_SENT" in sql
    assert "PLANNED" in sql


def test_0002_records_version_2(temp_db: Path) -> None:
    """Story 1.6 AC1: schema_migrations 에 version=2 행 박제."""
    with get_connection() as conn:
        row = conn.execute("SELECT version FROM schema_migrations WHERE version = 2").fetchone()
    assert row is not None
    assert int(row["version"]) == 2
