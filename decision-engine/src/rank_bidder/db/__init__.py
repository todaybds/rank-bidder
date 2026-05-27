"""SQLite data layer — D1·D2·D4·D5·D15(b,h,j,m).

Public API:
- ``get_connection()`` — READ context manager. WAL 모드라 lock 무관.
- ``write_transaction()`` — 모든 mutation 경로. file lock + BEGIN IMMEDIATE.
- ``SQLiteBusyError`` — file lock 5s timeout 초과.
- ``VersionConflictError`` — D5 optimistic version mismatch.
- ``configure(path)`` — 테스트용 DB 경로 주입.

직접 ``sqlite3.connect``로 write 금지 (architecture §Enforcement).
"""

from rank_bidder.db.connection import (
    SQLiteBusyError,
    configure,
    get_connection,
    write_transaction,
)
from rank_bidder.db.version import VersionConflictError

__all__ = [
    "SQLiteBusyError",
    "VersionConflictError",
    "configure",
    "get_connection",
    "write_transaction",
]
