-- Migration 0009: keywords.aliases (Story 1.10 long-tail KW unlock)
-- KW마다 광고 텍스트 변형 표현 후보 저장 (JSON list of strings).
-- parser는 term OR aliases 중 하나라도 단어경계 매치 시 인정 (FR-8 amend).
-- 디폴트 '[]' = Story 1.4b 호환 (term-only 매칭 그대로 동작).

ALTER TABLE keywords ADD COLUMN aliases TEXT NOT NULL DEFAULT '[]';
