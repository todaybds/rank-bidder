# Implementation Patterns

Architecture step-05 §Implementation Patterns의 운영판 export. Developer agent가 위반 발견 시 이 파일에 사례 추가.

## Naming (Architecture step-05)

### Database (SQLite)

- 테이블: `snake_case` 복수형 — `keywords`, `sites`, `cycle_entries`, `measurements`, `decisions`, `policies`, `notifications_log`, `spend_daily`, `runtime_config`, `schema_migrations`, `campaigns`
- 컬럼: `snake_case` — `target_rank`, `bid_cap`, `put_sent_at`
- PK: `id` (entity: UUID v7 TEXT, log: AUTOINCREMENT INTEGER)
- FK: `<referenced_table_singular>_id` — `keyword_id` references `keywords.id`
- 인덱스: `idx_<table>_<columns>`
- Timestamp: `*_at` UTC ISO 8601
- Boolean: 단일단어로 명확하면 그대로 (`enabled`), 아니면 `is_*` (`is_hot`)
- ENUM: CHECK constraint로 강제 — `CHECK (state IN ('PLANNED', ...))`

### API (FastAPI)

- REST resource: 복수형 — `/api/v1/keywords`, `/api/v1/sites`, `/api/v1/cycles`
- Action sub-resource: `/api/v1/keywords/{id}/pause`, `/api/v1/system/pause-all`
- Path param: `{id}`
- Query param: `snake_case` — `?site_id=...&limit=50`
- 페이지네이션: cursor — `?cursor=...&limit=50`
- 버전: URL prefix `/api/v1` (header 버전 거부)
- Auth: `Authorization: Bearer <token>` (대시보드) / `X-Auth-Token: <token>` (Lambda)

### Code (Python)

- 모듈/파일: `snake_case` — `naver_sa_client.py`
- 클래스: `PascalCase` — `NaverSAClient`
- 함수/변수: `snake_case`
- 상수: `UPPER_SNAKE_CASE` — `BCI_SECONDS = 180`
- Pydantic 모델: `PascalCase` + 접미사 — `KeywordCreate`, `KeywordRead`, `KeywordUpdate`
- 모듈 import: 절대경로 — `from rank_bidder.naver_sa import NaverSAClient`

### Code (JavaScript — dashboard)

- 파일: `kebab-case` — `keyword-detail.js`, `auth.js`
- 함수/변수: `camelCase`
- 모듈: ES modules + named exports
- 상수: `UPPER_SNAKE_CASE`

## Format

- 성공 응답: 객체 직접 반환 (래퍼 없음)
- 에러 envelope: `{"error":{"code":"...","message":"...","hint":"..."}}`
- 컬렉션: `{"items":[...],"next_cursor":"..."}`
- 날짜/시간: ISO 8601 UTC string — `"2026-05-27T14:30:00Z"`. Dashboard만 KST 변환.
- Boolean: `true`/`false` (0/1 거부)
- 통화: 정수 원 단위
- Rank: 정수
- Null: 명시적

## HTTP Status

- 200 OK / 201 Created / 204 No Content
- 400 Bad Request / 401 Unauthorized / 403 Forbidden / 404 Not Found
- 409 Conflict (D5 version mismatch)
- 422 Unprocessable Entity (Pydantic validation)
- 429 Too Many Requests
- 503 Service Unavailable (SQLite lock 5s 초과 / NFR-2 95% 단계)

## Logging

- 라이브러리: structlog (JSON output)
- 포맷: `{"ts":"...","level":"INFO","module":"engine.cycle","msg":"cycle_started","cycle_id":"01956...","kw_count":500}`
- 레벨: DEBUG / INFO / WARNING / ERROR / CRITICAL
- Correlation: `cycle_id`가 모든 사이클 관련 로그 포함 (trace id 역할)
- 금지: `print()`, `bare logging.info()` (모두 structlog 경유)

## Event 명명 (DB 내부 + 알림용)

- dot notation 소문자 + 과거형 — `cycle.started`, `bid.changed`, `keyword.frozen`, `site.disabled`
- 페이로드: `snake_case` + ISO 8601 timestamps

## 모든 AI Agent MUST

- 모든 외부 입출력: Pydantic 모델 경유 (raw dict 금지)
- 모든 로그: structlog (print/bare logging 금지)
- 모든 시간: 서버 UTC, 표시만 KST
- 모든 ID: UUID v7 (entity) 또는 AUTOINCREMENT (log)
- 모든 외부 API 호출: tenacity 재시도 + structlog 기록
- 모든 DB write: file lock 경유 (직접 `sqlite3.connect()` 금지, 공통 `db.connection` 모듈)
- 모든 secret 로드: SSM/.env (코드 hardcode 금지 — NFR-7, FR-25)

## 위반 사례 누적

(향후 발견 시 여기에 박제)
