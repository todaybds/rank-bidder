"""Story 3.1 — policies repository + 0006 migration."""

from __future__ import annotations

from pathlib import Path

import pytest
from rank_bidder.db.connection import get_connection, write_transaction
from rank_bidder.db.models import PolicyCreate, PolicyUpdate, SiteCreate
from rank_bidder.db.repositories import policies, sites
from rank_bidder.db.version import VersionConflictError


def test_0006_creates_policies_table(temp_db: Path) -> None:
    with get_connection() as conn:
        tables = {
            row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        indexes = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_policies%'"
            )
        }
    assert "policies" in tables
    assert "idx_policies_scope" in indexes


def test_0006_records_version_6(temp_db: Path) -> None:
    with get_connection() as conn:
        row = conn.execute("SELECT version FROM schema_migrations WHERE version = 6").fetchone()
    assert row is not None
    assert int(row["version"]) == 6


def test_create_and_get(temp_db: Path) -> None:
    with write_transaction() as conn:
        sites.create(conn, SiteCreate(id="s1", name="Site 1"))
        p = policies.create(
            conn,
            PolicyCreate(
                scope_type="site",
                scope_id="s1",
                start_minute_of_week=0,
                duration_minutes=600,
                target_rank=3,
                bid_cap=5000,
            ),
        )
    assert p.id > 0
    assert p.scope_type == "site"
    assert p.target_rank == 3
    assert p.bid_cap == 5000
    assert p.version == 0


def test_list_by_scope_orders_by_start(temp_db: Path) -> None:
    with write_transaction() as conn:
        sites.create(conn, SiteCreate(id="s1", name="Site 1"))
        policies.create(
            conn,
            PolicyCreate(
                scope_type="site",
                scope_id="s1",
                start_minute_of_week=600,
                duration_minutes=120,
                target_rank=2,
                bid_cap=8000,
            ),
        )
        policies.create(
            conn,
            PolicyCreate(
                scope_type="site",
                scope_id="s1",
                start_minute_of_week=100,
                duration_minutes=300,
                target_rank=1,
                bid_cap=10000,
            ),
        )
    with get_connection() as conn:
        rows = policies.list_by_scope(conn, "site", "s1")
    assert [r.start_minute_of_week for r in rows] == [100, 600]


def test_update_bumps_version(temp_db: Path) -> None:
    with write_transaction() as conn:
        sites.create(conn, SiteCreate(id="s1", name="Site 1"))
        p = policies.create(
            conn,
            PolicyCreate(
                scope_type="site",
                scope_id="s1",
                start_minute_of_week=0,
                duration_minutes=600,
                target_rank=3,
                bid_cap=5000,
            ),
        )
        updated = policies.update(conn, p.id, PolicyUpdate(bid_cap=7000), expected_version=0)
    assert updated.bid_cap == 7000
    assert updated.version == 1


def test_update_version_mismatch_raises(temp_db: Path) -> None:
    with write_transaction() as conn:
        sites.create(conn, SiteCreate(id="s1", name="Site 1"))
        p = policies.create(
            conn,
            PolicyCreate(
                scope_type="site",
                scope_id="s1",
                start_minute_of_week=0,
                duration_minutes=600,
                target_rank=3,
                bid_cap=5000,
            ),
        )
    with write_transaction() as conn, pytest.raises(VersionConflictError):
        policies.update(conn, p.id, PolicyUpdate(bid_cap=7000), expected_version=99)


def test_scope_type_check_constraint_blocks_bad_value(temp_db: Path) -> None:
    import sqlite3

    with write_transaction() as conn, pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO policies "
            "(scope_type, scope_id, start_minute_of_week, duration_minutes, "
            "target_rank, bid_cap, version, created_at, updated_at) "
            "VALUES ('BOGUS', 'x', 0, 60, 1, 1000, 0, datetime('now'), datetime('now'))"
        )


def test_minute_of_week_check_constraint(temp_db: Path) -> None:
    import sqlite3

    with write_transaction() as conn, pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO policies "
            "(scope_type, scope_id, start_minute_of_week, duration_minutes, "
            "target_rank, bid_cap, version, created_at, updated_at) "
            "VALUES ('site', 's1', 10080, 60, 1, 1000, 0, datetime('now'), datetime('now'))"
        )


def test_delete_with_version(temp_db: Path) -> None:
    with write_transaction() as conn:
        sites.create(conn, SiteCreate(id="s1", name="Site 1"))
        p = policies.create(
            conn,
            PolicyCreate(
                scope_type="site",
                scope_id="s1",
                start_minute_of_week=0,
                duration_minutes=60,
                target_rank=2,
                bid_cap=3000,
            ),
        )
        policies.delete(conn, p.id, expected_version=0)
    with get_connection() as conn:
        assert policies.get(conn, p.id) is None
