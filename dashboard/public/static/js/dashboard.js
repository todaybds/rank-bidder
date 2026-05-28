// 2026-05-28 보라웨어 톤 + 인라인 편집 + 일괄 변경.
// 2 endpoint fetch + 인라인 편집 PATCH + 일괄 POST.

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

let keywordsCache = [];
let selected = new Set();

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
  const movers = Array.isArray(metricsData.movers_top5) ? metricsData.movers_top5 : [];
  setText("sum-bid-up", movers.filter((m) => m.decision === "BID_UP").length);
  setText("sum-bid-down", movers.filter((m) => m.decision === "BID_DOWN").length);
}

function filteredKeywords() {
  const q = (document.getElementById("kw-search")?.value || "").trim().toLowerCase();
  const showDisabled = document.getElementById("show-disabled")?.checked;
  return keywordsCache.filter((k) => {
    if (!showDisabled && !k.enabled) return false;
    if (q && !(k.term || "").toLowerCase().includes(q)) return false;
    return true;
  });
}

function renderKeywords() {
  const items = filteredKeywords();
  const tbody = document.getElementById("kw-tbody");
  if (!tbody) return;
  if (!items.length) {
    tbody.innerHTML =
      '<tr><td colspan="10" class="muted" style="padding:1.5rem;text-align:center">키워드 없음</td></tr>';
  } else {
    tbody.innerHTML = items
      .map((kw, idx) => {
        const dec = kw.last_decision || "—";
        const badgeCls = decisionBadgeClass[dec] || "bw-badge-muted";
        const decLabel = dec === "—" ? "없음" : dec;
        const checked = selected.has(kw.id) ? "checked" : "";
        const enabledChecked = kw.enabled ? "checked" : "";
        const stateCls = kw.enabled ? "" : "bw-row-disabled";
        return `<tr class="${stateCls}" data-kw-id="${escapeHtml(kw.id)}" data-version="${kw.version}">
          <td class="check"><input type="checkbox" class="kw-check" data-id="${escapeHtml(kw.id)}" ${checked} /></td>
          <td class="num">${idx + 1}</td>
          <td class="bw-term">${escapeHtml(kw.term)}</td>
          <td class="num editable" data-field="target_rank" title="클릭해서 편집">${fmtRank(kw.target_rank)}</td>
          <td class="num bw-bid-current">${fmtKrw(kw.current_bid)}</td>
          <td class="num editable" data-field="bid_cap" title="클릭해서 편집">${fmtKrw(kw.bid_cap)}</td>
          <td><span class="bw-badge ${badgeCls}">${escapeHtml(decLabel)}</span></td>
          <td class="muted bw-reason" title="${escapeHtml(kw.last_reason || "")}">${escapeHtml((kw.last_reason || "").slice(0, 50))}</td>
          <td class="num muted">${escapeHtml(fmtKstTime(kw.last_decision_at))}</td>
          <td class="check"><input type="checkbox" class="kw-toggle" data-id="${escapeHtml(kw.id)}" data-version="${kw.version}" ${enabledChecked} /></td>
        </tr>`;
      })
      .join("");
  }
  setText("kw-count", `(${items.length} / 전체 ${keywordsCache.length})`);
  setText("sum-active-kw", keywordsCache.filter((k) => k.enabled).length);
  setText("sum-cap-reached", keywordsCache.filter((k) => k.last_decision === "CAP_REACHED").length);
  updateBulkButton();
}

function updateBulkButton() {
  const btn = document.getElementById("btn-bulk-edit");
  setText("selected-count", `(${selected.size})`);
  if (btn) btn.disabled = selected.size === 0;
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
    return;
  }
  if (count) count.textContent = `(${items.length})`;
  body.innerHTML = `<ul class="event-list">${items
    .map(
      (f) =>
        `<li><time>${escapeHtml(fmtKstTime(f.at))}</time> <strong>${escapeHtml(f.event_type)}</strong> — ${escapeHtml(f.summary)}</li>`,
    )
    .join("")}</ul>`;
}

async function refreshAll() {
  try {
    const [metricsResp, kwResp] = await Promise.all([
      fetch(`${API_BASE}/api/v1/metrics/dashboard`, { headers: authHeaders() }),
      fetch(`${API_BASE}/api/v1/keywords`, { headers: authHeaders() }),
    ]);
    if (!metricsResp.ok || !kwResp.ok) {
      const msg = `HTTP ${metricsResp.status}/${kwResp.status}`;
      document.getElementById("kw-tbody").innerHTML =
        `<tr><td colspan="10" class="error" style="padding:1rem">조회 실패 — ${escapeHtml(msg)}</td></tr>`;
      return;
    }
    const metricsData = await metricsResp.json();
    const kwData = await kwResp.json();
    keywordsCache = kwData.items || [];
    setText("generated-at", fmtKstTime(metricsData.generated_at));
    renderSummary(metricsData);
    renderKeywords();
    renderFailures(metricsData.system_failures_24h);
  } catch (e) {
    console.error("dashboard.refresh.failed", e);
    document.getElementById("kw-tbody").innerHTML =
      `<tr><td colspan="10" class="error" style="padding:1rem">네트워크 오류: ${escapeHtml(e.message)}</td></tr>`;
  }
}

// ── 인라인 편집 ──────────────────────────────────────────────────

function startInlineEdit(cell) {
  if (cell.querySelector("input")) return; // 이미 편집 중
  const tr = cell.closest("tr");
  const kwId = tr.dataset.kwId;
  const version = Number(tr.dataset.version);
  const field = cell.dataset.field;
  const kw = keywordsCache.find((k) => k.id === kwId);
  if (!kw) return;
  const oldValue = field === "target_rank" ? kw.target_rank : kw.bid_cap;
  const min = field === "target_rank" ? 1 : 100;
  const max = field === "target_rank" ? 10 : 100000;
  const step = field === "target_rank" ? 1 : 100;

  cell.innerHTML = `<input type="number" class="bw-inline-input" value="${oldValue}" min="${min}" max="${max}" step="${step}" />`;
  const input = cell.querySelector("input");
  input.focus();
  input.select();

  const commit = async () => {
    const newVal = Number(input.value);
    if (!Number.isFinite(newVal) || newVal === oldValue) {
      cell.textContent = field === "target_rank" ? fmtRank(oldValue) : fmtKrw(oldValue);
      return;
    }
    cell.innerHTML = '<span class="muted">저장 중…</span>';
    try {
      const body = { if_match_version: version };
      body[field] = newVal;
      const resp = await fetch(`${API_BASE}/api/v1/keywords/${kwId}`, {
        method: "PATCH",
        headers: authHeaders(),
        body: JSON.stringify(body),
      });
      if (!resp.ok) {
        const j = await resp.json().catch(() => ({}));
        const code = j?.detail?.error?.code || `HTTP_${resp.status}`;
        cell.innerHTML = `<span class="error">실패: ${escapeHtml(code)}</span>`;
        setTimeout(() => refreshAll(), 1500);
        return;
      }
      refreshAll(); // 전체 새로고침으로 모든 데이터 동기화
    } catch (e) {
      cell.innerHTML = `<span class="error">네트워크 오류</span>`;
      setTimeout(() => refreshAll(), 1500);
    }
  };

  input.addEventListener("blur", commit);
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      input.blur();
    } else if (e.key === "Escape") {
      cell.textContent = field === "target_rank" ? fmtRank(oldValue) : fmtKrw(oldValue);
    }
  });
}

// ── 토글 (행 우측 ON 체크박스) ──────────────────────────────────

async function toggleKeyword(kwId, version, enabled) {
  try {
    const resp = await fetch(`${API_BASE}/api/v1/keywords/${kwId}/toggle`, {
      method: "POST",
      headers: authHeaders(),
      body: JSON.stringify({ enabled, if_match_version: version }),
    });
    if (!resp.ok) {
      alert(`토글 실패: HTTP ${resp.status}`);
    }
  } catch (e) {
    alert(`토글 네트워크 오류: ${e.message}`);
  }
  refreshAll();
}

// ── 일괄 변경 ──────────────────────────────────────────────────

async function submitBulkEdit() {
  const target = document.getElementById("bulk-target").value.trim();
  const cap = document.getElementById("bulk-cap").value.trim();
  const enabledRaw = document.getElementById("bulk-enabled").value;
  const body = { keyword_ids: Array.from(selected) };
  if (target) body.target_rank = Number(target);
  if (cap) body.bid_cap = Number(cap);
  if (enabledRaw === "true") body.enabled = true;
  if (enabledRaw === "false") body.enabled = false;
  if (
    body.target_rank === undefined &&
    body.bid_cap === undefined &&
    body.enabled === undefined
  ) {
    document.getElementById("bulk-result").textContent = "최소 1개 필드 입력 필요";
    return;
  }
  document.getElementById("bulk-result").textContent = "처리 중…";
  try {
    const resp = await fetch(`${API_BASE}/api/v1/keywords/bulk-update`, {
      method: "POST",
      headers: authHeaders(),
      body: JSON.stringify(body),
    });
    const j = await resp.json().catch(() => ({}));
    if (!resp.ok) {
      document.getElementById("bulk-result").textContent =
        `실패: ${j?.detail?.error?.code || resp.status}`;
      return;
    }
    document.getElementById("bulk-result").textContent =
      `완료 — 변경 ${j.updated}개, 실패 ${j.failed?.length ?? 0}개`;
    selected.clear();
    setTimeout(() => {
      document.getElementById("bulk-edit-modal").close();
      refreshAll();
    }, 800);
  } catch (e) {
    document.getElementById("bulk-result").textContent = `네트워크 오류: ${e.message}`;
  }
}

// ── 이벤트 위임 ─────────────────────────────────────────────────

document.getElementById("kw-tbody")?.addEventListener("click", (e) => {
  const editable = e.target.closest(".editable");
  if (editable) {
    startInlineEdit(editable);
    return;
  }
});

document.getElementById("kw-tbody")?.addEventListener("change", (e) => {
  const check = e.target.closest(".kw-check");
  if (check) {
    if (check.checked) selected.add(check.dataset.id);
    else selected.delete(check.dataset.id);
    updateBulkButton();
    return;
  }
  const toggle = e.target.closest(".kw-toggle");
  if (toggle) {
    toggleKeyword(toggle.dataset.id, Number(toggle.dataset.version), toggle.checked);
    return;
  }
});

document.getElementById("select-all")?.addEventListener("change", (e) => {
  const items = filteredKeywords();
  if (e.target.checked) items.forEach((k) => selected.add(k.id));
  else items.forEach((k) => selected.delete(k.id));
  renderKeywords();
});

document.getElementById("btn-bulk-edit")?.addEventListener("click", () => {
  document.getElementById("bulk-count").textContent = `(${selected.size}개)`;
  document.getElementById("bulk-target").value = "";
  document.getElementById("bulk-cap").value = "";
  document.getElementById("bulk-enabled").value = "";
  document.getElementById("bulk-result").textContent = "";
  document.getElementById("bulk-edit-modal").showModal();
});

document.getElementById("bulk-submit")?.addEventListener("click", () => submitBulkEdit());

// search + 비활성 포함 토글
document.getElementById("kw-search")?.addEventListener("input", () => renderKeywords());
document.getElementById("show-disabled")?.addEventListener("change", () => renderKeywords());

// refresh
document.getElementById("btn-refresh")?.addEventListener("click", () => refreshAll());

// auto-refresh
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

refreshAll();
startAutoRefresh();
