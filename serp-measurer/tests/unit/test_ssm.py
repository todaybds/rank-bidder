"""Unit tests — ssm.get_auth_token (boto3 mock + cache).

moto 의존 추가 회피 — unittest.mock.patch("boto3.client")만 사용 (NFR-8).
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest
from measurer import ssm


@pytest.fixture(autouse=True)
def _reset_cache_and_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """매 테스트 시작 시 module cache + env 초기화."""
    ssm._cached_token = None
    monkeypatch.setenv("AUTH_TOKEN_PARAMETER_NAME", "/rank-bidder/lambda/auth-token")


def _make_ssm_client_mock(value: str) -> MagicMock:
    client = MagicMock()
    client.get_parameter.return_value = {"Parameter": {"Value": value}}
    return client


def test_first_call_fetches_from_ssm() -> None:
    fake_client = _make_ssm_client_mock("secret-token-32-chars-aaaaaaaaaaaaaa")
    with patch("measurer.ssm.boto3.client", return_value=fake_client) as boto_factory:
        token = ssm.get_auth_token()
    assert token == "secret-token-32-chars-aaaaaaaaaaaaaa"
    boto_factory.assert_called_once_with("ssm")
    fake_client.get_parameter.assert_called_once_with(
        Name="/rank-bidder/lambda/auth-token",
        WithDecryption=True,
    )


def test_second_call_hits_cache_no_boto3_invocation() -> None:
    fake_client = _make_ssm_client_mock("cached-token")
    with patch("measurer.ssm.boto3.client", return_value=fake_client) as boto_factory:
        first = ssm.get_auth_token()
        second = ssm.get_auth_token()
        third = ssm.get_auth_token()
    assert first == second == third == "cached-token"
    boto_factory.assert_called_once()
    fake_client.get_parameter.assert_called_once()


def test_missing_env_var_raises_runtime_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AUTH_TOKEN_PARAMETER_NAME", raising=False)
    with pytest.raises(RuntimeError, match="AUTH_TOKEN_PARAMETER_NAME"):
        ssm.get_auth_token()


def test_empty_env_var_raises_runtime_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTH_TOKEN_PARAMETER_NAME", "")
    with pytest.raises(RuntimeError, match="AUTH_TOKEN_PARAMETER_NAME"):
        ssm.get_auth_token()


def test_uses_env_var_for_parameter_name() -> None:
    """env var이 다른 값으로 박제되면 boto3 call도 그 값으로."""
    os.environ["AUTH_TOKEN_PARAMETER_NAME"] = "/custom/path"
    fake_client = _make_ssm_client_mock("v")
    with patch("measurer.ssm.boto3.client", return_value=fake_client):
        ssm.get_auth_token()
    fake_client.get_parameter.assert_called_once_with(Name="/custom/path", WithDecryption=True)
