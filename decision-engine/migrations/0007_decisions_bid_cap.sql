-- Migration 0007: decisions.bid_cap (Story 3.1, D17)
-- 결정 시점 effective bid_cap 박제. Story 3.2 cap_streak_started_at + cap_race detector가 이 컬럼으로
-- "현재 cap regime 시작 시각" 판정. 정책 전환으로 cap이 바뀌면 streak 자동 break (= D17 reset).

ALTER TABLE decisions ADD COLUMN bid_cap INTEGER;
