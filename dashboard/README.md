# dashboard

Vercel 정적 hosting (Architecture step-04 D19~D22 + D29).

## 기술 스택

- **vanilla HTML + JS** (NFR-8 단순성, bus factor 1 — React/Next.js 거부)
- **Chart.js v4 CDN** (Story 4.2에서 차트 추가)
- **60s polling** fetch (Story 4.2 — FR-14 1분 신선도)
- **bearer auth** via Authorization header (Story 4.1 — FR-25)
- **robots noindex + Disallow** (D29)

## 페이지 (Story별)

- `/` (`index.html`) — 메인뷰 5요소 (Story 4.2, FR-14)
- `/keyword.html?id=` — 키워드 상세 (Story 4.3, FR-15)
- `/policies.html` — 멀티타임 정책 편집 (Story 3.3, FR-16)
- `/import.html` — import fallback 모달 (Story 4.5, FR-28)
- `/system.html` — 전역 통제 fallback (Story 4.5, FR-29)

## 로컬 dev

```powershell
cd c:\Users\ok\rank-bidder\dashboard
npx vercel dev
```

또는 단순 static server:

```powershell
python -m http.server 8080 --directory public
```

## 배포

`git push to main` → Vercel auto deploy (Story 4.1에서 Vercel 연결).
