-- Migration 0002: cycle_entries + measurements + decisions (Story 1.6)
-- D1 (8 테이블 중 다음 3개) + D15 (b) state-machine table
-- State 강제 enforcement는 Story 1.7 (state_machine.py) — 본 마이그레이션은 schema + CHECK 만.
-- BEGIN/COMMIT는 migrate.py apply_migration 가 자체 wrapping (0001과 동일 패턴).

CREATE TABLE cycle_entries (
  cycle_id TEXT NOT NULL,
  keyword_id TEXT NOT NULL REFERENCES keywords (id) ON DELETE RESTRICT,
  state TEXT NOT NULL CHECK (state IN (
    'PLANNED', 'MEASURED', 'DECIDED', 'PUT_SENT', 'COMMITTED', 'FAILED'
  )),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (cycle_id, keyword_id)
);

-- D15 (c) partial index — 활성 사이클(PLANNED/PUT_SENT)만 빠르게 조회
-- COMMITTED/FAILED 누적 row는 인덱스 제외 → 인덱스 사이즈 일정 유지
CREATE INDEX idx_cycle_entries_active ON cycle_entries (state)
WHERE state IN ('PUT_SENT', 'PLANNED');

CREATE TABLE measurements (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  keyword_id TEXT NOT NULL REFERENCES keywords (id) ON DELETE RESTRICT,
  measured_at TEXT NOT NULL,
  rank_samples TEXT NOT NULL,
  rank_final INTEGER,
  current_bid INTEGER NOT NULL
);

CREATE INDEX idx_measurements_kw_time ON measurements (keyword_id, measured_at DESC);

CREATE TABLE decisions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  keyword_id TEXT NOT NULL REFERENCES keywords (id) ON DELETE RESTRICT,
  cycle_id TEXT NOT NULL,
  decided_at TEXT NOT NULL,
  decision TEXT NOT NULL CHECK (decision IN ('BID_UP', 'BID_DOWN', 'HOLD', 'CAP_REACHED', 'SKIP_STALE')),
  old_bid INTEGER NOT NULL,
  new_bid INTEGER NOT NULL,
  rank_observed INTEGER,
  reason TEXT,
  api_response_status INTEGER,
  api_error TEXT
);

CREATE INDEX idx_decisions_kw_time ON decisions (keyword_id, decided_at DESC);
CREATE INDEX idx_decisions_decided_at ON decisions (decided_at);
