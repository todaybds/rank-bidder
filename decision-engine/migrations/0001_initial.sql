-- Migration 0001: schema_migrations + sites + keywords
-- Story 1.2 — D1 (8 테이블 중 첫 3개) + D2 (raw .sql 순번)
-- PRAGMA는 db/connection.py가 담당. 본 파일은 DDL only.

CREATE TABLE schema_migrations (
  version INTEGER PRIMARY KEY,
  applied_at TEXT NOT NULL
);

CREATE TABLE sites (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
  version INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE keywords (
  id TEXT PRIMARY KEY,
  site_id TEXT NOT NULL REFERENCES sites (id) ON DELETE RESTRICT,
  term TEXT NOT NULL,
  target_rank INTEGER NOT NULL CHECK (target_rank BETWEEN 1 AND 10),
  bid_cap INTEGER NOT NULL CHECK (bid_cap BETWEEN 100 AND 100000),
  enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
  version INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX idx_keywords_site_id ON keywords (site_id);

-- Partial index: D15 (g) cycle snapshot — enabled KW만 빠르게 (사이클 시작 시 사용).
CREATE INDEX idx_keywords_enabled_site_id ON keywords (enabled, site_id)
WHERE enabled = 1;
