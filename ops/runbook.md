# Runbook

일상 운영 절차. Story 1.9 + 4.1에서 구체 채움. 사고 발생 시 시각·증상·복구 행동 추가 기록.

## 예정 섹션

- Oracle VM 접속 / SSH key 위치
- systemd timer 상태 확인 (`systemctl status rank-bidder-cycle-full.timer`)
- Caddy 인증서 갱신 상태 (`journalctl -u caddy -n 50`)
- DuckDNS 도메인 새로고침 (자동 — 단 IP 변경 시 수동 update 가능)
- SQLite 직접 query (`sqlite3 /var/lib/rank-bidder/rank_bidder.db`)
- 로그 위치 (`/var/log/caddy/`, `journalctl -u rank-bidder-api`)
- 응급 정지 (`POST /api/v1/system/pause-all` 또는 SQLite 직접 update)

_Story 1.9·4.1·6.2 진행 시 채워짐._
