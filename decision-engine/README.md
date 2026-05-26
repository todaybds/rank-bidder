# decision-engine

Rank Bidder의 결정 엔진 — Oracle Cloud Seoul AMD micro VM (Always Free)에 배포되는 컴포넌트.

## 구성

- **FastAPI** API server + cron jobs (단일 process)
- **SQLite** WAL + synchronous=FULL + file lock (NFR-7 데이터 소유권)
- **Naver SA API client** (HMAC + 토큰버킷 + 백오프 + NTP guard)
- **SERP measurer client** (Lambda Function URL + X-Auth-Token)
- **MCP server** (Claude 챗 transport, Epic 5에서 추가)

## 로컬 개발

```powershell
# workspace root에서
cd c:\Users\ok\rank-bidder
uv sync
uv run --package decision-engine pytest decision-engine/tests
uv run --package decision-engine ruff check .
```

자세한 구조는 Architecture step-06 §Complete Project Tree 참고.
