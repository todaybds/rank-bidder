# Backup Recovery Rehearsal

NFR-9 — 분기 1회 백업 복구 리허설 절차.

## 예정 절차 (Story 6.3에서 박제)

1. AWS S3 Seoul (`s3://rank-bidder-backup-seoul/`)에서 가장 최근 daily 백업 다운로드
2. 신규 (또는 별도) Oracle VM에서 동일 schema_migrations 순서로 복원
3. `decision-engine`의 `db/migrate.py`로 마이그레이션 정상성 확인
4. `pytest decision-engine/tests` 통과 확인
5. 결정 엔진 startup → `/health` 200 응답 확인
6. 측정 dry-run 1 사이클 (실제 PUT 없이) 통과 확인
7. 리허설 결과를 본 파일 끝에 시각·소요 시간·발견 사항 기록

_Story 6.3 진행 시 본 절차의 구체 commands 채워짐._
