-- Migration 0009: keywords.aliases (Story 1.10 long-tail KW unlock)
-- KW마다 광고 텍스트 변형 표현 후보 저장 (JSON list of strings).
-- parser는 term OR aliases 중 하나라도 단어경계 매치 시 인정 (FR-8 amend).
-- 디폴트 '[]' = Story 1.4b 호환 (term-only 매칭 그대로 동작).
--
-- Idempotency 주의 (Story 1.10 review patch 2026-05-28):
-- SQLite의 `ALTER TABLE ADD COLUMN`은 자체적으로 idempotent하지 않다
-- (재실행 시 "duplicate column name" 에러). migrate.py가 `schema_migrations`
-- table에서 version 박제 여부로 pending 결정 → 정상 path 재실행은 skip.
-- DR/restore 시 schema_migrations row 부재 + raw schema만 복원된 경우엔
-- 본 migration이 실패하므로 DR 절차에 `INSERT INTO schema_migrations(version)
-- VALUES (1)...(9)` 박제까지 포함해야 한다.

ALTER TABLE keywords ADD COLUMN aliases TEXT NOT NULL DEFAULT '[]';
