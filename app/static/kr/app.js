"use strict";

const $ = (sel) => document.querySelector(sel);

// Two run modes (see config.js):
//   STATIC=false -> live FastAPI backend (/api/kr/drift/{ticker}), local use
//   STATIC=true  -> pre-built JSON in ../data/kr/{ticker}.json (GitHub Pages)
const STATIC = !!window.SUH_DH_STATIC;
const BUILT = window.SUH_DH_BUILT || null;
const API_BASE = (window.SUH_DH_API_BASE || "").replace(/\/$/, "");

const OFFSETS = [1, 7, 30, 60];

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function fmtPct(v) {
  if (v === null || v === undefined) return "–";
  return (v > 0 ? "+" : "") + v.toFixed(1) + "%";
}

// Korean prices are whole won — show with thousands separators, no decimals.
function fmtWon(v) {
  if (v === null || v === undefined) return "–";
  return Math.round(Number(v)).toLocaleString("ko-KR");
}

// Diverging heat: gains red, losses blue (Korean market convention too).
function heatStyle(v) {
  if (v === null || v === undefined) return "";
  const a = Math.min(Math.abs(v) / 30, 1);
  const alpha = (0.12 + 0.7 * a).toFixed(2);
  const rgb = v > 0 ? "206,42,42" : "40,92,206";
  return `background: rgba(${rgb},${alpha}); color:#f8fafc;`;
}

function row(q) {
  const d = q.drift;
  const prev = d ? d.prev1_pct : null;
  const pre7 = d && d.pre_returns ? d.pre_returns["d-7"] : null;
  const r = (n) => (d && d.returns ? d.returns["d" + n] : null);
  const cells = OFFSETS.map((n) =>
    `<td class="num" style="${heatStyle(r(n))}">${fmtPct(r(n))}</td>`).join("");
  return `<tr>
    <td class="date">${esc(q.date)}${q.upcoming ? ' <span class="pending">예정</span>' : ""}</td>
    <td class="num">${d ? fmtWon(d.d_minus1_close) : "–"}</td>
    <td class="num strong">${d ? fmtWon(d.d0_close) : (q.upcoming ? "발표 전" : "–")}</td>
    <td class="num" style="${heatStyle(pre7)}">${fmtPct(pre7)}</td>
    <td class="num" style="${heatStyle(prev)}">${fmtPct(prev)}</td>
    ${cells}
  </tr>`;
}

function summaryCards(summary) {
  return OFFSETS.map((n) => {
    const s = summary["d" + n] || {};
    const cls = s.avg > 0 ? "up" : s.avg < 0 ? "down" : "";
    return `<div class="sum-card">
      <div class="sum-label">D+${n} 평균</div>
      <div class="sum-val ${cls}">${fmtPct(s.avg)}</div>
      <div class="sum-sub">상승 ${s.up ?? 0} / ${s.n ?? 0}회</div>
    </div>`;
  }).join("");
}

function render(data) {
  const rows = (data.quarters || []).map(row).join("");
  const auto = data.date_source === "yahoo"
    ? `<div class="src-note">ⓘ 등록되지 않은 종목이라 실적발표일을 Yahoo에서 자동 추정했습니다. 정확도가 낮을 수 있어요.</div>`
    : "";
  $("#content").innerHTML = `
    ${auto}
    <div class="table-wrap">
      <table class="drift">
        <thead><tr>
          <th>실적발표일</th><th>D-1 종가</th><th>발표일 종가</th><th>D-7</th><th>직전1일</th>
          <th>D+1</th><th>D+7</th><th>D+30</th><th>D+60</th>
        </tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>
    <div class="legend">
      <span class="lg-up">상승</span>
      <span class="swatch s1"></span><span class="swatch s2"></span><span class="swatch s3"></span>
      <span class="swatch s0"></span>
      <span class="swatch s-3"></span><span class="swatch s-2"></span><span class="swatch s-1"></span>
      <span class="lg-down">하락</span>
      <span class="spacer"></span>
      <span class="muted">D-7 = 발표 7거래일 전 → 직전일(D-1) 변동(발표 반응 제외) · D+N = 발표일 이후 N 거래일</span>
    </div>
    <div class="sum-caption">최근 ${data.summary_window ?? "–"}개 분기 평균</div>
    <div class="summary">${summaryCards(data.summary || {})}</div>`;
}

function renderError(msg, detail) {
  $("#content").innerHTML =
    `<div class="error"><b>${esc(msg)}</b>${detail ? "<br><small>" + esc(detail) + "</small>" : ""}</div>`;
  $("#status").textContent = "오류";
}

async function loadDrift(ticker) {
  ticker = (ticker || "").trim().toUpperCase();
  if (!ticker) return;
  $("#status").textContent = "불러오는 중…";
  $("#content").innerHTML = `<div class="loading">${esc(ticker)} 실적·주가 데이터를 불러오는 중…</div>`;
  try {
    const url = STATIC ? `../data/kr/${ticker}.json` : `/api/kr/drift/${ticker}`;
    let res = await fetch(url, { cache: "no-store" });
    if (!res.ok && STATIC) {
      if (API_BASE) {
        $("#content").innerHTML = `<div class="loading">${esc(ticker)} 라이브 조회 중 (백엔드)…</div>`;
        res = await fetch(`${API_BASE}/api/kr/drift/${ticker}`, { cache: "no-store" });
      } else {
        renderError(`${ticker}는 등록된 종목이 아닙니다.`,
          "정적 사이트에선 큐레이션된 국내 종목만 조회됩니다. 원하는 종목을 알려주면 실적발표일을 등록해 드려요.");
        return;
      }
    }
    const data = await res.json();
    if (!res.ok || data.error) {
      renderError(data.error || "데이터를 불러오지 못했습니다.", data.detail);
      return;
    }
    const name = data.name && data.name !== ticker ? `${data.name} (${ticker})` : ticker;
    document.title = `${name} 실적 전후 주가 · SUH_DH`;
    if (!(data.quarters || []).some((q) => q.drift)) {
      renderError(`${esc(name)}의 실적발표일을 찾지 못했습니다.`,
        "등록된 종목이 아니고 Yahoo에도 실적일 데이터가 없어요. 원하시면 이 종목을 큐레이션 목록에 등록해 드릴게요.");
      return;
    }
    render(data);
    const reported = (data.quarters || []).filter((q) => q.reported).length;
    $("#status").textContent = `${esc(name)} · 분기 ${reported}건`
      + (STATIC && BUILT ? ` · 갱신 ${new Date(BUILT).toLocaleDateString("ko-KR")}` : "");
    if (location.hash.slice(1) !== ticker) location.hash = ticker;
    renderRegistered(ticker);
  } catch (e) {
    renderError("데이터를 불러오지 못했습니다", e.message);
  }
}

// ---------- registered (curated) tickers side panel ----------
// Grouped by sector; Korean tickers are numeric codes so we show the name.
let REGISTERED_GROUPS = [];

function renderRegistered(active) {
  const wrap = $("#registered-list");
  if (!wrap) return;
  const flat = REGISTERED_GROUPS.flatMap((g) => g.items || []);
  if (!flat.length) {
    wrap.innerHTML = `<div class="reg-empty">아직 등록된 종목이 없어요.</div>`;
    return;
  }
  const a = (active || "").toUpperCase();
  wrap.innerHTML = REGISTERED_GROUPS.map((g) =>
    `<div class="reg-group">
       <div class="reg-sector">${esc(g.sector || "")}</div>
       ${(g.items || []).map((it) =>
         `<button type="button" class="reg-item${it.ticker === a ? " active" : ""}" data-t="${esc(it.ticker)}">${esc(it.name)}</button>`
       ).join("")}
     </div>`
  ).join("");
}

function fillDatalist() {
  const items = REGISTERED_GROUPS.flatMap((g) => g.items || []);
  $("#ticker-list").innerHTML = items.map((it) =>
    `<option value="${esc(it.ticker)}">${esc(it.name)}</option>`).join("");
}

async function loadRegistered() {
  try {
    const url = STATIC ? "../data/kr_tickers.json" : "/api/kr/tickers";
    const res = await fetch(url, { cache: "no-store" });
    if (res.ok) {
      const data = await res.json();
      REGISTERED_GROUPS = data.groups || [];
    }
  } catch (_) { /* panel is optional */ }
  fillDatalist();
  renderRegistered(location.hash.slice(1));
}

// ---------- events ----------
$("#load-btn").addEventListener("click", () => loadDrift($("#ticker-input").value));
$("#ticker-input").addEventListener("keydown", (e) => {
  if (e.key === "Enter") loadDrift($("#ticker-input").value);
});
function setPanel(open) {
  const p = $("#registered-panel");
  p.classList.toggle("open", open);
  p.setAttribute("aria-hidden", open ? "false" : "true");
}
$("#reg-toggle").addEventListener("click", () =>
  setPanel(!$("#registered-panel").classList.contains("open")));
$("#reg-close").addEventListener("click", () => setPanel(false));
$("#registered-list").addEventListener("click", (e) => {
  const btn = e.target.closest(".reg-item");
  if (!btn) return;
  $("#ticker-input").value = btn.dataset.t;
  loadDrift(btn.dataset.t);
  setPanel(false);
});

(async function init() {
  await loadRegistered();
  const first = REGISTERED_GROUPS.flatMap((g) => g.items || [])[0];
  const initial = location.hash.slice(1) || (first ? first.ticker : "");
  if (initial) {
    $("#ticker-input").value = initial;
    loadDrift(initial);
  }
})();
