# Token Rotation

분기 1회 토큰 회전 절차 (Architecture D6, FR-25).

## 대상 토큰

| 토큰 | 저장 위치 | 회전 주기 |
|---|---|---|
| Dashboard bearer token | SSM `/rank-bidder/dashboard/bearer-token` + Vercel env + Oracle env | 분기 1회 |
| Lambda X-Auth-Token | SSM `/rank-bidder/lambda/auth-token` | 분기 1회 |
| Naver SA API key | SSM `/rank-bidder/naver/api-key` + `/rank-bidder/naver/secret-key` | 1년 1회 (네이버 정책 따라) |
| Anthropic API key | SSM `/rank-bidder/anthropic/api-key` | 6개월 1회 |
| GitHub Actions secrets | repo secrets | 6개월 1회 |

## 예정 절차 (Story 4.1·5.1 진행 시 채워짐)

_Story 진행 시 본 절차의 구체 commands·시점·운영자 확인 단계 채워짐._
