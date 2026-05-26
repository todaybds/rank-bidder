"""Smoke test — Story 1.1.

Real handler tests arrive in Story 1.4 (HTML fixture 기반 파싱 검증).
"""

import json

from measurer.handler import lambda_handler


def test_smoke_handler_stub_returns_501() -> None:
    """Story 1.1 placeholder returns NOT_IMPLEMENTED."""
    response = lambda_handler({}, None)
    assert response["statusCode"] == 501
    body = json.loads(response["body"])
    assert body["error"]["code"] == "NOT_IMPLEMENTED"
