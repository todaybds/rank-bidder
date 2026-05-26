# Invariants Tracking

Architecture D15 §Invariants (I1~I8) 추적. 위반 발견 시 본 파일에 시각·증상·resolution 기록.

## I1~I8 (D15 §Invariants)

- **I1**: PUT_SENT 다음 상태는 COMMITTED 또는 FAILED 외 불가
- **I2**: BCI lock은 PUT_SENT 시각 기준. reconcile은 새 BCI 시작 안 함
- **I3**: KW snapshot 후 OFF 명령은 cycle_entries.snapshot_at 기준 effective
- **I4**: NFR-2 축소 시 staleness threshold 자동 확장 → death spiral 방지
- **I5**: UUID v7 generator monotonic — 시계 역행 시에도 strictly increasing
- **I6**: PUT_SENT 직전 final guard로 site.enabled AND keyword.enabled 재확인
- **I7**: Multi-time wrap-around은 minute_of_week modular 표현으로 안전
- **I8**: Cap 변경은 BCI lock 무관, 다음 사이클 clip — 즉시 PUT 강제 안 함

## 검증 위치

- I1·I3·I5·I6: Story 1.7 unit tests (`decision-engine/tests/unit/test_state_machine.py`)
- I2: Story 1.8 unit tests (`test_bid_decision.py`)
- I4: Story 1.8·6.4 unit tests (`test_freeze_dynamic.py` + `test_auto_shrink.py`)
- I7: Story 3.1 unit tests (`test_multi_time_modular.py`)
- I8: Story 3.1·1.8 unit tests

## 위반 사례 누적

(향후 발견 시 여기에 박제 — 시각·증상·root cause·resolution)
