# systemd 배포 가이드 (Story 1.9 — Minimum LIVE Gate)

Oracle Cloud Always Free Seoul VM (Ubuntu 22.04+) 기준.

## 사전 준비

1. `/opt/rank-bidder/` 에 repo clone + `uv sync` (.venv 생성)
2. `/opt/rank-bidder/.env` 박제 (RANKBIDDER_DB_PATH, NAVER SA, LAMBDA URL/TOKEN)
3. `sudo useradd -r -s /bin/false rank-bidder` + `chown -R rank-bidder /opt/rank-bidder`
4. sentinel KW 1개 등록 — Python REPL 또는 별도 스크립트로:
   ```python
   from rank_bidder.db.connection import configure, write_transaction
   from rank_bidder.db.models import SiteCreate, KeywordCreate
   from rank_bidder.db.repositories import sites, keywords
   configure("/opt/rank-bidder/var/rank-bidder.db")
   with write_transaction() as conn:
       sites.create(conn, SiteCreate(id="vista", name="비스타동원"))
       keywords.create(conn, KeywordCreate(
           id="nkw-a001-01-000008209367424",  # 비스타 KW (Story 1.3 측정 대상)
           site_id="vista", term="평택고덕동브레인시티비스타동원",
           target_rank=2, bid_cap=30000,
       ))
   ```
5. `.env` 에 KW별 adgroup_id 매핑 (v1 임시 — v2에서 keywords 테이블 컬럼화):
   ```
   RANKBIDDER_KW_nkw-a001-01-000008209367424_ADGROUP_ID=grp-a001-01-000000067417166
   ```

## 설치

```bash
sudo cp systemd/*.service systemd/*.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now \
  rank-bidder-api.service \
  rank-bidder-cycle-full.timer \
  rank-bidder-cycle-hot.timer \
  rank-bidder-keep-alive.timer
```

## 검증

```bash
# 서비스/타이머 상태
systemctl status rank-bidder-api.service
systemctl list-timers --all | grep rank-bidder

# 로그 (cycle_id correlation)
journalctl -u rank-bidder-cycle-full.service -f
journalctl -u rank-bidder-api.service -f

# /health probe
curl http://127.0.0.1:8000/health
# → {"ok": true, "heartbeat_id": N}

# 24h 후 LIVE Gate (AC8)
# SM-1: systemctl status — 모든 unit active 유지
# SM-2: heartbeats / cycle_full 로그에 측정·결정·PUT 표출
# SM-3: skipped <= 5% (failed/scanned 비율)
```

## LIVE Gate 통과 시
sprint-status.yaml `1-9-cron-sentinel-live-gate: done` + epic-1: done 처리.
