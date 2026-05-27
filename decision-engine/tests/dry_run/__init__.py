"""Story 1.3 dry-run measurement scripts.

⚠️ 실제 Naver SA API 호출 — 운영 광고그룹 영향 + 광고비 발생 가능.
``@pytest.mark.naver_live`` 마커로 격리 — 기본 ``pytest`` 명령에서 SKIP.

실행:
    uv run pytest -m naver_live -s decision-engine/tests/dry_run/

필수 env:
    RANKBIDDER_NAVER_SA_API_KEY
    RANKBIDDER_NAVER_SA_SECRET_KEY
    RANKBIDDER_NAVER_SA_CUSTOMER_ID
    RANKBIDDER_NAVER_SA_BASE_URL (default https://api.searchad.naver.com)
    RANKBIDDER_NAVER_SA_TEST_KEYWORD_ID (사용자가 결정한 dry-run 대상 KW)
"""
