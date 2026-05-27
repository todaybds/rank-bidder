"""Monotonic UUID v7 generator (Story 1.7, I5).

자작 v1 폐기 사유 = "측정 안된 가정". UUID v7은 timestamp + random이라 자연스럽게 단조
증가지만 — 시계 역행(NTP resync 직후 등) 시 strictly increasing 보장 안 됨.
본 모듈은 마지막 발급된 UUID를 메모리에 보관하고, 신규가 그보다 작거나 같으면 +1로 강제.

I5: UUID v7 generator는 monotonic — 시계 역행 시에도 strictly increasing.
"""

from __future__ import annotations

import threading
import uuid as _stdlib_uuid

import uuid_utils

_LOCK = threading.Lock()
_LAST: _stdlib_uuid.UUID | None = None


def _to_stdlib(u: object) -> _stdlib_uuid.UUID:
    """uuid_utils.UUID → stdlib uuid.UUID (비교 가능 + str()로 동일 직렬화)."""
    return _stdlib_uuid.UUID(str(u))


def new_cycle_id() -> str:
    """Monotonic UUID v7 string.

    동시 호출 / 시계 역행 시에도 last + 1 (정수 비교)로 strictly increasing 보장.
    반환: 표준 8-4-4-4-12 hex string (D15 cycle_id PRIMARY KEY TEXT).
    """
    global _LAST
    with _LOCK:
        candidate = _to_stdlib(uuid_utils.uuid7())
        if _LAST is not None and candidate.int <= _LAST.int:
            # 시계 역행 또는 동일 nanosecond → last + 1 강제
            candidate = _stdlib_uuid.UUID(int=_LAST.int + 1)
        _LAST = candidate
        return str(candidate)


def reset_for_test() -> None:
    """Test fixture용 — 모듈 전역 _LAST 초기화. 운영 코드에서 호출 금지."""
    global _LAST
    with _LOCK:
        _LAST = None
