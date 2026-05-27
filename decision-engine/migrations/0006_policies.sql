-- Migration 0006: policies (Story 3.1)
-- Multi-time policy row — scope=(site|keyword) × start_minute_of_week + duration → target_rank/bid_cap.
-- D5 version counter, D17 Cap timer reset는 engine 측 책임.

CREATE TABLE policies (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  scope_type TEXT NOT NULL CHECK (scope_type IN ('site', 'keyword')),
  scope_id TEXT NOT NULL,
  start_minute_of_week INTEGER NOT NULL CHECK (start_minute_of_week BETWEEN 0 AND 10079),
  duration_minutes INTEGER NOT NULL CHECK (duration_minutes > 0 AND duration_minutes <= 10080),
  target_rank INTEGER NOT NULL CHECK (target_rank BETWEEN 1 AND 10),
  bid_cap INTEGER NOT NULL CHECK (bid_cap BETWEEN 100 AND 100000),
  version INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX idx_policies_scope ON policies (scope_type, scope_id);
