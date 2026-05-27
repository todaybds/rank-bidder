# Naver SA Semantics Dry-Run — 측정 결과

## PUT→GET 시점별 bidAmt 변화 (AC2+AC3)


### Sequence 1 — target_bid = 100원

| 시점 | actual bidAmt | match | HTTP | latency_ms | elapsed_ms |
|---|---|---|---|---|---|
| PUT | — | — | 400 | 75.98 | 0 |
| get_0s | 70 | ✗ | 200 | 79.76 | 156 |
| get_30s | 70 | ✗ | 200 | 136.73 | 30137 |
| get_60s | 70 | ✗ | 200 | 124.62 | 60125 |
| get_180s | 70 | ✗ | 200 | 124.33 | 180124 |
| get_300s | 70 | ✗ | 200 | 124.6 | 300125 |

### Sequence 2 — target_bid = 200원

| 시점 | actual bidAmt | match | HTTP | latency_ms | elapsed_ms |
|---|---|---|---|---|---|
| PUT | — | — | 400 | 106.37 | 0 |
| get_0s | 70 | ✗ | 200 | 120.72 | 228 |
| get_30s | 70 | ✗ | 200 | 129.89 | 30131 |
| get_60s | 70 | ✗ | 200 | 104.58 | 60105 |
| get_180s | 70 | ✗ | 200 | 93.86 | 180094 |
| get_300s | 70 | ✗ | 200 | 139.54 | 300141 |

### Sequence 3 — target_bid = 150원

| 시점 | actual bidAmt | match | HTTP | latency_ms | elapsed_ms |
|---|---|---|---|---|---|
| PUT | — | — | 400 | 76.16 | 0 |
| get_0s | 70 | ✗ | 200 | 100.06 | 177 |
| get_30s | 70 | ✗ | 200 | 88.28 | 30089 |
| get_60s | 70 | ✗ | 200 | 83.51 | 60084 |
| get_180s | 70 | ✗ | 200 | 132.53 | 180133 |
| get_300s | 70 | ✗ | 200 | 150.13 | 300151 |

### GET latency 분포 (200 OK only)

- n = 15, p50 = 124.3ms, p90 ≈ 138.4ms, max = 150.1ms

### HTTP status 분포

- 200: 15회
- 400: 4회

## Rate Limit Probe — 10초 동안 20회 GET (AC3)

- 총 20회, status 분포: {200: 20}
- latency: p50 = 92.6ms, max = 154.5ms

✅ 2 RPS는 안전. 토큰버킷 5-8 RPS 설정 가능 (Story 1.5).

## 403 Invalid Timestamp Probe (AC1)

- step=bad_timestamp, status=403, latency=69.35ms
  - body: `{"timestamp": "1779861321726", "status": 403, "type": "urn:naver:api:problem:invalid-timestamp", "title": "Invalid Timestamp", "detail": "Request has expired."}`

## SQLite synchronous=FULL fsync latency (AC4)

- 측정 환경: Python 3.13.12, SQLite 3.50.4, Windows-10-10.0.19045-SP0
- N = 1000 write transactions × INSERT 100 bytes
- **p50 = 14.348ms / p90 = 16.916ms / p99 = 38.257ms / max = 125.615ms**
- Architecture 가정 (~5ms × 100 PUT/min ≈ 9%) 검증:
  - p50 14.348ms × 100/min = 1434.8ms/min = 2.39% (5분 사이클 기준)
  - p99 worst-case ~6.38% (참고용 — 실제 PUT은 사이클당 1-N회로 한정)


## D15 룰 변경 권고 (AC5+AC6 — 운영자 검토 후 architecture.md 수정)

### D15 (c) Write-ahead PUT + reconcile-on-PUT_SENT-only
- [ ] PUT 응답이 즉시 반영되는가? (위 GET_0s 결과 확인)
- [ ] 그렇다면 reconcile 룰 단순화 가능 (PUT 응답 200만 보고 COMMITTED 전이)
- [ ] 아니라면 현 룰 (PUT_SENT 상태 행만 다음 사이클 시작 시 GET reconcile) 유지

### D15 (i) PUT response semantics — `put_sent_at < now - 3분 → APPLIED`
- [ ] 3분 임계가 적절한가? GET 결과의 `match` 컬럼이 어느 시점부터 `✓` 시작하는지 확인
- [ ] 더 빠르면 (예: 1분 내) → 임계 단축
- [ ] 더 늦으면 (5분 후도 mismatch) → 임계 연장 또는 별도 reconcile 사이클

### D15 (j) SQLite durability
- [ ] p50 fsync latency 실측이 가정 ~5ms와 일치하는가?
- [ ] 큰 차이가 있다면 architecture.md D4·D15(j) 의 9% 비용 계산 갱신
- [ ] 1000회 중 max latency > 100ms 발생 빈도 확인 — 큰 spike는 사이클 overlap 위험

### 변경 적용 후
- [ ] architecture.md 수정 + Change Log 기록
- [ ] Story 1.3 Completion Notes에 변경 요약 박제
- [ ] Story 1.5 (SA API 풀세트 client) 시작 가능 — 본 보고서가 source of truth
