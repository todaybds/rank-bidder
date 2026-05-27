"""Naver SA API client 예외 계층 (Story 1.5).

호출자가 분기해서 처리:
- ``NaverInvalidRequest`` (400) — 입력 잘못, 재시도 의미 없음
- ``NaverKeywordDeleted`` (404) — Naver 관리자에서 KW 삭제됨, cycle_entries → NAVER_DELETED
- ``NaverSANtpDrift`` (403 invalid-timestamp 재동기화 후 재발) — 시계 문제, 운영자 알림
- ``NaverSAUnavailable`` (429/5xx tenacity 재시도 후 실패) — 일시 장애, 다음 사이클로 미룸
- ``NaverSAError`` — 베이스, 위 4개의 super
"""

from __future__ import annotations


class NaverSAError(Exception):
    """Naver SA API 모든 예외의 베이스."""

    def __init__(
        self, message: str, *, status_code: int | None = None, body: object = None
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body


class NaverInvalidRequest(NaverSAError):
    """HTTP 400 — 입력값 잘못. 재시도 무의미. 호출자가 검증·수정 필요."""


class NaverKeywordDeleted(NaverSAError):
    """HTTP 404 — KW가 Naver 관리자에서 삭제됨. D15 (n) NAVER_DELETED 전이."""


class NaverSANtpDrift(NaverSAError):
    """403 invalid-timestamp — NTP 재동기화 1회 시도 후에도 403 재발 시. 운영자 개입 필요."""


class NaverSAUnavailable(NaverSAError):
    """429/5xx — tenacity 1→2→4초 백오프 3회 재시도 후에도 실패. 다음 사이클로 미룸."""
