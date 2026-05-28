"""Smoke tests — handler.lambda_handler.

5 케이스: 403 (no token / wrong token), 400 (invalid body / too many), 200 (happy).
모든 케이스가 ``sample_keyword`` + ``ssm.get_auth_token`` mock — m.search.naver.com
실제 호출 0건 (CI 안전).
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from measurer.handler import lambda_handler

_EXPECTED_TOKEN = "test-token-expected"


def _event(body: str | None, headers: dict[str, str] | None = None) -> dict[str, object]:
    return {
        "version": "2.0",
        "rawPath": "/",
        "requestContext": {"http": {"method": "POST", "path": "/"}},
        "headers": headers or {"content-type": "application/json"},
        "body": body,
        "isBase64Encoded": False,
    }


@pytest.fixture
def _patch_ssm():
    """ssm.get_auth_token → _EXPECTED_TOKEN."""
    with patch("measurer.handler.get_auth_token", return_value=_EXPECTED_TOKEN):
        yield


@pytest.fixture
def _patch_sampler():
    """sample_keyword → 결정적 happy result. Story 1.10 aliases kwarg 수용."""

    def _fake_sample(term: str, samples_n: int, aliases=None) -> dict[str, object]:
        return {
            "samples": [1] * samples_n,
            "chosen_rank": 1,
            "latency_ms": 100,
        }

    with patch("measurer.handler.sample_keyword", side_effect=_fake_sample):
        yield


def _body(payload: dict[str, object]) -> str:
    return json.dumps(payload, ensure_ascii=False)


def test_403_without_auth_token_header(_patch_ssm) -> None:
    event = _event(_body({"keywords": [{"id": "k1", "term": "수자인"}]}))
    response = lambda_handler(event, None)
    assert response["statusCode"] == 403
    body = json.loads(response["body"])
    assert body["error"]["code"] == "INVALID_AUTH_TOKEN"


def test_403_with_wrong_auth_token(_patch_ssm) -> None:
    event = _event(
        _body({"keywords": [{"id": "k1", "term": "수자인"}]}),
        headers={"x-auth-token": "wrong-value"},
    )
    response = lambda_handler(event, None)
    assert response["statusCode"] == 403
    body = json.loads(response["body"])
    assert body["error"]["code"] == "INVALID_AUTH_TOKEN"


def test_400_invalid_body_not_json(_patch_ssm) -> None:
    event = _event("not-json-at-all", headers={"x-auth-token": _EXPECTED_TOKEN})
    response = lambda_handler(event, None)
    assert response["statusCode"] == 400
    body = json.loads(response["body"])
    assert body["error"]["code"] == "INVALID_REQUEST_BODY"


def test_400_body_is_array_not_object(_patch_ssm) -> None:
    event = _event(json.dumps([1, 2, 3]), headers={"x-auth-token": _EXPECTED_TOKEN})
    response = lambda_handler(event, None)
    assert response["statusCode"] == 400
    body = json.loads(response["body"])
    assert body["error"]["code"] == "INVALID_REQUEST_BODY"


def test_400_too_many_keywords(_patch_ssm, _patch_sampler) -> None:
    payload = {
        "keywords": [{"id": f"k{i}", "term": f"term-{i}"} for i in range(51)],
        "samples_n": 3,
    }
    event = _event(_body(payload), headers={"x-auth-token": _EXPECTED_TOKEN})
    response = lambda_handler(event, None)
    assert response["statusCode"] == 400
    body = json.loads(response["body"])
    assert body["error"]["code"] == "TOO_MANY_KEYWORDS"


def test_400_samples_n_out_of_range(_patch_ssm, _patch_sampler) -> None:
    payload = {
        "keywords": [{"id": "k1", "term": "수자인"}],
        "samples_n": 1,  # < 3
    }
    event = _event(_body(payload), headers={"x-auth-token": _EXPECTED_TOKEN})
    response = lambda_handler(event, None)
    assert response["statusCode"] == 400
    body = json.loads(response["body"])
    assert body["error"]["code"] == "INVALID_REQUEST_BODY"


def test_400_keywords_empty_list(_patch_ssm) -> None:
    event = _event(
        _body({"keywords": []}),
        headers={"x-auth-token": _EXPECTED_TOKEN},
    )
    response = lambda_handler(event, None)
    assert response["statusCode"] == 400
    body = json.loads(response["body"])
    assert body["error"]["code"] == "INVALID_REQUEST_BODY"


def test_400_keyword_missing_id(_patch_ssm) -> None:
    event = _event(
        _body({"keywords": [{"term": "수자인"}]}),
        headers={"x-auth-token": _EXPECTED_TOKEN},
    )
    response = lambda_handler(event, None)
    assert response["statusCode"] == 400
    body = json.loads(response["body"])
    assert body["error"]["code"] == "INVALID_REQUEST_BODY"


def test_happy_path_returns_results_array(_patch_ssm, _patch_sampler) -> None:
    payload = {
        "keywords": [
            {"id": "kw-1", "term": "수자인"},
            {"id": "kw-2", "term": "칸타빌"},
        ],
        "samples_n": 3,
    }
    event = _event(_body(payload), headers={"x-auth-token": _EXPECTED_TOKEN})
    response = lambda_handler(event, None)
    assert response["statusCode"] == 200
    assert response["headers"]["Content-Type"] == "application/json"

    body = json.loads(response["body"])
    assert "results" in body
    assert len(body["results"]) == 2

    r1, r2 = body["results"]
    assert r1["id"] == "kw-1"
    assert r1["samples"] == [1, 1, 1]
    assert r1["chosen_rank"] == 1
    assert isinstance(r1["latency_ms"], int)

    assert r2["id"] == "kw-2"
    assert r2["chosen_rank"] == 1


def test_happy_path_default_samples_n_is_3(_patch_ssm, _patch_sampler) -> None:
    payload = {"keywords": [{"id": "k1", "term": "수자인"}]}  # samples_n 미지정
    event = _event(_body(payload), headers={"x-auth-token": _EXPECTED_TOKEN})
    response = lambda_handler(event, None)
    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert len(body["results"][0]["samples"]) == 3


def test_happy_path_with_base64_encoded_body(_patch_ssm, _patch_sampler) -> None:
    import base64

    raw = _body({"keywords": [{"id": "k1", "term": "수자인"}]})
    encoded = base64.b64encode(raw.encode("utf-8")).decode("ascii")
    event = _event(encoded, headers={"x-auth-token": _EXPECTED_TOKEN})
    event["isBase64Encoded"] = True
    response = lambda_handler(event, None)
    assert response["statusCode"] == 200


def test_sampler_exception_returns_per_keyword_measurement_failure(_patch_ssm) -> None:
    """예상 못한 sampler 예외도 keyword isolation — 전체 응답 200, errors[]에 박제."""

    def _explode(term: str, samples_n: int, aliases=None) -> dict[str, object]:
        raise RuntimeError(f"unexpected: {term}")

    payload = {"keywords": [{"id": "k1", "term": "수자인"}], "samples_n": 3}
    event = _event(_body(payload), headers={"x-auth-token": _EXPECTED_TOKEN})

    with patch("measurer.handler.sample_keyword", side_effect=_explode):
        response = lambda_handler(event, None)

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["results"][0]["chosen_rank"] is None
    assert body["results"][0]["errors"][0]["code"] == "MEASUREMENT_FAILURE"


def test_500_when_ssm_load_fails() -> None:
    """SSM 호출 자체가 실패하면 500 INTERNAL_ERROR."""
    event = _event(
        _body({"keywords": [{"id": "k1", "term": "수자인"}]}),
        headers={"x-auth-token": "any"},
    )
    with patch("measurer.handler.get_auth_token", side_effect=RuntimeError("ssm down")):
        response = lambda_handler(event, None)
    assert response["statusCode"] == 500
    body = json.loads(response["body"])
    assert body["error"]["code"] == "INTERNAL_ERROR"


# ---------------------------------------------------------------------------
# Story 1.10 — aliases optional payload field
# ---------------------------------------------------------------------------


def test_aliases_optional_payload_passthrough(_patch_ssm) -> None:
    """aliases 포함한 payload → 200 + sampler가 aliases kwarg으로 받음."""
    received_aliases: list = []

    def _capture(term: str, samples_n: int, aliases=None) -> dict[str, object]:
        received_aliases.append(aliases)
        return {"samples": [1] * samples_n, "chosen_rank": 1, "latency_ms": 100}

    payload = {
        "keywords": [
            {
                "id": "k1",
                "term": "평택고덕동브레인시티비스타동원",
                "aliases": ["평택비스타동원", "브레인시티비스타동원"],
            },
        ],
        "samples_n": 3,
    }
    event = _event(_body(payload), headers={"x-auth-token": _EXPECTED_TOKEN})

    with patch("measurer.handler.sample_keyword", side_effect=_capture):
        response = lambda_handler(event, None)

    assert response["statusCode"] == 200
    assert received_aliases == [["평택비스타동원", "브레인시티비스타동원"]]


def test_aliases_absent_passes_empty_list(_patch_ssm) -> None:
    """aliases 부재 payload → sampler에 aliases=[] 전달 (term-only 동작)."""
    received_aliases: list = []

    def _capture(term: str, samples_n: int, aliases=None) -> dict[str, object]:
        received_aliases.append(aliases)
        return {"samples": [1] * samples_n, "chosen_rank": 1, "latency_ms": 100}

    payload = {"keywords": [{"id": "k1", "term": "수자인"}], "samples_n": 3}
    event = _event(_body(payload), headers={"x-auth-token": _EXPECTED_TOKEN})

    with patch("measurer.handler.sample_keyword", side_effect=_capture):
        response = lambda_handler(event, None)

    assert response["statusCode"] == 200
    assert received_aliases == [[]]


def test_aliases_too_many_returns_400(_patch_ssm, _patch_sampler) -> None:
    """aliases > 20 → 400 INVALID_REQUEST_BODY."""
    payload = {
        "keywords": [{"id": "k1", "term": "수자인", "aliases": [f"a{i}" for i in range(21)]}],
        "samples_n": 3,
    }
    event = _event(_body(payload), headers={"x-auth-token": _EXPECTED_TOKEN})
    response = lambda_handler(event, None)
    assert response["statusCode"] == 400
    body = json.loads(response["body"])
    assert body["error"]["code"] == "INVALID_REQUEST_BODY"
    assert "aliases" in body["error"]["message"].lower()


def test_aliases_non_list_returns_400(_patch_ssm, _patch_sampler) -> None:
    """aliases가 list가 아니면 → 400."""
    payload = {
        "keywords": [{"id": "k1", "term": "수자인", "aliases": "not-a-list"}],
        "samples_n": 3,
    }
    event = _event(_body(payload), headers={"x-auth-token": _EXPECTED_TOKEN})
    response = lambda_handler(event, None)
    assert response["statusCode"] == 400
    body = json.loads(response["body"])
    assert body["error"]["code"] == "INVALID_REQUEST_BODY"


def test_aliases_empty_string_item_returns_400(_patch_ssm, _patch_sampler) -> None:
    """aliases 항목이 공백뿐이면 → 400."""
    payload = {
        "keywords": [{"id": "k1", "term": "수자인", "aliases": ["valid", "   "]}],
        "samples_n": 3,
    }
    event = _event(_body(payload), headers={"x-auth-token": _EXPECTED_TOKEN})
    response = lambda_handler(event, None)
    assert response["statusCode"] == 400
    body = json.loads(response["body"])
    assert body["error"]["code"] == "INVALID_REQUEST_BODY"
