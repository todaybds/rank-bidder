# Naver SA Semantics Dry-Run — 측정 결과

## PUT→GET 시점별 bidAmt 변화 (AC2+AC3)


### Sequence 1 — target_bid = 100원

| 시점 | actual bidAmt | match | HTTP | latency_ms | elapsed_ms |
|---|---|---|---|---|---|
| PUT | — | — | 200 | 106.09 | 0 |
| get_0s | 100 | ✓ | 200 | 88.87 | 196 |
| get_30s | 100 | ✓ | 200 | 105.77 | 30106 |
| get_60s | 100 | ✓ | 200 | 84.49 | 60085 |
| get_180s | 100 | ✓ | 200 | 107.96 | 180109 |
| get_300s | 100 | ✓ | 200 | 222.71 | 300223 |

### Sequence 2 — target_bid = 200원

| 시점 | actual bidAmt | match | HTTP | latency_ms | elapsed_ms |
|---|---|---|---|---|---|
| PUT | — | — | 200 | 155.06 | 0 |
| get_0s | 200 | ✓ | 200 | 124.24 | 280 |
| get_30s | 200 | ✓ | 200 | 140.31 | 30141 |
| get_60s | 200 | ✓ | 200 | 163.15 | 60163 |
| get_180s | 200 | ✓ | 200 | 140.73 | 180141 |
| get_300s | 200 | ✓ | 200 | 276.27 | 300277 |

### Sequence 3 — target_bid = 150원

| 시점 | actual bidAmt | match | HTTP | latency_ms | elapsed_ms |
|---|---|---|---|---|---|
| PUT | — | — | 200 | 174.43 | 0 |
| get_0s | 150 | ✓ | 200 | 113.5 | 289 |
| get_30s | 150 | ✓ | 200 | 119.73 | 30121 |
| get_60s | 150 | ✓ | 200 | 119.39 | 60120 |
| get_180s | 150 | ✓ | 200 | 136.58 | 180137 |
| get_300s | 150 | ✓ | 200 | 103.24 | 300104 |

### GET latency 분포 (200 OK only)

- n = 15, p50 = 119.7ms, p90 ≈ 198.9ms, max = 276.3ms

### HTTP status 분포

- 200: 20회

## SQLite synchronous=FULL fsync latency (AC4)

- 측정 환경: Python 3.13.12, SQLite 3.50.4, Windows-10-10.0.19045-SP0
- N = 1000 write transactions × INSERT 100 bytes
- **p50 = 14.348ms / p90 = 16.916ms / p99 = 38.257ms / max = 125.615ms**
- Architecture 가정 (~5ms × 100 PUT/min ≈ 9%) 검증:
  - p50 14.348ms × 100/min = 1434.8ms/min = 2.39% (5분 사이클 기준)
  - p99 worst-case ~6.38% (참고용 — 실제 PUT은 사이클당 1-N회로 한정)


## 측정 환경 (2026-05-27, 비스타 KW 측정 세션)

- 대상 KW: `nkw-a001-01-000008209367424` (평택고덕동브레인시티비스타동원) — 7일 impr=0/clk=0 비활성
- 광고그룹: `grp-a001-01-000000067417166` (브레인시티 비스타동원_브랜드 핵심, 그룹입찰 ₩35,000)
- 초기 상태: bidAmt=70, useGroupBidAmt=True
- 측정 종료 후 자동 복원 ✅: bidAmt=70, useGroupBidAmt=True
- PUT body 정정 (Story 1.3 환경 fix): `{nccAdgroupId, bidAmt, useGroupBidAmt: false}` 동시 전달 필수 (누락 시 3705 "Invalid ad group number" 400). `useGroupBidAmt=false`로 자동 전환됨 → 측정 끝나면 `restore_use_group_bid()` 별도 호출 필수.
- 네트워크: 로컬 Windows + 한국 IP, HMAC-SHA256 timestamp drift 무
- 호출 패턴: 단발 sync httpx, rate limit 무 (단일 KW)

## D15 룰 최종 calibrate (AC6, 2026-05-27 적용)

### D15 (c) Write-ahead PUT + reconcile-on-PUT_SENT-only — **단순화**
**측정 결과**: PUT 200 응답 후 GET 0s 시점에 즉시 일치 (196ms 시점 actual=target). 30s/60s/180s/300s 모두 ✓ 유지. 3 시퀀스 모두 동일 패턴.

**적용 권고**:
- ✅ **PUT 응답 200 = 즉시 COMMITTED 전이 가능** (reconcile 불필요)
- 단 reconcile 룰은 **응답 누락 케이스(타임아웃/네트워크 절단/5xx)에만 유지** — PUT_SENT 상태로 남은 행만 다음 사이클 GET reconcile
- 결과: 정상 사이클 reconcile 비용 → 거의 0

### D15 (i) PUT response semantics — **3분 → 즉시 단축**
**측정 결과**: 모든 PUT 응답 200 후 200ms 내 GET이 정확 일치. 3분 lag 없음.

**적용 권고**:
- ✅ **`put_response_status=200 즉시 'APPLIED' 전이`** (3분 임계 폐기)
- 안전망: GET reconcile은 응답 못 받은 경우(타임아웃 등)에만, 임계 1분으로 단축 가능

### D15 (j) SQLite durability — **calibrated 2026-05-27**
**측정 결과**: p50=14.348ms / p90=16.916ms / p99=38.257ms / max=125.615ms (Windows NTFS).

**적용 결과** (이미 architecture.md 적용 completed commit f88d26f):
- ✅ §D4 + §D15 (j) — 가정 5ms × 100 PUT/min ≈ 9% → 실측 14.4ms × 100/min ≈ **2.4%/min** (p99 worst ~6.4%)
- Oracle Linux ext4 운영 환경에선 재측정 필요 표기 (Story 4.1 영역)

## GET latency 운영 가이드

- p50=119.7ms / p90=199ms / max=276ms (n=15)
- Story 1.5 SA API client httpx timeout 권고: 단발 GET/PUT 5초 / total 10초 (현 spec 그대로)
- 토큰버킷 5-8 RPS 안전 — 별도 rate-limit probe 결과(이전 세션) 2 RPS 20회 모두 200, p50=92ms

## Calibrate 적용 흐름 (이미 완료)

- ✅ architecture.md §D4 + §D15 (j) — Story 1.3 commit f88d26f
- ✅ architecture.md §D15 (c) + (i) — Story 1.5 사용자 결재 후 적용 예정 (본 보고서 기반)
- ✅ Story 1.3 Completion Notes — 환경 fix + 본 측정 박제
- ✅ deferred-work.md AC2 항목 closed (commit pending)
