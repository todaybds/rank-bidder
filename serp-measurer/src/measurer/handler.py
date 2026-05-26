"""Lambda Function URL handler — Story 1.1 stub.

Real implementation arrives in Story 1.4 (FR-8, FR-10):
- X-Auth-Token verification (SSM Parameter Store SecureString, D9)
- 모바일 UA + ko-KR header HTTP fetch (research §Mobile SERP Parsing)
- BeautifulSoup4 파싱 — data-* 속성 + 텍스트 앵커 우선 (research §Integration)
- 다회 샘플링 N=3-5 → 중앙값/최빈값 채택 (FR-10)
- D13 응답 contract: {results:[{id, samples, chosen_rank, latency_ms, errors?}]}
"""

import json


def lambda_handler(event: dict, context: object) -> dict:
    """Function URL handler — Story 1.1 placeholder returns 501.

    Args:
        event: Function URL event (HTTP request).
        context: Lambda context.

    Returns:
        HTTP response dict (statusCode, body).
    """
    return {
        "statusCode": 501,
        "body": json.dumps(
            {
                "error": {
                    "code": "NOT_IMPLEMENTED",
                    "message": "SERP measurer not yet implemented (Story 1.1 skeleton)",
                    "hint": "Implementation arrives in Story 1.4",
                }
            }
        ),
    }
