-- Migration 0004: campaigns table + keywords.adgroup_id (Story 2.3)
-- Story 1.9의 RANKBIDDER_KW_<id>_ADGROUP_ID env 우회를 정식 컬럼화.
-- Story 2.3 spec L532-533 campaigns table 추가 + adgroup_id를 keywords 테이블에 추가.

CREATE TABLE campaigns (
  id TEXT PRIMARY KEY,
  site_id TEXT NOT NULL REFERENCES sites (id) ON DELETE RESTRICT,
  naver_campaign_id TEXT NOT NULL UNIQUE,
  created_at TEXT NOT NULL
);

CREATE INDEX idx_campaigns_site_id ON campaigns (site_id);

-- keywords 테이블에 adgroup_id 컬럼 추가 (Story 1.9 env 우회 흡수).
-- SQLite는 ALTER TABLE ADD COLUMN 만 지원 — DEFAULT NULL 로 기존 row 호환.
ALTER TABLE keywords ADD COLUMN adgroup_id TEXT;

CREATE INDEX idx_keywords_adgroup_id ON keywords (adgroup_id);
