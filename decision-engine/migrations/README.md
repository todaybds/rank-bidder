# migrations

Raw SQL 순번 마이그레이션 (Architecture D2, NFR-8 — Alembic 거부, ORM 없음).

순번 규칙: `<NNNN>_<snake_name>.sql` (zero-padded 4 digits).

## 예정 마이그레이션 (Story별)

- `0001_initial.sql` — Story 1.2 (sites + keywords + schema_migrations)
- `0002_cycle_entries_measurements_decisions.sql` — Story 1.6 (D15 b state machine)
- `0003_campaigns.sql` — Story 2.3 (site ↔ campaign 매핑)
- `0004_notifications_log.sql` — Story 2.4 (D15 n NAVER_DELETED 알림)
- `0005_policies.sql` — Story 3.1 (멀티타임 정책)
- `0006_spend_daily.sql` — Story 4.4 (FR-24)
- `0007_runtime_config.sql` — Story 4.5 (general_bid_paused + Story 6.4 자동축소 행 추가)

## 적용 방식

`db/migrate.py` (Story 1.2)가 `schema_migrations` 테이블 보고 미적용 마이그레이션을 순서대로 적용.
SQLite WAL + `synchronous=FULL` 모드에서 idempotent.

### CLI

```bash
# RANKBIDDER_DB_PATH가 설정된 환경에서:
uv run --package decision-engine python -m rank_bidder.db.migrate current
uv run --package decision-engine python -m rank_bidder.db.migrate up
```

### FastAPI lifespan

`decision-engine/src/rank_bidder/main.py`의 `lifespan`이 startup 시 자동으로 `migrate.up()` 호출.
production deploy 절차는 systemd `ExecStartPre=`로 명시 실행 권장 (이중 안전망).

### 규칙

- 파일명: `<NNNN>_<snake_name>.sql` — `NNNN`은 1부터 빈틈 없이 증가.
- PRAGMA는 절대 마이그레이션 파일에 넣지 말 것 — `db/connection.py`가 단일 source.
- 한 번 적용된 마이그레이션은 절대 수정 금지 (idempotent + history 보존). 변경은 새 번호로 추가.
