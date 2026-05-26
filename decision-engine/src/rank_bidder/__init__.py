"""Rank Bidder — Decision Engine package root.

Module layout (Architecture step-06):

- api/            FastAPI routers (Story 1.9~ Epic 4·5)
- engine/         결정 엔진 (FR-1~5, FR-26, D15 a~t) — Story 1.7·1.8
- naver_sa/       Naver SA API client (D14) — Story 1.5
- lambda_client/  SERP measurer 호출 (D13) — Story 1.4·1.9
- db/             SQLite layer (D1~D5, WAL+sync=FULL) — Story 1.2·1.6
- policies/       멀티타임 + 자동축소 (D17, D18) — Epic 3·6
- notify/         이메일 알림 (FR-22, FR-23) — Epic 6
- jobs/           cron entrypoints — Story 1.9·Epic 6
- observability/  structlog + metrics + /health (NFR-3) — Story 1.9
- chat/           Claude tool functions (FR-17~21) — Epic 5
- auth/           bearer token (FR-25) — Story 4.1
- mcp/            MCP server (D11 step-07 close) — Epic 5
"""

__version__ = "0.1.0"
