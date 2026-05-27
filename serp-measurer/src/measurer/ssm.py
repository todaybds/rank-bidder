"""SSM Parameter Store auth-token loader (D9).

Lambda cold start에 1회 boto3 GetParameter → module-level cache. Warm
invocation은 메모리 캐시 hit (boto3 호출 0건).
"""

from __future__ import annotations

import os

import boto3

_cached_token: str | None = None


def get_auth_token() -> str:
    """SSM SecureString `${AUTH_TOKEN_PARAMETER_NAME}` 값을 반환.

    첫 호출 시 boto3로 fetch + cache. 이후 호출은 cache hit.

    Returns:
        Decrypted SecureString 값.

    Raises:
        RuntimeError: ``AUTH_TOKEN_PARAMETER_NAME`` env var 미설정 시.
        botocore.exceptions.ClientError: SSM 호출 실패 (권한·parameter 부재 등).
    """
    global _cached_token
    if _cached_token is not None:
        return _cached_token

    parameter_name = os.environ.get("AUTH_TOKEN_PARAMETER_NAME")
    if not parameter_name:
        raise RuntimeError(
            "AUTH_TOKEN_PARAMETER_NAME env var not set "
            "(should be wired via template.yaml Environment.Variables)"
        )

    client = boto3.client("ssm")
    response = client.get_parameter(Name=parameter_name, WithDecryption=True)
    _cached_token = response["Parameter"]["Value"]
    return _cached_token
