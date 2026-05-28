"""Lambda Function URL handler — SERP Measurer (Story 1.4 LIVE).

Flow:
1. structlog 1회 configure (cold start).
2. body parse — JSON 디코드 실패 → 400 INVALID_REQUEST_BODY.
3. X-Auth-Token 검증 (D9) — fail → 403 INVALID_AUTH_TOKEN.
4. request validate — keywords list / samples_n 범위 (3-5) / max 50 KW.
5. per-keyword ``sample_keyword`` → D13 응답 구조.
6. 응답 200 또는 envelope 에러 (D12).

Function URL payload v2.0 format을 가정 — ``event["headers"]`` lowercase keys,
``event["body"]`` string (possibly base64-encoded). API Gateway v1
(``event["httpMethod"]``)와 다르다는 점 주의.
"""

from __future__ import annotations

import base64
import json
import time
from typing import Any

import structlog

from measurer.auth import get_header, verify_token
from measurer.sampler import sample_keyword
from measurer.ssm import get_auth_token

MAX_KEYWORDS_PER_CALL = 50
SAMPLES_N_MIN = 3
SAMPLES_N_MAX = 5
SAMPLES_N_DEFAULT = 3
#: Story 1.10 — KW alias 최대 개수 (운영자 등록 부담 + parser 비용 cap).
MAX_ALIASES_PER_KEYWORD = 20
#: P1 (review 2026-05-27) — raw body 사이즈 한도. JSON 50 KW × term 평균 30B = 1.5KB 이론치.
#: 여유 있게 256KB로. Function URL 한도(6MB) 한참 아래에서 미리 자른다.
MAX_BODY_BYTES = 256 * 1024

_structlog_configured = False


def _configure_structlog_once() -> None:
    """Cold start 1회만 structlog JSON 출력 configure."""
    global _structlog_configured
    if _structlog_configured:
        return
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True, key="ts"),
            structlog.processors.JSONRenderer(),
        ],
    )
    _structlog_configured = True


log = structlog.get_logger(__name__)


def _ok_response(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(payload, ensure_ascii=False),
    }


def _error_response(status_code: int, code: str, message: str, hint: str) -> dict[str, Any]:
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(
            {"error": {"code": code, "message": message, "hint": hint}},
            ensure_ascii=False,
        ),
    }


def _parse_body(event: dict[str, Any]) -> dict[str, Any]:
    """Function URL body를 JSON dict로 디코드.

    Raises:
        ValueError: body 부재 / base64 디코드 실패 / JSON 디코드 실패 / non-dict.
    """
    raw_body = event.get("body")
    if raw_body is None:
        raise ValueError("body is empty")

    if event.get("isBase64Encoded"):
        try:
            raw_body = base64.b64decode(raw_body).decode("utf-8")
        except (ValueError, UnicodeDecodeError) as exc:
            raise ValueError(f"base64 decode failed: {exc}") from exc

    try:
        parsed = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        raise ValueError(f"json decode failed: {exc}") from exc

    if not isinstance(parsed, dict):
        raise ValueError("body must be JSON object")
    return parsed


def _validate_request(body: dict[str, Any]) -> tuple[list[dict[str, str]], int]:
    """Body 안의 keywords + samples_n 검증.

    Returns:
        (keywords list, samples_n int)

    Raises:
        ValueError: keyword 형식 오류.
        _TooManyKeywordsError: keyword 51개 이상.
    """
    keywords = body.get("keywords")
    if not isinstance(keywords, list) or len(keywords) == 0:
        raise ValueError("keywords must be non-empty list")

    if len(keywords) > MAX_KEYWORDS_PER_CALL:
        raise _TooManyKeywordsError(len(keywords))

    for idx, kw in enumerate(keywords):
        if not isinstance(kw, dict):
            raise ValueError(f"keywords[{idx}] must be object")
        # P3 (review 2026-05-27): str 타입 + strip 후 non-empty 필수 (공백만 거부).
        raw_id = kw.get("id")
        if not isinstance(raw_id, str) or not raw_id.strip():
            raise ValueError(f"keywords[{idx}].id must be non-empty string")
        raw_term = kw.get("term")
        if not isinstance(raw_term, str) or not raw_term.strip():
            raise ValueError(f"keywords[{idx}].term must be non-empty string")
        # 정규화된 값으로 덮어써서 downstream에서 일관 사용.
        kw["id"] = raw_id.strip()
        kw["term"] = raw_term.strip()
        # Story 1.10: aliases optional list[str]. 부재 시 빈 list. 항목 strip+non-empty.
        raw_aliases = kw.get("aliases")
        if raw_aliases is None:
            kw["aliases"] = []
        elif isinstance(raw_aliases, list):
            if len(raw_aliases) > MAX_ALIASES_PER_KEYWORD:
                raise ValueError(
                    f"keywords[{idx}].aliases too many "
                    f"({len(raw_aliases)} > {MAX_ALIASES_PER_KEYWORD})"
                )
            cleaned: list[str] = []
            for j, alias in enumerate(raw_aliases):
                if not isinstance(alias, str) or not alias.strip():
                    raise ValueError(f"keywords[{idx}].aliases[{j}] must be non-empty string")
                cleaned.append(alias.strip())
            kw["aliases"] = cleaned
        else:
            raise ValueError(f"keywords[{idx}].aliases must be list of strings or omitted")

    # D1 (review 2026-05-27): samples_n=3.0 같은 JSON 정수 표기 float 수용.
    #   ``int(v) == v`` 통과 시 정수로 coerce, 외에는 거부. bool은 별도 거부.
    raw_samples_n = body.get("samples_n", SAMPLES_N_DEFAULT)
    if isinstance(raw_samples_n, bool):
        raise ValueError("samples_n must be integer (got bool)")
    if isinstance(raw_samples_n, int):
        samples_n = raw_samples_n
    elif isinstance(raw_samples_n, float) and raw_samples_n.is_integer():
        samples_n = int(raw_samples_n)
    else:
        raise ValueError("samples_n must be integer")
    if not (SAMPLES_N_MIN <= samples_n <= SAMPLES_N_MAX):
        raise ValueError(
            f"samples_n must be in [{SAMPLES_N_MIN}, {SAMPLES_N_MAX}], got {samples_n}"
        )

    return keywords, samples_n


class _TooManyKeywordsError(Exception):
    """Internal — 51개 이상 KW를 400 TOO_MANY_KEYWORDS로 변환하기 위한 sentinel."""

    def __init__(self, count: int) -> None:
        super().__init__(f"got {count} keywords, max {MAX_KEYWORDS_PER_CALL}")
        self.count = count


def lambda_handler(event: dict[str, Any], _context: object) -> dict[str, Any]:
    """Function URL POST → multi-sampled SERP rank 응답.

    Args:
        event: Function URL payload v2.0.
        _context: Lambda context (사용 안 함).

    Returns:
        v2.0 응답 dict (statusCode, headers, body).
    """
    _configure_structlog_once()
    start = time.perf_counter()

    # P1 (review 2026-05-27): body 사이즈 가드를 가장 먼저. 인증 전 무거운 파싱 차단.
    raw_body = event.get("body") or ""
    if not isinstance(raw_body, str):
        raw_body = str(raw_body)
    if len(raw_body) > MAX_BODY_BYTES:
        log.warning("request.body_too_large", size=len(raw_body))
        return _error_response(
            413,
            "BODY_TOO_LARGE",
            f"Request body exceeds {MAX_BODY_BYTES} bytes",
            f"Send <= {MAX_BODY_BYTES // 1024} KB per call (max 50 keywords)",
        )

    # P1 (review 2026-05-27): 1. auth check를 body JSON parse 앞으로 — pre-auth attack surface 차단.
    headers = event.get("headers")
    if not isinstance(headers, dict):
        headers = {}
    provided = get_header(headers, "X-Auth-Token")
    try:
        expected = get_auth_token()
    except Exception as exc:  # noqa: BLE001 — SSM 부재/권한/runtime 모두 500
        log.error("auth.ssm_load_failed", error=str(exc))
        return _error_response(
            500,
            "INTERNAL_ERROR",
            "Auth token could not be loaded from SSM",
            "Check Lambda execution role + SSM parameter existence",
        )
    if not verify_token(provided, expected):
        log.warning("auth.token_mismatch", provided_present=provided is not None)
        return _error_response(
            403,
            "INVALID_AUTH_TOKEN",
            "X-Auth-Token header missing or invalid",
            "Set X-Auth-Token to the value stored in SSM /rank-bidder/lambda/auth-token",
        )

    # 2. body parse (인증 통과 후)
    try:
        body = _parse_body(event)
    except ValueError as exc:
        log.warning("request.invalid_body", error=str(exc))
        return _error_response(
            400,
            "INVALID_REQUEST_BODY",
            f"Request body could not be parsed: {exc}",
            "Send JSON object: {keywords:[{id,term},...], samples_n?:3-5}",
        )

    # 3. validate
    try:
        keywords, samples_n = _validate_request(body)
    except _TooManyKeywordsError as exc:
        log.warning("request.too_many_keywords", count=exc.count)
        return _error_response(
            400,
            "TOO_MANY_KEYWORDS",
            str(exc),
            f"Split into batches of {MAX_KEYWORDS_PER_CALL} keywords per call",
        )
    except ValueError as exc:
        log.warning("request.validation_failed", error=str(exc))
        return _error_response(
            400,
            "INVALID_REQUEST_BODY",
            str(exc),
            "Each keyword must be {id:str, term:str}; samples_n must be int in [3,5]",
        )

    log.info("request.received", kw_count=len(keywords), samples_n=samples_n)

    # 4. process each keyword
    results: list[dict[str, Any]] = []
    success_count = 0
    failure_count = 0
    for kw in keywords:
        try:
            kw_result = sample_keyword(kw["term"], samples_n, aliases=kw.get("aliases", []))
        except Exception as exc:  # noqa: BLE001 — KW 단위 isolation
            log.error("sampler.unexpected_error", id=kw["id"], term=kw["term"], error=str(exc))
            kw_result = {
                "samples": [None] * samples_n,
                "chosen_rank": None,
                "latency_ms": 0,
                "errors": [
                    {
                        "code": "MEASUREMENT_FAILURE",
                        "message": f"unexpected error: {exc}",
                        "valid_count": 0,
                    }
                ],
            }
        kw_result["id"] = kw["id"]
        if kw_result.get("chosen_rank") is not None:
            success_count += 1
        else:
            failure_count += 1
        results.append(kw_result)

    total_latency_ms = int((time.perf_counter() - start) * 1000)
    log.info(
        "request.completed",
        total_latency_ms=total_latency_ms,
        success_count=success_count,
        failure_count=failure_count,
    )

    return _ok_response({"results": results})
