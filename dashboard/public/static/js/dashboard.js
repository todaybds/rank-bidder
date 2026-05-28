// Story 4.2 — dashboard 5위젯 fetch + render + 60s auto-refresh.
// 위젯별 error isolation: endpoint 응답의 각 위젯 dict가 `error` 키를 가지면
// 그 위젯만 "데이터 없음" 표시, 다른 위젯은 정상 렌더.

const API_BASE = (window.RANKBIDDER_API_BASE || localStorage.getItem("apiBase") || "").replace(
  /\/$/,
  "",
);
const AUTH_TOKEN = window.RANKBIDDER_AUTH_TOKEN || localStorage.getItem("authToken") || "";

const REFRESH_INTERVAL_MS = 60 * 1000;

function authHeaders() {
  const h = { "content-type": "application/json" };
  if (AUTH_TOKEN) h["authorization"] = `Bearer ${AUTH_TOKEN}`;
  return h;
}

function fmtKrw(n) {
  if (n === null || n === undefined) return "—";
  return Number(n).toLocaleString("ko-KR") + "원";
}

function fmtPct(n) {
  if (n === null || n === undefined) return "—";
  return Number(n).toFixed(1) + "%";
}

function fmtRank(n) {
  if (n === null || n === undefined) return "—";
  return `${n}위`;
}

function fmtKstTime(iso) {
  if (!iso) return "—";
  try {
    // SQLite datetime은 UTC (KST 오프셋 없음). KST 변환.
    const isoNorm = iso.includes("T") ? iso : iso.replace(" ", "T");
    const utc = isoNorm.endsWith("Z") || isoNorm.includes("+") ? isoNorm : isoNorm + "Z";
    const d = new Date(utc);
    return d.toLocaleString("ko-KR", { timeZone: "Asia/Seoul", hour12: false });
  } catch {
    return iso;
  }
}

function escapeHtml(s) {
  if (s === null || s === undefined) return "";
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function widgetError(el, msg) {
  el.innerHTML = `<p class="error">⚠ ${escapeHtml(msg)}</p>`;
}

// ---------- Widget renderers ----------

function renderHitRate(el, data) {
  if (data.error) {
    return widgetError(el, `데이터 조회 실패: ${data.error.code}`);
  }
  const overall = data.overall || {};
  const bySite = data.by_site || [];
  const overallHtml = `
    <div class="big-number">${fmtPct(overall.rate_pct)}</div>
    <div class="muted">전체 (${overall.hit ?? 0}건 적중 / ${overall.miss ?? 0}건 빗나감)</div>
  `;
  const siteRows = bySite.length
    ? `<table class="compact"><thead><tr><th>사이트</th><th>적중률</th><th>적중/빗나감</th></tr></thead><tbody>${bySite
        .map(
          (s) =>
            `<tr><td>${escapeHtml(s.site_name)}</td><td>${fmtPct(s.rate_pct)}</td><td>${s.hit}/${s.miss}</td></tr>`,
        )
        .join("")}</tbody></table>`
    : `<p class="muted">사이트별 데이터 없음</p>`;
  el.innerHTML = overallHtml + siteRows;
}

function renderSerp(el, data) {
  if (data.error) {
    return widgetError(el, `데이터 조회 실패: ${data.error.code}`);
  }
  if (!Array.isArray(data) || data.length === 0) {
    el.innerHTML = `<p class="muted">활성 KW 없음</p>`;
    return;
  }
  // outlier 먼저 정렬
  const sorted = [...data].sort((a, b) => {
    if (a.outlier !== b.outlier) return b.outlier ? 1 : -1;
    return (a.delta ?? 99) - (b.delta ?? 99);
  });
  const rows = sorted
    .map((r) => {
      const cls = r.outlier ? "outlier" : "";
      const deltaText =
        r.delta === null || r.delta === undefined
          ? "측정 실패"
          : r.delta === 0
            ? "목표 일치"
            : r.delta > 0
              ? `+${r.delta} (목표보다 낮음)`
              : `${r.delta} (목표보다 높음)`;
      return `<tr class="${cls}"><td>${escapeHtml(r.term)}</td><td>${fmtRank(r.rank_observed)}</td><td>${fmtRank(r.target_rank)}</td><td>${deltaText}</td></tr>`;
    })
    .join("");
  el.innerHTML = `<table class="compact"><thead><tr><th>키워드</th><th>현재</th><th>목표</th><th>차이</th></tr></thead><tbody>${rows}</tbody></table>`;
}

function renderFailures(el, data) {
  if (data.error) {
    return widgetError(el, `데이터 조회 실패: ${data.error.code}`);
  }
  if (!Array.isArray(data) || data.length === 0) {
    el.innerHTML = `<p class="muted">최근 24시간 장애 없음 ✓</p>`;
    return;
  }
  const rows = data
    .map(
      (f) =>
        `<li><time>${escapeHtml(fmtKstTime(f.at))}</time> <strong>${escapeHtml(f.event_type)}</strong> — ${escapeHtml(f.summary)}</li>`,
    )
    .join("");
  el.innerHTML = `<ul class="event-list">${rows}</ul>`;
}

function renderMovers(el, data) {
  if (data.error) {
    return widgetError(el, `데이터 조회 실패: ${data.error.code}`);
  }
  if (!Array.isArray(data) || data.length === 0) {
    el.innerHTML = `<p class="muted">최근 24시간 입찰 변동 없음</p>`;
    return;
  }
  const rows = data
    .map((m) => {
      const dirClass = m.decision === "BID_UP" ? "up" : "down";
      const arrow = m.decision === "BID_UP" ? "▲" : "▼";
      return `<tr><td>${escapeHtml(m.term)}</td><td class="${dirClass}">${arrow} ${m.delta_pct}%</td><td>${fmtKrw(m.old_bid)} → ${fmtKrw(m.new_bid)}</td><td class="muted">${escapeHtml(fmtKstTime(m.decided_at))}</td></tr>`;
    })
    .join("");
  el.innerHTML = `<table class="compact"><thead><tr><th>키워드</th><th>변동</th><th>입찰가</th><th>시각</th></tr></thead><tbody>${rows}</tbody></table>`;
}

function renderSpend(el, data) {
  if (data.error) {
    return widgetError(el, `데이터 조회 실패: ${data.error.code}`);
  }
  if (!data.available) {
    el.innerHTML = `<p class="muted">${escapeHtml(data.note || "데이터 수집 대기")}</p><p class="muted">Story 4.4 광고비 일일 수집이 완료되면 자동 활성화됩니다.</p>`;
    return;
  }
  const todayHtml = `
    <div class="big-number">${fmtKrw(data.today_krw)}</div>
    <div class="muted">오늘 (이번달 누적 ${fmtKrw(data.month_krw)})</div>
  `;
  const bySite = data.by_site || [];
  const siteRows = bySite.length
    ? `<table class="compact"><thead><tr><th>사이트</th><th>오늘</th><th>이번달</th></tr></thead><tbody>${bySite
        .map(
          (s) =>
            `<tr><td>${escapeHtml(s.site_name)}</td><td>${fmtKrw(s.today_krw)}</td><td>${fmtKrw(s.month_krw)}</td></tr>`,
        )
        .join("")}</tbody></table>`
    : "";
  el.innerHTML = todayHtml + siteRows;
}

// ---------- Fetch + dispatch ----------

async function refreshDashboard() {
  try {
    const resp = await fetch(`${API_BASE}/api/v1/metrics/dashboard`, {
      method: "GET",
      headers: authHeaders(),
    });
    if (!resp.ok) {
      const text = await resp.text();
      // 위젯 5개 모두 같은 에러 메시지로 — 인증/네트워크 등 endpoint 자체 실패.
      const errMsg = `HTTP ${resp.status} — ${text.slice(0, 120)}`;
      ["widget-hit-rate", "widget-serp", "widget-failures", "widget-movers", "widget-spend"].forEach(
        (id) => {
          const body = document.querySelector(`#${id} .widget-body`);
          if (body) widgetError(body, errMsg);
        },
      );
      return;
    }
    const data = await resp.json();
    document.getElementById("generated-at").textContent = fmtKstTime(data.generated_at);

    renderHitRate(document.querySelector("#widget-hit-rate .widget-body"), data.hit_rate_24h || {});
    renderSerp(
      document.querySelector("#widget-serp .widget-body"),
      data.current_serp_vs_target || [],
    );
    renderFailures(
      document.querySelector("#widget-failures .widget-body"),
      data.system_failures_24h || [],
    );
    renderMovers(document.querySelector("#widget-movers .widget-body"), data.movers_top5 || []);
    renderSpend(document.querySelector("#widget-spend .widget-body"), data.spend_cum || {});
  } catch (e) {
    console.error("dashboard.refresh.failed", e);
    ["widget-hit-rate", "widget-serp", "widget-failures", "widget-movers", "widget-spend"].forEach(
      (id) => {
        const body = document.querySelector(`#${id} .widget-body`);
        if (body) widgetError(body, `네트워크 오류: ${e.message}`);
      },
    );
  }
}

// ---------- Auto-refresh with visibility pause ----------

let refreshTimer = null;

function startAutoRefresh() {
  if (refreshTimer) return;
  refreshTimer = setInterval(() => {
    if (!document.hidden) refreshDashboard();
  }, REFRESH_INTERVAL_MS);
}

function stopAutoRefresh() {
  if (refreshTimer) {
    clearInterval(refreshTimer);
    refreshTimer = null;
  }
}

document.addEventListener("visibilitychange", () => {
  // 탭이 다시 보이는 즉시 한 번 새로고침 (사용자가 돌아왔을 때 stale 데이터 보이는 거 회피).
  if (!document.hidden) refreshDashboard();
});

document.getElementById("btn-refresh")?.addEventListener("click", () => {
  refreshDashboard();
});

// 초기 1회 + 60s 주기 시작
refreshDashboard();
startAutoRefresh();
