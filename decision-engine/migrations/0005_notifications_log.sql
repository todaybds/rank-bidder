-- Migration 0005: notifications_log (Story 2.4)
-- D15 (s) 묶음 알림 row. 실제 email 발송은 Epic 6 SMTP — 여기는 row insert만.

CREATE TABLE notifications_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  event_type TEXT NOT NULL,
  related_ids TEXT NOT NULL,
  payload TEXT NOT NULL,
  created_at TEXT NOT NULL,
  sent_at TEXT,
  suppressed_until TEXT
);

CREATE INDEX idx_notifications_event_created ON notifications_log (event_type, created_at DESC);
CREATE INDEX idx_notifications_pending ON notifications_log (created_at) WHERE sent_at IS NULL;
