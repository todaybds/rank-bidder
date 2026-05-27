"""Dry-run pytest fixtures — env 검증 + 결과 디렉토리."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from typing import NamedTuple

import pytest


class NaverCreds(NamedTuple):
    api_key: str
    secret_key: str
    customer_id: str
    base_url: str
    test_keyword_id: str


@pytest.fixture(scope="session")
def naver_creds() -> NaverCreds:
    """필수 env 검증 후 자격증명 묶음 반환. 누락 시 명확한 SKIP."""
    api_key = os.environ.get("RANKBIDDER_NAVER_SA_API_KEY", "")
    secret_key = os.environ.get("RANKBIDDER_NAVER_SA_SECRET_KEY", "")
    customer_id = os.environ.get("RANKBIDDER_NAVER_SA_CUSTOMER_ID", "")
    base_url = os.environ.get("RANKBIDDER_NAVER_SA_BASE_URL", "https://api.searchad.naver.com")
    test_kw_id = os.environ.get("RANKBIDDER_NAVER_SA_TEST_KEYWORD_ID", "")

    missing = [
        name
        for name, val in [
            ("RANKBIDDER_NAVER_SA_API_KEY", api_key),
            ("RANKBIDDER_NAVER_SA_SECRET_KEY", secret_key),
            ("RANKBIDDER_NAVER_SA_CUSTOMER_ID", customer_id),
            ("RANKBIDDER_NAVER_SA_TEST_KEYWORD_ID", test_kw_id),
        ]
        if not val
    ]
    if missing:
        pytest.skip(f"dry-run env 누락: {', '.join(missing)} — .env 또는 shell env 설정 필요.")

    return NaverCreds(api_key, secret_key, customer_id, base_url, test_kw_id)


@pytest.fixture(scope="session")
def results_dir() -> Path:
    """``tests/dry_run/results/`` — gitignore 등록됨."""
    path = Path(__file__).parent / "results"
    path.mkdir(exist_ok=True)
    return path


@pytest.fixture(scope="session")
def run_timestamp() -> str:
    """파일명 접미사용 ISO 8601 timestamp (콜론 제거)."""
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
