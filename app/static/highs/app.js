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
// Abbreviated magnitude (1.29T / 750.71B / 877.99M) for 시총 · 거래대금.
function fmtAbbr(v) {
  if (v == null) return null;
  if (v >= 1e12) return (v / 1e12).toFixed(2) + "T";
  if (v >= 1e9) return (v / 1e9).toFixed(2) + "B";
  if (v >= 1e6) return (v / 1e6).toFixed(2) + "M";
  if (v >= 1e3) return (v / 1e3).toFixed(1) + "K";
  return v.toFixed(0);
}
function fmtMoney(v) { const a = fmtAbbr(v); return a == null ? "-" : "$" + a; }
function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

// Flatten a sector's stocks (sub-industries + loose) sorted by market cap.
function sectorStocks(sec) {
  let arr = [];
  (sec.industries || []).forEach((ind) => { arr = arr.concat(ind.stocks || []); });
  arr = arr.concat(sec.stocks || []);
  arr.sort((a, b) => (b.market_cap || 0) - (a.market_cap || 0));
  return arr;
}
function allStocks(data) {
  let arr = [];
  (data.sectors || []).forEach((sec) => { arr = arr.concat(sectorStocks(sec)); });
  return arr;
}
function avgChange(stocks) {
  const v = stocks.map((s) => s.change_pct).filter((x) => x != null);
  return v.length ? v.reduce((a, b) => a + b, 0) / v.length : null;
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
  const tip = on ? `즐겨찾기 해제 (추가일 ${since})` : "즐겨찾기 추가";
  return `<button class="star${on ? " on" : ""}" title="${esc(tip)}"
      onclick="toggleFav('${esc(ticker)}')">${on ? "★" : "☆"}</button>`;
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

// ---------- list rendering (sector cards) ----------
let lastDashboard = null;
let historyData = { days: [] };
const SECTOR_COLORS = ["#3b82f6", "#22c55e", "#f59e0b", "#a855f7", "#ef4444",
  "#14b8a6", "#ec4899", "#eab308", "#64748b", "#06b6d4"];

function stockRow(s, extra) {
  const up = (s.change_pct ?? 0) >= 0;
  const chgCls = up ? "chg-up" : "chg-down";
  const ath = s.ath ? `<span class="ath" title="사상 최고가">ATH</span>` : "";
  const cls = extra ? " extra" : "";
  return `<tr class="hl-row${cls}" data-ticker="${esc(s.ticker)}">
      <td class="c-name">
        <span class="star-cell" data-star="${esc(s.ticker)}">${starCellInner(s.ticker)}</span>
        <button class="ticker-link" onclick="openChart('${esc(s.ticker)}','${esc(s.company || "")}')">${esc(s.ticker)}</button>
        ${ath}
        <span class="company" title="${esc(s.company || "")}">${esc(s.company || "")}</span>
        <button class="exp" title="사업개요 · 상승 이유" onclick="toggleDetail(this,'${esc(s.ticker)}')">▸</button>
      </td>
      <td class="num">${fmtPrice(s.price)}</td>
      <td class="num ${chgCls}">${fmtPct(s.change_pct)}</td>
      <td class="num">${fmtMoney(s.market_cap)}</td>
      <td class="num">${fmtMoney(s.turnover)}</td>
    </tr>
    <tr class="detail${cls}" data-detail="${esc(s.ticker)}" hidden>
      <td colspan="5">
        <div class="desc" data-desc="${esc(s.ticker)}"><span class="pending">사업 개요 불러오는 중…</span></div>
        <div class="reason" data-reason="${esc(s.ticker)}"><span class="pending">상승 이유 불러오는 중…</span></div>
      </td>
    </tr>`;
}

function sectorCard(sec, stocks) {
  const avg = avgChange(stocks);
  const avgCls = (avg ?? 0) >= 0 ? "chg-up" : "chg-down";
  const top = stocks.slice(0, 5), rest = stocks.slice(5);
  const body = top.map((s) => stockRow(s, false)).join("") +
    rest.map((s) => stockRow(s, true)).join("");
  const more = rest.length
    ? `<button class="more" onclick="toggleMore(this)">+${rest.length}개 더보기 ▾</button>` : "";
  return `<section class="scard" data-sector="${esc(sec.sector)}">
    <div class="scard-head">
      <span class="scard-name">${esc(sec.sector)}</span>
      <span class="scard-count">${stocks.length}종목</span>
      <span class="scard-avg ${avgCls}">평균 ${fmtPct(avg)}</span>
      <button class="scard-finviz" title="이 섹터 종목 차트를 Finviz에서 모아보기" onclick="sectorFinviz(this)">📊</button>
    </div>
    <table class="shl">
      <colgroup><col class="c-nm"><col class="c-pr"><col class="c-ch"><col class="c-mc"><col class="c-to"></colgroup>
      <thead><tr>
        <th>종목</th><th class="num">현재가</th><th class="num">등락률</th>
        <th class="num">시가총액</th><th class="num">거래대금</th>
      </tr></thead>
      <tbody>${body}</tbody>
    </table>
    ${more}
  </section>`;
}

function render(data) {
  lastDashboard = data;
  if (!data.sectors || !data.sectors.length) {
    $("#content").innerHTML = `<section id="trend" class="trend"></section>
      <div class="loading">오늘 52주 신고가 종목이 없습니다.</div>`;
    refreshTrends();
    return;
  }
  // Sector cards ordered by breadth (today's new-high count), tie-break by size.
  const cards = data.sectors
    .map((sec) => ({ sec, stocks: sectorStocks(sec) }))
    .sort((a, b) => b.stocks.length - a.stocks.length ||
      (b.sec.market_cap || 0) - (a.sec.market_cap || 0));
  const grid = cards.map((c) => sectorCard(c.sec, c.stocks)).join("");
  $("#content").innerHTML = `<section id="trend" class="trend"></section>
    <div id="sector-grid">${grid}</div>`;
  loadReasons(data.sectors);
  refreshTrends();
}

// row/card interactions
function toggleDetail(btn, ticker) {
  const card = btn.closest(".scard");
  const d = card && card.querySelector(`tr.detail[data-detail="${CSS.escape(ticker)}"]`);
  if (!d) return;
  const show = d.hidden;
  d.hidden = !show;
  btn.classList.toggle("open", show);
}
function toggleMore(btn) {
  const card = btn.closest(".scard");
  const on = card.classList.toggle("expanded");
  const n = card.querySelectorAll("tr.hl-row.extra").length;
  btn.innerHTML = on ? "접기 ▴" : `+${n}개 더보기 ▾`;
}
window.toggleDetail = toggleDetail;
window.toggleMore = toggleMore;

// ---------- 신고가 추이 (trends) ----------
async function refreshTrends() {
  try {
    const r = await fetchData("highs_history.json");
    if (r.ok) { const j = await r.json(); if (j && j.days) historyData = j; }
  } catch (_) { /* no history yet — the panels show an accumulation note */ }
  const el = document.getElementById("trend");
  if (el) renderTrends(el);
}

function renderTrends(el) {
  const data = lastDashboard || { sectors: [] };
  const stocks = allStocks(data);
  const today = {
    count: data.count ?? stocks.length,
    ath: stocks.filter((s) => s.ath).length,
    avg: avgChange(stocks),
    sectors: (data.sectors || []).length,
  };
  const days = historyData.days || [];
  let delta = null;
  if (days.length >= 2) delta = today.count - (days[days.length - 2].count || 0);
  const dtxt = delta == null ? "" :
    `<span class="tdelta ${delta >= 0 ? "up" : "down"}">전일 ${delta >= 0 ? "+" : ""}${delta}</span>`;
  const n = days.length;
  const tiles = `<div class="tiles">
    <div class="tile"><div class="tval">${today.count}</div><div class="tlbl">오늘 신고가 ${dtxt}</div></div>
    <div class="tile"><div class="tval">${today.ath}</div><div class="tlbl">사상 최고가 (ATH)</div></div>
    <div class="tile"><div class="tval ${(today.avg ?? 0) >= 0 ? "chg-up" : "chg-down"}">${fmtPct(today.avg)}</div><div class="tlbl">평균 등락률</div></div>
    <div class="tile"><div class="tval">${today.sectors}</div><div class="tlbl">섹터 수</div></div>
  </div>`;
  const panels = `<div class="trend-grid">
    <div class="panel">
      <div class="panel-h">최근 60거래일 신고가 추이 <span class="muted">· 누적 ${n}일</span></div>
      <div id="trend-count" class="plot"></div>
      ${n < 8 ? `<div class="trend-note">추이 데이터는 영업일마다 자동 누적됩니다 (현재 ${n}일). 며칠간 쌓이면 흐름이 뚜렷해집니다.</div>` : ""}
    </div>
    <div class="panel">
      <div class="panel-h">섹터별 신고가 <span class="muted">· 오늘 · 최근 ${Math.min(Math.max(n, 1), 14)}일 추이</span></div>
      <div id="trend-sectors" class="sector-trend"></div>
    </div>
  </div>`;
  el.innerHTML = tiles + panels;
  plotTrendCount(days);
  renderSectorTrend(days, data);
}

function plotTrendCount(days) {
  const host = document.getElementById("trend-count");
  if (!host || !window.Plotly) return;
  if (!days.length) { host.innerHTML = `<div class="trend-empty">아직 추이 데이터가 없습니다.</div>`; return; }
  const last = days.slice(-60);
  const x = last.map((d) => d.date);
  const ath = last.map((d) => d.ath || 0);
  const other = last.map((d) => Math.max((d.count || 0) - (d.ath || 0), 0));
  const traces = [
    { x, y: other, name: "신고가", type: "bar", marker: { color: "#3b82f6" } },
    { x, y: ath, name: "ATH", type: "bar", marker: { color: "#f59e0b" } },
  ];
  const layout = {
    barmode: "stack", paper_bgcolor: "#0f172a", plot_bgcolor: "#0f172a",
    font: { color: "#cbd5e1", size: 10 }, showlegend: true,
    legend: { orientation: "h", y: 1.18, x: 0, font: { size: 10 } },
    margin: { l: 34, r: 8, t: 14, b: 40 },
    xaxis: { type: "category", gridcolor: "#1e293b", nticks: 8, tickangle: -45 },
    yaxis: { gridcolor: "#1e293b", rangemode: "tozero", title: { text: "종목수", font: { size: 10 } } },
  };
  Plotly.newPlot("trend-count", traces, layout,
    { displayModeBar: false, responsive: true });
}

function sparkline(vals, color) {
  const w = 60, h = 18, n = vals.length || 1;
  const max = Math.max(1, ...vals), bw = w / n;
  const bars = vals.map((v, i) => {
    const bh = Math.max(1, Math.round((v / max) * (h - 2)));
    return `<rect x="${(i * bw).toFixed(1)}" y="${h - bh}" width="${Math.max(1, bw - 1).toFixed(1)}" height="${bh}" fill="${color}" opacity="0.85"/>`;
  }).join("");
  return `<svg width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none">${bars}</svg>`;
}

function renderSectorTrend(days, data) {
  const host = document.getElementById("trend-sectors");
  if (!host) return;
  const cur = {};
  (data.sectors || []).forEach((sec) => {
    const ss = sectorStocks(sec);
    cur[sec.sector] = { count: ss.length, avg: avgChange(ss) };
  });
  const names = Object.keys(cur).sort((a, b) => cur[b].count - cur[a].count).slice(0, 10);
  if (!names.length) { host.innerHTML = `<div class="trend-empty">데이터 없음</div>`; return; }
  const last = days.slice(-14);
  const maxCount = Math.max(1, ...names.map((nm) => cur[nm].count));
  host.innerHTML = names.map((nm, i) => {
    const series = last.map((d) => (d.sectors && d.sectors[nm]) || 0);
    const color = SECTOR_COLORS[i % SECTOR_COLORS.length];
    const c = cur[nm];
    const w = Math.round((c.count / maxCount) * 100);
    const avgCls = (c.avg ?? 0) >= 0 ? "chg-up" : "chg-down";
    return `<div class="st-row">
      <span class="st-dot" style="background:${color}"></span>
      <span class="st-name" title="${esc(nm)}">${esc(nm)}</span>
      <span class="st-bar"><span style="width:${w}%;background:${color}"></span></span>
      <span class="st-count">${c.count}</span>
      <span class="st-spark">${sparkline(series, color)}</span>
      <span class="st-avg ${avgCls}">${fmtPct(c.avg)}</span>
    </div>`;
  }).join("");
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
// Open a set of tickers in Finviz's Charts view (v=210) — many charts, one page.
function openFinvizList(tickers) {
  const uniq = [...new Set(tickers.filter(Boolean))];
  if (!uniq.length) { alert("표시할 종목이 없습니다."); return; }
  const url = "https://finviz.com/screener.ashx?v=210&t=" + uniq.map(encodeURIComponent).join(",");
  window.open(url, "_blank", "noopener");
}

// Global button: every ticker currently VISIBLE in the grid (top-of-card by
// default, plus any sector you expanded with 더보기).
function openFinvizCharts() {
  const tickers = [];
  document.querySelectorAll("#sector-grid tr.hl-row[data-ticker]").forEach((tr) => {
    if (tr.offsetParent !== null) tickers.push(tr.getAttribute("data-ticker"));
  });
  if (!tickers.length) { alert("표시된 종목이 없습니다."); return; }
  openFinvizList(tickers);
}

// Per-card button: that sector's tickers (including ones under 더보기).
function sectorFinviz(btn) {
  const card = btn.closest(".scard");
  if (!card) return;
  const tickers = [...card.querySelectorAll("tr.hl-row[data-ticker]")]
    .map((tr) => tr.getAttribute("data-ticker"));
  openFinvizList(tickers);
}
window.sectorFinviz = sectorFinviz;
$("#finviz-charts-btn").addEventListener("click", openFinvizCharts);
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
