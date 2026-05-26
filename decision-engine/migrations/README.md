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
