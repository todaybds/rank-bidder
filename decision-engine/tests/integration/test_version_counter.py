"""AC4 — D5 optimistic version counter."""

from __future__ import annotations

from pathlib import Path

import pytest
from rank_bidder.db import VersionConflictError, get_connection, write_transaction
from rank_bidder.db.models import SiteCreate, SiteUpdate
from rank_bidder.db.repositories import sites as sites_repo


def test_update_increments_version_on_match(temp_db: Path) -> None:
    with write_transaction() as conn:
        site = sites_repo.create(conn, SiteCreate(id="s-1", name="kantavil"))
    assert site.version == 0

    with write_transaction() as conn:
        updated = sites_repo.update(conn, "s-1", SiteUpdate(enabled=False), expected_version=0)
    assert updated.version == 1
    assert updated.enabled is False


def test_update_raises_on_version_mismatch(temp_db: Path) -> None:
    with write_transaction() as conn:
        sites_repo.create(conn, SiteCreate(id="s-1", name="kantavil"))
        sites_repo.update(conn, "s-1", SiteUpdate(enabled=False), expected_version=0)
        # 현재 version = 1

    with write_transaction() as conn, pytest.raises(VersionConflictError) as exc_info:
        sites_repo.update(conn, "s-1", SiteUpdate(enabled=True), expected_version=0)
    assert exc_info.value.current_version == 1
    assert exc_info.value.expected_version == 0


def test_update_raises_on_missing_row(temp_db: Path) -> None:
    with write_transaction() as conn, pytest.raises(VersionConflictError) as exc_info:
        sites_repo.update(conn, "ghost", SiteUpdate(enabled=True), expected_version=0)
    assert exc_info.value.current_version is None


def test_delete_with_version_check(temp_db: Path) -> None:
    with write_transaction() as conn:
        sites_repo.create(conn, SiteCreate(id="s-x", name="x"))
    with write_transaction() as conn:
        sites_repo.delete(conn, "s-x", expected_version=0)
    with get_connection() as conn:
        assert sites_repo.get(conn, "s-x") is None


def test_noop_update_rejects_stale_version(temp_db: Path) -> None:
    """P2: payload 전체 None이어도 version mismatch면 VersionConflictError.

    이전 회귀: empty SiteUpdate + 잘못된 expected_version → 조용히 existing 반환
    (lost-update 감지 우회).
    """
    with write_transaction() as conn:
        sites_repo.create(conn, SiteCreate(id="s-noop", name="n"))
        sites_repo.update(conn, "s-noop", SiteUpdate(enabled=False), expected_version=0)
        # 현재 version = 1

    with write_transaction() as conn, pytest.raises(VersionConflictError) as exc_info:
        sites_repo.update(conn, "s-noop", SiteUpdate(), expected_version=0)
    assert exc_info.value.current_version == 1
    assert exc_info.value.expected_version == 0


def test_delete_rejects_stale_version(temp_db: Path) -> None:
    with write_transaction() as conn:
        sites_repo.create(conn, SiteCreate(id="s-y", name="y"))
        sites_repo.update(conn, "s-y", SiteUpdate(enabled=False), expected_version=0)
    with write_transaction() as conn, pytest.raises(VersionConflictError):
        sites_repo.delete(conn, "s-y", expected_version=0)
