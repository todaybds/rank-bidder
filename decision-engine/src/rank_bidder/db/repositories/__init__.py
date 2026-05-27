"""DB repositories — per-table CRUD with D5 version checks.

각 repository 함수는 ``conn``을 인자로 받는다 (호출자가 ``write_transaction()`` /
``get_connection()``으로 수명 관리). 본 패키지 내부에서 ``sqlite3.connect`` 직접 호출 금지.
"""

from rank_bidder.db.repositories import (
    campaigns,
    cycle_entries,
    decisions,
    keywords,
    measurements,
    notifications,
    policies,
    runtime_config,
    sites,
)

__all__ = [
    "campaigns",
    "cycle_entries",
    "decisions",
    "keywords",
    "measurements",
    "notifications",
    "policies",
    "runtime_config",
    "sites",
]
