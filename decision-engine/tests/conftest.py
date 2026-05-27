"""Pytest conftest — Story 1.2 SQLite fixture 추가.

- ``temp_db``: 임시 경로 + connection.configure() + migration up → yield path → 정리.
- ``empty_db``: migration 적용 없이 빈 DB 경로만.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from rank_bidder.db import configure
from rank_bidder.db.migrate import DEFAULT_MIGRATIONS_DIR, up


@pytest.fixture
def empty_db(tmp_path: Path) -> Iterator[Path]:
    """빈 DB 파일 경로 — configure만 적용, 마이그레이션 X."""
    db_path = tmp_path / "test.db"
    configure(db_path)
    yield db_path
    # tmp_path 자동 cleanup이 WAL/lock 파일까지 처리.


@pytest.fixture
def temp_db(tmp_path: Path) -> Iterator[Path]:
    """마이그레이션 적용된 DB 경로 — 대부분의 integration test가 사용."""
    db_path = tmp_path / "test.db"
    configure(db_path)
    up(DEFAULT_MIGRATIONS_DIR)
    yield db_path
