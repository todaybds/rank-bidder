# deploy — Story 4.1 외부 셋업 가이드 (2026-05-27 code-review 반영, 2026-05-28 GCP pivot)

GCP Compute Engine Always Free (us-west1, e2-micro, Ubuntu 22.04 LTS) 1인 운영 전제. 운영자(본인)만 사용 — robots noindex + Bearer 토큰.

> **2026-05-28 pivot 메모**: 본래 Oracle Cloud Always Free Seoul 대상이었으나 Oracle 가입이 anti-fraud로 차단되어 GCP로 변경. Seoul → us-west1(Oregon). 네이버 SA API는 region 무관 + SERP 측정은 별도 Lambda Seoul에서 수행 → 운영 영향 없음. SSH latency ~150ms는 cron 자동운영이라 무시 가능.

## 산출물

| 파일 | 위치 | 용도 |
|---|---|---|
| `Caddyfile` | `/etc/caddy/Caddyfile` | rank-bidder.duckdns.org → uvicorn 8000 reverse proxy + Let's Encrypt |
| `systemd/caddy.service` | `/etc/systemd/system/caddy.service` | Caddy systemd unit (notify type) + LogsDirectory/StateDirectory |
| `decision-engine/systemd/rank-bidder-api.service` | `/etc/systemd/system/rank-bidder-api.service` | uvicorn API + `--proxy-headers` |
| `decision-engine/systemd/rank-bidder-cycle-full.{service,timer}` | `/etc/systemd/system/` | full cycle (측정+결정+PUT) 5분 주기 — **자동입찰 핵심** |
| `decision-engine/systemd/rank-bidder-cycle-hot.{service,timer}` | `/etc/systemd/system/` | hot cycle (측정만) 1분 주기 — 빠른 변화 추적 |
| `decision-engine/systemd/rank-bidder-keep-alive.{service,timer}` | `/etc/systemd/system/` | heartbeat 5분 주기 — DB write 살아있음 + recovery 트리거 |
| `decision-engine/systemd/rank-bidder-notify-sender.{service,timer}` | `/etc/systemd/system/` | Story 6.1 notification sender 1분 주기 (dry-run 기본) |
| `systemd/rank-bidder-duckdns-update.{service,timer}` | `/etc/systemd/system/` | DuckDNS A record 5분 주기 갱신 (VM IP drift 대비) |
| `duckdns-update.sh` | `/usr/local/bin/rank-bidder-duckdns-update.sh` | DuckDNS update 실행 스크립트 |

## 외부 셋업 단계 (사용자 실행)

### 1. DuckDNS (token + domain)

1. https://www.duckdns.org/ Google OAuth 로그인.
2. 서브도메인 `rank-bidder` 발급 → token (UUID) 메모.
3. A record는 비워두기 — 아래 4단계에서 update script가 자동 채움.

### 2. GCP VM (Always Free us-west1 e2-micro)

**VM 생성** (콘솔 또는 gcloud SDK):

```powershell
# 로컬 PowerShell (gcloud SDK 인증 + default project=todaybds 설정 후)
gcloud compute instances create rank-bidder `
  --zone=us-west1-a `
  --machine-type=e2-micro `
  --image-family=ubuntu-2204-lts `
  --image-project=ubuntu-os-cloud `
  --tags=http-server,https-server
```

**방화벽 (GCP VPC firewall rules)**: 기본 프로젝트의 `default-allow-http` / `default-allow-https`가 자동 활성. VM에 `http-server` + `https-server` 네트워크 태그가 붙어있어야 적용됨 (위 생성 명령에 포함). 기존 VM에 태그가 없으면:

```powershell
gcloud compute instances add-tags rank-bidder --zone=us-west1-a --tags=http-server,https-server
```

> 호스트 방화벽(`ufw`)은 GCP Ubuntu 이미지에서 기본 비활성 — 손댈 필요 없음. GCP VPC firewall에서 일괄 관리.

**SSH 접속**:

```powershell
gcloud compute ssh rank-bidder --zone=us-west1-a
# 또는 GCP 콘솔 → Compute Engine → VM 인스턴스 → SSH 버튼
```

**Caddy + 유틸 설치 (VM 안에서, Ubuntu 22.04)**:

```bash
sudo apt update
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https curl git dnsutils
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
  | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
  | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt update
sudo apt install -y caddy
# apt가 기본 caddy.service를 enable/start하지만, 3단계에서 /etc/systemd/system/caddy.service로
# 덮어쓰면 우리 unit이 우선. 충돌 방지 위해 일단 정지:
sudo systemctl disable --now caddy
```

**uv 설치 (Python 패키지 매니저, 시스템 전역)**:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sudo env UV_INSTALL_DIR=/usr/local/bin sh
# 검증
/usr/local/bin/uv --version
```

### 3. 산출물 배포

```bash
# rank-bidder 시스템 유저 생성 (login shell 차단)
sudo useradd -r -s /usr/sbin/nologin -d /opt/rank-bidder rank-bidder

# 코드 (rank-bidder가 직접 clone 못 하므로 root로 clone 후 chown)
sudo git clone https://github.com/todaybds/rank-bidder.git /opt/rank-bidder
sudo chown -R rank-bidder: /opt/rank-bidder

# Python 3.13 + venv (Ubuntu 22.04 기본은 3.10 → uv가 3.13 다운로드/캐시)
# 주의: -H 플래그로 HOME을 rank-bidder 거(/opt/rank-bidder)로 강제. -H 없으면
# uv가 호출 유저(/home/<caller>)의 uv.toml 읽으려다 권한 거부로 실패.
cd /opt/rank-bidder
sudo -Hu rank-bidder /usr/local/bin/uv python install 3.13
sudo -Hu rank-bidder /usr/local/bin/uv sync
# venv 경로 = /opt/rank-bidder/.venv  ← uv workspace 루트 (systemd unit과 일치).
# 루트 pyproject.toml의 [tool.uv.workspace]가 decision-engine + serp-measurer를 묶어
# 단일 venv를 워크스페이스 루트에 만듦. `uv venv` 별도 호출 불필요 — `uv sync`가 알아서 만듦.

# systemd unit 배치
sudo install -m 0644 deploy/Caddyfile /etc/caddy/Caddyfile
sudo install -m 0644 deploy/systemd/caddy.service /etc/systemd/system/
sudo install -m 0644 decision-engine/systemd/rank-bidder-api.service /etc/systemd/system/
# 결정 엔진 cron timer 4종 (cycle-full / cycle-hot / keep-alive / notify-sender)
sudo install -m 0644 decision-engine/systemd/rank-bidder-cycle-full.service /etc/systemd/system/
sudo install -m 0644 decision-engine/systemd/rank-bidder-cycle-full.timer /etc/systemd/system/
sudo install -m 0644 decision-engine/systemd/rank-bidder-cycle-hot.service /etc/systemd/system/
sudo install -m 0644 decision-engine/systemd/rank-bidder-cycle-hot.timer /etc/systemd/system/
sudo install -m 0644 decision-engine/systemd/rank-bidder-keep-alive.service /etc/systemd/system/
sudo install -m 0644 decision-engine/systemd/rank-bidder-keep-alive.timer /etc/systemd/system/
sudo install -m 0644 decision-engine/systemd/rank-bidder-notify-sender.service /etc/systemd/system/
sudo install -m 0644 decision-engine/systemd/rank-bidder-notify-sender.timer /etc/systemd/system/

# DuckDNS updater 배치 (code-review H7)
sudo install -m 0755 deploy/duckdns-update.sh /usr/local/bin/rank-bidder-duckdns-update.sh
sudo install -m 0644 deploy/systemd/rank-bidder-duckdns-update.service /etc/systemd/system/
sudo install -m 0644 deploy/systemd/rank-bidder-duckdns-update.timer /etc/systemd/system/

sudo install -d -m 0700 /etc/duckdns
echo "rank-bidder" | sudo tee /etc/duckdns/domain >/dev/null
echo "<duckdns-token-from-step-1>" | sudo tee /etc/duckdns/token >/dev/null
sudo chmod 0600 /etc/duckdns/token

# 환경
sudo install -d -o rank-bidder -m 0755 /var/lib/rank-bidder

# /opt/rank-bidder/.env 작성:
#   RANKBIDDER_DB_PATH=/var/lib/rank-bidder/rank_bidder.db
#   RANKBIDDER_AUTH_TOKEN=<openssl rand -base64 48>
#   RANKBIDDER_DASHBOARD_ORIGIN=https://<vercel-project>.vercel.app  ← CORS allow (code-review H5)
#   RANKBIDDER_ENV=prod
#   RANKBIDDER_NAVER_SA_API_KEY=<...>
#   RANKBIDDER_NAVER_SA_SECRET_KEY=<...>
#   RANKBIDDER_NAVER_SA_CUSTOMER_ID=<...>
sudo chmod 0600 /opt/rank-bidder/.env
sudo chown rank-bidder: /opt/rank-bidder/.env

sudo systemctl daemon-reload
sudo systemctl enable --now rank-bidder-duckdns-update.timer
sudo systemctl enable --now rank-bidder-api caddy
# cron timer 4종 enable (자동입찰 cycle은 이것들이 가동돼야 동작)
sudo systemctl enable --now rank-bidder-cycle-full.timer rank-bidder-cycle-hot.timer rank-bidder-keep-alive.timer rank-bidder-notify-sender.timer
```

### 4. DuckDNS 동작 확인

```bash
# 30s 대기 후 (OnBootSec=30s) 첫 실행 확인
sudo systemctl status rank-bidder-duckdns-update.service
# Active: inactive (dead) since ...  Status: "duckdns-update: OK domain=rank-bidder"

# A record 확인 (resolver propagation ~5min)
dig +short rank-bidder.duckdns.org
# → GCP VM external IPv4 출력

# 이후 5min 주기로 자동 갱신 (VM stop/start 시에도 자동 복구)
sudo systemctl list-timers rank-bidder-duckdns-update.timer
```

### 5. 토큰 동기화

토큰 1개를 3곳 동일 설정:

| 위치 | 키 | 용도 |
|---|---|---|
| GCP VM `/opt/rank-bidder/.env` | `RANKBIDDER_AUTH_TOKEN` | uvicorn 미들웨어 검증 |
| Vercel project env | `RANKBIDDER_AUTH_TOKEN` | dashboard build script가 env.js에 박제 |
| AWS SSM Parameter Store | `/rank-bidder/auth_token` (SecureString) | 백업 + 회전 시 단일 진실 |

**토큰 회전 절차 (`openssl rand -base64 48` 신규 토큰):**

1. SSM Parameter Store에 신규 토큰 put (`aws ssm put-parameter --name /rank-bidder/auth_token --value "$NEW" --type SecureString --overwrite`).
2. GCP VM `.env` 갱신 + `sudo systemctl restart rank-bidder-api`.
3. Vercel env 갱신 (`vercel env rm RANKBIDDER_AUTH_TOKEN production && vercel env add RANKBIDDER_AUTH_TOKEN production`) + `vercel --prod` 재배포 (build script가 env.js에 반영).

### 6. Vercel 정적 dashboard (code-review C1)

```bash
cd dashboard
vercel link
vercel env add RANKBIDDER_AUTH_TOKEN production
vercel env add RANKBIDDER_API_BASE production  # e.g., https://rank-bidder.duckdns.org
vercel --prod
```

배포 시 `scripts/build-env-js.sh`가 자동 실행돼 `public/static/js/env.js` 에 token + API base를 박제. 정적 HTML이 `<script src="/static/js/env.js">` 로 로드 → `window.RANKBIDDER_AUTH_TOKEN` 글로벌 통해 fetch 헤더에 첨부.

**보안 주의**: env.js는 클라이언트에 그대로 노출. 1인 운영 + Bearer 1개 한정. SaaS화 시 Vercel Edge Function 프록시 전환 필요.

### 7. 사이트 + KW seed

```bash
TOKEN=$RANKBIDDER_AUTH_TOKEN
BASE=https://rank-bidder.duckdns.org

# 사이트 등록
curl -X POST "$BASE/api/v1/sites" \
  -H "Authorization: Bearer $TOKEN" -H "content-type: application/json" \
  -d '{"id":"kantabile-platform-city","name":"칸타빌 플랫폼시티"}'

# 키워드 일괄 import (사이트당 1 캠페인) — JSON 키 명확히 `campaign_id` (code-review 4.5 C1)
curl -X POST "$BASE/api/v1/imports" \
  -H "Authorization: Bearer $TOKEN" -H "content-type: application/json" \
  -d '{"site_id":"kantabile-platform-city","campaign_id":"<NCC...>","target_rank":2,"bid_cap":8000}'
```

또는 dashboard `index.html` 우측 상단 "키워드 import" 모달 (Vercel 배포 후).

## 검증

```bash
# /health probe — Bearer bypass
curl -i https://rank-bidder.duckdns.org/health
# → 200 {"ok": true, "heartbeat_id": <int>}

# Caddy → uvicorn 통과 + Bearer 미들웨어 동작 확인 (auth-required 라우트, Bearer 없이 401)
curl -i https://rank-bidder.duckdns.org/api/v1/sites
# → 401 {"error":{"code":"UNAUTHORIZED",...}}

# 정상 인증 (사이트 목록 — 비어있으면 [])
curl -i -H "Authorization: Bearer $RANKBIDDER_AUTH_TOKEN" \
  https://rank-bidder.duckdns.org/api/v1/sites
# → 200 []

# 등록된 라우트 전체 확인 — Swagger UI (브라우저 또는 curl)
# https://rank-bidder.duckdns.org/docs

# TLS 발급자 확인 (Let's Encrypt)
echo | openssl s_client -servername rank-bidder.duckdns.org \
  -connect rank-bidder.duckdns.org:443 2>/dev/null \
  | openssl x509 -noout -issuer -dates
# → issuer=C = US, O = Let's Encrypt, CN = E8
```

> 참고: `GET /api/v1/keywords` 와 `/robots.txt`는 현재 미등록 라우트 — Epic 4.2 (dashboard 메인) backlog에서 추가 예정. 검증 시 404 나면 정상.

## 트러블슈팅

- **401 with valid token**: `.env`의 토큰과 curl `-H Bearer` 값 정확 일치 확인. 공백·줄바꿈 주의.
- **uvicorn ENOENT/실패**: venv 경로 = `/opt/rank-bidder/.venv/bin/uvicorn` (uv workspace 루트). `sudo -Hu rank-bidder /usr/local/bin/uv sync` 다시 실행. **주의**: `sudo -u`만 쓰면 HOME이 호출 유저 거 그대로라 uv가 `/home/<caller>/uv.toml` 권한 에러로 실패 — `-H` 필수.
- **uv: command not found**: `UV_INSTALL_DIR=/usr/local/bin` 안 먹었을 가능성. `which uv` → 없으면 `curl -LsSf https://astral.sh/uv/install.sh | sudo env UV_INSTALL_DIR=/usr/local/bin sh` 재실행.
- **Let's Encrypt 실패**: DuckDNS DNS propagation 대기 (~5 min). `sudo journalctl -u caddy -f`. systemd unit이 LogsDirectory/StateDirectory 사용 — `/var/lib/caddy` ACME state 존재 확인.
- **Caddy: address already in use (80/443)**: apt 기본 caddy.service가 살아있을 가능성. `sudo systemctl status caddy` 확인 + `sudo systemctl disable --now caddy` 후 재시작.
- **Vercel dashboard 401**: env.js가 비어있을 가능성. `vercel env ls`로 RANKBIDDER_AUTH_TOKEN 확인 + `vercel --prod` 재배포 후 `view-source:` 로 env.js 토큰 박제 확인.
- **VM 재부팅 후 dashboard 접속 안 됨**: DuckDNS A record가 새 IP 반영 안 됐을 가능성. `sudo systemctl status rank-bidder-duckdns-update.service` 마지막 실행 OK 확인. `dig +short rank-bidder.duckdns.org` 비교.
- **CORS 차단**: `.env`의 `RANKBIDDER_DASHBOARD_ORIGIN` 이 실제 Vercel URL과 정확 일치하는지 (https://, 끝 슬래시 없이) 확인.

## 자동화 안 한 이유

DuckDNS token 입력, Vercel CLI 인터랙티브 로그인, SSM put_parameter 모두 1회성 + 운영자 결재 필요. 매번 코드 산출물로 자동화하면 보안 토큰이 git/CI 로그에 박힐 위험 → 수동 단계로 유지.
