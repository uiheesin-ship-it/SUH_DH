"use strict";

const $ = (sel) => document.querySelector(sel);

// Two run modes (see config.js):
//   STATIC=false -> live FastAPI backend (/api/drift/{ticker}), local use
//   STATIC=true  -> pre-built JSON in ../data/drift/{ticker}.json (GitHub Pages),
//                   limited to the tickers listed in ../data/drift/_index.json
const STATIC = !!window.SUH_DH_STATIC;
const BUILT = window.SUH_DH_BUILT || null;
// Optional always-on backend (e.g. a hosted FastAPI or your ngrok URL). When
// set, the static site falls back to it for tickers that weren't pre-built,
// so any ticker works. Configure via config.js (window.SUH_DH_API_BASE).
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

function fmtNum(v, digits = 2) {
  if (v === null || v === undefined) return "–";
  return Number(v).toFixed(digits);
}

// Diverging heat: gains red, losses blue (matching the reference table).
// Saturates around ±30% so a normal earnings move still reads clearly.
function heatStyle(v) {
  if (v === null || v === undefined) return "";
  const a = Math.min(Math.abs(v) / 30, 1);          // saturate at ±30%
  const alpha = (0.12 + 0.7 * a).toFixed(2);
  const rgb = v > 0 ? "206,42,42" : "40,92,206";     // gains red, losses blue
  return `background: rgba(${rgb},${alpha}); color:#f8fafc;`;
}

// EPS / guidance result -> badge class.
const RESULT_CLASS = {
  "대폭상회": "r-strong-up", "상회": "r-up", "소폭상회": "r-slight-up",
  "부합": "r-inline", "소폭하회": "r-slight-down", "하회": "r-down",
  "대폭하회": "r-strong-down", "발표예정": "r-pending",
};

function epsCell(q) {
  const cls = RESULT_CLASS[q.result_ko] || "r-inline";
  const sub = q.surprise_pct !== null && q.surprise_pct !== undefined
    ? `<span class="sub">${fmtPct(q.surprise_pct)}</span>` : "";
  const tip = (q.eps_estimate !== null && q.eps_estimate !== undefined)
    ? `컨센 ${fmtNum(q.eps_estimate)} / 실제 ${fmtNum(q.reported_eps)}` : "발표 전";
  return `<span class="badge ${cls}" title="${esc(tip)}">${esc(q.result_ko)}</span>${sub}`;
}

function guidanceCell(q) {
  if (!q.guidance || !q.guidance.length) return "<span class='muted'>–</span>";
  return q.guidance.map((g) => {
    const cls = RESULT_CLASS[g.guidance_result_ko] || "r-inline";
    const sp = g.guidance_surprise_pct !== null && g.guidance_surprise_pct !== undefined
      ? ` (${fmtPct(g.guidance_surprise_pct)})` : "";
    const metric = g.metric === "revenue" ? "매출" : g.metric === "eps" ? "EPS" : g.metric || "";
    const period = g.guided_period ? esc(g.guided_period) + " " : "";
    const numbers = (g.guidance_mid !== undefined && g.consensus !== undefined)
      ? `<span class="sub">${period}${metric} 가이드 ${esc(g.guidance_mid)} vs 컨센 ${esc(g.consensus)}</span>` : "";
    const src = (g.sources && g.sources.length)
      ? ` <a class="src" href="${esc(g.sources[0])}" target="_blank" rel="noopener" title="출처">↗</a>` : "";
    const note = g.note ? ` <span class="note" title="${esc(g.note)}">ⓘ</span>` : "";
    return `<div class="gline"><span class="badge ${cls}">${esc(g.guidance_result_ko)}${sp}</span>${numbers}${src}${note}</div>`;
  }).join("");
}

function row(q) {
  const d = q.drift;
  const prev = d ? d.prev1_pct : null;
  const pre7 = d && d.pre_returns ? d.pre_returns["d-7"] : null;
  const r = (n) => (d && d.returns ? d.returns["d" + n] : null);
  const cells = OFFSETS.map((n) =>
    `<td class="num" style="${heatStyle(r(n))}">${fmtPct(r(n))}</td>`).join("");
  return `<tr>
    <td class="date">${esc(q.date)}</td>
    <td class="num">${d ? fmtNum(d.d_minus1_close) : "–"}</td>
    <td class="num strong">${d ? fmtNum(d.d0_close) : (q.upcoming ? "발표 전" : "–")}</td>
    <td class="num" style="${heatStyle(pre7)}">${fmtPct(pre7)}</td>
    <td class="num" style="${heatStyle(prev)}">${fmtPct(prev)}</td>
    ${cells}
    <td class="eps">${epsCell(q)}</td>
    <td class="guide">${guidanceCell(q)}</td>
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
  $("#content").innerHTML = `
    <div class="table-wrap">
      <table class="drift">
        <thead><tr>
          <th>실적발표일</th><th>D-1 종가</th><th>발표일 종가</th><th>D-7</th><th>직전1일</th>
          <th>D+1</th><th>D+7</th><th>D+30</th><th>D+60</th>
          <th>EPS vs 컨센</th><th>가이던스 vs 컨센</th>
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
    const url = STATIC ? `../data/drift/${ticker}.json` : `/api/drift/${ticker}`;
    let res = await fetch(url, { cache: "no-store" });
    if (!res.ok && STATIC) {
      // Not pre-built. If a backend is configured, fetch the ticker live there;
      // otherwise explain the static-site limitation.
      if (API_BASE) {
        $("#content").innerHTML = `<div class="loading">${esc(ticker)} 라이브 조회 중 (백엔드)…</div>`;
        res = await fetch(`${API_BASE}/api/drift/${ticker}`, { cache: "no-store" });
      } else {
        renderError(`${ticker}는 미리 만들어진 목록에 없습니다.`,
          "정적 사이트에선 큐레이션된 티커만 조회됩니다. 백엔드(SUH_DH_API_BASE)를 연결하면 아무 티커나 라이브로 조회할 수 있어요. (또는 로컬 ./run.sh 실행)");
        return;
      }
    }
    const data = await res.json();
    if (!res.ok || data.error) {
      renderError(data.error || "데이터를 불러오지 못했습니다.", data.detail);
      return;
    }
    document.title = `${ticker} 실적 전후 주가 · SUH_DH`;
    render(data);
    const demo = (data.quarters || []).some((q) => q.guidance && q.guidance.some((g) => (g.note || "").includes("데모")));
    $("#demo-badge").classList.toggle("hidden", !demo);
    const reported = (data.quarters || []).filter((q) => q.reported).length;
    $("#status").textContent = `${esc(ticker)} · 실적 ${reported}건`
      + (STATIC && BUILT ? ` · 갱신 ${new Date(BUILT).toLocaleDateString("ko-KR")}` : "");
    if (location.hash.slice(1) !== ticker) location.hash = ticker;
    renderRegistered(ticker);  // highlight in the side panel if registered
  } catch (e) {
    renderError("데이터를 불러오지 못했습니다", e.message);
  }
}

// In static mode, offer the pre-built tickers as a datalist.
async function loadIndex() {
  if (!STATIC) return;
  try {
    const res = await fetch("../data/drift/_index.json", { cache: "no-store" });
    if (!res.ok) return;
    const { tickers = [] } = await res.json();
    $("#ticker-list").innerHTML = tickers.map((t) => `<option value="${esc(t)}">`).join("");
    if (tickers.length && !$("#ticker-input").value && !location.hash.slice(1)) {
      $("#ticker-input").value = tickers[0];
    }
  } catch (_) { /* index is optional */ }
}

// ---------- registered (guidance) tickers side panel ----------
let REGISTERED = [];

function renderRegistered(active) {
  const ul = $("#registered-list");
  if (!ul) return;
  if (!REGISTERED.length) {
    ul.innerHTML = `<li class="reg-empty">아직 등록된 종목이 없어요.</li>`;
    return;
  }
  const a = (active || "").toUpperCase();
  ul.innerHTML = REGISTERED.map((t) =>
    `<li><button type="button" class="reg-item${t === a ? " active" : ""}" data-t="${esc(t)}">${esc(t)}</button></li>`
  ).join("");
}

async function loadRegistered() {
  try {
    const url = STATIC ? "../data/guidance_tickers.json" : "/api/guidance/tickers";
    const res = await fetch(url, { cache: "no-store" });
    if (res.ok) {
      const data = await res.json();
      REGISTERED = data.tickers || [];
    }
  } catch (_) { /* panel is optional */ }
  renderRegistered(location.hash.slice(1));
}

// ---------- events ----------
$("#load-btn").addEventListener("click", () => loadDrift($("#ticker-input").value));
$("#ticker-input").addEventListener("keydown", (e) => {
  if (e.key === "Enter") loadDrift($("#ticker-input").value);
});
$("#registered-list").addEventListener("click", (e) => {
  const btn = e.target.closest(".reg-item");
  if (!btn) return;
  $("#ticker-input").value = btn.dataset.t;
  loadDrift(btn.dataset.t);
});

(async function init() {
  await Promise.all([loadIndex(), loadRegistered()]);
  const initial = location.hash.slice(1) || $("#ticker-input").value || (STATIC ? "" : "MU");
  if (initial) {
    $("#ticker-input").value = initial;
    loadDrift(initial);
  }
})();
