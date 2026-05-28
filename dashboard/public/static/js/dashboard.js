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

const decisionLabel = {
  BID_UP: "▲ UP",
  BID_DOWN: "▼ DOWN",
  HOLD: "= HOLD",
  CAP_REACHED: "■ CAP",
  SKIP_STALE: "? SKIP",
};

/** 결정 사유 축약 — 길이 줄이고 핵심만. tooltip은 full 보존. */
function shortReason(reason, decision) {
  if (!reason) return "";
  // [estimate:N] 패턴 — gap만 추출
  const gap = reason.match(/gap\s+([+-]?[\d.]+%)/);
  if (gap) return `estimate gap ${gap[1]}`;
  if (decision === "CAP_REACHED") {
    const cap = reason.match(/CAP_REACHED at (\d+)/);
    return cap ? `cap ${Number(cap[1]).toLocaleString("ko-KR")}원` : "cap 도달";
  }
  if (decision === "HOLD") {
    if (reason.includes("deadband")) return "estimate 근접 (HOLD)";
    if (reason.includes("==")) return "목표 일치";
    if (reason.includes("PAUSED")) return "시스템 일시정지";
    return "HOLD";
  }
  if (reason.includes("BID_DOWN_FLOORED")) return "최저 100원 도달";
  if (reason.includes("BID_UP_CAPPED")) return "최대입찰가 도달";
  if (reason.includes("CAP_CLIP_DOWN")) return "최대입찰가 인하 적용";
  if (reason.includes("MEASUREMENT_FAILURE")) return "측정 실패";
  if (reason.includes("ESTIMATE_UNAVAILABLE")) return "추정 데이터 없음";
  return reason.slice(0, 40);
}

/** bid 변동 표시 (▲ +800 / ▼ -100 / 변동 없음). */
function bidDelta(current, previous) {
  if (current === null || current === undefined || previous === null || previous === undefined) {
    return "";
  }
  const diff = current - previous;
  if (diff === 0) return "";
  if (diff > 0) {
    return `<span class="bw-delta-up">▲ +${diff.toLocaleString("ko-KR")}</span>`;
  }
  return `<span class="bw-delta-down">▼ ${diff.toLocaleString("ko-KR")}</span>`;
}

/** 권장 cap 안내 badge — Naver estimate가 현재 cap을 초과 시 빨강 "권장 N원" 표시.
 * estimate <= cap이면 안내 안 함 (이미 충분). */
function recommendedCapBadge(cap, recommended) {
  if (recommended === null || recommended === undefined) return "";
  if (recommended <= cap) return ""; // 충분 — 안내 불필요
  const pct = Math.round(((recommended - cap) / cap) * 100);
  return `<div class="bw-cap-recommend">권장 ${fmtKrw(recommended)} <span class="bw-cap-gap">(+${pct}%)</span></div>`;
}

/** 순위 표시: "현재 / 목표" — rank_observed null이면 "— / N위". */
function rankDisplay(observed, target) {
  const tgt = target ? `${target}위` : "—";
  if (observed === null || observed === undefined) {
    return `<span class="muted">—</span> / <span class="bw-rank-target">${tgt}</span>`;
  }
  const obsCls = observed === target ? "bw-rank-hit" : "bw-rank-miss";
  return `<span class="${obsCls}">${observed}위</span> / <span class="bw-rank-target">${tgt}</span>`;
}

let keywordsCache = [];
let selected = new Set();
// 정렬 상태: column 키 + asc/desc. null이면 default (enabled DESC + bid_cap DESC).
let sortState = { col: null, dir: "asc" };

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
  let items = keywordsCache.filter((k) => {
    if (!showDisabled && !k.enabled) return false;
    if (q && !(k.term || "").toLowerCase().includes(q)) return false;
    return true;
  });
  // 정렬
  if (sortState.col) {
    const col = sortState.col;
    const dir = sortState.dir === "asc" ? 1 : -1;
    items = [...items].sort((a, b) => {
      const av = a[col];
      const bv = b[col];
      // null은 항상 맨 뒤
      if (av === null || av === undefined) return 1;
      if (bv === null || bv === undefined) return -1;
      if (typeof av === "number" && typeof bv === "number") return (av - bv) * dir;
      return String(av).localeCompare(String(bv), "ko") * dir;
    });
  }
  return items;
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
        const decLabel = dec === "—" ? "—" : decisionLabel[dec] || dec;
        const checked = selected.has(kw.id) ? "checked" : "";
        const enabledChecked = kw.enabled ? "checked" : "";
        const rowCls = [
          kw.enabled ? "" : "bw-row-disabled",
          dec === "CAP_REACHED" ? "bw-row-cap" : "",
          dec === "SKIP_STALE" ? "bw-row-stale" : "",
        ]
          .filter(Boolean)
          .join(" ");
        const delta = bidDelta(kw.current_bid, kw.previous_bid);
        const reason = shortReason(kw.last_reason, dec);
        const putAt = kw.last_put_at
          ? fmtKstTime(kw.last_put_at)
          : '<span class="muted">변경 이력 없음</span>';
        return `<tr class="${rowCls}" data-kw-id="${escapeHtml(kw.id)}" data-version="${kw.version}">
          <td class="check"><input type="checkbox" class="kw-check" data-id="${escapeHtml(kw.id)}" ${checked} /></td>
          <td class="num">${idx + 1}</td>
          <td class="bw-term">${escapeHtml(kw.term)}</td>
          <td class="num bw-rank-cell">${rankDisplay(kw.rank_observed, kw.target_rank)}</td>
          <td class="num bw-bid-cell">
            <span class="bw-bid-current">${fmtKrw(kw.current_bid)}</span>
            ${delta}
          </td>
          <td class="num editable" data-field="bid_cap" title="클릭해서 편집">
            ${fmtKrw(kw.bid_cap)}
            ${recommendedCapBadge(kw.bid_cap, kw.recommended_cap)}
          </td>
          <td><span class="bw-badge ${badgeCls}">${escapeHtml(decLabel)}</span></td>
          <td class="muted bw-reason" title="${escapeHtml(kw.last_reason || "")}">${escapeHtml(reason)}</td>
          <td class="num muted">${putAt}</td>
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
  const multRaw = document.getElementById("bulk-cap-multiplier").value.trim();
  const resultEl = document.getElementById("bulk-result");
  const ids = Array.from(selected);

  // 비율 변경 경로 — KW마다 다른 값이라 개별 PATCH N회.
  if (multRaw) {
    const mult = Number(multRaw);
    if (!Number.isFinite(mult) || mult <= 0 || mult > 10) {
      resultEl.textContent = "배수는 0.1~10 사이";
      return;
    }
    if (!confirm(`선택한 ${ids.length}개 KW의 최대입찰가에 × ${mult} 적용. 진행?`)) return;
    resultEl.textContent = `비율 변경 처리 중… 0/${ids.length}`;
    let ok = 0;
    let fail = 0;
    for (const id of ids) {
      const kw = keywordsCache.find((k) => k.id === id);
      if (!kw) {
        fail++;
        continue;
      }
      const raw = Math.max(100, Math.min(100000, Math.floor((kw.bid_cap * mult) / 100) * 100));
      try {
        const resp = await fetch(`${API_BASE}/api/v1/keywords/${id}`, {
          method: "PATCH",
          headers: authHeaders(),
          body: JSON.stringify({ bid_cap: raw, if_match_version: kw.version }),
        });
        if (resp.ok) ok++;
        else fail++;
      } catch {
        fail++;
      }
      resultEl.textContent = `비율 변경 처리 중… ${ok + fail}/${ids.length}`;
    }
    resultEl.textContent = `완료 — 변경 ${ok}개, 실패 ${fail}개`;
    selected.clear();
    setTimeout(() => {
      document.getElementById("bulk-edit-modal").close();
      refreshAll();
    }, 1000);
    return;
  }

  // 절대값 일괄
  const body = { keyword_ids: ids };
  if (target) body.target_rank = Number(target);
  if (cap) body.bid_cap = Number(cap);
  if (enabledRaw === "true") body.enabled = true;
  if (enabledRaw === "false") body.enabled = false;
  if (
    body.target_rank === undefined &&
    body.bid_cap === undefined &&
    body.enabled === undefined
  ) {
    resultEl.textContent = "최소 1개 필드 입력 필요 (또는 배수 입력)";
    return;
  }
  resultEl.textContent = "처리 중…";
  try {
    const resp = await fetch(`${API_BASE}/api/v1/keywords/bulk-update`, {
      method: "POST",
      headers: authHeaders(),
      body: JSON.stringify(body),
    });
    const j = await resp.json().catch(() => ({}));
    if (!resp.ok) {
      resultEl.textContent = `실패: ${j?.detail?.error?.code || resp.status}`;
      return;
    }
    resultEl.textContent = `완료 — 변경 ${j.updated}개, 실패 ${j.failed?.length ?? 0}개`;
    selected.clear();
    setTimeout(() => {
      document.getElementById("bulk-edit-modal").close();
      refreshAll();
    }, 800);
  } catch (e) {
    resultEl.textContent = `네트워크 오류: ${e.message}`;
  }
}

// ── CSV export ──────────────────────────────────────────────────

function exportCsv() {
  const items = filteredKeywords();
  if (!items.length) {
    alert("내보낼 키워드 없음 (검색/필터 결과 비어있음).");
    return;
  }
  const header = [
    "키워드",
    "사이트",
    "활성",
    "목표순위",
    "현재순위",
    "현재입찰가",
    "직전입찰가",
    "최대입찰가",
    "최근결정",
    "최근사유",
    "최근입찰변경",
  ];
  const rows = items.map((k) => [
    k.term,
    k.site_id,
    k.enabled ? "ON" : "OFF",
    k.target_rank,
    k.rank_observed ?? "",
    k.current_bid ?? "",
    k.previous_bid ?? "",
    k.bid_cap,
    k.last_decision ?? "",
    (k.last_reason ?? "").replace(/[\r\n]/g, " "),
    k.last_put_at ?? "",
  ]);
  const csv = [header, ...rows]
    .map((row) => row.map((cell) => `"${String(cell).replace(/"/g, '""')}"`).join(","))
    .join("\n");
  // BOM 박제 (Excel 한글 깨짐 차단)
  const blob = new Blob(["﻿" + csv], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  const ts = new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-");
  a.href = url;
  a.download = `rank-bidder-keywords-${ts}.csv`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

// ── 헤더 정렬 ──────────────────────────────────────────────────

function setupSortHandlers() {
  document.querySelectorAll(".bw-keywords-table th.sortable").forEach((th) => {
    th.addEventListener("click", () => {
      const col = th.dataset.sort;
      if (sortState.col === col) {
        sortState.dir = sortState.dir === "asc" ? "desc" : "asc";
      } else {
        sortState.col = col;
        sortState.dir = "asc";
      }
      // 모든 헤더 indicator 갱신
      document.querySelectorAll(".bw-keywords-table th.sortable").forEach((h) => {
        h.classList.remove("bw-sort-asc", "bw-sort-desc");
      });
      th.classList.add(sortState.dir === "asc" ? "bw-sort-asc" : "bw-sort-desc");
      renderKeywords();
    });
  });
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
  document.getElementById("bulk-cap-multiplier").value = "";
  document.getElementById("bulk-result").textContent = "";
  document.getElementById("bulk-edit-modal").showModal();
});

document.getElementById("btn-export-csv")?.addEventListener("click", () => exportCsv());

setupSortHandlers();

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
