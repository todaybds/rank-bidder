"""Pytest conftest — Story 1.4.

- ``sys.path``에 ``src/`` 추가 (Lambda runtime PYTHONPATH 미러).
- ``measurer.ssm._cached_token`` autouse reset (테스트 간 cache 누수 방지).
- ``AUTH_TOKEN_PARAMETER_NAME`` env autouse 박제 (SSM mock 없이 ssm.py가 raise하지 않도록).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Allow `from measurer import ...` from tests (mirrors Lambda runtime PYTHONPATH).
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


@pytest.fixture(autouse=True)
def _reset_ssm_cache_and_env(monkeypatch: pytest.MonkeyPatch):
    """매 테스트 시작 시 SSM cache + env 초기화."""
    from measurer import ssm  # 지연 import — sys.path 셋업 후.

    ssm._cached_token = None
    monkeypatch.setenv("AUTH_TOKEN_PARAMETER_NAME", "/rank-bidder/lambda/auth-token")
    yield
    ssm._cached_token = None
