#!/bin/sh
# DuckDNS A record updater (Story 4.1 H7 fix, 2026-05-27 code-review).
#
# Oracle Cloud Always Free Seoul VM의 public IPv4는 VM stop/start 시 변경 가능.
# DuckDNS A record가 ephemeral IP를 따라가지 않으면 도메인 dead → Let's Encrypt 60일
# 갱신 silent 실패 + 모든 dashboard fetch 401(인증 통과 못함) 또는 timeout.
#
# 본 스크립트:
# 1. /etc/duckdns/token (mode 0600, owned by root) 에서 token 로드
# 2. /etc/duckdns/domain 에서 subdomain 로드 (e.g., "rank-bidder")
# 3. https://www.duckdns.org/update?domains=DOMAIN&token=TOKEN&ip= 호출 (ip= 비우면 클라이언트 IP 자동 인식)
# 4. 응답 "OK" 만 정상. "KO" → exit 1 (systemd Restart=on-failure로 5분 후 재시도).
#
# 호출 cadence: rank-bidder-duckdns-update.timer (5분 OnCalendar + OnBootSec=30s).
# 운영 비용: $0 (DuckDNS 무료 + 자체 curl).

set -eu

TOKEN_FILE="/etc/duckdns/token"
DOMAIN_FILE="/etc/duckdns/domain"

if [ ! -f "$TOKEN_FILE" ]; then
    echo "duckdns-update: ERROR - $TOKEN_FILE not found" >&2
    exit 1
fi
if [ ! -f "$DOMAIN_FILE" ]; then
    echo "duckdns-update: ERROR - $DOMAIN_FILE not found" >&2
    exit 1
fi

TOKEN=$(cat "$TOKEN_FILE" | tr -d '[:space:]')
DOMAIN=$(cat "$DOMAIN_FILE" | tr -d '[:space:]')

if [ -z "$TOKEN" ] || [ -z "$DOMAIN" ]; then
    echo "duckdns-update: ERROR - empty token or domain" >&2
    exit 1
fi

RESPONSE=$(curl -fsS --max-time 30 \
    "https://www.duckdns.org/update?domains=${DOMAIN}&token=${TOKEN}&ip=")

if [ "$RESPONSE" = "OK" ]; then
    echo "duckdns-update: OK domain=${DOMAIN}"
    exit 0
fi

echo "duckdns-update: FAILED domain=${DOMAIN} response=${RESPONSE}" >&2
exit 1
