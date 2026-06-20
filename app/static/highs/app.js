"use strict";

const $ = (sel) => document.querySelector(sel);

// Two run modes (see config.js):
//   STATIC=false -> live FastAPI backend (/api/*), used when running locally
//   STATIC=true  -> pre-built daily JSON in ../data/*, used on GitHub Pages
const STATIC = !!window.SUH_DH_STATIC;
const BUILT = window.SUH_DH_BUILT || null;

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
  const sign = v > 0 ? "+" : "";
  return sign + v.toFixed(2) + "%";
}
function fmtPrice(v) {
  return v == null ? "-" : "$" + v.toFixed(2);
}
function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

// ---------- dashboard ----------
async function loadDashboard() {
  $("#status").textContent = "불러오는 중…";
  try {
    const url = STATIC ? "../data/highs.json" : "/api/highs";
    const res = await fetch(url, { cache: "no-store" });
    const data = await res.json();
    if (!res.ok || data.error) {
      renderError(data.error || "데이터를 불러오지 못했습니다.", data.detail);
      return;
    }
    render(data);
    $("#demo-badge").classList.toggle("hidden", !data.demo);
    if (STATIC) {
      const when = BUILT ? new Date(BUILT).toLocaleString("ko-KR") : "최근";
      $("#status").textContent = `${data.count}개 종목 · 마지막 갱신 ${when} · 매일 자동 갱신`;
    } else {
      $("#status").textContent =
        `${data.count}개 종목 · 업데이트 ${new Date().toLocaleTimeString("ko-KR")}`;
    }
  } catch (e) {
    renderError("데이터를 불러오지 못했습니다", e.message);
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
    <td>
      <button class="ticker-link" onclick="openChart('${esc(s.ticker)}','${esc(s.company || "")}')">${esc(s.ticker)}</button>
      <div class="company">${esc(s.company || "")}</div>
    </td>
    <td class="num ${cls}">${fmtPct(s.change_pct)}</td>
    <td class="num">${fmtPrice(s.price)}</td>
    <td class="num">${fmtCap(s.market_cap)}</td>
    <td class="reason" data-reason="${esc(s.ticker)}"><span class="pending">상승 이유 불러오는 중…</span></td>
  </tr>`;
}

function stockTable(stocks) {
  return `<table>
    <thead><tr>
      <th>티커</th><th class="num">전일대비</th><th class="num">가격</th>
      <th class="num">시총</th><th>상승 이유 (뉴스 · 실적)</th>
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

// ---------- reasons ----------
// Static builds embed the reason in each stock; live mode fetches lazily.
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
  try {
    const res = await fetch(`/api/reason/${encodeURIComponent(ticker)}`);
    fillReason(ticker, await res.json());
  } catch (_) {
    fillReason(ticker, { news: [] });
  }
  pumpReasons();
}

function fillReason(ticker, data) {
  document.querySelectorAll(`[data-reason="${CSS.escape(ticker)}"]`).forEach((cell) => {
    let html = "";
    if (data.earnings_recent) {
      html += `<span class="badge earnings">실적발표 ${esc(data.earnings_date || "")}</span> `;
    }
    if (data.news && data.news.length) {
      const n = data.news[0];
      const link = n.link
        ? `<a href="${esc(n.link)}" target="_blank" rel="noopener">${esc(n.title)}</a>`
        : esc(n.title);
      html += `${link} <span class="src">— ${esc(n.publisher || "")} ${esc(n.published || "")}</span>`;
    } else if (!data.earnings_recent) {
      html += `<span class="src">관련 뉴스 없음 (섹터 강세로 추정)</span>`;
    }
    cell.innerHTML = html;
  });
}

// ---------- chart modal ----------
let currentTicker = null;
let currentRange = "max";

function sliceChart(d, n) {
  if (!d.dates || d.dates.length <= n) return d;
  const keys = ["dates", "open", "high", "low", "close", "volume", "ma5", "ma20", "ma50", "ma120"];
  const out = { ...d };
  keys.forEach((k) => { if (Array.isArray(d[k])) out[k] = d[k].slice(-n); });
  return out;
}

async function fetchChart(ticker, range) {
  if (STATIC) {
    const res = await fetch(`../data/chart/${encodeURIComponent(ticker)}.json`, { cache: "no-store" });
    if (!res.ok) throw new Error("no static chart");
    const full = await res.json();
    return range === "6mo" ? sliceChart(full, 126) : full;
  }
  const res = await fetch(`/api/chart/${encodeURIComponent(ticker)}?range=${range}`);
  const d = await res.json();
  if (!res.ok || d.error) throw new Error(d.detail || d.error || "chart error");
  return d;
}

function openChart(ticker, company) {
  currentTicker = ticker;
  currentRange = "max";
  $("#chart-ticker").textContent = ticker;
  $("#chart-company").textContent = company || "";
  $("#chart-external").href = `https://finance.yahoo.com/quote/${encodeURIComponent(ticker)}`;
  document.querySelectorAll(".range-toggle button").forEach((b) =>
    b.classList.toggle("active", b.dataset.range === "max"));
  $("#chart-modal").classList.remove("hidden");
  drawChart();
}

function closeChart() {
  $("#chart-modal").classList.add("hidden");
  Plotly.purge("chart-area");
}

async function drawChart() {
  const area = $("#chart-area");
  area.innerHTML = `<div class="loading">차트 로딩 중…</div>`;
  try {
    const d = await fetchChart(currentTicker, currentRange);
    if (!d.dates || !d.dates.length) {
      area.innerHTML = `<div class="error">차트 데이터가 없습니다. 위의 Yahoo 링크로 확인해 주세요.</div>`;
      return;
    }
    area.innerHTML = "";
    plotChart(area, d);
  } catch (e) {
    area.innerHTML = `<div class="error">차트를 불러오지 못했습니다.<br><small>${esc(e.message)}</small><br>위의 Yahoo 링크로 확인해 주세요.</div>`;
  }
}

function maTrace(x, y, name, color) {
  return {
    x, y, name, type: "scatter", mode: "lines",
    line: { color, width: 1.3 }, connectgaps: false, xaxis: "x", yaxis: "y",
  };
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
  const volume = {
    x, y: d.volume, type: "bar", name: "거래량",
    marker: { color: volColors }, xaxis: "x", yaxis: "y2",
  };
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
    showlegend: false, margin: { l: 55, r: 20, t: 10, b: 30 }, height: 520,
    dragmode: "pan",
    xaxis: { rangeslider: { visible: false }, gridcolor: "#334155", domain: [0, 1], anchor: "y" },
    yaxis: { domain: [0.26, 1], gridcolor: "#334155", title: "가격", side: "right" },
    yaxis2: { domain: [0, 0.2], gridcolor: "#334155", title: "거래량", side: "right" },
  };
  Plotly.newPlot(area, traces, layout, { responsive: true, scrollZoom: true, displaylogo: false });
}

// ---------- events ----------
$("#refresh-btn").addEventListener("click", loadDashboard);
$("#chart-close").addEventListener("click", closeChart);
$("#chart-modal").addEventListener("click", (e) => { if (e.target.id === "chart-modal") closeChart(); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeChart(); });
document.querySelectorAll(".range-toggle button").forEach((b) =>
  b.addEventListener("click", () => {
    currentRange = b.dataset.range;
    document.querySelectorAll(".range-toggle button").forEach((x) =>
      x.classList.toggle("active", x === b));
    drawChart();
  }));

// ---------- auto refresh (live mode only) ----------
let timer = null;
function scheduleAuto() {
  if (timer) clearInterval(timer);
  if (!$("#auto-toggle").checked) return;
  timer = setInterval(loadDashboard, parseInt($("#auto-interval").value, 10) * 1000);
}
$("#auto-toggle").addEventListener("change", scheduleAuto);
$("#auto-interval").addEventListener("change", scheduleAuto);

window.openChart = openChart;

// In static mode the data only changes once a day, so hide live auto-refresh.
if (STATIC) {
  const auto = document.querySelector(".auto");
  if (auto) auto.classList.add("hidden");
}

loadDashboard();
scheduleAuto();
