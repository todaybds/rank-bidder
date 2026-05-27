"""Unit tests — sampler.sample_keyword.

fetch_serp_html을 mock해 시퀀스 통제. parser.extract_rank는 실제 동작
(html=None이면 sampler가 None 처리). 더 단순한 mock 전략은 fetch + extract를
한 번에 mock하는 것 — 그렇게 진행.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from measurer import sampler


def _mock_pipeline(rank_sequence: list[int | None]):
    """fetch_serp_html + extract_rank 조합을 ``rank_sequence`` 그대로 반환하도록.

    각 호출에서 (html_str, 200) 또는 (None, 0) 반환. html이 None이면 sampler가
    extract_rank 호출 안 함. html이 string이면 extract_rank가 mock된 값을 반환.
    """
    fetch_returns = [("html", 200) if r is not None else (None, 0) for r in rank_sequence]
    extract_returns = [r for r in rank_sequence if r is not None]

    fetch_patch = patch.object(sampler, "fetch_serp_html", side_effect=fetch_returns)
    extract_patch = patch.object(sampler, "extract_rank", side_effect=extract_returns)
    return fetch_patch, extract_patch


def test_three_valid_unique_mode_returns_that_rank() -> None:
    """[1, 2, 1] → mode=1 (2회) vs 2 (1회) → chosen=1."""
    fp, ep = _mock_pipeline([1, 2, 1])
    with fp, ep:
        result = sampler.sample_keyword("수자인", 3)
    assert result["samples"] == [1, 2, 1]
    assert result["chosen_rank"] == 1
    assert "errors" not in result
    assert isinstance(result["latency_ms"], int)


def test_two_valid_tie_returns_median_low() -> None:
    """[1, 2] — 두 값 동률, median_low([1,2])=1."""
    fp, ep = _mock_pipeline([1, 2])
    with fp, ep:
        result = sampler.sample_keyword("수자인", 2)
    assert result["samples"] == [1, 2]
    assert result["chosen_rank"] == 1
    assert "errors" not in result


def test_three_valid_tie_returns_median_low() -> None:
    """[3, 1, 2] — 세 값 동률, median_low([3,1,2]) → sorted=[1,2,3], median_low=2."""
    fp, ep = _mock_pipeline([3, 1, 2])
    with fp, ep:
        result = sampler.sample_keyword("수자인", 3)
    assert result["chosen_rank"] == 2


def test_one_valid_returns_measurement_failure() -> None:
    """[None, 1, None] valid=1 → chosen=None + MEASUREMENT_FAILURE."""
    fp, ep = _mock_pipeline([None, 1, None])
    with fp, ep:
        result = sampler.sample_keyword("수자인", 3)
    assert result["samples"] == [None, 1, None]
    assert result["chosen_rank"] is None
    assert result["errors"] == [
        {
            "code": "MEASUREMENT_FAILURE",
            "message": "valid samples < 2",
            "valid_count": 1,
        }
    ]


def test_all_none_returns_measurement_failure_with_count_zero() -> None:
    fp, ep = _mock_pipeline([None, None, None])
    with fp, ep:
        result = sampler.sample_keyword("수자인", 3)
    assert result["samples"] == [None, None, None]
    assert result["chosen_rank"] is None
    assert result["errors"][0]["valid_count"] == 0


def test_samples_n_5_all_same_rank() -> None:
    fp, ep = _mock_pipeline([2, 2, 2, 2, 2])
    with fp, ep:
        result = sampler.sample_keyword("수자인", 5)
    assert result["samples"] == [2, 2, 2, 2, 2]
    assert result["chosen_rank"] == 2


def test_latency_ms_is_non_negative_integer() -> None:
    fp, ep = _mock_pipeline([1, 1])
    with fp, ep:
        result = sampler.sample_keyword("t", 2)
    assert isinstance(result["latency_ms"], int)
    assert result["latency_ms"] >= 0


def test_samples_n_zero_returns_measurement_failure() -> None:
    """방어적 — samples_n=0이면 valid 0 → MEASUREMENT_FAILURE.

    실제 handler는 3-5 validation으로 차단하지만 sampler 자체는 받은 값 그대로 사용.
    """
    fp, ep = _mock_pipeline([])
    with fp, ep:
        result = sampler.sample_keyword("t", 0)
    assert result["samples"] == []
    assert result["chosen_rank"] is None
    assert result["errors"][0]["valid_count"] == 0


def test_two_none_one_valid_returns_failure() -> None:
    """경계 — valid=1, samples_n=3."""
    fp, ep = _mock_pipeline([1, None, None])
    with fp, ep:
        result = sampler.sample_keyword("t", 3)
    assert result["chosen_rank"] is None
    assert result["errors"][0]["valid_count"] == 1


def test_samples_preserves_none_positions() -> None:
    """raw samples 배열에 None 위치가 그대로 유지 (D13 contract)."""
    fp, ep = _mock_pipeline([1, None, 2])
    with fp, ep:
        result = sampler.sample_keyword("t", 3)
    assert result["samples"] == [1, None, 2]
    # valid=2 → mode 동률 → median_low([1,2])=1
    assert result["chosen_rank"] == 1


@pytest.fixture(autouse=True)
def _silence_structlog(monkeypatch: pytest.MonkeyPatch) -> None:
    """테스트 중 structlog 출력 억제 — 가독성."""
    import logging

    logging.disable(logging.CRITICAL)
    yield
    logging.disable(logging.NOTSET)
