"""X-Auth-Token 검증 (D9, timing-safe).

Function URL은 AuthType=NONE이지만 handler 첫 줄에서 header 값을 SSM 값과
constant-time 비교해 우회 차단. NFR-7 준수.
"""

from __future__ import annotations

import hmac


def get_header(headers: dict[str, str], name: str) -> str | None:
    """대소문자 무시 헤더 조회.

    Function URL payload v2.0은 header 키가 lowercase로 정규화되지만,
    로컬 sam local invoke 등에서 mixed-case가 올 수 있어 방어적 lookup.

    Args:
        headers: ``event["headers"]`` dict (없을 수 있어 호출자가 빈 dict 전달).
        name: 조회 헤더 이름 (예: ``"X-Auth-Token"``).

    Returns:
        헤더 값 또는 None.
    """
    target = name.lower()
    for key, value in headers.items():
        if key.lower() == target:
            return value
    return None


def verify_token(provided: str | None, expected: str) -> bool:
    """Constant-time 비교로 token 검증.

    ``provided`` 가 None/빈 문자열/길이 다름이어도 timing-safe하게 False 반환.

    Args:
        provided: 요청에서 추출한 X-Auth-Token 값.
        expected: SSM에서 로드한 기대값.

    Returns:
        True if 정확히 일치, 아니면 False.
    """
    if provided is None or not provided:
        return False
    if expected is None or not expected:
        # P0 (review 2026-05-27): expected가 빈 문자열이면 compare_digest 무력화.
        return False
    return hmac.compare_digest(provided.encode("utf-8"), expected.encode("utf-8"))
