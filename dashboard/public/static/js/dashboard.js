// 2026-05-28 보라웨어 톤 재설계 — 사이드바 + 상단 summary + KW 메인 테이블.
// 2 endpoint 병렬 fetch: /api/v1/metrics/dashboard (요약 5개) + /api/v1/keywords (KW 리스트).
// 60s auto-refresh + visibility-pause + 검색 클라이언트 사이드 필터.

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
  return Number(n).toLocaleString("ko-KR");
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
    const isoNorm = iso.includes("T") ? iso : iso.replace(" ", "T");
    const utc = isoNorm.endsWith("Z") || isoNorm.includes("+") ? isoNorm : isoNorm + "Z";
    const d = new Date(utc);
    return d.toLocaleString("ko-KR", {
      timeZone: "Asia/Seoul",
      hour12: false,
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
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

const decisionBadgeClass = {
  BID_UP: "bw-badge-up",
  BID_DOWN: "bw-badge-down",
  HOLD: "bw-badge-hold",
  CAP_REACHED: "bw-badge-warn",
  SKIP_STALE: "bw-badge-muted",
};

let keywordsCache = []; // 검색 필터링용

function setText(id, text) {
  const el = document.getElementById(id);
  if (el) el.textContent = text;
}

function renderSummary(metricsData) {
  const hr = metricsData.hit_rate_24h || {};
  if (hr.error) {
    setText("sum-hit-rate", "—");
    setText("sum-hit-rate-sub", "조회 실패");
  } else {
    const overall = hr.overall || {};
    setText("sum-hit-rate", fmtPct(overall.rate_pct));
    setText("sum-hit-rate-sub", `${overall.hit ?? 0} 적중 / ${overall.miss ?? 0} 빗나감`);
  }

  // 변동 Top 5에서 BID_UP/DOWN 카운트 (현 시점 24h)
  const movers = Array.isArray(metricsData.movers_top5) ? metricsData.movers_top5 : [];
  const up = movers.filter((m) => m.decision === "BID_UP").length;
  const down = movers.filter((m) => m.decision === "BID_DOWN").length;
  setText("sum-bid-up", up);
  setText("sum-bid-down", down);

  // CAP_REACHED 카운트 — current SERP 위젯에서 ?  KW 리스트 후처리에서 채움 (renderKeywords)
}

function renderKeywords(items) {
  const tbody = document.getElementById("kw-tbody");
  if (!tbody) return;
  if (!items || items.length === 0) {
    tbody.innerHTML =
      '<tr><td colspan="8" class="muted" style="padding:1.5rem;text-align:center">활성 KW 없음</td></tr>';
    return;
  }
  const rows = items
    .map((kw, idx) => {
      const dec = kw.last_decision || "—";
      const badgeCls = decisionBadgeClass[dec] || "bw-badge-muted";
      const decLabel = dec === "—" ? "없음" : dec;
      const stateCls = kw.enabled ? "" : "bw-row-disabled";
      return `<tr class="${stateCls}">
        <td class="num">${idx + 1}</td>
        <td class="bw-term">${escapeHtml(kw.term)}</td>
        <td class="num">${fmtRank(kw.target_rank)}</td>
        <td class="num bw-bid-current">${fmtKrw(kw.current_bid)}</td>
        <td class="num muted">${fmtKrw(kw.bid_cap)}</td>
        <td><span class="bw-badge ${badgeCls}">${escapeHtml(decLabel)}</span></td>
        <td class="muted bw-reason" title="${escapeHtml(kw.last_reason || "")}">${escapeHtml((kw.last_reason || "").slice(0, 50))}</td>
        <td class="num muted">${escapeHtml(fmtKstTime(kw.last_decision_at))}</td>
      </tr>`;
    })
    .join("");
  tbody.innerHTML = rows;

  // 활성 KW count + CAP_REACHED count 계산
  setText("kw-count", `(${items.filter((k) => k.enabled).length})`);
  const capReached = items.filter((k) => k.last_decision === "CAP_REACHED").length;
  setText("sum-cap-reached", capReached);
  setText("sum-active-kw", items.filter((k) => k.enabled).length);
}

function renderFailures(items) {
  const body = document.getElementById("failures-body");
  const count = document.getElementById("failures-count");
  if (!body) return;
  if (!items || items.length === 0) {
    body.innerHTML = '<p class="muted">최근 24시간 장애 없음 ✓</p>';
    if (count) count.textContent = "(0)";
    return;
  }
  if (items.error) {
    body.innerHTML = `<p class="error">조회 실패: ${escapeHtml(items.error.code)}</p>`;
    if (count) count.textContent = "";
    return;
  }
  if (count) count.textContent = `(${items.length})`;
  const rows = items
    .map(
      (f) =>
        `<li><time>${escapeHtml(fmtKstTime(f.at))}</time> <strong>${escapeHtml(f.event_type)}</strong> — ${escapeHtml(f.summary)}</li>`,
    )
    .join("");
  body.innerHTML = `<ul class="event-list">${rows}</ul>`;
}

async function refreshAll() {
  try {
    const [metricsResp, kwResp] = await Promise.all([
      fetch(`${API_BASE}/api/v1/metrics/dashboard`, { headers: authHeaders() }),
      fetch(`${API_BASE}/api/v1/keywords?enabled=true`, { headers: authHeaders() }),
    ]);
    if (!metricsResp.ok || !kwResp.ok) {
      const msg = `HTTP ${metricsResp.status}/${kwResp.status}`;
      document.getElementById("kw-tbody").innerHTML =
        `<tr><td colspan="8" class="error" style="padding:1rem">조회 실패 — ${escapeHtml(msg)} (인증/네트워크 확인)</td></tr>`;
      return;
    }
    const metricsData = await metricsResp.json();
    const kwData = await kwResp.json();
    keywordsCache = kwData.items || [];

    setText("generated-at", fmtKstTime(metricsData.generated_at));
    renderSummary(metricsData);
    applySearchAndRender();
    renderFailures(metricsData.system_failures_24h);
  } catch (e) {
    console.error("dashboard.refresh.failed", e);
    document.getElementById("kw-tbody").innerHTML =
      `<tr><td colspan="8" class="error" style="padding:1rem">네트워크 오류: ${escapeHtml(e.message)}</td></tr>`;
  }
}

function applySearchAndRender() {
  const q = (document.getElementById("kw-search")?.value || "").trim().toLowerCase();
  const filtered = q
    ? keywordsCache.filter((k) => (k.term || "").toLowerCase().includes(q))
    : keywordsCache;
  renderKeywords(filtered);
}

// auto-refresh + visibility pause
let refreshTimer = null;
function startAutoRefresh() {
  if (refreshTimer) return;
  refreshTimer = setInterval(() => {
    if (!document.hidden) refreshAll();
  }, REFRESH_INTERVAL_MS);
}
document.addEventListener("visibilitychange", () => {
  if (!document.hidden) refreshAll();
});
document.getElementById("btn-refresh")?.addEventListener("click", () => refreshAll());
document.getElementById("kw-search")?.addEventListener("input", () => applySearchAndRender());

refreshAll();
startAutoRefresh();
