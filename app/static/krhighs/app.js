"use strict";

const $ = (sel) => document.querySelector(sel);
const STATIC = !!window.SUH_DH_STATIC;
const BUILT = window.SUH_DH_BUILT || null;
const API_BASE = (window.SUH_DH_API_BASE || "").replace(/\/+$/, "");

function bust(url) { return url + (url.includes("?") ? "&" : "?") + "_=" + Date.now(); }

// ---------- formatting (KRW) ----------
function fmtCap(v) {                 // market cap in won -> 조 / 억
  if (v == null) return "-";
  if (v >= 1e12) return (v / 1e12).toFixed(2) + "조";
  if (v >= 1e8) return Math.round(v / 1e8).toLocaleString() + "억";
  return Math.round(v).toLocaleString();
}
function fmtPct(v) { return v == null ? "-" : (v > 0 ? "+" : "") + v.toFixed(2) + "%"; }
function fmtWon(v) { return v == null ? "-" : "₩" + Math.round(v).toLocaleString(); }
function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

// ---------- load ----------
async function loadDashboard() {
  $("#status").textContent = "불러오는 중…";
  try {
    const res = STATIC ? await SUHData.fetch("krhighs.json", true)
                       : await fetch("/api/krhighs", { cache: "no-store" });
    const data = await res.json();
    if (!res.ok || data.error) {
      renderError(data.error || "데이터를 불러오지 못했습니다.", data.detail);
      return;
    }
    render(data);
    $("#demo-badge").classList.toggle("hidden", !data.demo);
    const when = STATIC ? (BUILT ? new Date(BUILT).toLocaleString("ko-KR") : "최근")
                        : new Date().toLocaleTimeString("ko-KR");
    $("#status").textContent = `${data.count}개 종목 · ${STATIC ? "마지막 갱신 " + when + " · 매일 자동" : "업데이트 " + when}`;
  } catch (e) {
    renderError("데이터를 불러오지 못했습니다", e.message);
  }
}

function renderError(msg, detail) {
  $("#content").innerHTML =
    `<div class="error"><b>${esc(msg)}</b>${detail ? "<br><small>" + esc(detail) + "</small>" : ""}</div>`;
  $("#status").textContent = "오류";
}

// ---------- table ----------
function stockRow(s) {
  const cls = (s.change_pct ?? 0) >= 0 ? "chg-up" : "chg-down";
  const yh = s.yahoo || s.ticker;
  return `<tr data-ticker="${esc(s.ticker)}">
    <td>
      <button class="ticker-link" onclick="openChart('${esc(s.ticker)}','${esc(s.company || "")}','${esc(s.market || "")}')">${esc(s.company || s.ticker)}</button>
      <div class="company">${esc(s.ticker)} · ${esc(s.market || "")}</div>
    </td>
    <td class="num ${cls}">${fmtPct(s.change_pct)}</td>
    <td class="num">${fmtWon(s.price)}</td>
    <td class="num">${fmtCap(s.market_cap)}</td>
  </tr>`;
}

function stockTable(stocks) {
  return `<table>
    <colgroup><col class="c-ticker"><col class="c-chg"><col class="c-price"><col class="c-cap"></colgroup>
    <thead><tr>
      <th>종목</th><th class="num">전일대비</th><th class="num">현재가</th><th class="num">시총</th>
    </tr></thead>
    <tbody>${stocks.map(stockRow).join("")}</tbody>
  </table>`;
}

function render(data) {
  if (!data.sectors || !data.sectors.length) {
    $("#content").innerHTML = `<div class="loading">오늘 국장 52주 신고가 종목이 없습니다.</div>`;
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
}

// ---------- chart ----------
let currentTicker = null, chartData = null, suppressRelayout = false, chartMarket = null;

async function fetchChart(code) {          // code = 6자리 종목코드
  const mkt = chartMarket ? `market=${encodeURIComponent(chartMarket)}&` : "";
  const cb = "_=" + Date.now();            // cache-bust: never serve a stale chart
  if (STATIC) {
    const res = await fetch(`../data/chart/${encodeURIComponent(code)}.json?${cb}`, { cache: "no-store" });
    if (res.ok) return res.json();
    if (API_BASE) {                    // not pre-built → same-day FDR chart from backend
      const r = await fetch(`${API_BASE}/api/krchart/${encodeURIComponent(code)}?${mkt}${cb}`);
      const d = await r.json();
      if (r.ok && !d.error) return d;
    }
    throw new Error("저장된 차트가 없습니다");
  }
  const res = await fetch(`/api/krchart/${encodeURIComponent(code)}?${mkt}${cb}`);
  const d = await res.json();
  if (!res.ok || d.error) throw new Error(d.detail || d.error || "chart error");
  return d;
}

function openChart(code, company, market) {   // code = 6자리 종목코드
  currentTicker = code;
  chartMarket = market || null;
  $("#chart-ticker").textContent = code;
  $("#chart-company").textContent = company || "";
  $("#chart-external").href = `https://finance.naver.com/item/main.naver?code=${encodeURIComponent(code || "")}`;
  $("#chart-pane").classList.remove("hidden");
  $("#divider").classList.remove("hidden");
  $("#list-pane").classList.add("chart-open");
  document.querySelectorAll("tr.active").forEach((r) => r.classList.remove("active"));
  document.querySelectorAll(`tr[data-ticker="${CSS.escape(code)}"]`).forEach((r) => r.classList.add("active"));
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
      area.innerHTML = `<div class="error">차트 데이터가 없습니다.</div>`;
      return;
    }
    chartData = d;
    area.innerHTML = "";
    plotChart(d);
  } catch (e) {
    area.innerHTML = `<div class="error">차트를 불러오지 못했습니다.<br><small>${esc(e.message)}</small></div>`;
  }
}

function maTrace(x, y, name, color) {
  return { x, y, name, type: "scatter", mode: "lines",
    line: { color, width: 1.3 }, connectgaps: false, xaxis: "x", yaxis: "y" };
}

function plotChart(d) {
  const x = d.dates;
  const candles = { x, type: "candlestick", name: "가격",
    open: d.open, high: d.high, low: d.low, close: d.close,
    increasing: { line: { color: "#22c55e" } }, decreasing: { line: { color: "#ef4444" } },
    xaxis: "x", yaxis: "y" };
  const volColors = d.close.map((c, i) => i > 0 && c < d.close[i - 1] ? "rgba(239,68,68,.5)" : "rgba(34,197,94,.5)");
  const volume = { x, y: d.volume, type: "bar", name: "거래량", marker: { color: volColors }, xaxis: "x", yaxis: "y2" };
  const traces = [volume, candles,
    maTrace(x, d.ma5, "MA5", "#f59e0b"), maTrace(x, d.ma20, "MA20", "#3b82f6"),
    maTrace(x, d.ma50, "MA50", "#a855f7"), maTrace(x, d.ma120, "MA120", "#ef4444")];
  const layout = {
    paper_bgcolor: "#1e293b", plot_bgcolor: "#1e293b", font: { color: "#e2e8f0", size: 11 },
    showlegend: false, margin: { l: 62, r: 18, t: 8, b: 28 }, dragmode: "pan",
    xaxis: { type: "category", gridcolor: "#334155", domain: [0, 1], anchor: "y", nticks: 8, rangeslider: { visible: false } },
    yaxis: { domain: [0.24, 1], gridcolor: "#334155", title: "가격", side: "right" },
    yaxis2: { domain: [0, 0.18], gridcolor: "#334155", title: "거래량", side: "right" },
  };
  Plotly.newPlot("chart-area", traces, layout,
    { responsive: true, scrollZoom: true, displaylogo: false, modeBarButtonsToRemove: ["select2d", "lasso2d"] });
  document.getElementById("chart-area").on("plotly_relayout", (ev) => rescaleY(ev));
  const n = d.dates.length, win = Math.min(126, n), start = n - win;
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
  Plotly.relayout("chart-area", { "yaxis.range": [pmin - pad, pmax + pad], "yaxis2.range": [0, vmax * 1.15] })
    .then(() => { suppressRelayout = false; });
}

function rescaleY(ev) {
  if (suppressRelayout || !chartData) return;
  const n = chartData.dates.length;
  let lo, hi;
  if (ev["xaxis.autorange"] || ev["autosize"]) { lo = 0; hi = n - 1; }
  else if (ev["xaxis.range[0]"] !== undefined) { lo = Math.floor(ev["xaxis.range[0]"]); hi = Math.ceil(ev["xaxis.range[1]"]); }
  else if (Array.isArray(ev["xaxis.range"])) { lo = Math.floor(ev["xaxis.range"][0]); hi = Math.ceil(ev["xaxis.range"][1]); }
  else return;
  setYForWindow(lo, hi);
}

(function setupDivider() {
  const divider = $("#divider"), pane = $("#chart-pane");
  let dragging = false;
  divider.addEventListener("mousedown", (e) => { dragging = true; divider.classList.add("dragging"); document.body.style.userSelect = "none"; e.preventDefault(); });
  window.addEventListener("mousemove", (e) => { if (!dragging) return; pane.style.width = Math.min(Math.max(window.innerWidth - e.clientX, 300), window.innerWidth - 200) + "px"; });
  window.addEventListener("mouseup", () => { if (!dragging) return; dragging = false; divider.classList.remove("dragging"); document.body.style.userSelect = ""; if (chartData) Plotly.Plots.resize("chart-area"); });
})();

$("#refresh-btn").addEventListener("click", loadDashboard);
$("#chart-close").addEventListener("click", closeChart);
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeChart(); });
window.addEventListener("resize", () => { if (chartData) Plotly.Plots.resize("chart-area"); });
window.openChart = openChart;
loadDashboard();
