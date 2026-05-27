"""m.search.naver.com HTTP fetch helper.

- ``requests.Session`` module-level (cold start 1회, warm reuse → TCP keep-alive).
- 모바일 UA + ``Accept-Language: ko-KR,ko;q=0.9`` (Research §Mobile SERP).
- Region은 SAM template.yaml에서 ``ap-northeast-2`` 고정 (NFR-6).
- 단일 호출 timeout 10s. 5xx/timeout/network error → ``(None, status_or_0)``.
  재시도 안 함 — sampler의 다회 샘플링이 자연 재시도 역할 (FR-10).
"""

from __future__ import annotations

from urllib.parse import urlencode

import requests
import structlog

log = structlog.get_logger(__name__)

#: Android Chrome 모바일 UA 명시 박제. Naver SERP는 UA 기반으로 모바일 레이아웃
#: 분기 — 데스크탑 UA로 호출 시 광고 영역 구조 자체가 달라짐.
MOBILE_UA = (
    "Mozilla/5.0 (Linux; Android 13; SM-S908N) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Mobile Safari/537.36"
)

DEFAULT_HEADERS = {
    "User-Agent": MOBILE_UA,
    "Accept-Language": "ko-KR,ko;q=0.9",
    "Connection": "keep-alive",
}

_SERP_BASE_URL = "https://m.search.naver.com/search.naver"
_DEFAULT_TIMEOUT_S = 10.0
#: P2 (review 2026-05-27) — SERP 응답 본문 최대 4MB. 통상 200-500KB.
_MAX_RESPONSE_BYTES = 4 * 1024 * 1024

#: module-level session — cold start 1회 초기화 후 warm invocation에서 reuse.
_SESSION: requests.Session = requests.Session()
_SESSION.headers.update(DEFAULT_HEADERS)


def fetch_serp_html(term: str, timeout: float = _DEFAULT_TIMEOUT_S) -> tuple[str | None, int]:
    """모바일 SERP HTML fetch.

    Args:
        term: 검색어 (URL encoding은 내부에서 처리).
        timeout: 단일 호출 timeout(초). 디폴트 10s.

    Returns:
        ``(html_text, http_status)`` — 200 OK 시 ``(text, 200)``. 그 외(5xx/4xx/
        Timeout/ConnectionError 등) ``(None, status_code_or_0)``. 0은 네트워크
        에러로 status를 못 받은 경우.
    """
    url = f"{_SERP_BASE_URL}?{urlencode({'query': term})}"
    try:
        # P2 (review 2026-05-27): stream=True + iter_content + size cap → 100MB OOM 차단.
        response = _SESSION.get(url, timeout=timeout, stream=True)
    except requests.Timeout:
        log.warning("serp.fetch_timeout", term=term, timeout_s=timeout)
        return None, 0
    except requests.ConnectionError:
        log.warning("serp.fetch_connection_error", term=term)
        return None, 0
    except requests.RequestException as exc:
        log.warning("serp.fetch_error", term=term, error=str(exc))
        return None, 0

    try:
        if response.status_code != 200:
            log.warning("serp.fetch_non_200", term=term, status=response.status_code)
            return None, response.status_code

        # P2: SERP HTML 응답 본문 사이즈 가드 (Naver mobile SERP는 통상 200-500KB).
        chunks: list[bytes] = []
        total = 0
        try:
            for chunk in response.iter_content(chunk_size=64 * 1024):
                if not chunk:
                    continue
                total += len(chunk)
                if total > _MAX_RESPONSE_BYTES:
                    log.warning("serp.response_too_large", term=term, bytes_so_far=total)
                    return None, response.status_code
                chunks.append(chunk)
        except requests.RequestException as exc:
            log.warning("serp.body_read_error", term=term, error=str(exc))
            return None, response.status_code

        raw = b"".join(chunks)
        # P1 (review 2026-05-27): UTF-8 명시 (chardet guess 의존 제거 — Naver mobile은 UTF-8).
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            # 보조: cp949 fallback (Naver가 드물게 보내는 케이스 대응).
            try:
                text = raw.decode("cp949")
            except UnicodeDecodeError:
                log.warning("serp.decode_failed", term=term, bytes=total)
                return None, response.status_code
        return text, 200
    finally:
        response.close()
