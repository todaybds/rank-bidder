// Story 3.3 — 멀티타임 정책 편집 GUI.
// Bearer 토큰은 Vercel build-time env `RANKBIDDER_API_BASE` + `RANKBIDDER_AUTH_TOKEN`로
// 주입. dev 환경에선 localStorage에서 fallback.

const API_BASE = (window.RANKBIDDER_API_BASE || localStorage.getItem("apiBase") || "").replace(
  /\/$/,
  "",
);
const AUTH_TOKEN = window.RANKBIDDER_AUTH_TOKEN || localStorage.getItem("authToken") || "";

const WEEKDAY_LABELS = ["월", "화", "수", "목", "금", "토", "일"];

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
    throw new Error(`${code}: ${JSON.stringify(json?.detail || json)}`);
  }
  return json;
}

function minuteOfWeekToWeekdayTime(m) {
  const weekday = Math.floor(m / 1440);
  const min = m % 1440;
  const hh = String(Math.floor(min / 60)).padStart(2, "0");
  const mm = String(min % 60).padStart(2, "0");
  return { weekday, time: `${hh}:${mm}` };
}

function durationLabel(min) {
  if (min < 60) return `${min}분`;
  const h = Math.floor(min / 60);
  const m = min % 60;
  return m ? `${h}h${m}m` : `${h}h`;
}

function detectOverlap(policies) {
  // 같은 minute_of_week 구간이 1개 초과로 매치되는 경우 = overlap.
  const total = 10080;
  for (let m = 0; m < total; m += 60) {
    let hits = 0;
    for (const p of policies) {
      const offset = ((m - p.start_minute_of_week) % total + total) % total;
      if (offset < p.duration_minutes) hits += 1;
      if (hits > 1) return true;
    }
  }
  return false;
}

function renderPolicies(policies) {
  const tbody = document.querySelector("#policy-table tbody");
  const empty = document.getElementById("policy-empty");
  const overlap = document.getElementById("policy-overlap");
  tbody.innerHTML = "";

  if (!policies.length) {
    empty.hidden = false;
    overlap.hidden = true;
    return;
  }
  empty.hidden = true;

  if (detectOverlap(policies)) {
    overlap.hidden = false;
    overlap.textContent =
      "⚠ 시간 구간 중복 — 다중 매치 시 가장 최근 등록(highest id) 정책이 우선합니다.";
  } else {
    overlap.hidden = true;
  }

  for (const p of policies) {
    const { weekday, time } = minuteOfWeekToWeekdayTime(p.start_minute_of_week);
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${p.id}</td>
      <td>${WEEKDAY_LABELS[weekday]} ${time}</td>
      <td>${durationLabel(p.duration_minutes)}</td>
      <td>${p.target_rank}</td>
      <td>${p.bid_cap.toLocaleString()}</td>
      <td>${p.version}</td>
      <td>
        <button data-action="edit" data-id="${p.id}">편집</button>
        <button data-action="delete" data-id="${p.id}" data-version="${p.version}" class="danger">삭제</button>
      </td>
    `;
    tbody.appendChild(tr);
  }
}

async function loadPolicies() {
  const scope_type = document.getElementById("scope-type").value;
  const scope_id = document.getElementById("scope-id").value.trim();
  if (!scope_id) {
    alert("scope id 입력 필요");
    return;
  }
  try {
    const data = await api(
      "GET",
      `/api/v1/policies?scope_type=${encodeURIComponent(scope_type)}&scope_id=${encodeURIComponent(scope_id)}`,
    );
    renderPolicies(data.items);
  } catch (e) {
    alert(`로드 실패: ${e.message}`);
  }
}

function timeToMinuteOfDay(t) {
  const [hh, mm] = t.split(":").map(Number);
  return hh * 60 + mm;
}

function getSelectedWeekdays() {
  return [...document.querySelectorAll("input[name=weekday]:checked")].map((el) =>
    Number(el.value),
  );
}

function readForm() {
  const weekdays = getSelectedWeekdays();
  const time = document.getElementById("start-time").value;
  if (!weekdays.length || !time) {
    throw new Error("요일 + 시작 시각 필수");
  }
  return {
    weekdays,
    minute_of_day: timeToMinuteOfDay(time),
    duration_minutes: Number(document.getElementById("duration").value),
    target_rank: Number(document.getElementById("target-rank").value),
    bid_cap: Number(document.getElementById("bid-cap").value),
  };
}

function resetForm() {
  document.getElementById("form-policy-id").value = "";
  document.getElementById("form-version").value = "";
  document.querySelectorAll("input[name=weekday]").forEach((el) => (el.checked = false));
  document.getElementById("start-time").value = "";
  document.getElementById("duration").value = "60";
  document.getElementById("target-rank").value = "2";
  document.getElementById("bid-cap").value = "5000";
}

async function submitForm(ev) {
  ev.preventDefault();
  const editingId = document.getElementById("form-policy-id").value;
  const scope_type = document.getElementById("scope-type").value;
  const scope_id = document.getElementById("scope-id").value.trim();

  let form;
  try {
    form = readForm();
  } catch (e) {
    alert(e.message);
    return;
  }

  try {
    if (editingId) {
      // PUT — 첫 번째 weekday 만 사용 (편집 시 1 row).
      const weekday = form.weekdays[0];
      const start_minute_of_week = weekday * 1440 + form.minute_of_day;
      await api("PUT", `/api/v1/policies/${editingId}`, {
        if_match_version: Number(document.getElementById("form-version").value),
        start_minute_of_week,
        duration_minutes: form.duration_minutes,
        target_rank: form.target_rank,
        bid_cap: form.bid_cap,
      });
    } else {
      // POST — weekday 다중 선택 → 각각 1 row.
      for (const weekday of form.weekdays) {
        const start_minute_of_week = weekday * 1440 + form.minute_of_day;
        await api("POST", "/api/v1/policies", {
          scope_type,
          scope_id,
          start_minute_of_week,
          duration_minutes: form.duration_minutes,
          target_rank: form.target_rank,
          bid_cap: form.bid_cap,
        });
      }
    }
    resetForm();
    await loadPolicies();
  } catch (e) {
    alert(`저장 실패: ${e.message}`);
  }
}

async function tableClick(ev) {
  const btn = ev.target.closest("button[data-action]");
  if (!btn) return;
  const id = btn.dataset.id;
  if (btn.dataset.action === "delete") {
    if (!confirm(`정책 ${id} 삭제?`)) return;
    try {
      await api("DELETE", `/api/v1/policies/${id}?if_match_version=${btn.dataset.version}`);
      await loadPolicies();
    } catch (e) {
      alert(`삭제 실패: ${e.message}`);
    }
    return;
  }
  if (btn.dataset.action === "edit") {
    const row = btn.closest("tr");
    const cells = row.querySelectorAll("td");
    // td 순서: id / 요일·시각 / 지속 / target / cap / v / actions
    const weekdayLabel = cells[1].textContent.split(" ")[0];
    const time = cells[1].textContent.split(" ")[1];
    const weekday = WEEKDAY_LABELS.indexOf(weekdayLabel);
    document.querySelectorAll("input[name=weekday]").forEach((el) => {
      el.checked = Number(el.value) === weekday;
    });
    document.getElementById("start-time").value = time;
    // 지속 — table은 라벨이라 server에서 받은 raw value를 다시 GET → 단순화 위해 alert.
    // 실제 편집은 PUT API 가 모든 필드 받음 → 사용자에게 분 단위로 다시 입력 권장.
    document.getElementById("form-policy-id").value = id;
    document.getElementById("form-version").value = row.cells[5].textContent;
    document.getElementById("target-rank").value = cells[3].textContent;
    document.getElementById("bid-cap").value = cells[4].textContent.replace(/,/g, "");
    // 지속만 사용자에게 다시 입력 요청
    alert(`정책 ${id} 편집 — 지속(분) 값을 다시 확인/입력하세요.`);
  }
}

document.getElementById("load-policies").addEventListener("click", loadPolicies);
document.getElementById("policy-form").addEventListener("submit", submitForm);
document.getElementById("reset-form").addEventListener("click", resetForm);
document.querySelector("#policy-table tbody").addEventListener("click", tableClick);
