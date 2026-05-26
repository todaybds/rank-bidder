# deploy

Oracle Cloud Seoul AMD micro VM 배포 자원 (Architecture step-06).

## 예정 파일 (Story별)

- `cloud-init.yaml` — Oracle VM 부트스트랩 (Story 1.9)
- `systemd/rank-bidder-api.service` — FastAPI uvicorn (Story 1.9)
- `systemd/rank-bidder-cycle-full.{timer,service}` — 5분 전체 사이클 (Story 1.9)
- `systemd/rank-bidder-cycle-hot.{timer,service}` — 1분 핫 측정 (Story 1.9)
- `systemd/rank-bidder-spend.{timer,service}` — 일 1회 spend 수집 (Story 4.4)
- `systemd/rank-bidder-backup.{timer,service}` — 일 1회 S3 백업 (Story 6.3)
- `systemd/rank-bidder-keep-alive.{timer,service}` — 매 분 Oracle 7일 정지 회피 (D30)
- `systemd/caddy.service` — HTTPS termination (Story 4.1)
- `Caddyfile` — DuckDNS 도메인 reverse proxy (Story 4.1, D7)

Story 1.1 시점에는 stub만 — 실제 deploy 자원은 후속 Story에서 추가.
