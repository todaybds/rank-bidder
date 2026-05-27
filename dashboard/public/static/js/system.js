// Story 4.5 — system 통제 dashboard.

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

async function api(method, path, body) {
  const opts = { method, headers: authHeaders() };
  if (body !== undefined) opts.body = JSON.stringify(body);
  const resp = await fetch(`${API_BASE}${path}`, opts);
  const text = await resp.text();
  const json = text ? JSON.parse(text) : null;
  if (!resp.ok) {
    const code = json?.detail?.error?.code || `HTTP_${resp.status}`;
    throw new Error(code);
  }
  return json;
}

async function loadStatus() {
  try {
    const status = await api("GET", "/api/v1/system/status");
    const el = document.getElementById("pause-status");
    if (status.general_bid_paused) {
      el.textContent = "⏸ 일시정지";
      el.style.color = "#c33";
    } else {
      el.textContent = "▶ 정상";
      el.style.color = "#080";
    }
  } catch (e) {
    document.getElementById("pause-status").textContent = `조회 실패: ${e.message}`;
  }
}

async function pause() {
  if (!confirm("전체 자동입찰 일시정지 — 진행 시 OK")) return;
  try {
    await api("POST", "/api/v1/system/pause-all");
    await loadStatus();
  } catch (e) {
    alert(`일시정지 실패: ${e.message}`);
  }
}

async function resume() {
  if (!confirm("자동입찰 재개 — 진행 시 OK")) return;
  try {
    await api("POST", "/api/v1/system/resume");
    await loadStatus();
  } catch (e) {
    alert(`재개 실패: ${e.message}`);
  }
}

async function pingChat() {
  const statusEl = document.getElementById("chat-status");
  const banner = document.getElementById("chat-banner");
  try {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 5000);
    const resp = await fetch(`${API_BASE}/api/v1/chat/health`, {
      headers: authHeaders(),
      signal: controller.signal,
    });
    clearTimeout(timer);
    if (!resp.ok) throw new Error(`HTTP_${resp.status}`);
    statusEl.textContent = "OK";
    statusEl.style.color = "#080";
    banner.hidden = true;
  } catch (e) {
    statusEl.textContent = `장애 (${e.name || "error"})`;
    statusEl.style.color = "#c33";
    banner.hidden = false;
    banner.textContent = "⚠ 챗 사용 불가 — 대시보드로 작업하세요. (FR-30 fallback)";
  }
}

document.getElementById("btn-pause").addEventListener("click", pause);
document.getElementById("btn-resume").addEventListener("click", resume);

loadStatus();
pingChat();
setInterval(pingChat, 60_000);
