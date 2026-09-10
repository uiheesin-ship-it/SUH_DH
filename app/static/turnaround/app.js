"use strict";

const $ = (sel) => document.querySelector(sel);

// Two run modes (see config.js):
//   STATIC=false -> live FastAPI backend (/api/turnaround, /api/chart)
//   STATIC=true  -> pre-built daily JSON in ../data/turnaround.json + ../data/chart/*
const STATIC = !!window.SUH_DH_STATIC;
const API_BASE = (window.SUH_DH_API_BASE || "").replace(/\/+$/, "");

let STOCKS = [];
let META = {};
let sortKey = "turnaround_score";
let sortDir = -1;
let currentTicker = null;
let currentRec = null;

// ---------- formatting ----------
function fmtCap(v) {
  if (v == null) return "-";
  if (v >= 1e12) return (v / 1e12).toFixed(2) + "T";
  if (v >= 1e9) return (v / 1e9).toFixed(2) + "B";
  if (v >= 1e6) return (v / 1e6).toFixed(1) + "M";
  return (+v).toLocaleString();
}
function fmtPrice(v) { return v == null ? "-" : "$" + (+v).toFixed(2); }
function fmtPct(v, d = 1) { return v == null ? "-" : (v * 100).toFixed(d) + "%"; }
function fmtNum(v, d = 2) { return v == null ? "-" : (+v).toFixed(d); }
function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
function signed(v, d = 1) {
  if (v == null) return "-";
  const cls = v >= 0 ? "pos" : "neg";
  return `<span class="${cls}">${(v * 100).toFixed(d)}%</span>`;
}

const TRIGGER_KO = {
  earnings_gap: "실적갭",
  power_bar: "대량상승봉",
  pocket_pivot: "포켓피벗",
  reclaim_200: "200일선회복",
  rs_new_high: "RS신고가",
};

// ---------- load ----------
async function load() {
  $("#status").textContent = "불러오는 중…";
  try {
    const res = STATIC ? await SUHData.fetch("turnaround.json", true)
                       : await fetch("/api/turnaround", { cache: "no-store" });
    const data = await res.json();
    if (!res.ok || data.error) {
      renderError(data.error || "데이터를 불러오지 못했습니다.", data.detail);
      return;
    }
    STOCKS = data.stocks || [];
    META = data;
    $("#demo-badge").classList.toggle("hidden", !data.demo);
    fillSectors();
    render();
    const built = data.built ? new Date(data.built).toLocaleString("ko-KR") : "-";
    $("#status").textContent = `${data.count}종목 · 유니버스 ${data.universe_size} · ${built}`;
  } catch (e) {
    renderError("데이터를 불러오지 못했습니다.", String(e));
  }
}

function renderError(msg, detail) {
  $("#content").innerHTML =
    `<div class="empty"><b>${esc(msg)}</b>${detail ? `<br><small>${esc(detail)}</small>` : ""}</div>`;
  $("#status").textContent = "오류";
}

function fillSectors() {
  const sel = $("#f-sector");
  const seen = [...new Set(STOCKS.map((s) => s.sector).filter(Boolean))].sort();
  sel.innerHTML = `<option value="">전체</option>` +
    seen.map((s) => `<option value="${esc(s)}">${esc(s)}</option>`).join("");
}

// ---------- filtering ----------
function visible() {
  const minScore = +$("#f-score").value;
  const minDd = +$("#f-drawdown").value / 100;
  const stage = $("#f-stage").value;
  const sector = $("#f-sector").value;
  const fresh = $("#f-fresh").checked;
  const earnings = $("#f-earnings").checked;
  const q = $("#f-search").value.trim().toLowerCase();

  let rows = STOCKS.filter((s) => {
    if ((s.turnaround_score ?? 0) < minScore) return false;
    if ((s.off_peak_high ?? 0) < minDd) return false;
    if (stage && s.stage !== stage) return false;
    if (sector && s.sector !== sector) return false;
    if (fresh && !s.trigger_fresh) return false;
    if (earnings && !(s.days_to_earnings != null && s.days_to_earnings >= 0
                      && s.days_to_earnings <= 14)) return false;
    if (q) {
      const hay = `${s.ticker} ${s.company_name || ""}`.toLowerCase();
      if (!hay.includes(q)) return false;
    }
    if (!passColFilters(s)) return false;
    return true;
  });

  rows.sort((a, b) => {
    const av = a[sortKey], bv = b[sortKey];
    if (av == null && bv == null) return 0;
    if (av == null) return 1;
    if (bv == null) return -1;
    if (typeof av === "string") return sortDir * av.localeCompare(bv);
    return sortDir * (av - bv);
  });
  return rows;
}

// ---------- per-column filters ----------
// Same model as the base screener: a ⏷ on each filterable header opens a
// popover. Numeric columns take a min/max, categorical ones a checkbox list of
// the values actually present in the current scan. These compose with the top
// bar (AND), so the bar stays the coarse pass and the headers do the fine one.
//
// ``scale`` is what the column DISPLAYS divided by what it stores: base_depth
// holds 0.21 and shows 21%, so the user types 21 and the filter compares 0.21.
const COL_FILTER = {
  sector:            { type: "cat" },
  turnaround_score:  { type: "num", scale: 1,    unit: "점" },
  stage:             { type: "cat" },
  quality_score:     { type: "num", scale: 1,    unit: "점" },
  edge_score:        { type: "num", scale: 1,    unit: "점" },
  setup_score:       { type: "num", scale: 1,    unit: "점" },
  trigger_score:     { type: "num", scale: 1,    unit: "점" },
  off_peak_high:     { type: "num", scale: 100,  unit: "%" },
  distance_to_pivot: { type: "num", scale: 100,  unit: "%" },
  base_days:         { type: "num", scale: 1,    unit: "일", numericSort: true },
  base_depth:        { type: "num", scale: 100,  unit: "%" },
  days_to_earnings:  { type: "num", scale: 1,    unit: "일" },
  current_price:     { type: "num", scale: 1,    unit: "$" },
  market_cap:        { type: "num", scale: 1e-9, unit: "B" },
};
let colFilters = {};   // key -> {min,max} (num) | {allowed:[...]} (cat)

function colFilterActive(key) {
  const f = colFilters[key], meta = COL_FILTER[key];
  if (!f || !meta) return false;
  return meta.type === "num" ? (f.min != null || f.max != null)
                             : !!(f.allowed && f.allowed.length);
}
function activeColCount() {
  return Object.keys(colFilters).filter(colFilterActive).length;
}
function passColFilters(s) {
  for (const key in colFilters) {
    const meta = COL_FILTER[key];
    if (!meta || !colFilterActive(key)) continue;
    const f = colFilters[key], v = s[key];
    if (meta.type === "num") {
      const sc = meta.scale || 1;
      // A null value fails any bound rather than passing silently — otherwise
      // "실적 D- ≤ 14" would keep every stock whose earnings date is unknown.
      if (f.min != null && !(v != null && v >= f.min / sc)) return false;
      if (f.max != null && !(v != null && v <= f.max / sc)) return false;
    } else if (!f.allowed.some((a) => String(a) === String(v))) {
      return false;
    }
  }
  return true;
}
function colDistinct(key) {
  const meta = COL_FILTER[key], set = new Set();
  STOCKS.forEach((s) => {
    const v = s[key];
    if (v !== null && v !== undefined && v !== "") set.add(v);
  });
  const arr = [...set];
  arr.sort(meta.numericSort ? (a, b) => a - b : undefined);
  return arr;
}

let colPopEl = null;
function closeColPop() {
  if (colPopEl) {
    colPopEl.remove();
    colPopEl = null;
    document.removeEventListener("mousedown", onColPopDown, true);
  }
}
function onColPopDown(e) {
  if (colPopEl && !colPopEl.contains(e.target) && !e.target.classList.contains("col-filter")) closeColPop();
}
function openColFilter(key, anchorEl) {
  closeColPop();
  const meta = COL_FILTER[key];
  if (!meta) return;
  const f = colFilters[key] = colFilters[key]
    || (meta.type === "num" ? { min: null, max: null } : { allowed: [] });
  const label = (COLS.find((c) => c.k === key) || {}).t || key;

  const pop = document.createElement("div");
  pop.className = "colpop";
  let inner = `<div class="colpop-h">${esc(label)} 필터</div>`;
  if (meta.type === "num") {
    const u = meta.unit || "";
    inner += `<div class="colpop-row"><span>≥</span><input type="number" id="cp-min" value="${f.min ?? ""}" placeholder="min"><span>${esc(u)}</span></div>
              <div class="colpop-row"><span>≤</span><input type="number" id="cp-max" value="${f.max ?? ""}" placeholder="max"><span>${esc(u)}</span></div>`;
  } else {
    const allowed = new Set((f.allowed || []).map(String));
    const anySel = allowed.size > 0;
    inner += `<div class="colpop-actions"><button id="cp-all">전체</button><button id="cp-none">해제</button></div><div class="colpop-list">` +
      colDistinct(key).map((v) => {
        const checked = !anySel || allowed.has(String(v));
        return `<label><input type="checkbox" class="cp-chk" value="${esc(String(v))}" ${checked ? "checked" : ""}> ${esc(String(v))}</label>`;
      }).join("") + `</div>`;
  }
  inner += `<div class="colpop-foot"><button id="cp-clear">이 열 해제</button><button id="cp-clearall">전체 해제</button></div>`;
  pop.innerHTML = inner;
  document.body.appendChild(pop);
  colPopEl = pop;

  // Place under the caret, nudged back inside the viewport on the right edge.
  const r = anchorEl.getBoundingClientRect();
  pop.style.left = Math.max(8, Math.min(r.left, window.innerWidth - pop.offsetWidth - 8)) + "px";
  pop.style.top = (r.bottom + 4) + "px";

  if (meta.type === "num") {
    const upd = () => {
      const mn = pop.querySelector("#cp-min").value, mx = pop.querySelector("#cp-max").value;
      f.min = mn === "" ? null : +mn;
      f.max = mx === "" ? null : +mx;
      render();
    };
    pop.querySelector("#cp-min").addEventListener("input", upd);
    pop.querySelector("#cp-max").addEventListener("input", upd);
  } else {
    const chks = () => [...pop.querySelectorAll(".cp-chk")];
    const updCat = () => {
      const all = chks(), checked = all.filter((c) => c.checked).map((c) => c.value);
      // All-checked and none-checked both mean "no constraint" — otherwise
      // unticking the last box would empty the table with no way back.
      f.allowed = (checked.length === all.length || checked.length === 0) ? [] : checked;
      render();
    };
    pop.querySelectorAll(".cp-chk").forEach((c) => c.addEventListener("change", updCat));
    pop.querySelector("#cp-all").addEventListener("click", () => { chks().forEach((c) => c.checked = true); updCat(); });
    pop.querySelector("#cp-none").addEventListener("click", () => { chks().forEach((c) => c.checked = false); updCat(); });
  }
  pop.querySelector("#cp-clear").addEventListener("click", () => { delete colFilters[key]; closeColPop(); render(); });
  pop.querySelector("#cp-clearall").addEventListener("click", () => { colFilters = {}; closeColPop(); render(); });
  setTimeout(() => document.addEventListener("mousedown", onColPopDown, true), 0);
}

// ---------- table ----------
const COLS = [
  { k: "ticker", t: "티커", l: true },
  { k: "sector", t: "섹터", l: true },
  { k: "turnaround_score", t: "점수" },
  { k: "stage", t: "단계", l: true },
  { k: "quality_score", t: "품질40" },
  { k: "edge_score", t: "오른끝30" },
  { k: "setup_score", t: "셋업20" },
  { k: "trigger_score", t: "트리거10" },
  { k: "off_peak_high", t: "고점대비" },
  { k: "distance_to_pivot", t: "피봇거리" },
  { k: "base_days", t: "기간" },
  { k: "base_depth", t: "깊이" },
  { k: "days_to_earnings", t: "실적D-" },
  { k: "current_price", t: "주가" },
  { k: "market_cap", t: "시총" },
];

function render() {
  const rows = visible();
  $("#count-badge").textContent = `${rows.length} / ${STOCKS.length}`;
  // An active column filter lives inside a header popover, so surface it here —
  // otherwise a short list looks like a bad scan rather than a narrow filter.
  const nCol = activeColCount();
  const chip = $("#colfilter-chip");
  chip.classList.toggle("hidden", nCol === 0);
  if (nCol) chip.querySelector("#colfilter-n").textContent = nCol;
  if (!rows.length) {
    $("#content").innerHTML = `<div class="empty">조건에 맞는 종목이 없습니다. 필터를 낮춰보세요.</div>`;
    return;
  }
  const head = COLS.map((c) => {
    const arrow = sortKey === c.k ? (sortDir < 0 ? " ▾" : " ▴") : "";
    const fic = COL_FILTER[c.k]
      ? `<span class="col-filter${colFilterActive(c.k) ? " on" : ""}" data-fkey="${esc(c.k)}" title="열 필터">⏷</span>`
      : "";
    return `<th class="${c.l ? "l" : ""}" data-k="${c.k}">${c.t}${arrow}${fic}</th>`;
  }).join("");

  const body = rows.map((s) => {
    const trig = (s.triggers || []).slice(0, 2)
      .map((t) => `<span class="chip trig">${esc(TRIGGER_KO[t] || t)}</span>`).join("");
    const dd = s.days_to_earnings;
    const ddCell = dd == null ? "-"
      : `<span class="chip dday${dd >= 0 && dd <= 14 ? " soon" : ""}">D${dd >= 0 ? "-" : "+"}${Math.abs(dd)}</span>`;
    return `<tr data-t="${esc(s.ticker)}" class="${s.ticker === currentTicker ? "sel" : ""}">
      <td class="l"><span class="tk">${esc(s.ticker)}</span><div class="co">${esc(s.company_name || "")}</div></td>
      <td class="l co">${esc(s.sector || "-")}</td>
      <td><span class="score-pill ${esc(s.grade)}">${fmtNum(s.turnaround_score, 1)}</span></td>
      <td class="l"><span class="chip st-${esc(s.stage)}">${esc(s.stage)}</span>${trig}</td>
      <td>${fmtNum(s.quality_score, 1)}</td>
      <td>${fmtNum(s.edge_score, 1)}</td>
      <td>${fmtNum(s.setup_score, 1)}</td>
      <td>${fmtNum(s.trigger_score, 1)}</td>
      <td>${fmtPct(s.off_peak_high)}</td>
      <td>${fmtPct(s.distance_to_pivot)}</td>
      <td>${s.base_days ?? "-"}</td>
      <td>${fmtPct(s.base_depth)}</td>
      <td>${ddCell}</td>
      <td>${fmtPrice(s.current_price)}</td>
      <td>${fmtCap(s.market_cap)}</td>
    </tr>`;
  }).join("");

  $("#content").innerHTML = `<table class="tbl"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;

  $("#content").querySelectorAll(".col-filter").forEach((el) =>
    el.addEventListener("click", (e) => {
      e.stopPropagation();               // the caret must not also sort the column
      openColFilter(el.dataset.fkey, el);
    }));
  $("#content").querySelectorAll("thead th").forEach((th) => {
    th.addEventListener("click", () => {
      const k = th.dataset.k;
      if (sortKey === k) sortDir = -sortDir;
      else { sortKey = k; sortDir = (k === "ticker" || k === "sector" || k === "stage") ? 1 : -1; }
      render();
    });
  });
  $("#content").querySelectorAll("tbody tr").forEach((tr) => {
    tr.addEventListener("click", () => openChart(tr.dataset.t));
  });
}

// ---------- score panel ----------
function bar(label, value, max, cls) {
  const pct = max ? Math.max(0, Math.min(100, (value / max) * 100)) : 0;
  return `<div class="bar-row">
    <span class="lbl">${esc(label)}</span>
    <span class="bar-track"><span class="bar-fill ${cls}" style="width:${pct.toFixed(1)}%"></span></span>
    <span class="val">${fmtNum(value, 1)} / ${max}</span>
  </div>`;
}

function renderScorePanel(s) {
  $("#score-panel").innerHTML =
    bar("베이스 품질", s.quality_score, 40, "q") +
    bar("오른쪽 끝", s.edge_score, 30, "e") +
    bar("바닥 셋업", s.setup_score, 20, "s") +
    bar("첫 전환", s.trigger_score, 10, "t");
}

function renderDetail(s) {
  const trig = (s.triggers || []).map((t) => TRIGGER_KO[t] || t).join(", ") || "-";
  const rows = [
    ["단계 / 등급", `${s.stage} · ${s.grade}`],
    ["피봇 상태", `${s.pivot_status} (${s.pivot_kind === "ledge" ? "레지" : "베이스고점"})`],
    ["유효 피봇 / 거리", `${fmtPrice(s.pivot_price)} · ${fmtPct(s.distance_to_pivot)}`],
    ["베이스 밴드 위치", fmtNum(s.base_position, 2)],
    ["최근 조여짐", fmtNum(s.tighten_ratio, 2)],
    ["베이스 기간 / 깊이", `${s.base_days ?? "-"}일 · ${fmtPct(s.base_depth)}`],
    ["베이스 고 / 저", `${fmtPrice(s.base_high)} · ${fmtPrice(s.base_low)}`],
    ["베이스 시작 / 저점일", `${s.base_start_date || "-"} · ${s.base_low_date || "-"}`],
    ["저점 위치(앞쪽 비율)", fmtNum(s.low_position, 2)],
    ["회복도(창 내 위치)", fmtNum(s.base_recovery, 2)],
    ["베이스 드리프트", fmtPct(s.base_drift)],
    ["수축비 (후반/전반)", fmtNum(s.q_contraction_ratio, 2)],
    ["거래량 마름 (10/50)", fmtNum(s.q_dryup_ratio, 2)],
    ["응집도", fmtNum(s.q_containment, 2)],
    ["저점 하회 / 저점 상승", `${fmtPct(s.q_undercut)} · ${fmtPct(s.q_higher_low)}`],
    ["3년 고점 대비", fmtPct(s.off_peak_high)],
    ["52주 저점 대비", signed(s.off_52w_low)],
    ["200일선 기울기(40일)", signed(s.sma200_slope)],
    ["주가 vs 50 / 200일선", `${signed(s.price_vs_sma50)} · ${signed(s.price_vs_sma200)}`],
    ["RS 라인 복구", signed(s.rs_repair)],
    ["트리거", `${trig}${s.trigger_date ? ` (${s.trigger_date})` : ""}`],
    ["다음 실적", s.next_earnings_date ? `${s.next_earnings_date} (D-${s.days_to_earnings})` : "-"],
    ["최근 4분기 서프라이즈", s.recent_beats == null ? "-" : `${s.recent_beats}회 상회`],
    ["수익률 1/3/6/12M", `${signed(s.ret_1m)} · ${signed(s.ret_3m)} · ${signed(s.ret_6m)} · ${signed(s.ret_12m)}`],
    ["ADR% / RS%", `${fmtNum(s.adr_pct, 1)}% · ${s.rs_percentile ?? "-"}`],
  ];
  $("#detail-panel").innerHTML = `<h4>세부 지표</h4><div class="kv">` +
    rows.map(([k, v]) => `<span class="k">${esc(k)}</span><span class="v">${v}</span>`).join("") +
    `</div>`;
}

// ---------- chart ----------
async function fetchChart(ticker) {
  if (STATIC) {
    const res = await fetch(`../data/chart/${encodeURIComponent(ticker)}.json`, { cache: "no-store" });
    if (res.ok) return res.json();
    if (API_BASE) {
      const r = await fetch(`${API_BASE}/api/chart/${encodeURIComponent(ticker)}?range=max`);
      const d = await r.json();
      if (r.ok && !d.error) return d;
    }
    throw new Error("저장된 차트가 없습니다");
  }
  const res = await fetch(`/api/chart/${encodeURIComponent(ticker)}?range=max`);
  const d = await res.json();
  if (!res.ok || d.error) throw new Error(d.detail || d.error || "chart error");
  return d;
}

function sma(values, win) {
  const out = new Array(values.length).fill(null);
  let sum = 0;
  for (let i = 0; i < values.length; i++) {
    sum += values[i];
    if (i >= win) sum -= values[i - win];
    if (i >= win - 1) out[i] = sum / win;
  }
  return out;
}

async function openChart(ticker) {
  currentTicker = ticker;
  currentRec = STOCKS.find((s) => s.ticker === ticker) || {};
  $("#chart-pane").classList.remove("hidden");
  $("#divider").classList.remove("hidden");
  $("#chart-ticker").textContent = ticker;
  $("#chart-company").textContent = currentRec.company_name || "";
  $("#chart-external").href = `https://finance.yahoo.com/quote/${encodeURIComponent(ticker)}`;
  renderScorePanel(currentRec);
  renderDetail(currentRec);
  render();

  $("#chart-area").innerHTML = `<div class="loading">차트 불러오는 중…</div>`;
  let d;
  try {
    d = await fetchChart(ticker);
  } catch (e) {
    $("#chart-area").innerHTML = `<div class="empty">${esc(String(e.message || e))}</div>`;
    return;
  }
  const dates = d.dates || [];
  const close = d.close || [];
  const s50 = sma(close, 50);
  const s200 = sma(close, 200);

  const traces = [
    {
      x: dates, open: d.open, high: d.high, low: d.low, close: close,
      type: "candlestick", name: ticker,
      increasing: { line: { color: "#15803d" } },
      decreasing: { line: { color: "#b91c1c" } },
    },
    { x: dates, y: s50, type: "scatter", mode: "lines", name: "SMA50",
      line: { color: "#2563eb", width: 1.2 } },
    { x: dates, y: s200, type: "scatter", mode: "lines", name: "SMA200",
      line: { color: "#9333ea", width: 1.2 } },
  ];

  const shapes = [];
  const rec = currentRec;
  if (rec.base_start_date && rec.base_end_date) {
    shapes.push({
      type: "rect", xref: "x", yref: "paper",
      x0: rec.base_start_date, x1: rec.base_end_date, y0: 0, y1: 1,
      fillcolor: "#b45309", opacity: 0.08, line: { width: 0 }, layer: "below",
    });
  }
  if (rec.pivot_price) {
    shapes.push({
      type: "line", xref: "paper", yref: "y", x0: 0, x1: 1,
      y0: rec.pivot_price, y1: rec.pivot_price,
      line: { color: "#0f766e", width: 1.4, dash: "dash" },
    });
  }
  if (rec.base_low) {
    shapes.push({
      type: "line", xref: "paper", yref: "y", x0: 0, x1: 1,
      y0: rec.base_low, y1: rec.base_low,
      line: { color: "#b45309", width: 1, dash: "dot" },
    });
  }

  Plotly.newPlot("chart-area", traces, {
    margin: { l: 48, r: 12, t: 8, b: 32 },
    height: 380,
    paper_bgcolor: "#ffffff",
    plot_bgcolor: "#ffffff",
    font: { color: "#23201b", size: 11 },
    xaxis: { rangeslider: { visible: false }, gridcolor: "#eae5dc" },
    yaxis: { gridcolor: "#eae5dc", side: "left" },
    showlegend: false,
    shapes,
  }, { responsive: true, displayModeBar: false });
}

// ---------- Finviz charts view ----------
// Open the currently-filtered tickers in Finviz's Charts view (v=210), a
// paginated grid of daily candlesticks — far lighter than rendering hundreds of
// Plotly charts in-app, and the fastest way to eyeball whether a base is real.
function openFinvizCharts() {
  const rows = visible();
  const tickers = rows.map((s) => String(s.ticker).trim().toUpperCase()).filter(Boolean);
  if (!tickers.length) {
    alert("표시된 종목이 없습니다. 필터를 완화한 뒤 다시 눌러 주세요.");
    return;
  }
  // Cap the list so the URL isn't rejected for length. Finviz paginates 20
  // charts a page, so the cap is still more than anyone scrolls through.
  const CAP = 500;
  let list = tickers;
  if (list.length > CAP) {
    if (!confirm(`표시된 종목이 ${list.length}개입니다. Finviz 링크 길이 제한으로 상위 ${CAP}개만 엽니다. 계속할까요?`)) return;
    list = list.slice(0, CAP);
  }
  const url = "https://finviz.com/screener.ashx?v=210&t=" + encodeURIComponent(list.join(","));
  window.open(url, "_blank", "noopener");
}

// ---------- TradingView TXT export ----------
// Turn the filtered tickers into an ``EXCHANGE:SYMBOL`` comma list
// (NASDAQ:AAPL,NYSE:BRK.B,…) for TradingView's watchlist import. The exchange
// comes from data/us_exchanges.json (built from FDR listings and shared with the
// base and flat pages). A ticker missing from the map is exported bare —
// TradingView resolves most of those itself, so a gap is not worth dropping the
// row over.
let _EXCH = null;
async function loadExchanges() {
  if (_EXCH) return _EXCH;
  try {
    const r = await fetch(`../data/us_exchanges.json?_=${Date.now()}`, { cache: "no-store" });
    _EXCH = r.ok ? await r.json() : {};
  } catch (_) { _EXCH = {}; }
  return _EXCH;
}
function tvSymbol(ticker, map) {
  const t = String(ticker || "").toUpperCase().trim();
  if (!t) return "";
  const exch = map[t.replace(/\./g, "-")];   // map is keyed Finviz-style (BRK-B)
  const sym = t.replace(/-/g, ".");           // TradingView wants BRK.B
  return exch ? `${exch}:${sym}` : sym;
}
// Sector-grouped, each group preceded by a "###Sector" header, comma-separated —
// the format TradingView reads back as watchlist sections.
function tvGroupedText(rows, map) {
  const groups = new Map();   // sector -> [symbols], first-seen order preserved
  for (const s of rows) {
    const sec = (s.sector || "기타").replace(/,/g, " ");   // a comma would break the delimiter
    const sym = tvSymbol(s.ticker, map);
    if (!sym) continue;
    if (!groups.has(sec)) groups.set(sec, []);
    groups.get(sec).push(sym);
  }
  const parts = [];
  let total = 0, missing = 0;
  for (const [sec, syms] of groups) {
    if (!syms.length) continue;
    parts.push("###" + sec);
    for (const sym of syms) { parts.push(sym); total++; if (!sym.includes(":")) missing++; }
  }
  return { text: parts.join(","), total, missing };
}
async function exportTradingView() {
  const rows = visible();
  if (!rows.length) { alert("표시된 종목이 없습니다."); return; }
  const map = await loadExchanges();
  const { text, total, missing } = tvGroupedText(rows, map);
  const blob = new Blob([text], { type: "text/plain;charset=utf-8" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `tradingview_turnaround_${new Date().toISOString().slice(0, 10)}.txt`;
  a.click();
  URL.revokeObjectURL(a.href);
  if (missing) alert(`${total}개 중 ${missing}개는 거래소를 못 찾아 접두사 없이 넣었어요 (TradingView가 대부분 자동 인식합니다).`);
}

// ---------- CSV ----------
function exportCsv() {
  const rows = visible();
  const cols = ["ticker", "company_name", "sector", "turnaround_score", "grade", "stage",
    "quality_score", "edge_score", "setup_score", "trigger_score", "off_peak_high",
    "distance_to_pivot", "pivot_status", "base_days", "base_depth", "base_position",
    "days_to_earnings", "triggers", "current_price", "market_cap"];
  const lines = [cols.join(",")];
  for (const r of rows) {
    lines.push(cols.map((c) => {
      let v = r[c];
      if (Array.isArray(v)) v = v.join(" ");
      if (v == null) return "";
      const s = String(v);
      return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
    }).join(","));
  }
  const blob = new Blob(["﻿" + lines.join("\n")], { type: "text/csv;charset=utf-8" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `turnaround_${new Date().toISOString().slice(0, 10)}.csv`;
  a.click();
  URL.revokeObjectURL(a.href);
}

// ---------- wiring ----------
function bind() {
  $("#f-score").addEventListener("input", () => {
    $("#f-score-val").textContent = $("#f-score").value; render();
  });
  $("#f-drawdown").addEventListener("input", () => {
    $("#f-drawdown-val").textContent = $("#f-drawdown").value + "%"; render();
  });
  ["#f-stage", "#f-sector"].forEach((s) => $(s).addEventListener("change", render));
  ["#f-fresh", "#f-earnings"].forEach((s) => $(s).addEventListener("change", render));
  $("#f-search").addEventListener("input", render);
  $("#refresh-btn").addEventListener("click", load);
  $("#csv-btn").addEventListener("click", exportCsv);
  $("#colfilter-clear").addEventListener("click", () => { colFilters = {}; closeColPop(); render(); });
  $("#finviz-btn").addEventListener("click", openFinvizCharts);
  $("#tv-btn").addEventListener("click", exportTradingView);
  $("#chart-close").addEventListener("click", () => {
    $("#chart-pane").classList.add("hidden");
    $("#divider").classList.add("hidden");
    currentTicker = null;
    render();
  });
  $("#logic-btn").addEventListener("click", () => $("#logic-modal").classList.remove("hidden"));
  $("#logic-close").addEventListener("click", () => $("#logic-modal").classList.add("hidden"));
  $("#logic-modal").addEventListener("click", (e) => {
    if (e.target.id === "logic-modal") $("#logic-modal").classList.add("hidden");
  });

  // draggable split
  let dragging = false;
  $("#divider").addEventListener("mousedown", () => { dragging = true; document.body.style.userSelect = "none"; });
  window.addEventListener("mouseup", () => { dragging = false; document.body.style.userSelect = ""; });
  window.addEventListener("mousemove", (e) => {
    if (!dragging) return;
    const total = $("#split").clientWidth;
    const right = Math.min(Math.max(total - e.clientX, 320), total - 360);
    $("#chart-pane").style.flex = `0 0 ${right}px`;
    Plotly.Plots.resize($("#chart-area"));
  });
}

bind();
load();
