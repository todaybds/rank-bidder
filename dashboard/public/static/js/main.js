// Story 4.5 — index 페이지: import 모달 + chat health 배너.
// Story 4.2가 5요소 위젯 채울 자리.

const API_BASE = (window.RANKBIDDER_API_BASE || localStorage.getItem("apiBase") || "").replace(
  /\/$/,
  "",
);
const AUTH_TOKEN = window.RANKBIDDER_AUTH_TOKEN || localStorage.getItem("authToken") || "";

function authHeaders() {
  const h = { "content-type": "application/json" };
  if (AUTH_TOKEN) h["authorization"] = `Bearer ${AUTH_TOKEN}`;
  return h;
}

const modal = document.getElementById("import-modal");
const btnOpen = document.getElementById("btn-import");
const btnSubmit = document.getElementById("import-submit");
const resultEl = document.getElementById("import-result");

btnOpen?.addEventListener("click", () => {
  resultEl.textContent = "";
  modal.showModal();
});

btnSubmit?.addEventListener("click", async () => {
  // 2026-05-27 code-review 4.5 C1 fix: server expects `campaign_id` (not `naver_campaign_id`).
  // 2026-05-27 code-review 4.5 C2 fix: response = {imported, skipped, default_cap_applied, errors[]}.
  const site_id = document.getElementById("import-site-id").value.trim();
  const campaign_id = document.getElementById("import-campaign-id").value.trim();
  const target_rank = Number(document.getElementById("import-target").value);
  const bid_cap = Number(document.getElementById("import-bid-cap").value);
  if (!site_id || !campaign_id) {
    resultEl.textContent = "site_id + campaign_id 필수";
    return;
  }
  resultEl.textContent = "등록 중…";
  try {
    const resp = await fetch(`${API_BASE}/api/v1/imports`, {
      method: "POST",
      headers: authHeaders(),
      body: JSON.stringify({ site_id, campaign_id, target_rank, bid_cap }),
    });
    const json = await resp.json();
    if (!resp.ok) {
      const code = json?.detail?.error?.code || `HTTP_${resp.status}`;
      throw new Error(code);
    }
    const imported = json.imported ?? 0;
    const skipped = json.skipped ?? 0;
    const errors = json.errors ?? [];
    const capApplied = json.default_cap_applied ?? 0;
    let msg = `성공 ${imported} · 스킵 ${skipped} · 실패 ${errors.length}`;
    if (capApplied > 0) msg += ` (cap default 적용 ${capApplied})`;
    if (errors.length > 0) {
      const firstErrors = errors.slice(0, 3).map((e) => e.reason || JSON.stringify(e)).join("; ");
      msg += ` — ${firstErrors}${errors.length > 3 ? "…" : ""}`;
    }
    resultEl.textContent = msg;
  } catch (e) {
    resultEl.textContent = `실패: ${e.message}`;
  }
});

async function pingChat() {
  const banner = document.getElementById("chat-banner");
  if (!banner) return;
  try {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 5000);
    const resp = await fetch(`${API_BASE}/api/v1/chat/health`, {
      headers: authHeaders(),
      signal: controller.signal,
    });
    clearTimeout(timer);
    if (!resp.ok) throw new Error("not_ok");
    banner.hidden = true;
  } catch {
    banner.hidden = false;
    banner.textContent = "⚠ 챗 사용 불가 — 대시보드로 작업하세요.";
  }
}
pingChat();
setInterval(pingChat, 60_000);
