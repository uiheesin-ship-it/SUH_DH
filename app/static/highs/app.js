"use strict";

const $ = (sel) => document.querySelector(sel);

// Two run modes (see config.js):
//   STATIC=false -> live FastAPI backend (/api/*), used when running locally
//   STATIC=true  -> pre-built daily JSON in ../data/*, used on GitHub Pages
const STATIC = !!window.SUH_DH_STATIC;
const BUILT = window.SUH_DH_BUILT || null;

// A hosted backend (Render) lets the refresh button pull *real-time* new highs
// on the static Pages site (the daily JSON only updates when the build runs).
// apiUrl() returns a usable live endpoint, or null when there's no backend.
const API_BASE = (window.SUH_DH_API_BASE || "").replace(/\/+$/, "");
function apiUrl(path) {
  if (!STATIC) return path;                    // local dev: same-origin FastAPI
  return API_BASE ? API_BASE + path : null;    // Pages: hosted backend, else none
}
let usingLive = false;   // true once a live fetch succeeded (drives reasons/charts)
let latestBuilt = BUILT;  // newest build seen; bumped by the static poller below

// GitHub Pages (and its CDN) can keep serving a stale snapshot for a few
// minutes. A per-request cache-buster guarantees the refresh button and the
// auto-poller see the freshest committed build, not a cached copy.
function bust(url) {
  return url + (url.includes("?") ? "&" : "?") + "_=" + Date.now();
}

// Static mode: the new-high list/meta are committed to the repo very frequently
// by the highs.yml workflow. Read them from raw.githubusercontent (fresh,
// independent of Pages redeploys); fall back to the deployed snapshot if raw is
// unreachable (CORS/offline), so there's never a regression.
const RAW_BASE =
  "https://raw.githubusercontent.com/uiheesin-ship-it/SUH_DH/refs/heads/claude/funny-carson-ent3s7/data";
async function fetchData(file) {
  if (STATIC) {
    try {
      const r = await fetch(bust(`${RAW_BASE}/${file}`), { cache: "no-store" });
      if (r.ok) return r;
    } catch (_) { /* fall through to the deployed copy */ }
  }
  return fetch(bust(`../data/${file}`), { cache: "no-store" });
}

// A sleeping free-tier backend can take a long time to answer (or never).
// Abort after `ms` so the refresh button fails fast to the saved snapshot
// instead of hanging forever on "불러오는 중…".
async function fetchWithTimeout(url, ms, opts = {}) {
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), ms);
  try {
    return await fetch(url, { ...opts, signal: ctrl.signal });
  } finally {
    clearTimeout(t);
  }
}

function whenText() {
  return latestBuilt ? new Date(latestBuilt).toLocaleString("ko-KR") : "최근";
}

// ---------- formatting ----------
function fmtCap(v) {
  if (v == null) return "-";
  if (v >= 1e12) return (v / 1e12).toFixed(2) + "T";
  if (v >= 1e9) return (v / 1e9).toFixed(2) + "B";
  if (v >= 1e6) return (v / 1e6).toFixed(1) + "M";
  return v.toLocaleString();
}
function fmtPct(v) {
  if (v == null) return "-";
  return (v > 0 ? "+" : "") + v.toFixed(2) + "%";
}
function fmtPrice(v) { return v == null ? "-" : "$" + v.toFixed(2); }
function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

// ---------- favorites (★) ----------
// Per-browser bookmarks kept in localStorage: { TICKER: "YYYY-MM-DD" } where the
// date is when the star was (re)turned on. A starred ticker keeps its star and
// that date whenever it reappears in the list; un-starring then re-starring
// stamps the new date. (Stored locally, so it's per device/browser.)
const FAV_KEY = "suh_dh_fav_highs";
function loadFavs() {
  try { return JSON.parse(localStorage.getItem(FAV_KEY) || "{}") || {}; }
  catch (_) { return {}; }
}
function saveFavs(f) {
  try { localStorage.setItem(FAV_KEY, JSON.stringify(f)); } catch (_) {}
}
function todayStr() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}
function starCellInner(ticker) {
  const since = loadFavs()[ticker];
  const on = !!since;
  return `<button class="star${on ? " on" : ""}" title="${on ? "즐겨찾기 해제" : "즐겨찾기"}"
      onclick="toggleFav('${esc(ticker)}')">${on ? "★" : "☆"}</button>` +
    (on ? `<div class="star-date">${esc(since)}</div>` : "");
}
function toggleFav(ticker) {
  const favs = loadFavs();
  if (favs[ticker]) delete favs[ticker];
  else favs[ticker] = todayStr();          // stamp (re)star date
  saveFavs(favs);
  document.querySelectorAll(`[data-star="${CSS.escape(ticker)}"]`).forEach((cell) => {
    cell.innerHTML = starCellInner(ticker);
  });
}
window.toggleFav = toggleFav;

// ---------- dashboard ----------
async function loadDashboard(live = false) {
  // `live=true` (refresh button) pulls fresh data from the backend right now;
  // otherwise we show the pre-built snapshot (instant, no cold-start wait).
  const liveUrl = apiUrl("/api/highs");
  const wantLive = !!live && !!liveUrl;
  $("#status").textContent = wantLive
    ? "실시간 불러오는 중… (백엔드가 자고 있으면 최대 60초)"
    : "불러오는 중…";
  try {
    let res;
    if (wantLive) {
      // Allow for a free-tier cold start, but bail cleanly if it never wakes.
      res = await fetchWithTimeout(liveUrl, 60000, { cache: "no-store" });
    } else if (STATIC) {
      res = await fetchData("highs.json");
    } else {
      res = await fetch("/api/highs", { cache: "no-store" });
    }
    const data = await res.json();
    if (!res.ok || data.error) {
      if (wantLive) return loadStaticFallback(data.error, data.detail);
      renderError(data.error || "데이터를 불러오지 못했습니다.", data.detail);
      return;
    }
    usingLive = wantLive;
    render(data);
    $("#demo-badge").classList.toggle("hidden", !data.demo);
    if (usingLive) {
      $("#status").textContent =
        `${data.count}개 종목 · 실시간 ${new Date().toLocaleTimeString("ko-KR")}`;
    } else if (STATIC) {
      const hint = liveUrl ? " · [새로고침]으로 실시간" : " · 새 빌드 자동 반영";
      $("#status").textContent = `${data.count}개 종목 · 마지막 갱신 ${whenText()}${hint}`;
    } else {
      $("#status").textContent =
        `${data.count}개 종목 · 업데이트 ${new Date().toLocaleTimeString("ko-KR")}`;
    }
  } catch (e) {
    if (wantLive) return loadStaticFallback("실시간 백엔드에 연결하지 못했습니다", e.message);
    renderError("데이터를 불러오지 못했습니다", e.message);
  }
}

// Live fetch failed or no backend is connected — quietly show the freshest
// saved snapshot instead of an alarming error. The snapshot is re-pulled
// (cache-busted) so the button still does something useful: it lands on the
// latest committed build. We say "저장본" so it's honest, without shouting "실패".
async function loadStaticFallback(msg, detail) {
  usingLive = false;
  try {
    const res = await fetchData("highs.json");
    const data = await res.json();
    render(data);
    $("#demo-badge").classList.toggle("hidden", !data.demo);
    $("#status").textContent = `${data.count}개 종목 · 마지막 갱신 ${whenText()} · 저장본`;
  } catch (e) {
    renderError(msg || "데이터를 불러오지 못했습니다", detail || e.message);
  }
}

function renderError(msg, detail) {
  $("#content").innerHTML =
    `<div class="error"><b>${esc(msg)}</b>${detail ? "<br><small>" + esc(detail) + "</small>" : ""}</div>`;
  $("#status").textContent = "오류";
}

function stockRow(s) {
  const cls = (s.change_pct ?? 0) >= 0 ? "chg-up" : "chg-down";
  return `<tr data-ticker="${esc(s.ticker)}">
    <td class="star-cell" data-star="${esc(s.ticker)}">${starCellInner(s.ticker)}</td>
    <td>
      <button class="ticker-link" onclick="openChart('${esc(s.ticker)}','${esc(s.company || "")}')">${esc(s.ticker)}</button>
      <div class="company">${esc(s.company || "")}</div>
    </td>
    <td class="num ${cls}">${fmtPct(s.change_pct)}</td>
    <td class="num">${fmtPrice(s.price)}</td>
    <td class="num">${fmtCap(s.market_cap)}</td>
    <td class="desc" data-desc="${esc(s.ticker)}"><span class="pending">설명 불러오는 중…</span></td>
    <td class="reason" data-reason="${esc(s.ticker)}"><span class="pending">상승 이유 불러오는 중…</span></td>
  </tr>`;
}

function stockTable(stocks) {
  return `<table>
    <colgroup>
      <col class="c-star"><col class="c-ticker"><col class="c-chg"><col class="c-price">
      <col class="c-cap"><col class="c-desc"><col class="c-reason">
    </colgroup>
    <thead><tr>
      <th class="star-th" title="즐겨찾기">★</th>
      <th>티커</th><th class="num">전일대비</th><th class="num">가격</th>
      <th class="num">시총</th><th>사업 개요</th><th>상승 이유 (뉴스 · 실적)</th>
    </tr></thead>
    <tbody>${stocks.map(stockRow).join("")}</tbody>
  </table>`;
}

function render(data) {
  if (!data.sectors || !data.sectors.length) {
    $("#content").innerHTML = `<div class="loading">오늘 52주 신고가 종목이 없습니다.</div>`;
    return;
  }
  const html = data.sectors.map((sec, i) => {
    const inner =
      sec.industries.map((ind) => `
        <div class="industry">
          <div class="industry-name">${esc(ind.industry)} · ${ind.count}</div>
          ${stockTable(ind.stocks)}
        </div>`).join("") +
      (sec.stocks.length ? `<div class="industry">${stockTable(sec.stocks)}</div>` : "");
    return `<section class="sector ${i > 2 ? "collapsed" : ""}">
      <div class="sector-head" onclick="this.parentNode.classList.toggle('collapsed')">
        <span class="caret">▼</span>
        <span class="sector-name">${esc(sec.sector)}</span>
        <span class="sector-meta">${sec.count}종목 · 시총합 ${fmtCap(sec.market_cap)}</span>
      </div>
      <div class="sector-body">${inner}</div>
    </section>`;
  }).join("");
  $("#content").innerHTML = html;
  loadReasons(data.sectors);
}

// ---------- reasons + descriptions (static: embedded, live: lazy) ----------
let reasonQueue = [];
const REASON_CONCURRENCY = 3;
const reasonSeen = new Set();

function loadReasons(sectors) {
  reasonQueue = [];
  reasonSeen.clear();
  const handle = (s) => {
    if (s.reason) {
      fillReason(s.ticker, s.reason);
    } else if (!reasonSeen.has(s.ticker)) {
      reasonSeen.add(s.ticker);
      reasonQueue.push(s.ticker);
    }
  };
  sectors.forEach((sec) => {
    sec.industries.forEach((ind) => ind.stocks.forEach(handle));
    sec.stocks.forEach(handle);
  });
  for (let i = 0; i < REASON_CONCURRENCY; i++) pumpReasons();
}

async function pumpReasons() {
  if (!reasonQueue.length) return;
  const ticker = reasonQueue.shift();
  const rurl = apiUrl(`/api/reason/${encodeURIComponent(ticker)}`);
  if (!rurl) {                       // static snapshot with no backend to ask
    fillReason(ticker, { news: [] });
    return pumpReasons();
  }
  try {
    const res = await fetch(rurl);
    fillReason(ticker, await res.json());
  } catch (_) {
    fillReason(ticker, { news: [] });
  }
  pumpReasons();
}

function fillReason(ticker, data) {
  // description column
  document.querySelectorAll(`[data-desc="${CSS.escape(ticker)}"]`).forEach((cell) => {
    cell.innerHTML = data.description
      ? esc(data.description)
      : `<span class="src">설명 없음</span>`;
  });
  // reason column (Korean headline, link preserved)
  document.querySelectorAll(`[data-reason="${CSS.escape(ticker)}"]`).forEach((cell) => {
    let html = "";
    if (data.earnings_recent) {
      html += `<span class="badge earnings">실적발표 ${esc(data.earnings_date || "")}</span>`;
    }
    if (data.news && data.news.length) {
      const n = data.news[0];
      const title = n.title_ko || n.title;
      const link = n.link
        ? `<a href="${esc(n.link)}" target="_blank" rel="noopener">${esc(title)}</a>`
        : esc(title);
      html += `${link} <span class="src">— ${esc(n.publisher || "")} ${esc(n.published || "")}</span>`;
    } else if (!data.earnings_recent) {
      html += `<span class="src">관련 뉴스 없음 (섹터 강세로 추정)</span>`;
    }
    cell.innerHTML = html;
  });
}

// ---------- chart panel (slide-in, resizable) ----------
let currentTicker = null;
let chartData = null;
let suppressRelayout = false;

async function fetchChart(ticker) {
  const curl = apiUrl(`/api/chart/${encodeURIComponent(ticker)}?range=max`);
  // In live mode (or local), ask the backend so any ticker has a chart. In a
  // pure static snapshot, read the pre-built file; fall back to the backend
  // (if any) when a ticker wasn't pre-built.
  if (!STATIC || usingLive) {
    const res = await fetch(curl);
    const d = await res.json();
    if (!res.ok || d.error) throw new Error(d.detail || d.error || "chart error");
    return d;
  }
  const res = await fetch(`../data/chart/${encodeURIComponent(ticker)}.json`, { cache: "no-store" });
  if (res.ok) return res.json();
  if (curl) {
    const r2 = await fetch(curl);
    const d = await r2.json();
    if (r2.ok && !d.error) return d;
  }
  throw new Error("저장된 차트가 없습니다");
}

function openChart(ticker, company) {
  currentTicker = ticker;
  $("#chart-ticker").textContent = ticker;
  $("#chart-company").textContent = company || "";
  $("#chart-external").href = `https://finance.yahoo.com/quote/${encodeURIComponent(ticker)}`;

  $("#chart-pane").classList.remove("hidden");
  $("#divider").classList.remove("hidden");
  $("#list-pane").classList.add("chart-open");
  document.querySelectorAll("tr.active").forEach((r) => r.classList.remove("active"));
  document.querySelectorAll(`tr[data-ticker="${CSS.escape(ticker)}"]`).forEach((r) => r.classList.add("active"));

  drawChart();
}

function closeChart() {
  $("#chart-pane").classList.add("hidden");
  $("#divider").classList.add("hidden");
  $("#list-pane").classList.remove("chart-open");
  document.querySelectorAll("tr.active").forEach((r) => r.classList.remove("active"));
  Plotly.purge("chart-area");
  chartData = null;
}

async function drawChart() {
  const area = $("#chart-area");
  area.innerHTML = `<div class="loading">차트 로딩 중…</div>`;
  try {
    const d = await fetchChart(currentTicker);
    if (!d.dates || !d.dates.length) {
      area.innerHTML = `<div class="error">차트 데이터가 없습니다. 위의 Yahoo 링크로 확인해 주세요.</div>`;
      return;
    }
    chartData = d;
    area.innerHTML = "";
    plotChart(area, d);
  } catch (e) {
    area.innerHTML = `<div class="error">차트를 불러오지 못했습니다.<br><small>${esc(e.message)}</small><br>위의 Yahoo 링크로 확인해 주세요.</div>`;
  }
}

function maTrace(x, y, name, color) {
  return { x, y, name, type: "scatter", mode: "lines",
    line: { color, width: 1.3 }, connectgaps: false, xaxis: "x", yaxis: "y" };
}

function plotChart(area, d) {
  const x = d.dates;
  const candles = {
    x, type: "candlestick", name: "가격",
    open: d.open, high: d.high, low: d.low, close: d.close,
    increasing: { line: { color: "#22c55e" } },
    decreasing: { line: { color: "#ef4444" } },
    xaxis: "x", yaxis: "y",
  };
  const volColors = d.close.map((c, i) =>
    i > 0 && c < d.close[i - 1] ? "rgba(239,68,68,.5)" : "rgba(34,197,94,.5)");
  const volume = { x, y: d.volume, type: "bar", name: "거래량",
    marker: { color: volColors }, xaxis: "x", yaxis: "y2" };

  const traces = [
    volume, candles,
    maTrace(x, d.ma5, "MA5", "#f59e0b"),
    maTrace(x, d.ma20, "MA20", "#3b82f6"),
    maTrace(x, d.ma50, "MA50", "#a855f7"),
    maTrace(x, d.ma120, "MA120", "#ef4444"),
  ];
  const layout = {
    paper_bgcolor: "#1e293b", plot_bgcolor: "#1e293b",
    font: { color: "#e2e8f0", size: 11 },
    showlegend: false, margin: { l: 55, r: 18, t: 8, b: 28 },
    dragmode: "pan",  // click-drag pans left/right; mouse wheel zooms
    // category axis: only trading days, so no weekend/holiday gaps in candles
    xaxis: { type: "category", gridcolor: "#334155", domain: [0, 1], anchor: "y",
             nticks: 8, rangeslider: { visible: false } },
    yaxis: { domain: [0.24, 1], gridcolor: "#334155", title: "가격", side: "right" },
    yaxis2: { domain: [0, 0.18], gridcolor: "#334155", title: "거래량", side: "right" },
  };
  Plotly.newPlot("chart-area", traces, layout,
    { responsive: true, scrollZoom: true, displaylogo: false,
      modeBarButtonsToRemove: ["select2d", "lasso2d"] });
  // Rescale the price/volume axes to whatever slice of time is visible.
  document.getElementById("chart-area").on("plotly_relayout", (ev) => rescaleY(ev));

  // Open on the most recent ~6 months; panning left / zooming out reveals more.
  const n = d.dates.length;
  const win = Math.min(126, n);
  const start = n - win;
  suppressRelayout = true;
  Plotly.relayout("chart-area", { "xaxis.range": [start - 0.5, n - 0.5] })
    .then(() => { suppressRelayout = false; setYForWindow(start, n - 1); });
}

function setYForWindow(lo, hi) {
  if (!chartData) return;
  const n = chartData.dates.length;
  lo = Math.max(0, lo); hi = Math.min(n - 1, hi);
  if (hi <= lo) return;
  let pmin = Infinity, pmax = -Infinity, vmax = 0;
  for (let i = lo; i <= hi; i++) {
    if (chartData.low[i] < pmin) pmin = chartData.low[i];
    if (chartData.high[i] > pmax) pmax = chartData.high[i];
    if (chartData.volume[i] > vmax) vmax = chartData.volume[i];
  }
  if (!isFinite(pmin) || !isFinite(pmax)) return;
  const pad = (pmax - pmin) * 0.06 || 1;
  suppressRelayout = true;
  Plotly.relayout("chart-area", {
    "yaxis.range": [pmin - pad, pmax + pad],
    "yaxis2.range": [0, vmax * 1.15],
  }).then(() => { suppressRelayout = false; });
}

function rescaleY(ev) {
  if (suppressRelayout || !chartData) return;
  const n = chartData.dates.length;
  let lo, hi;
  if (ev["xaxis.autorange"] || ev["autosize"]) {
    lo = 0; hi = n - 1;
  } else if (ev["xaxis.range[0]"] !== undefined) {
    lo = Math.floor(ev["xaxis.range[0]"]);
    hi = Math.ceil(ev["xaxis.range[1]"]);
  } else if (Array.isArray(ev["xaxis.range"])) {
    lo = Math.floor(ev["xaxis.range"][0]);
    hi = Math.ceil(ev["xaxis.range"][1]);
  } else {
    return;
  }
  setYForWindow(lo, hi);
}

// ---------- divider drag (resize left/right) ----------
(function setupDivider() {
  const divider = $("#divider");
  const pane = $("#chart-pane");
  let dragging = false;
  divider.addEventListener("mousedown", (e) => {
    dragging = true; divider.classList.add("dragging");
    document.body.style.userSelect = "none"; e.preventDefault();
  });
  window.addEventListener("mousemove", (e) => {
    if (!dragging) return;
    const w = Math.min(Math.max(window.innerWidth - e.clientX, 300), window.innerWidth - 200);
    pane.style.width = w + "px";
  });
  window.addEventListener("mouseup", () => {
    if (!dragging) return;
    dragging = false; divider.classList.remove("dragging");
    document.body.style.userSelect = "";
    if (chartData) Plotly.Plots.resize("chart-area");
  });
})();

// ---------- events ----------
$("#refresh-btn").addEventListener("click", () => loadDashboard(true));
$("#chart-close").addEventListener("click", closeChart);
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeChart(); });
window.addEventListener("resize", () => { if (chartData) Plotly.Plots.resize("chart-area"); });

// ---------- auto refresh ----------
// Live mode: re-pull the backend each tick.
// Static mode: cheaply poll meta.json for a newer build and only re-render when
// the snapshot actually changed. The 52-week-high list only moves while the US
// market is open, so most polls are no-ops — no flicker, no scroll reset — but
// the moment a fresh build lands, the page picks it up on its own.
let timer = null;

async function checkForNewBuild() {
  try {
    const res = await fetchData("meta.json");
    if (!res.ok) return;
    const meta = await res.json();
    if (meta.built && meta.built !== latestBuilt) {
      latestBuilt = meta.built;
      await loadDashboard(false);   // pull + render the fresh snapshot
    }
  } catch (_) { /* offline / not built yet — try again next tick */ }
}

function autoTick() {
  return STATIC ? checkForNewBuild() : loadDashboard(false);
}

function scheduleAuto() {
  if (timer) clearInterval(timer);
  if (!$("#auto-toggle").checked) return;
  timer = setInterval(autoTick, parseInt($("#auto-interval").value, 10) * 1000);
}
$("#auto-toggle").addEventListener("change", scheduleAuto);
$("#auto-interval").addEventListener("change", scheduleAuto);

window.openChart = openChart;

// Seed the "last build" marker from meta.json (config.js's baked SUH_DH_BUILT is
// only the build this page shipped with), then load and start the poller.
(async () => {
  try {
    const res = await fetchData("meta.json");
    if (res.ok) { const m = await res.json(); if (m.built) latestBuilt = m.built; }
  } catch (_) { /* ignore — fall back to the baked build time */ }
  await loadDashboard();
  scheduleAuto();
})();
