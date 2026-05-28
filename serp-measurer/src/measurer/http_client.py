"""m.search.naver.com HTTP fetch helper — 봇 회피 강화판 (2026-05-28).

본 모듈은 Naver가 GCP VM IP를 봇으로 감지해서 403 차단하는 이슈 대응:
- **UA pool 회전**: 매 호출 새 모바일 UA 선택 (단일 UA로 시그너처 박히는 거 회피).
- **Session warmup**: 첫 호출 전 ``m.naver.com`` 메인 GET → set-cookie 자동 박힘.
  매 호출에 쿠키 동봉 (브라우저 표준 흐름 모사).
- **Referer 박제**: 메인 ``https://m.naver.com/`` 에서 검색한 것처럼 (직접 SERP URL
  호출하는 봇 신호 회피).
- **풍부한 브라우저 헤더**: Accept, Accept-Encoding, sec-ch-ua, sec-fetch-* 등.
  curl/requests 기본 헤더 차이로 봇 감지되는 거 차단.

Region은 SAM template.yaml에서 ``ap-northeast-2`` 고정 (NFR-6). 단일 호출 timeout
10s. 5xx/timeout/network error → ``(None, status_or_0)``. 재시도 안 함 — sampler의
다회 샘플링이 자연 재시도 역할 (FR-10).
"""

from __future__ import annotations

import random
import threading
from urllib.parse import urlencode

import requests
import structlog

log = structlog.get_logger(__name__)

#: 모바일 UA 풀 — Android Chrome + iOS Safari 다양한 기기/버전.
#: 매 호출 random.choice로 회전. 단일 UA 시그너처 박혀서 봇 감지되는 패턴 회피.
_MOBILE_UA_POOL = [
    "Mozilla/5.0 (Linux; Android 13; SM-S908N) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 14; SM-S921N) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.6167.143 Mobile Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1",
]

#: sec-ch-ua header — Chrome UA에만 적용. iOS Safari는 안 보냄.
_SEC_CH_UA_CHROME = '"Chromium";v="120", "Google Chrome";v="120", "Not?A_Brand";v="24"'

_BASE_HEADERS_COMMON = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "sec-fetch-dest": "document",
    "sec-fetch-mode": "navigate",
    "sec-fetch-site": "same-origin",
    "sec-fetch-user": "?1",
    "Cache-Control": "max-age=0",
}

_NAVER_MOBILE_HOME = "https://m.naver.com/"
_SERP_BASE_URL = "https://m.search.naver.com/search.naver"
_DEFAULT_TIMEOUT_S = 10.0
#: SERP 응답 본문 최대 4MB. 통상 200-500KB.
_MAX_RESPONSE_BYTES = 4 * 1024 * 1024

#: module-level session — cold start 1회 초기화 + warmup 후 재사용.
_SESSION: requests.Session = requests.Session()
_SESSION_WARMED = False
_WARMUP_LOCK = threading.Lock()


def _build_headers(referer: str | None = None) -> dict[str, str]:
    """매 호출 새 UA + Referer 박제 헤더 빌드."""
    ua = random.choice(_MOBILE_UA_POOL)
    headers = dict(_BASE_HEADERS_COMMON)
    headers["User-Agent"] = ua
    if "Chrome" in ua and "Mobile" in ua:
        headers["sec-ch-ua"] = _SEC_CH_UA_CHROME
        headers["sec-ch-ua-mobile"] = "?1"
        headers["sec-ch-ua-platform"] = '"Android"'
    if referer:
        headers["Referer"] = referer
    return headers


def _warmup_session(timeout: float = _DEFAULT_TIMEOUT_S) -> None:
    """Session warmup — m.naver.com 메인 GET → set-cookie 자동 박힘.

    Thread-safe (lock). 첫 fetch 전 1회만 호출. 실패해도 계속 진행 (best-effort).
    """
    global _SESSION_WARMED
    with _WARMUP_LOCK:
        if _SESSION_WARMED:
            return
        try:
            headers = _build_headers()
            resp = _SESSION.get(_NAVER_MOBILE_HOME, headers=headers, timeout=timeout)
            log.info(
                "serp.session_warmup",
                status=resp.status_code,
                cookies=len(_SESSION.cookies),
            )
            resp.close()
        except requests.RequestException as exc:
            log.warning("serp.session_warmup_failed", error=str(exc))
        finally:
            _SESSION_WARMED = True  # 실패해도 무한 재시도 차단


def fetch_serp_html(term: str, timeout: float = _DEFAULT_TIMEOUT_S) -> tuple[str | None, int]:
    """모바일 SERP HTML fetch — 봇 회피 강화.

    Args:
        term: 검색어 (URL encoding은 내부에서 처리).
        timeout: 단일 호출 timeout(초). 디폴트 10s.

    Returns:
        ``(html_text, http_status)`` — 200 OK 시 ``(text, 200)``. 그 외(5xx/4xx/
        Timeout/ConnectionError 등) ``(None, status_code_or_0)``. 0은 네트워크
        에러로 status를 못 받은 경우.
    """
    _warmup_session(timeout=timeout)

    url = f"{_SERP_BASE_URL}?{urlencode({'query': term})}"
    headers = _build_headers(referer=_NAVER_MOBILE_HOME)

    try:
        # stream=True + iter_content + size cap → 100MB OOM 차단.
        response = _SESSION.get(url, headers=headers, timeout=timeout, stream=True)
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

        # SERP HTML 응답 본문 사이즈 가드 (Naver mobile SERP는 통상 200-500KB).
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


def reset_session_for_test() -> None:
    """테스트 hook — module-level session/warmup 상태 초기화. unit test 격리용."""
    global _SESSION, _SESSION_WARMED
    _SESSION.close()
    _SESSION = requests.Session()
    _SESSION_WARMED = False
