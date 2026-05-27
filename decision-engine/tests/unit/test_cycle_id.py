"""Story 1.7 — monotonic UUID v7 cycle_id."""

from __future__ import annotations

import uuid as _uuid

from rank_bidder.engine import cycle_id


def setup_function() -> None:
    cycle_id.reset_for_test()


def test_returns_uuid_v7_format() -> None:
    cid = cycle_id.new_cycle_id()
    parsed = _uuid.UUID(cid)
    assert parsed.version == 7


def test_monotonic_strictly_increasing_burst() -> None:
    """1000회 연속 호출 모두 strictly increasing."""
    last = _uuid.UUID(cycle_id.new_cycle_id())
    for _ in range(1000):
        nxt = _uuid.UUID(cycle_id.new_cycle_id())
        assert nxt.int > last.int, f"non-monotonic: {nxt} <= {last}"
        last = nxt


def test_monotonic_under_clock_reversal(monkeypatch) -> None:
    """uuid_utils.uuid7가 작은 값을 반환하도록 mock → last+1 강제 확인 (I5)."""
    import rank_bidder.engine.cycle_id as cid_mod

    # 첫 호출 — 정상.
    first_str = cid_mod.new_cycle_id()
    first = _uuid.UUID(first_str)

    # 두번째 호출 — uuid_utils.uuid7이 first보다 작은 값을 반환하도록 mock.
    smaller_int = first.int - 1_000_000
    # Python stdlib UUID는 version=7을 거부 (RFC 9562). 비교만 하므로 raw int 사용.
    smaller = _uuid.UUID(int=smaller_int)

    class _FakeMod:
        @staticmethod
        def uuid7() -> _uuid.UUID:
            return smaller

    monkeypatch.setattr(cid_mod, "uuid_utils", _FakeMod)
    second = _uuid.UUID(cid_mod.new_cycle_id())
    assert second.int == first.int + 1, "시계 역행에도 last+1 보장"


def test_reset_for_test_clears_state() -> None:
    first = cycle_id.new_cycle_id()
    cycle_id.reset_for_test()
    second = cycle_id.new_cycle_id()
    # reset 후엔 비교 없이 새로 생성 → 시간 충분히 지났으면 자연스럽게 second > first.
    # (이 test의 의도는 reset이 raise 안 한다는 것 + 다시 호출 가능 검증.)
    assert _uuid.UUID(first).version == 7
    assert _uuid.UUID(second).version == 7
