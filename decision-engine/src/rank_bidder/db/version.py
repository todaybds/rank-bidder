"""Optimistic version counter helper — D5.

직접 ``conn.execute("UPDATE ...")``로 mutation하지 말 것. 모든 row update는
``update_with_version()`` 경유 — silent overwrite 차단 (D5) + ``updated_at`` 자동 갱신.
"""

from __future__ import annotations

import sqlite3


class VersionConflictError(Exception):
    """Optimistic concurrency 충돌 — HTTP 409로 매핑."""

    def __init__(self, table: str, row_id: str, expected_version: int, current_version: int | None):
        self.table = table
        self.row_id = row_id
        self.expected_version = expected_version
        self.current_version = current_version
        if current_version is None:
            msg = f"{table}({row_id}) 행 없음 — expected_version={expected_version}"
        else:
            msg = (
                f"{table}({row_id}) version 충돌 — "
                f"expected={expected_version}, current={current_version}"
            )
        super().__init__(msg)


def update_with_version(
    conn: sqlite3.Connection,
    table: str,
    row_id: str,
    expected_version: int,
    set_clause: str,
    set_params: tuple,
) -> int:
    """``UPDATE <table> SET <set_clause>, version=version+1, updated_at=now() WHERE id=? AND version=?``.

    Args:
        set_clause: SET 절의 컬럼 부분만 (예: ``"name=?, enabled=?"``). version·updated_at은 함수가 자동 추가.
        set_params: ``set_clause``의 placeholder 값 tuple (id·expected_version 미포함).

    Returns:
        새 version 번호 (= ``expected_version + 1``).

    Raises:
        VersionConflictError: row 없거나 version mismatch.
    """
    full_clause = f"{set_clause}, version = version + 1, updated_at = datetime('now')"
    sql = f"UPDATE {table} SET {full_clause} WHERE id = ? AND version = ?"
    params = (*set_params, row_id, expected_version)

    cursor = conn.execute(sql, params)
    if cursor.rowcount == 0:
        row = conn.execute(f"SELECT version FROM {table} WHERE id = ?", (row_id,)).fetchone()
        current = int(row["version"]) if row is not None else None
        raise VersionConflictError(table, row_id, expected_version, current)
    return expected_version + 1
