# ops

Rank Bidder 운영 문서 인덱스 (Architecture step-06 §ops/).

NFR-8 단순성 + bus factor 1 — 본인이 부재 시 또는 시간 지난 후 본인이 다시 봐도 운영을 재개할 수 있도록 작성.

## 파일

| 파일 | 목적 | 어느 Story에서 채워짐 |
|---|---|---|
| `patterns.md` | step-05 Implementation Patterns export + 위반 사례 누적 | Story 1.1 (initial export) + 이후 위반 발견 시 |
| `runbook.md` | 일상 운영 절차 (서비스 재시작 / 로그 확인 / Caddy 갱신 등) | Story 1.9 + 4.1 + 운영 중 |
| `recovery-rehearsal.md` | NFR-9 분기 1회 백업 복구 리허설 절차 | Story 6.3 |
| `token-rotation.md` | 분기 1회 bearer/X-Auth-Token/SA API key 회전 절차 | Story 4.1 |
| `on-call.md` | FR-22 알림 받았을 때 분류·진단 가이드 | Story 6.2 |
| `invariants.md` | D15 I1~I8 추적 + 위반 발견 기록 | Story 1.7 |

## 사용 규칙

- 새 외부 의존을 추가하려면 PR 본문에 `ops/patterns.md`와 PRD/architecture 변경 절차 참조 (NFR-8).
- 운영 중 발견한 incident는 `runbook.md`에 시각·증상·복구 행동 기록 — 다음 분기 retrospective 재료.
