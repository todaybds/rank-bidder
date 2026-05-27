# deploy — Story 4.1 외부 셋업 가이드

Oracle Cloud Always Free Seoul VM 1인 운영 전제. 운영자(본인)만 사용 — robots noindex + Bearer 토큰.

## 산출물

| 파일 | 위치 | 용도 |
|---|---|---|
| `Caddyfile` | `/etc/caddy/Caddyfile` | rank-bidder.duckdns.org → uvicorn 8000 reverse proxy + Let's Encrypt |
| `systemd/caddy.service` | `/etc/systemd/system/caddy.service` | Caddy systemd unit (notify type) |
| `decision-engine/systemd/rank-bidder-api.service` | `/etc/systemd/system/rank-bidder-api.service` | uvicorn API (Story 1.9 산출) |

## 외부 셋업 단계 (사용자 실행)

### 1. DuckDNS

1. https://www.duckdns.org/ 로그인.
2. 서브도메인 `rank-bidder` 발급.
3. A record → Oracle VM public IPv4 등록.

### 2. Oracle Cloud VM (Always Free Seoul)

```bash
# 80/443 ingress 룰
# Security List → Add Ingress Rule
#   Source 0.0.0.0/0, TCP, Dest Port 80 + 443

# 호스트 방화벽
sudo firewall-cmd --add-service=http --add-service=https --permanent
sudo firewall-cmd --reload

# Caddy 설치 (Oracle Linux 9)
sudo dnf install -y 'dnf-command(copr)'
sudo dnf copr enable -y @caddy/caddy
sudo dnf install -y caddy
```

### 3. 산출물 배포

```bash
# 코드
git clone <repo> /opt/rank-bidder
cd /opt/rank-bidder/decision-engine
uv venv .venv && uv sync

# systemd
sudo install -m 0644 deploy/Caddyfile /etc/caddy/Caddyfile
sudo install -m 0644 deploy/systemd/caddy.service /etc/systemd/system/
sudo install -m 0644 decision-engine/systemd/rank-bidder-api.service /etc/systemd/system/

# 환경
sudo install -d -o rank-bidder /opt/rank-bidder /var/lib/rank-bidder
# /opt/rank-bidder/.env 작성:
#   RANKBIDDER_DB_PATH=/var/lib/rank-bidder/rank_bidder.db
#   RANKBIDDER_AUTH_TOKEN=<32+ byte 랜덤>
#   RANKBIDDER_ENV=prod

sudo systemctl daemon-reload
sudo systemctl enable --now rank-bidder-api caddy
```

### 4. 토큰 동기화

토큰 1개를 3곳 동일 설정:

| 위치 | 키 | 용도 |
|---|---|---|
| Oracle VM `/opt/rank-bidder/.env` | `RANKBIDDER_AUTH_TOKEN` | uvicorn 미들웨어 검증 |
| Vercel project env | `RANKBIDDER_AUTH_TOKEN` | dashboard fetch 시 Bearer 헤더 첨부 |
| AWS SSM Parameter Store | `/rank-bidder/auth_token` (SecureString) | 백업 + 회전 시 단일 진실 |

토큰 회전 절차는 `ops/token-rotation.md`.

### 5. Vercel 정적 dashboard

```bash
cd dashboard
vercel link
vercel env add RANKBIDDER_AUTH_TOKEN
vercel env add RANKBIDDER_API_BASE  # https://rank-bidder.duckdns.org
vercel --prod
```

## 검증

```bash
# Caddy → uvicorn 통과 확인 (Bearer 없이 401)
curl -i https://rank-bidder.duckdns.org/api/v1/keywords

# /health probe — Bearer bypass
curl -i https://rank-bidder.duckdns.org/health
# → 200 {"ok": true, "heartbeat_id": <int>}

# 정상 인증
curl -i -H "Authorization: Bearer $RANKBIDDER_AUTH_TOKEN" \
  https://rank-bidder.duckdns.org/api/v1/keywords
# → 200

# robots noindex
curl https://rank-bidder.duckdns.org/robots.txt
# → Disallow: /
```

## 트러블슈팅

- **401 with valid token**: `.env`의 토큰과 curl `-H Bearer` 값 정확 일치 확인. 공백·줄바꿈 주의.
- **Let's Encrypt 실패**: DuckDNS DNS propagation 대기 (~5 min). `sudo journalctl -u caddy -f`.
- **uvicorn 미기동**: `sudo systemctl status rank-bidder-api`. `RANKBIDDER_DB_PATH` 미설정 + `RANKBIDDER_ENV=prod` 면 startup 실패 (의도된 fail-fast).

## 자동화 안 한 이유

DuckDNS API 호출, Vercel CLI 인터랙티브 로그인, SSM put_parameter 모두 1회성 + 운영자 결재 필요. 매번 코드 산출물로 자동화하면 보안 토큰이 git/CI 로그에 박힐 위험 → 수동 단계로 유지.
