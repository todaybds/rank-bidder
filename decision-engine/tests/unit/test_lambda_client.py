"""Story 2.1 hot-fix (2026-05-28) — lambda_client.serp.measure_keywords.

본 테스트는 VM-local fetch+parse 전환(2026-05-28) 이후의 unit test.
옛 Lambda HTTP mock 테스트는 같은 commit에서 폐기 (httpx/MockTransport, chunk loop
등은 더 이상 작동하지 않음). 모듈명 'lambda_client'는 backward-compat 유지, rename은
cleanup epic.

검증 범위:
  - keywords 시퀀스 → sample_keyword per-KW 호출 + 응답 dict에 id 박제
  - aliases 정상 passthrough
  - 빈 id/term은 INVALID_KEYWORD 에러 박스
  - 시그니처 옵션(chunk_size/function_url 등)은 backward-compat 위해 받기만
"""

from __future__ import annotations

from unittest.mock import patch

from rank_bidder.lambda_client.serp import LambdaClientError, measure_keywords


def _fake_sample_result(samples_n: int = 3) -> dict:
    return {
        "samples": [1] * samples_n,
        "chosen_rank": 1,
        "latency_ms": 123,
        "mode_count": 1,
        "dispersion": 0,
        "unique_count": 1,
    }


def test_measure_keywords_calls_sample_per_kw_and_attaches_id() -> None:
    keywords = [
        {"id": "kw-A", "term": "수자인", "aliases": ["수자인아파트"]},
        {"id": "kw-B", "term": "비스타동원"},
    ]
    # side_effect로 매 호출마다 새 dict 반환 — 같은 dict 객체 공유 시 id 덮어쓰기 방어.
    with patch(
        "rank_bidder.lambda_client.serp.sample_keyword",
        side_effect=lambda *a, **kw: _fake_sample_result(),
    ) as mock_sample:
        results = measure_keywords(keywords, samples_n=3)

    assert mock_sample.call_count == 2
    # aliases passthrough — kw-A는 list, kw-B는 None
    call_A = mock_sample.call_args_list[0]
    call_B = mock_sample.call_args_list[1]
    assert call_A.args[0] == "수자인" and call_A.args[1] == 3
    assert call_A.kwargs["aliases"] == ["수자인아파트"]
    assert call_B.args[0] == "비스타동원"
    assert call_B.kwargs["aliases"] is None

    # 응답 형태 — id 박제 + sample_keyword 응답 전체 보존
    assert [r["id"] for r in results] == ["kw-A", "kw-B"]
    assert results[0]["chosen_rank"] == 1
    assert results[0]["samples"] == [1, 1, 1]


def test_measure_keywords_invalid_kw_returns_error_box() -> None:
    keywords = [
        {"id": "", "term": "수자인"},     # id 비어있음
        {"id": "kw-X", "term": ""},        # term 비어있음
        {"id": "kw-OK", "term": "비스타동원"},
    ]
    with patch(
        "rank_bidder.lambda_client.serp.sample_keyword",
        side_effect=lambda *a, **kw: _fake_sample_result(),
    ) as mock_sample:
        results = measure_keywords(keywords, samples_n=3)

    # 유효 KW 1개만 sample_keyword 호출
    assert mock_sample.call_count == 1
    assert len(results) == 3
    assert results[0]["errors"][0]["code"] == "INVALID_KEYWORD"
    assert results[1]["errors"][0]["code"] == "INVALID_KEYWORD"
    assert results[2]["chosen_rank"] == 1


def test_legacy_lambda_options_accepted_and_ignored() -> None:
    """chunk_size / function_url / auth_token / client 옵션은 backward-compat 위해 무시."""
    with patch(
        "rank_bidder.lambda_client.serp.sample_keyword",
        return_value=_fake_sample_result(),
    ) as mock_sample:
        results = measure_keywords(
            [{"id": "k", "term": "t"}],
            samples_n=3,
            timeout_s=99.0,
            chunk_size=999,
            function_url="https://ignored",
            auth_token="ignored",
            client=object(),  # 무시됨
        )
    assert mock_sample.call_count == 1
    assert results[0]["id"] == "k"


def test_lambda_client_error_class_still_exists() -> None:
    """backward-compat: cycle_full이 LambdaClientError를 import 중."""
    assert issubclass(LambdaClientError, Exception)
