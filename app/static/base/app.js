"use strict";

const $ = (sel) => document.querySelector(sel);

// Two run modes (see config.js):
//   STATIC=false -> live FastAPI backend (/api/base, /api/chart)
//   STATIC=true  -> pre-built daily JSON in ../data/base.json + ../data/chart/*
const STATIC = !!window.SUH_DH_STATIC;
const BUILT = window.SUH_DH_BUILT || null;
// Optional hosted backend — used only as a chart fallback for setups whose
// chart wasn't pre-built (fast, scan-skipped builds don't pre-build them).
const API_BASE = (window.SUH_DH_API_BASE || "").replace(/\/+$/, "");

let STOCKS = [];
let META = {};
let sortKey = "total_score";
let sortDir = -1;         // -1 desc, 1 asc
let currentTicker = null;
let currentRec = null;
let chartData = null;
let suppressRelayout = false;
let watchOnly = false;
const WATCH_KEY = "suh_base_watch";
let WATCH = new Set(JSON.parse(localStorage.getItem(WATCH_KEY) || "[]"));

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

// ---------- load ----------
async function load() {
  $("#status").textContent = "불러오는 중…";
  try {
    // Static: read base.json from the repo's raw copy (freshest committed),
    // falling back to the deployed snapshot — see shared/data-source.js. This
    // decouples the data shown from Pages deploy timing.
    const res = STATIC ? await SUHData.fetch("base.json", true)
                       : await fetch("/api/base", { cache: "no-store" });
    const data = await res.json();
    if (!res.ok || data.error) {
      renderError(data.error || "데이터를 불러오지 못했습니다.", data.detail);
      return;
    }
    STOCKS = data.stocks || [];
    META = data;
    $("#demo-badge").classList.toggle("hidden", !data.demo);
    populateSectors();
    render();
    // Show the DATA's own build time (not the baked site-deploy time), so the
    // "갱신" stamp reflects the snapshot actually being displayed.
    const when = STATIC ? (data.built ? new Date(data.built).toLocaleString("ko-KR") : "최근")
                        : new Date().toLocaleTimeString("ko-KR");
    const dropTxt = data.dropped_count != null ? ` · 제외 ${data.dropped_count}` : "";
    $("#status").textContent =
      `${data.count}개 종목 (유니버스 ${data.universe_size}${dropTxt}) · ${STATIC ? "갱신 " + when + " · 매일 자동" : "업데이트 " + when}`;
  } catch (e) {
    renderError("데이터를 불러오지 못했습니다", e.message);
  }
}

function renderError(msg, detail) {
  $("#content").innerHTML =
    `<div class="error"><b>${esc(msg)}</b>${detail ? "<br><small>" + esc(detail) + "</small>" : ""}</div>`;
  $("#status").textContent = "오류";
}

function populateSectors() {
  const secs = [...new Set(STOCKS.map((s) => s.sector).filter(Boolean))].sort();
  const sel = $("#f-sector");
  const cur = sel.value;
  sel.innerHTML = `<option value="">전체</option>` +
    secs.map((s) => `<option value="${esc(s)}">${esc(s)}</option>`).join("");
  sel.value = cur;
}

// ---------- filtering + sorting ----------
function filtered() {
  const minScore = +$("#f-score").value;
  const grade = $("#f-grade").value;
  const pivot = $("#f-pivot").value;
  const alert = $("#f-alert").value;
  const sector = $("#f-sector").value;
  const ipoOnly = $("#f-ipo") ? $("#f-ipo").checked : false;
  const etfMode = $("#f-etf") ? $("#f-etf").value : "";
  const q = $("#f-search").value.trim().toUpperCase();

  let rows = STOCKS.filter((s) => {
    if (watchOnly && !WATCH.has(s.ticker)) return false;
    if (ipoOnly && !s.is_ipo) return false;
    if (etfMode === "only" && !s.is_etf) return false;
    if (etfMode === "exclude" && s.is_etf) return false;
    if ((s.total_score ?? 0) < minScore) return false;
    if (grade && s.setup_grade !== grade) return false;
    if (pivot && (s.pivot?.pivot_status) !== pivot) return false;
    if (alert && s.alert_type !== alert) return false;
    if (sector && s.sector !== sector) return false;
    if (q && !(String(s.ticker).toUpperCase().includes(q) ||
              String(s.company_name || "").toUpperCase().includes(q))) return false;
    if (!passColFilters(s)) return false;   // Excel-style per-column filters
    return true;
  });

  rows.sort((a, b) => {
    let va = sortVal(a, sortKey), vb = sortVal(b, sortKey);
    if (va == null) va = -Infinity;
    if (vb == null) vb = -Infinity;
    if (va < vb) return -1 * sortDir;
    if (va > vb) return 1 * sortDir;
    return 0;
  });
  return rows;
}

function sortVal(s, key) {
  switch (key) {
    case "distance_to_pivot": {
      const d = s.pivot?.distance_to_pivot;
      return d == null ? null : Math.abs(d);
    }
    case "base_depth": return s.base?.base_depth;
    case "pivot_status": return s.pivot?.pivot_status;
    default: return s[key];
  }
}

// ---------- render table ----------
const GRADE_CLS = { Prime: "g-prime", High: "g-high", Watch: "g-watch", Low: "g-low" };
const ALERT_CLS = { ready: "a-ready", breakout: "a-breakout", extended: "a-extended", none: "" };
const PIVOT_CLS = { ready: "p-ready", broken_out: "p-broken", watch: "p-watch",
                    early: "p-early", extended: "p-extended" };
const IB_CLS = { prime: "ib-prime", high: "ib-high", watch: "ib-watch", low: "ib-low" };
const BASETYPE = { flat: ["평평", "bt-flat"], tight: ["타이트", "bt-tight"],
                   abc: ["ABC", "bt-abc"], base: ["베이스", "bt-base"], none: ["-", ""] };

// ---------- Excel-style per-column filters (like the flat screener) ----------
// A value entered in a numeric filter is in the column's DISPLAYED units, so it
// is divided by `scale` before comparing to the stored value (e.g. 시총 2 => 2e9,
// pivot거리 5 => 0.05). Categorical columns show a checklist of distinct values.
const COL_FILTER = {
  total_score:       { type: "num", scale: 1, unit: "점" },
  inbase_score:      { type: "num", scale: 1, unit: "점" },
  beta:              { type: "num", scale: 1, unit: "" },
  base_type:         { type: "cat", label: (v) => (BASETYPE[v] || [v])[0] },
  setup_grade:       { type: "cat", label: (v) => v },
  alert_type:        { type: "cat", label: (v) => v },
  current_price:     { type: "num", scale: 1, unit: "$" },
  market_cap:        { type: "num", scale: 1e-9, unit: "B" },
  rs_percentile:     { type: "num", scale: 1, unit: "" },
  distance_to_pivot: { type: "num", scale: 100, unit: "%" },
  pivot_status:      { type: "cat", label: (v) => v },
  base_depth:        { type: "num", scale: 100, unit: "%" },
  sector_etf:        { type: "cat", label: (v) => v },
};
let colFilters = {};   // key -> {min,max} (num) or {allowed:[...]} (cat)

// Column value used by BOTH filtering and the checklist — mirrors sortVal so
// nested fields (pivot / base) filter on the same number the table shows.
function colValue(s, key) {
  switch (key) {
    case "distance_to_pivot": return s.pivot?.distance_to_pivot;
    case "base_depth": return s.base?.base_depth;
    case "pivot_status": return s.pivot?.pivot_status;
    default: return s[key];
  }
}

function colFilterActive(key) {
  const f = colFilters[key], meta = COL_FILTER[key];
  if (!f || !meta) return false;
  return meta.type === "num" ? (f.min != null || f.max != null)
                             : !!(f.allowed && f.allowed.length);
}

function passColFilters(s) {
  for (const key in colFilters) {
    const meta = COL_FILTER[key];
    if (!meta || !colFilterActive(key)) continue;
    const f = colFilters[key], v = colValue(s, key);
    if (meta.type === "num") {
      const sc = meta.scale || 1;
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
    const v = colValue(s, key);
    if (v !== null && v !== undefined && v !== "") set.add(v);
  });
  const arr = [...set];
  arr.sort(meta.numericSort ? (a, b) => a - b : undefined);
  return arr;
}

let colPopEl = null;
function closeColPop() {
  if (colPopEl) { colPopEl.remove(); colPopEl = null; document.removeEventListener("mousedown", onColPopDown, true); }
}
function onColPopDown(e) {
  if (colPopEl && !colPopEl.contains(e.target) && !e.target.classList.contains("col-filter")) closeColPop();
}
function openColFilter(key, anchor) {
  closeColPop();
  const meta = COL_FILTER[key];
  if (!meta) return;
  const f = colFilters[key] = colFilters[key] || (meta.type === "num" ? { min: null, max: null } : { allowed: [] });
  const label = (COLS.find((c) => c[0] === key) || [])[1] || key;
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
        const disp = meta.label ? meta.label(v) : String(v);
        const checked = !anySel || allowed.has(String(v));
        return `<label><input type="checkbox" class="cp-chk" value="${esc(String(v))}" ${checked ? "checked" : ""}> ${esc(disp)}</label>`;
      }).join("") + `</div>`;
  }
  inner += `<div class="colpop-foot"><button id="cp-clear">이 열 해제</button><button id="cp-clearall">전체 해제</button></div>`;
  pop.innerHTML = inner;
  document.body.appendChild(pop);
  colPopEl = pop;
  const r = anchor.getBoundingClientRect();
  pop.style.left = Math.max(8, Math.min(r.left, window.innerWidth - pop.offsetWidth - 8)) + "px";
  pop.style.top = (r.bottom + 4) + "px";

  if (meta.type === "num") {
    const upd = () => {
      const mn = pop.querySelector("#cp-min").value, mx = pop.querySelector("#cp-max").value;
      f.min = mn === "" ? null : +mn; f.max = mx === "" ? null : +mx; render();
    };
    pop.querySelector("#cp-min").addEventListener("input", upd);
    pop.querySelector("#cp-max").addEventListener("input", upd);
  } else {
    const chks = () => [...pop.querySelectorAll(".cp-chk")];
    const updCat = () => {
      const all = chks(), checked = all.filter((c) => c.checked).map((c) => c.value);
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

const COLS = [
  ["ticker", "티커", false],
  ["total_score", "점수", true],
  ["inbase_score", "In-Base", true],
  ["beta", "β", true],
  ["base_type", "유형", false],
  ["setup_grade", "등급", false],
  ["alert_type", "알림", false],
  ["current_price", "가격", true],
  ["market_cap", "시총", true],
  ["rs_percentile", "RS%", true],
  ["distance_to_pivot", "pivot거리", true],
  ["pivot_status", "pivot", false],
  ["base_depth", "베이스", true],
  ["sector_etf", "섹터ETF", false],
  ["notes", "메모", false],
];

function render() {
  const rows = filtered();
  $("#count-badge").textContent = `${rows.length}종목`;
  const wc = $("#watch-count"); if (wc) wc.textContent = WATCH.size;
  if (!rows.length) {
    let extra = "";
    const q = $("#f-search").value.trim().toUpperCase();
    if (q && Array.isArray(META.dropped)) {
      const drops = META.dropped.filter((d) => String(d.ticker).toUpperCase().includes(q));
      const inResults = STOCKS.some((s) => String(s.ticker).toUpperCase().includes(q));
      if (drops.length) {
        extra = `<div class="drop-note">🔎 <b>${esc(q)}</b> 스캔 제외 사유: ` +
          drops.map((d) => `<b>${esc(d.ticker)}</b> — ${esc(d.reason)}`).join(", ") +
          `<br><small>(제외 사유는 정밀분석 단계에서 걸린 것 — 히스토리·거래대금·저비타 등)</small></div>`;
      } else if (!inResults) {
        extra = `<div class="drop-note">🔎 <b>${esc(q)}</b> 은(는) 결과·제외목록 어디에도 없음 → <b>1차 Finviz 유니버스에 미포함</b>` +
          `<br><small>(주가>$1·거래량>50만주·시총≥$300M·정배열(50·200일선 위) 조건 미충족, 또는 그 시점 Finviz 응답에서 누락)</small></div>`;
      }
    }
    $("#content").innerHTML = `<div class="loading">조건에 맞는 종목이 없습니다. 필터를 완화해 보세요.${extra}</div>`;
    return;
  }
  const head = COLS.map(([k, label, num]) => {
    const arrow = sortKey === k ? (sortDir === -1 ? " ▾" : " ▴") : "";
    const fic = COL_FILTER[k]
      ? `<span class="col-filter${colFilterActive(k) ? " on" : ""}" data-fkey="${esc(k)}" title="열 필터">⏷</span>` : "";
    return `<th class="${num ? "num" : ""} sortable" data-key="${k}">${label}${arrow}${fic}</th>`;
  }).join("");

  const body = rows.map((s) => {
    const g = GRADE_CLS[s.setup_grade] || "";
    const a = ALERT_CLS[s.alert_type] || "";
    const p = PIVOT_CLS[s.pivot?.pivot_status] || "";
    const dist = s.pivot?.distance_to_pivot;
    return `<tr data-ticker="${esc(s.ticker)}">
      <td class="tk">
        <button class="star" data-star="${esc(s.ticker)}" title="관심종목">${WATCH.has(s.ticker) ? "★" : "☆"}</button>
        <button class="ticker-link" onclick="openChart('${esc(s.ticker)}')">${esc(s.ticker)}</button>
        <div class="company">${esc(s.company_name || "")}${s.is_etf ? ' <span class="badge bt-flat">ETF</span>' : ""}${s.is_ipo ? ` <span class="badge bt-abc" title="신규 상장(히스토리 ${s.history_days ?? "?"}일) — 이평선 조건은 적응 모드로 판정">신규상장</span>` : ""}</div>
      </td>
      <td class="num score"><b>${fmtNum(s.total_score, 0)}</b></td>
      <td class="num score"><b class="${IB_CLS[s.inbase_grade] || "ib-low"}">${fmtNum(s.inbase_score, 0)}</b>${s.extended ? ` <span class="ext-mark" title="이미 분출: ${esc((s.extension_flags || []).join(", "))}">분출</span>` : ""}</td>
      <td class="num${s.beta != null && s.beta < 0.8 ? " lowbeta" : ""}">${fmtNum(s.beta, 2)}</td>
      <td>${(() => { const [t, c] = BASETYPE[s.base_type] || BASETYPE.none; return t === "-" ? "-" : `<span class="badge ${c}">${t}</span>`; })()}</td>
      <td><span class="badge ${g}">${esc(s.setup_grade || "-")}</span></td>
      <td>${s.alert_type && s.alert_type !== "none"
            ? `<span class="badge ${a}">${esc(s.alert_type)}</span>` : "-"}</td>
      <td class="num">${fmtPrice(s.current_price)}</td>
      <td class="num">${fmtCap(s.market_cap)}</td>
      <td class="num">${fmtNum(s.rs_percentile, 0)}</td>
      <td class="num">${dist == null ? "-" : (dist * 100).toFixed(1) + "%"}</td>
      <td><span class="badge ${p}">${esc(s.pivot?.pivot_status || "-")}</span></td>
      <td class="num">${s.base?.base_depth == null ? "-"
            : (s.base.base_depth * 100).toFixed(0) + "% / " + (s.base.base_length_days ?? "-") + "d"}</td>
      <td class="etf">${esc(s.sector_etf || "-")}</td>
      <td class="notes">${esc(s.notes || "")}</td>
    </tr>`;
  }).join("");

  $("#content").innerHTML = `<table class="screen">
    <thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;

  document.querySelectorAll("th.sortable").forEach((th) =>
    th.addEventListener("click", () => {
      const k = th.dataset.key;
      if (sortKey === k) sortDir *= -1;
      else { sortKey = k; sortDir = (k === "ticker" || k === "sector_etf") ? 1 : -1; }
      render();
    }));
  document.querySelectorAll("button.star").forEach((b) =>
    b.addEventListener("click", (e) => { e.stopPropagation(); toggleWatch(b.dataset.star); }));
  document.querySelectorAll(".col-filter").forEach((el) =>
    el.addEventListener("click", (e) => { e.stopPropagation(); openColFilter(el.dataset.fkey, el); }));
  if (currentTicker) {
    document.querySelectorAll(`tr[data-ticker="${CSS.escape(currentTicker)}"]`)
      .forEach((r) => r.classList.add("active"));
  }
}

// ---------- watchlist ----------
function toggleWatch(ticker) {
  if (WATCH.has(ticker)) WATCH.delete(ticker); else WATCH.add(ticker);
  localStorage.setItem(WATCH_KEY, JSON.stringify([...WATCH]));
  if (window.SUHSync) SUHSync.record("base", ticker, WATCH.has(ticker));   // timestamped cloud sync
  render();
  if (currentTicker === ticker) {
    const cw = $("#chart-watch"); if (cw) cw.textContent = WATCH.has(ticker) ? "★" : "☆";
  }
}

// ---------- indicator glossary (hover tooltips) ----------
const GLOSSARY = {
  // score bars
  "Trend": "Minervini 추세 템플릿 충족도 (25점 만점).",
  "RS": "상대강도 — RS 백분위 + RS라인 신고가 + 시장 대비 초과수익 (20점).",
  "Base": "베이스 품질 — 길이·깊이·피봇 근접·50일선 근처·저점 절상 (25점).",
  "VCP": "변동성 수축 — ATR/변동폭 축소 + VCP 3단 구조 (15점).",
  "Vol": "거래량 — dry-up(거래량 마름) + 하락일 거래량 + 대량 하락일 적음 (10점).",
  "Sector": "섹터 강세 — 세부 섹터 ETF가 시장 대비 강하고 종목이 섹터 대비 강함 (5점).",
  // detail — trend
  "Trend Template": "Mark Minervini의 추세 조건 10가지. 가격이 150·200일선 위, 50>150>200 정배열, 200일선 상승, 52주 저점 대비 +30%↑·고점 대비 -25%↓, RS 백분위 80↑ 등. (충족 개수/전체)",
  "RS 백분위": "스캔한 유니버스 내 상대강도 순위(0~100). 90이면 상위 10%. 3/6/12개월 수익률을 합성해 계산.",
  "RS vs SPY 3M": "최근 3개월 이 종목 수익률 − S&P500(SPY) 수익률. 양수면 시장을 이긴 것.",
  "RS vs QQQ 3M": "최근 3개월 이 종목 수익률 − 나스닥100(QQQ) 수익률. 양수면 기술주 지수보다 강함.",
  "RS라인 SPY 신고가": "RS 라인(종목가격 ÷ SPY)이 최근 1년 최고치 근처(98%↑)인지. 가격이 아직 신고가가 아니어도 상대강도가 먼저 신고가를 내면 긍정적.",
  "직전 상승추세": "베이스 이전에 강한 상승이 있었는지 (20일전 ÷ 120일전 가격 − 1). +25%↑면 건설적.",
  // detail — base / pivot
  "구간": "탐지된 베이스(횡보) 구간의 시작~끝 날짜.",
  "길이/깊이": "베이스 기간(거래일)과 깊이(고점 대비 저점까지 하락률). 깊이 10~20% 우수, ~30% 양호, 35%↑ 제외.",
  "High/Low": "베이스 구간의 최고가 / 최저가.",
  "Pivot": "돌파 매수 기준가(보통 베이스 고점). 이 가격을 대량 거래로 넘으면 돌파 신호. 상태: ready/watch/early/broken_out/extended.",
  "피봇거리": "현재가가 pivot까지 남은 거리(%). 0~5% ready, 5~10% watch, 그 이상 early.",
  "Higher low": "베이스 후반 저점이 전반 저점보다 높은지(저점 절상). 매집의 신호.",
  "50일선 위치": "현재가가 50일선의 0.95~1.15배 범위인지 (괄호는 50일선 대비 이격도). 건전한 베이스는 보통 50일선 근처에서 형성.",
  // detail — volatility / vcp
  "ATR 축소비": "베이스 후반 1/3 ATR ÷ 전반 1/3 ATR. 작을수록 변동성 축소. 0.75↓ 통과, 0.60↓ 우수. (ATR=일평균 진폭)",
  "Range 축소비": "베이스 후반 1/3 일중 변동폭 ÷ 전반 1/3. 0.75↓면 변동성 축소로 봄.",
  "최근 압축": "최근 10일 ATR가 50일 ATR의 80% 미만인지 (막판 변동성 급압축 여부).",
  "변동성 등급": "변동성 축소 종합 등급 (excellent / good / weak).",
  "VCP 3단(R1/R2/R3)": "베이스를 3등분한 각 구간의 변동폭(%). 뒤로 갈수록 줄어드는(R1>R2>R3) 게 VCP(변동성 수축 패턴).",
  "VCP 통과/점수": "3단 수축 통과 여부와 0~1 점수 (단조 수축 + 마지막이 첫 구간의 60%↓면 우수).",
  // detail — volume / sector
  "Dry-up (10/50)": "최근 10일 평균 거래량 ÷ 50일 평균. 0.80 미만이면 '거래량 마름'(건전한 베이스 후반 특징). 0.70↓ 우수.",
  "베이스 후반 감소": "베이스 후반부 평균 거래량이 전반부의 80% 미만인지.",
  "대량 하락일(20d)": "최근 20일 중 −3%↑ 하락하며 거래량이 50일평균 1.5배↑였던 날 수. 2회↑면 분산(매도) 신호로 감점.",
  "A/D 점수": "최근 50일 상승일 vs 하락일 거래량 균형(−1~+1). 양수면 매집 우위.",
  "섹터 ETF": "이 종목에 매핑된 섹터 ETF (sector_mapping.csv 또는 섹터 기본값). 이 ETF 대비 상대강도로 섹터 점수 산출.",
  "섹터 3M / 종목-섹터": "섹터 ETF의 3개월 수익률 / (종목 3개월 − 섹터 3개월). 종목이 섹터보다 강하면 뒤 값이 양수.",
  "섹터 점수": "섹터 강세 종합(0~1). 종목>섹터>시장 구조이고 섹터가 추세 위·신고가 근처면 높음.",
  // In-Base
  "In-Base 점수": "종합점수와 별개로 '아직 조용히 베이스 중(분출 전)'인 정도(0~100). 안-뻗음(30)+타이트(25)+거래량마름(15)+지지선(15)+구조(15)에 저베타 페널티(vigor)를 곱함. 분출·저베타 종목은 낮게 나옴.",
  "β": "최근 1년 일간수익률의 시장(SPY) 대비 베타. <1이면 시장보다 덜 움직이는 저변동. AES 같은 방어주는 낮음.",
  "베타 / 추력(vigor)": "vigor = 베타(0.6) + 추력(0.4). 추력 = 12개월 상승·52주 저점 대비 상승. 낮으면 '잠자는 방어주'로 보고 In-Base를 깎고, β<0.8 이면서 추력도 약하면 목록에서 제외.",
  "베이스 유형": "평평(길고 얕은 횡보) · 타이트(짧고 매우 좁은 수축) · ABC(깊은 조정 후 저점 절상하며 지지선 반등) · 베이스(일반).",
  "분출 여부": "엄격 기준으로 이미 급등했는지: 5일 +10%↑ / 10일 +12%↑ / 50일선 +12%↑ / 피봇 돌파·과열 / 베이스 상단 급등 중 하나라도 걸리면 '분출'로 감점.",
  "단기 5일/10일": "최근 5거래일·10거래일 수익률. 크면 이미 튄 것(분출).",
  "최근10일 변동폭": "최근 10일 (고가−저가)/현재가. 작을수록 타이트하게 눌려 있음.",
  "베이스 내 위치": "현재가가 베이스 저점(0%)~고점(100%) 중 어디인지. 상단에서 막 급등했으면 분출 위험.",
};

// Wrap a label in a hover-tooltip span when the glossary has an entry for it.
function term(label) {
  const tip = GLOSSARY[label];
  return tip
    ? `<span class="term" data-tip="${esc(tip)}">${esc(label)}</span>`
    : esc(label);
}

// ---------- score / detail panels ----------
function scorePanel(s) {
  const parts = [
    ["Trend", s.trend_score, 25], ["RS", s.rs_score, 20], ["Base", s.base_score, 25],
    ["VCP", s.vcp_score, 15], ["Vol", s.volume_score, 10], ["Sector", s.sector_score, 5],
  ];
  const bars = parts.map(([name, val, max]) => {
    const pct = max ? Math.max(0, Math.min(100, (val / max) * 100)) : 0;
    return `<div class="sbar">
      <span class="sbar-name">${term(name)}</span>
      <span class="sbar-track"><span class="sbar-fill" style="width:${pct}%"></span></span>
      <span class="sbar-val">${fmtNum(val, 0)}/${max}</span>
    </div>`;
  }).join("");
  return `<div class="score-total">종합 <b>${fmtNum(s.total_score, 0)}</b>
      <span class="badge ${GRADE_CLS[s.setup_grade] || ""}">${esc(s.setup_grade)}</span>
      ${s.alert_type && s.alert_type !== "none"
        ? `<span class="badge ${ALERT_CLS[s.alert_type]}">${esc(s.alert_type)}</span>` : ""}
    </div>${bars}`;
}

function detailPanel(s) {
  const b = s.base || {}, p = s.pivot || {}, v = s.vcp || {}, vol = s.volatility || {}, vd = s.volume || {};
  const yesno = (x) => x === true ? "✓" : x === false ? "✗" : "—";
  const row = (k, val) => `<div class="d-row"><span>${term(k)}</span><span>${val}</span></div>`;
  return `
    <div class="d-grid">
      <div class="d-card"><h4>추세 (Minervini)</h4>
        ${s.is_ipo ? row("신규상장", `✔ 히스토리 ${s.history_days ?? "?"}일 — 이평선 적응 모드(있는 이평선으로 판정)`) : ""}
        ${row("Trend Template", `${yesno(s.trend_template_pass)} (${s.trend?.pass_count ?? "-"}/${s.trend?.total ?? 10})${s.trend?.ipo_adapted ? " · 적응" : ""}`)}
        ${row("RS 백분위", fmtNum(s.rs_percentile, 0))}
        ${row("RS vs SPY 3M", fmtPct(s.rs_vs_spy_3m))}
        ${row("RS vs QQQ 3M", fmtPct(s.rs_vs_qqq_3m))}
        ${row("RS라인 SPY 신고가", yesno(s.rs_line_spy_near_high))}
        ${row("직전 상승추세", `${fmtPct(s.prior_uptrend_return)} ${yesno(s.prior_uptrend_pass)}`)}
      </div>
      <div class="d-card"><h4>베이스 / 피봇</h4>
        ${row("구간", `${esc(b.base_start_date || "-")} ~ ${esc(b.base_end_date || "-")}`)}
        ${row("길이/깊이", `${b.base_length_days ?? "-"}d / ${fmtPct(b.base_depth)} (${esc(b.base_depth_grade || "-")})`)}
        ${row("High/Low", `${fmtPrice(b.base_high)} / ${fmtPrice(b.base_low)}`)}
        ${row("Pivot", `${fmtPrice(p.pivot_price)} · ${esc(p.pivot_status || "-")}`)}
        ${row("피봇거리", p.distance_to_pivot == null ? "-" : (p.distance_to_pivot * 100).toFixed(1) + "%")}
        ${row("Higher low", yesno(b.higher_low))}
        ${row("50일선 위치", `${yesno(s.sma50_position_pass)} (${s.distance_to_sma50 == null ? "-" : (s.distance_to_sma50 * 100).toFixed(1) + "%"})`)}
      </div>
      <div class="d-card"><h4>변동성 / VCP</h4>
        ${row("ATR 축소비", fmtNum(vol.atr_contraction_ratio))}
        ${row("Range 축소비", fmtNum(vol.range_contraction_ratio))}
        ${row("최근 압축", yesno(vol.recent_atr_compression_pass))}
        ${row("변동성 등급", esc(vol.volatility_contraction_grade || "-"))}
        ${row("VCP 3단(R1/R2/R3)", `${fmtPct(v.vcp_range_1,0)} / ${fmtPct(v.vcp_range_2,0)} / ${fmtPct(v.vcp_range_3,0)}`)}
        ${row("VCP 통과/점수", `${yesno(v.vcp_pattern_pass)} · ${fmtNum(v.vcp_score)}`)}
      </div>
      <div class="d-card"><h4>거래량 / 섹터</h4>
        ${row("Dry-up (10/50)", `${fmtNum(vd.volume_dry_up_ratio)} ${yesno(vd.volume_dry_up_pass)}`)}
        ${row("베이스 후반 감소", yesno(vd.base_volume_fade_pass))}
        ${row("대량 하락일(20d)", vd.high_volume_down_days_20d ?? "-")}
        ${row("A/D 점수", fmtNum(vd.accumulation_distribution_score))}
        ${row("섹터 ETF", esc(s.sector_etf || "-"))}
        ${row("섹터 3M / 종목-섹터", `${fmtPct(s.sector_return_3m)} / ${fmtPct(s.sector_detail?.stock_vs_sector_3m)}`)}
        ${row("섹터 점수", fmtNum(s.sector_action_score))}
      </div>
      <div class="d-card"><h4>In-Base 건전도 (분출 전 · 유형)</h4>
        ${row("In-Base 점수", `${fmtNum(s.inbase_score, 0)} (${esc(s.inbase_grade || "-")})`)}
        ${row("베타 / 추력(vigor)", `β ${fmtNum(s.beta, 2)} · vigor ${fmtNum(s.vigor, 2)}`)}
        ${row("베이스 유형", (BASETYPE[s.base_type] || BASETYPE.none)[0])}
        ${row("분출 여부", `${s.extended ? "✗ 분출" : "✓ 베이스 중"}${(s.extension_flags || []).length ? " · " + esc(s.extension_flags.join(", ")) : ""}`)}
        ${row("단기 5일/10일", `${fmtPct(s.ret_5d)} / ${fmtPct(s.ret_10d)}`)}
        ${row("최근10일 변동폭", fmtPct(s.recent_range_10, 1))}
        ${row("베이스 내 위치", s.base_position == null ? "-" : (s.base_position * 100).toFixed(0) + "%")}
      </div>
    </div>`;
}

// ---------- chart ----------
function sma(arr, n) {
  const out = new Array(arr.length).fill(null);
  let run = 0;
  for (let i = 0; i < arr.length; i++) {
    run += arr[i];
    if (i >= n) run -= arr[i - n];
    if (i >= n - 1) out[i] = run / n;
  }
  return out;
}

async function fetchChart(ticker) {
  if (STATIC) {
    const res = await fetch(`../data/chart/${encodeURIComponent(ticker)}.json`, { cache: "no-store" });
    if (res.ok) return res.json();
    // Not pre-built — fall back to the hosted backend if one is configured.
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

function openChart(ticker) {
  currentTicker = ticker;
  currentRec = STOCKS.find((s) => s.ticker === ticker) || {};
  $("#chart-ticker").textContent = ticker;
  $("#chart-company").textContent = currentRec.company_name || "";
  $("#chart-external").href = `https://finance.yahoo.com/quote/${encodeURIComponent(ticker)}`;
  { const cw = $("#chart-watch"); if (cw) cw.textContent = WATCH.has(ticker) ? "★" : "☆"; }
  $("#score-panel").innerHTML = scorePanel(currentRec);
  $("#detail-panel").innerHTML = detailPanel(currentRec);

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
      area.innerHTML = `<div class="error">차트 데이터가 없습니다. Yahoo 링크로 확인해 주세요.</div>`;
      return;
    }
    chartData = d;
    area.innerHTML = "";
    plotChart(area, d);
  } catch (e) {
    area.innerHTML = `<div class="error">차트를 불러오지 못했습니다.<br><small>${esc(e.message)}</small></div>`;
  }
}

function maTrace(x, y, name, color, dash) {
  return { x, y, name, type: "scatter", mode: "lines",
    line: { color, width: 1.3, dash: dash || "solid" }, connectgaps: false,
    xaxis: "x", yaxis: "y" };
}

function overlayShapes(d, rec) {
  const shapes = [];
  const n = d.dates.length;
  const idxOf = (date, fallback) => {
    const i = d.dates.indexOf(date);
    return i >= 0 ? i : fallback;
  };
  const b = rec.base || {}, p = rec.pivot || {};
  // Base window shading.
  if (b.base_length_days) {
    let endI = idxOf(b.base_end_date, n - 1);
    let startI = idxOf(b.base_start_date, Math.max(0, endI - (b.base_length_days - 1)));
    shapes.push({ type: "rect", xref: "x", yref: "paper",
      x0: startI - 0.5, x1: endI + 0.5, y0: 0, y1: 1,
      fillcolor: "rgba(56,189,248,0.08)", line: { width: 0 }, layer: "below" });
  }
  const hline = (y, color, dash) => shapes.push({
    type: "line", xref: "paper", yref: "y", x0: 0, x1: 1, y0: y, y1: y,
    line: { color, width: 1, dash: dash || "dot" } });
  if (b.base_high != null) hline(b.base_high, "rgba(148,163,184,.7)");
  if (b.base_low != null) hline(b.base_low, "rgba(148,163,184,.5)");
  if (p.pivot_price != null) hline(p.pivot_price, "#f59e0b", "dash");
  return shapes;
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

  const c = d.close;
  const traces = [
    volume, candles,
    maTrace(x, sma(c, 50), "SMA50", "#a855f7"),
    maTrace(x, sma(c, 150), "SMA150", "#38bdf8"),
    maTrace(x, sma(c, 200), "SMA200", "#ef4444"),
  ];
  const layout = {
    paper_bgcolor: "#1e293b", plot_bgcolor: "#1e293b",
    font: { color: "#e2e8f0", size: 11 },
    showlegend: false, margin: { l: 55, r: 18, t: 8, b: 28 },
    dragmode: "pan",
    shapes: overlayShapes(d, currentRec),
    xaxis: { type: "category", gridcolor: "#334155", domain: [0, 1], anchor: "y",
             nticks: 8, rangeslider: { visible: false } },
    yaxis: { domain: [0.24, 1], gridcolor: "#334155", title: "가격", side: "right" },
    yaxis2: { domain: [0, 0.18], gridcolor: "#334155", title: "거래량", side: "right" },
  };
  Plotly.newPlot("chart-area", traces, layout,
    { responsive: true, scrollZoom: true, displaylogo: false,
      modeBarButtonsToRemove: ["select2d", "lasso2d"] });
  document.getElementById("chart-area").on("plotly_relayout", (ev) => rescaleY(ev));

  const n = d.dates.length;
  const win = Math.min(160, n);
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
  if (ev["xaxis.autorange"] || ev["autosize"]) { lo = 0; hi = n - 1; }
  else if (ev["xaxis.range[0]"] !== undefined) {
    lo = Math.floor(ev["xaxis.range[0]"]); hi = Math.ceil(ev["xaxis.range[1]"]);
  } else if (Array.isArray(ev["xaxis.range"])) {
    lo = Math.floor(ev["xaxis.range"][0]); hi = Math.ceil(ev["xaxis.range"][1]);
  } else return;
  setYForWindow(lo, hi);
}

// ---------- divider drag ----------
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
    const w = Math.min(Math.max(window.innerWidth - e.clientX, 320), window.innerWidth - 200);
    pane.style.width = w + "px";
  });
  window.addEventListener("mouseup", () => {
    if (!dragging) return;
    dragging = false; divider.classList.remove("dragging");
    document.body.style.userSelect = "";
    if (chartData) Plotly.Plots.resize("chart-area");
  });
})();

// ---------- CSV export ----------
function exportCsv() {
  const rows = filtered();
  const cols = ["ticker", "company_name", "sector", "industry", "sector_etf",
    "is_ipo", "history_days",
    "current_price", "market_cap", "avg_dollar_volume_20d", "total_score", "setup_grade",
    "trend_template_pass", "rs_percentile", "rs_vs_spy_3m", "rs_vs_qqq_3m",
    "base_start_date", "base_length_days", "base_depth", "pivot_price", "distance_to_pivot",
    "pivot_status", "atr_contraction_ratio", "volume_dry_up_ratio", "high_volume_down_days_20d",
    "sector_action_score", "alert_type", "notes"];
  const get = (s, k) => {
    switch (k) {
      case "base_start_date": return s.base?.base_start_date;
      case "base_length_days": return s.base?.base_length_days;
      case "base_depth": return s.base?.base_depth;
      case "pivot_price": return s.pivot?.pivot_price;
      case "distance_to_pivot": return s.pivot?.distance_to_pivot;
      case "pivot_status": return s.pivot?.pivot_status;
      case "atr_contraction_ratio": return s.volatility?.atr_contraction_ratio;
      case "volume_dry_up_ratio": return s.volume?.volume_dry_up_ratio;
      case "high_volume_down_days_20d": return s.volume?.high_volume_down_days_20d;
      default: return s[k];
    }
  };
  const q = (v) => v == null ? "" : `"${String(v).replace(/"/g, '""')}"`;
  const csv = [cols.join(",")].concat(
    rows.map((s) => cols.map((k) => q(get(s, k))).join(","))).join("\n");
  const blob = new Blob(["﻿" + csv], { type: "text/csv;charset=utf-8" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `base_screen_${new Date().toISOString().slice(0, 10)}.csv`;
  a.click();
  URL.revokeObjectURL(a.href);
}

// ---------- events ----------
$("#refresh-btn").addEventListener("click", load);
$("#csv-btn").addEventListener("click", exportCsv);
$("#watch-btn").addEventListener("click", () => { watchOnly = !watchOnly; $("#watch-btn").classList.toggle("on", watchOnly); render(); });
$("#chart-watch").addEventListener("click", () => { if (currentTicker) toggleWatch(currentTicker); });
$("#chart-close").addEventListener("click", closeChart);
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeChart(); });
window.addEventListener("resize", () => { if (chartData) Plotly.Plots.resize("chart-area"); });
["f-grade", "f-pivot", "f-alert", "f-sector", "f-ipo", "f-etf"].forEach((id) =>
  $("#" + id).addEventListener("change", render));
$("#f-search").addEventListener("input", render);
$("#f-score").addEventListener("input", () => { $("#f-score-val").textContent = $("#f-score").value; render(); });

window.openChart = openChart;

// ---------- cross-device watchlist sync (☁ button) ----------
if (window.SUHSync) {
  SUHSync.mount("base", {
    container: document.querySelector(".controls"),
    getList: () => [...WATCH],
    setList: (arr) => {
      WATCH = new Set(arr);
      localStorage.setItem(WATCH_KEY, JSON.stringify([...WATCH]));
      render();
    },
  });
}

// ---------- hover tooltips for indicator labels ----------
// One shared tooltip on <body> that follows the cursor, so it never gets
// clipped by the scrolling panel and disappears the moment the cursor leaves.
(function setupTooltips() {
  const tip = document.createElement("div");
  tip.className = "tip hidden";
  document.body.appendChild(tip);
  const place = (e) => {
    const pad = 14, w = tip.offsetWidth, h = tip.offsetHeight;
    let x = e.clientX + pad, y = e.clientY + pad;
    if (x + w > window.innerWidth - 8) x = e.clientX - w - pad;
    if (y + h > window.innerHeight - 8) y = e.clientY - h - pad;
    tip.style.left = Math.max(8, x) + "px";
    tip.style.top = Math.max(8, y) + "px";
  };
  document.addEventListener("mouseover", (e) => {
    const t = e.target.closest && e.target.closest(".term");
    if (!t || !t.dataset.tip) return;
    tip.textContent = t.dataset.tip;
    tip.classList.remove("hidden");
    place(e);
  });
  document.addEventListener("mousemove", (e) => {
    if (!tip.classList.contains("hidden")) place(e);
  });
  document.addEventListener("mouseout", (e) => {
    if (e.target.closest && e.target.closest(".term")) tip.classList.add("hidden");
  });
})();

load();
