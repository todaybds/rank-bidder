-- Story 4.4 — 광고비 일일 수집 (FR-24, D15 t).
-- Naver SA /stats endpoint에서 어제 salesAmt를 받아 사이트/캠페인 단위로 저장.
-- 대시보드 위젯 5 (광고비 누적) + monthly 누적 집계용.

CREATE TABLE spend_daily (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  date TEXT NOT NULL,                  -- YYYY-MM-DD (KST)
  site_id TEXT REFERENCES sites (id),
  campaign_id TEXT,                    -- Naver nccCampaignId (또는 adgroup_id 대용)
  spend_amount INTEGER NOT NULL DEFAULT 0,
  click_count INTEGER NOT NULL DEFAULT 0,
  impression_count INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE (date, site_id, campaign_id)
);

CREATE INDEX idx_spend_daily_date ON spend_daily (date DESC);
CREATE INDEX idx_spend_daily_site_date ON spend_daily (site_id, date DESC);
