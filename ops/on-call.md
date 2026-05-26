# On-Call Guide

FR-22 시스템 장애 / FR-23 Cap 도달 알림 수신 시 분류·진단 가이드.

## 예정 분류 트리 (Story 6.2 진행 시 채워짐)

- `system_failure: SERP 측정 30m 연속 실패` → Lambda 상태 확인 / Naver IP 차단 의심
- `system_failure: SA API 10m 윈도우 50% 실패` → 매체 정책 변경 확인 / 토큰버킷 조정
- `system_failure: Lambda 사용률 80%` → 자동축소 발동 여부 확인 (`runtime_config`)
- `system_failure: Oracle CPU/메모리 90%` → 메모리 누수 / 비정상 process 확인
- `cap_reached_sustained: <KW>` → 운영자 판단으로 Cap 상향 or Target Rank 완화
- `cap_race: <site>` → 옥션 과열 가능성, 사이트 정책 재검토
- `naver_keyword_deleted: <KW list>` → 자동 OFF 처리됨, 확인만

_Story 6.2 진행 시 진단 commands + 의사결정 트리 박제._
