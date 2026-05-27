"""Bearer 토큰 인증 — Story 4.1 (FR-25, D7·D8·D29).

운영 1인 사용자 + Caddy reverse proxy 전제. 토큰값은 SSM Parameter Store + Vercel env +
Oracle env에 동일 설정 (`RANKBIDDER_AUTH_TOKEN`).

설계 결정:
- env unset → middleware bypass (TestClient/unit test + dev 환경 무회귀).
- env set → 모든 요청 ``Authorization: Bearer <token>`` 매치 필수. 미일치 시 401.
- ``/health`` 는 항상 bypass — systemd/Caddy/uptime probe가 토큰 없이 호출.
- ``hmac.compare_digest`` 로 constant-time compare (timing-attack 차단).
"""

from __future__ import annotations

import hmac
import os
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

ENV_VAR = "RANKBIDDER_AUTH_TOKEN"
BYPASS_PATHS = frozenset({"/health"})


def _expected_token() -> str | None:
    """``RANKBIDDER_AUTH_TOKEN`` env 값. 빈 문자열은 None 취급 (= bypass)."""
    raw = os.environ.get(ENV_VAR)
    if raw is None or raw.strip() == "":
        return None
    return raw


def _extract_bearer(header_value: str | None) -> str | None:
    """``Authorization: Bearer <token>`` 에서 토큰 추출. 형식 어긋나면 None."""
    if header_value is None:
        return None
    parts = header_value.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    return parts[1].strip() or None


async def bearer_middleware(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    """env 설정 시 Bearer 토큰 enforce, 아니면 bypass.

    매 요청 ``_expected_token()`` 호출 — env 변경 즉시 반영 (test isolation).
    """
    expected = _expected_token()
    if expected is None:
        return await call_next(request)

    if request.url.path in BYPASS_PATHS:
        return await call_next(request)

    presented = _extract_bearer(request.headers.get("authorization"))
    if presented is None or not hmac.compare_digest(presented, expected):
        return JSONResponse(
            status_code=401,
            content={"error": {"code": "UNAUTHORIZED", "message": "missing or invalid Bearer"}},
        )
    return await call_next(request)


def install(app: FastAPI) -> None:
    """``app.middleware('http')`` 등록 헬퍼 — main.py 에서 1회 호출."""
    app.middleware("http")(bearer_middleware)
