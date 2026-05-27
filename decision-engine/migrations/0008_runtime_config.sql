-- Migration 0008: runtime_config (Story 4.5, FR-28, FR-30)
-- 글로벌 시스템 통제 (pause-all / resume) + 미래 운영 토글 저장소.
-- 모든 row 글로벌 1개씩 → version counter 불필요 (UPDATE만, race는 SQLite WAL이 충분).

CREATE TABLE runtime_config (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

INSERT INTO runtime_config (key, value, updated_at)
VALUES ('general_bid_paused', 'false', datetime('now'));
