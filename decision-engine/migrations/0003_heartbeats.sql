-- Migration 0003: heartbeats (Story 1.9, D26 채널 (5) external probe)
-- /health endpoint가 호출될 때마다 1행 insert.
-- 외부 모니터(UptimeRobot 등)가 최신 row의 inserted_at 로 시스템 생존 판별.

CREATE TABLE heartbeats (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  inserted_at TEXT NOT NULL,
  source TEXT NOT NULL DEFAULT 'health'
);

CREATE INDEX idx_heartbeats_inserted_at ON heartbeats (inserted_at DESC);
