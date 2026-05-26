# Rank Bidder

네이버 검색광고 키워드의 모바일 SERP 순위를 사용자가 키워드별로 지정한 목표(예: 1·2·3위)에 자동으로 맞춰가는 **단독 운영 자동입찰 시스템**.

> 자작 v1 (Cloudflare Worker)이 (a) 순위 정확도 / (b) 반응 속도 / (c) 관찰가능성 셋 모두에서 폐기됐고, 상용 도구(보라웨어)는 외부 의존·black box·데이터 소유권 부재로 채택 불가였다. **Rank Bidder = ownership + customization + 종속 회피.**

## 구조 (monorepo)

```
rank-bidder/
├── decision-engine/   ← Oracle Cloud Seoul AMD micro VM (FastAPI + SQLite + cron)
├── serp-measurer/     ← AWS Lambda Seoul (한국 IP 모바일 SERP 측정)
├── dashboard/         ← Vercel static (vanilla HTML/JS + Chart.js v4)
└── ops/               ← 운영 문서 (patterns·runbook·invariants 등)
```

각 폴더의 README와 [Architecture step-06 §Complete Project Tree](#references)를 참고.

## 빠른 시작 (로컬 dev)

```powershell
# 1) workspace install
cd c:\Users\ok\rank-bidder
uv sync --all-packages

# 2) decision-engine 테스트
uv run pytest decision-engine/tests -v

# 3) decision-engine 로컬 실행 (Story 1.9 후 systemd로 대체)
uv run --package decision-engine fastapi dev decision-engine/src/rank_bidder/main.py

# 4) serp-measurer 빌드·테스트
cd serp-measurer
sam validate --lint
sam build
sam local invoke SerpMeasurerFunction -e events/event.json   # Docker 필요
cd ..

# 5) dashboard 정적 서빙
python -m http.server 8080 --directory dashboard/public
# 또는 npx vercel dev (Vercel CLI)
```

## 도구 버전

| Tool | Pin |
|---|---|
| Python | 3.13 (Lambda Provided.al2023 native) |
| uv | 0.11.16+ |
| AWS SAM CLI | 1.155.2+ |
| ruff | 0.11.x |
| sqlfluff | 3.2.x |
| Pre-commit | v5 (hooks: ruff + sqlfluff + check-yaml + detect-private-key) |

## 빌드 & 배포

| 컴포넌트 | 로컬 빌드 | 배포 (Story별) |
|---|---|---|
| decision-engine | `uv build` (간헐적) | Oracle SSH → `git pull` + `migrate.py` + `systemctl reload` (Story 1.9~) |
| serp-measurer | `sam build` | `sam deploy` to `ap-northeast-2` (Story 1.4) |
| dashboard | 빌드 없음 (정적 파일) | `git push to main` → Vercel auto (Story 4.1) |

## CI

`.github/workflows/ci.yml` — push/PR to `main` 시 자동 실행:

1. **lint-and-test**: ruff check + ruff format --check + pytest (decision-engine + serp-measurer)
2. **sam-build**: SAM validate --lint + SAM build (serp-measurer)

GitHub Actions Always Free public repo 2000 분/월 한도 안에서 운영 (NFR-2).

## Phased Rollout

| 옵션 | 범위 | 권장도 |
|---|---|---|
| A. Minimum LIVE | Epic 1만 (sentinel 1 KW LIVE Gate) | 위험 최소화 |
| **B. Operator-usable** ⭐ | Epic 1 + 2 + 4.1·4.2·4.5 + 6 | **실제 운영 가능** — 추천 |
| C. Full v1 | Epic 1~6 전체 | 풀세트 |

**구현 첫 핵심 = Story 1.3** — Naver SA API GET/PUT semantics dry-run. 이 결과가 D15 (c)/(d)/(j) recovery/BCI/durability 룰을 final calibrate. **자작 v1의 운명을 반복하지 않으려면 반드시 검증 후 진행.**

## References

기획 산출물 (모두 `c:/Users/ok/_bmad-output/planning-artifacts/` 하):

- [PRD](../_bmad-output/planning-artifacts/prds/prd-rank-bidder-2026-05-27/prd.md) — 30 FR + 9 NFR
- [Architecture](../_bmad-output/planning-artifacts/architectures/architecture-rank-bidder-2026-05-27/architecture.md) — D1~D30 + D15 (a~t) + I1~I8 invariants
- [Epics & Stories](../_bmad-output/planning-artifacts/epics/epics-rank-bidder-2026-05-27/epics.md) — 6 Epic × 29 Stories
- [Implementation Readiness](../_bmad-output/planning-artifacts/implementation-readiness-report-2026-05-27.md) — READY
- [Sprint Status](../_bmad-output/implementation-artifacts/sprint-status.yaml)
- [Research](../_bmad-output/planning-artifacts/research/technical-naver-rank-bidder-feasibility-research-2026-05-27.md)
- [Brief + addendum](../_bmad-output/planning-artifacts/briefs/brief-rank-bidder-2026-05-27/)

## Hard Constraints (Architecture §11 + NFR)

- 운영비 **$0** (Always Free 한도 안에서만). 유료 플랜 비허용 (종속 회피).
- **24/7** 무중단 (NFR-1) + **graceful degradation**.
- **한국 IP** 측정 (NFR-6, Lambda `ap-northeast-2` 고정).
- **데이터 소유권** (NFR-7) — 외부 SaaS DB / 로그 위탁 금지. SQLite on Oracle.
- **단순성** (NFR-8, bus factor 1) — 신규 외부 의존 추가는 PRD/architecture 변경 절차 필수.

## License

본인 운영 도구 — 외부 광고주 onboarding / SaaS 제공 안 함 (PRD §5 Non-Goals).
