"use strict";

const $ = (sel) => document.querySelector(sel);

// Two run modes (see config.js):
//   STATIC=false -> live FastAPI backend (/api/flat, /api/chart)
//   STATIC=true  -> pre-built daily JSON in ../data/flat.json + ../data/chart/*
const STATIC = !!window.SUH_DH_STATIC;
const BUILT = window.SUH_DH_BUILT || null;
const API_BASE = (window.SUH_DH_API_BASE || "").replace(/\/+$/, "");

let STOCKS = [];
let META = {};
let sortKey = "flatness_score";
let sortDir = -1;
let currentTicker = null;
let currentRec = null;
let chartData = null;
let suppressRelayout = false;
let watchOnly = false;
const WATCH_KEY = "suh_flat_watch";
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
    // Static: read flat.json from the repo's raw copy (freshest committed),
    // falling back to the deployed snapshot — see shared/data-source.js.
    const res = STATIC ? await SUHData.fetch("flat.json", true)
                       : await fetch("/api/flat", { cache: "no-store" });
    const data = await res.json();
    if (!res.ok || data.error) {
      renderError(data.error || "데이터를 불러오지 못했습니다.", data.detail);
      return;
    }
    STOCKS = data.stocks || [];
    META = data;
    $("#demo-badge").classList.toggle("hidden", !data.demo);
    render();
    const when = STATIC ? (data.built ? new Date(data.built).toLocaleString("ko-KR") : "최근")
                        : new Date().toLocaleTimeString("ko-KR");
    const extra = data.insufficient ? ` · 데이터부족 ${data.insufficient}` : "";
    $("#status").textContent =
      `${data.count}개 평평 베이스 (유니버스 ${data.universe_size}${extra}) · ${STATIC ? "갱신 " + when + " · 매일 자동" : "업데이트 " + when}`;
  } catch (e) {
    renderError("데이터를 불러오지 못했습니다", e.message);
  }
}

function renderError(msg, detail) {
  $("#content").innerHTML =
    `<div class="error"><b>${esc(msg)}</b>${detail ? "<br><small>" + esc(detail) + "</small>" : ""}</div>`;
  $("#status").textContent = "오류";
}

// ---------- filtering + sorting ----------
function filtered() {
  const minScore = +$("#f-score").value;
  const inclChronic = $("#f-chronic").checked;
  const inclReit = $("#f-reit").checked;
  const inclUnaccepted = $("#f-unaccepted").checked;
  const setupOnly = $("#f-setup").checked;
  const etfOnly = $("#f-etf-only") ? $("#f-etf-only").checked : false;
  const etfEx = $("#f-etf-ex") ? $("#f-etf-ex").checked : false;
  const q = $("#f-search").value.trim().toUpperCase();

  let rows = STOCKS.filter((s) => {
    if ((s.flatness_score ?? 0) < minScore) return false;
    if (!inclChronic && s.chronically_low_vol) return false;
    if (!inclReit && s.is_reit) return false;
    // 조정·바닥 유형은 평평도 문턱(§8)에 못 미쳐 '미달'이어도 절대 숨기지 않음
    // (우리가 찾는 모양이라 기본 화면에 항상 노출). 평평 유형만 미달 숨김 유지.
    if (!inclUnaccepted && s.accepted === false &&
        s.position_type !== "조정" && s.position_type !== "바닥") return false;
    if (etfOnly && !s.is_etf) return false;
    if (etfEx && !etfOnly && s.is_etf) return false;
    if (setupOnly && !s.setup_pass) return false;
    if (watchOnly && !WATCH.has(s.ticker)) return false;
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

function sortVal(s, key) { return s[key]; }

// ---------- Excel-style per-column filters ----------
// Each filterable column is either "num" (≥/≤ range, entered in the DISPLAYED
// unit — stored = entered/scale) or "cat" (checklist of the values present).
const COL_FILTER = {
  flatness_score:    { type: "num", scale: 1, unit: "점" },
  composite_score:   { type: "num", scale: 1, unit: "점" },
  setup_score:       { type: "num", scale: 1, unit: "점" },
  flatness_grade:    { type: "cat", label: (v) => v },
  position_type:     { type: "cat", label: (v) => v },
  base_category:     { type: "cat", label: (v) => CAT_SHORT[v] || v },
  base_status:       { type: "cat", label: (v) => STATUS_SHORT[v] || v },
  base_days:         { type: "cat", label: (v) => v + "d", numericSort: true },
  close_band:        { type: "num", scale: 100, unit: "%" },
  base_drift:        { type: "num", scale: 100, unit: "%" },
  containment_ratio: { type: "num", scale: 100, unit: "%" },
  current_position:  { type: "num", scale: 100, unit: "%" },
  historical_activity_pass: { type: "cat", label: (v) => (v ? "통과" : "미달") },
  current_price:     { type: "num", scale: 1, unit: "$" },
  market_cap:        { type: "num", scale: 1e-9, unit: "B" },
  rs_percentile:     { type: "num", scale: 1, unit: "" },
  beta:              { type: "num", scale: 1, unit: "" },
  sector:            { type: "cat", label: (v) => v },
};
let colFilters = {};   // key -> {min,max} (num) or {allowed:[...]} (cat)

function colFilterActive(key) {
  const f = colFilters[key], meta = COL_FILTER[key];
  if (!f || !meta) return false;
  return meta.type === "num" ? (f.min != null || f.max != null)
                             : !!(f.allowed && f.allowed.length);
}
function anyColFilter() { return Object.keys(colFilters).some(colFilterActive); }

function catValue(s, key) { return key === "historical_activity_pass" ? !!s[key] : s[key]; }

function passColFilters(s) {
  for (const key in colFilters) {
    const meta = COL_FILTER[key];
    if (!meta || !colFilterActive(key)) continue;
    const f = colFilters[key];
    if (meta.type === "num") {
      const sc = meta.scale || 1, v = s[key];
      if (f.min != null && !(v != null && v >= f.min / sc)) return false;
      if (f.max != null && !(v != null && v <= f.max / sc)) return false;
    } else {
      const v = catValue(s, key);
      if (!f.allowed.some((a) => String(a) === String(v))) return false;
    }
  }
  return true;
}

function colDistinct(key) {
  const meta = COL_FILTER[key], set = new Set();
  STOCKS.forEach((s) => {
    const v = catValue(s, key);
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

// ---------- render table ----------
const GRADE_CLS = { "Very Flat": "g-prime", "Flat": "g-high",
                    "Moderately Flat": "g-watch", "Not Flat": "g-low" };
const CAT_CLS = { "Continuation Flat Base": "bt-flat", "Neutral Flat Base": "bt-base",
                  "Turnaround Flat Base": "bt-tight" };
// Base-position type (200-day MA based): ①조정 pullback / ②바닥 bottom / ③평평 flat.
const POSITION_CLS = { "조정": "bt-flat", "바닥": "bt-tight", "평평": "g-low" };
const CAT_SHORT = { "Continuation Flat Base": "Continuation", "Neutral Flat Base": "Neutral",
                    "Turnaround Flat Base": "Turnaround" };
const STATUS_CLS = { "Active Flat Base": "p-ready", "Exited Upward": "p-extended",
                     "Exited Downward": "p-broken", "Unknown": "" };
const STATUS_SHORT = { "Active Flat Base": "Active", "Exited Upward": "Exited↑",
                       "Exited Downward": "Exited↓", "Unknown": "-" };
const COLS = [
  ["ticker", "티커", false],
  ["flatness_score", "Flatness", true],
  ["composite_score", "종합", true],
  ["setup_score", "셋업", true],
  ["flatness_grade", "등급", false],
  ["position_type", "유형", false],
  ["base_status", "상태", false],
  ["base_days", "기간", true],
  ["close_band", "CloseBand", true],
  ["base_drift", "Drift", true],
  ["containment_ratio", "밀집도", true],
  ["current_position", "위치", true],
  ["historical_activity_pass", "활동성", false],
  ["current_price", "가격", true],
  ["market_cap", "시총", true],
  ["rs_percentile", "RS%", true],
  ["beta", "β", true],
  ["sector", "섹터", false],
];

function render() {
  const rows = filtered();
  $("#count-badge").textContent = `${rows.length}종목`;
  $("#watch-count").textContent = WATCH.size;
  if (!rows.length) {
    $("#content").innerHTML = `<div class="loading">조건에 맞는 종목이 없습니다. 필터를 완화해 보세요.</div>`;
    return;
  }
  const head = COLS.map(([k, label, num]) => {
    const arrow = sortKey === k ? (sortDir === -1 ? " ▾" : " ▴") : "";
    const fic = COL_FILTER[k]
      ? `<span class="col-filter${colFilterActive(k) ? " on" : ""}" data-fkey="${esc(k)}" title="열 필터">⏷</span>` : "";
    return `<th class="${num ? "num" : ""} sortable" data-key="${k}">${label}${arrow}${fic}</th>`;
  }).join("");

  const body = rows.map((s) => {
    const g = GRADE_CLS[s.flatness_grade] || "";
    const cat = CAT_CLS[s.base_category] || "";
    const st = STATUS_CLS[s.base_status] || "";
    const star = WATCH.has(s.ticker) ? "★" : "☆";
    return `<tr data-ticker="${esc(s.ticker)}">
      <td class="tk">
        <button class="star" data-star="${esc(s.ticker)}" title="관심종목">${star}</button>
        <button class="ticker-link" onclick="openChart('${esc(s.ticker)}')">${esc(s.ticker)}</button>${s.is_etf ? ' <span class="badge bt-flat">ETF</span>' : ""}${s.is_reit ? ' <span class="badge bt-base">REIT</span>' : ""}${s.accepted === false ? ' <span class="ext-mark" title="' + esc(s.exclude_reason || "기준 미달") + '">미달</span>' : ""}
        <div class="company">${esc(s.company_name || "")}</div>
      </td>
      <td class="num score"><b>${fmtNum(s.flatness_score, 0)}</b></td>
      <td class="num"><b>${fmtNum(s.composite_score, 0)}</b></td>
      <td class="num${s.setup_pass ? "" : " lowbeta"}">${fmtNum(s.setup_score, 0)}${s.setup_pass ? " ✓" : ""}</td>
      <td><span class="badge ${g}">${esc(s.flatness_grade || "-")}</span></td>
      <td>${s.position_type ? `<span class="badge ${POSITION_CLS[s.position_type] || ""}">${esc(s.position_type)}</span>` : "-"}</td>
      <td><span class="badge ${st}">${esc(STATUS_SHORT[s.base_status] || s.base_status || "-")}</span></td>
      <td class="num">${s.base_days ?? "-"}d</td>
      <td class="num">${fmtPct(s.close_band, 1)}</td>
      <td class="num">${fmtPct(s.base_drift, 1)}</td>
      <td class="num">${fmtPct(s.containment_ratio, 0)}</td>
      <td class="num">${s.current_position == null ? "-" : (s.current_position * 100).toFixed(0) + "%"}</td>
      <td>${s.historical_activity_pass ? "✓" : (s.chronically_low_vol ? '<span class="lowbeta">저변동</span>' : "✗")}</td>
      <td class="num">${fmtPrice(s.current_price)}</td>
      <td class="num">${fmtCap(s.market_cap)}</td>
      <td class="num">${fmtNum(s.rs_percentile, 0)}</td>
      <td class="num${s.beta != null && s.beta < 0.8 ? " lowbeta" : ""}">${fmtNum(s.beta, 2)}</td>
      <td class="etf">${esc(s.sector || "-")}</td>
    </tr>`;
  }).join("");

  $("#content").innerHTML = `<table class="screen">
    <thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;

  document.querySelectorAll("th.sortable").forEach((th) =>
    th.addEventListener("click", () => {
      const k = th.dataset.key;
      if (sortKey === k) sortDir *= -1;
      else { sortKey = k; sortDir = (k === "ticker" || k === "sector") ? 1 : -1; }
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
  if (window.SUHSync) SUHSync.record("flat", ticker, WATCH.has(ticker));   // timestamped cloud sync
  render();
  if (currentTicker === ticker) $("#chart-watch").textContent = WATCH.has(ticker) ? "★" : "☆";
}

// ---------- indicator glossary (hover tooltips) ----------
const GLOSSARY = {
  "Flatness Score": "현재 베이스가 얼마나 평평한지만 재는 0~100점. Close Band(35)+회귀기울기(25)+밀집도(20)+전후반안정(10)+이상치(10). 거래량·RS·섹터·펀더멘털은 절대 포함하지 않음.",
  "Close Band": "(종가 Q90 − Q10) / 종가 중앙값. 하루짜리 꼬리 영향을 줄이려 고저가 대신 종가 분위수 사용. 작을수록 좁고 평평.",
  "Raw High-Low": "(기간 최고가 − 최저가) / 종가 중앙값. 참고용이며 점수엔 안 들어감(꼬리 때문에 노이즈).",
  "Base Drift": "베이스 로그종가 회귀선 기준, 시작→끝 가격중심 이동률 = exp(기울기×(일수−1))−1. |값|이 작을수록 수평.",
  "Containment": "종가가 중앙값 ±7.5% 안에 있던 거래일 비율. 높을수록 중심에 밀집.",
  "Center Shift": "후반부 종가중앙값 / 전반부 종가중앙값 − 1의 절대값. 밴드가 좁아도 중심이 계속 움직이면 평평으로 안 봄.",
  "Outlier Ratio": "일간 종가수익률 |값|이 8%↑인 날의 비율. 하루이틀은 허용, 반복되는 급등락은 제외.",
  "일간변동": "베이스 구간의 평균 일간 |수익률|. 0.5% 미만이면 '정지/딜 고정'(M&A 딜 가격에 붙어 거의 안 움직임)으로 보고 결과에서 제외. 정상적인 조용한 횡보는 보통 1~2%.",
  "Current Position": "현재가가 베이스 밴드(Q10~Q90) 중 어디인지. 0%=하단, 100%=상단. 점수엔 미포함.",
  "Base Status": "Active(밴드 유지) / Exited↑(상단 +3% 초과 이탈) / Exited↓(하단 −3% 미만 이탈).",
  "Base Category": "이전 추세 태그(점수 무관). Continuation=베이스 직전 +20%↑ 상승 / Turnaround=−20%↓ 하락 / Neutral=그 사이.",
  "대표 이전수익률": "베이스 시작 직전 60일·120일 수익률 중 절대값이 큰 값. +20%↑ Continuation, −20%↓ Turnaround.",
  "과거활동성(Historical Activity)": "REIT·죽은 주식 배제용. 베이스 이전 데이터만 사용. 이전120일 CloseBand≥20% OR 과거252일 내 최대|20/60일 수익률|≥15% OR 이전252일밴드≥현재밴드×1.5 중 하나면 통과. 방향은 안 따짐.",
  "Base Distinctness": "이전 252일 CloseBand / 현재 베이스 CloseBand. 과거가 지금보다 얼마나 넓었는지. 1.5↑면 베이스가 뚜렷.",
  "만성 저변동성": "이전252일밴드<20% + 최대20일수익<12% + 최대60일수익<12% + Distinctness<1.3 을 모두 만족하는 원래 안 움직이는 종목. 기본 제외.",
  "미달": "카테고리별 추가기준(§8) 미충족. Continuation은 20일·70점, Neutral/Turnaround는 40일·80점·밀집85%·드리프트5%·중심5%·활동성통과 필요. 단, 유형이 조정·바닥이면 미달이어도 기본 화면에 항상 표시(우리가 찾는 모양이라). 평평 유형만 기본 숨김이며 '미달 후보 포함'을 켜야 보임.",
  "유형(위치)": "베이스가 200일선 어디에 있나로 분류. ①조정=200일선 위(2~3일 이탈 허용)+200 상승+직전 저점→고점 40%↑ 폭등 후 조정(길이별 15/20/25%). ②바닥=200일선 아래+후반 신저가 없음(칼날 배제). ③평평=나머지(조정 얕음·상승 없음, 제일 많음). 유형 열의 ⏷로 골라볼 수 있음.",
  "직전상승 / 조정": "직전상승=베이스 직전 1년 내 저점→고점 상승폭(폭발력). 조정=그 고점 대비 베이스 중앙값이 눌린 폭. ①조정 유형은 상승 40%↑ + 조정 15~25%↑ 필요.",
  "셋업(추세/이평선)": "평평도와 완전히 별개인 '자리 품질' 점수(0~100). 유형(조정/바닥) 안에서 얼마나 좋은 자리인지 순위용. 구성: 이평상승(30)+정배열/회복(22)+이평지지(22)+준비도(18)+고점근접(8). 방향(추세지속/바닥반전) 구분은 이제 '유형' 열이 담당하고, 셋업은 순수 품질만 잼. 갓 눌린 조정 베이스는 고점서 멀어 점수가 낮게 나오지만(그래서 통과 여부는 점수와 무관), 회복이 진행될수록 점수가 오름. '셋업 통과만' 필터 = 유형이 조정·바닥이고 아직 돌파(연장) 안 한 것.",
  "베이스 상단 대비": "현재가 ÷ 베이스 상단(Q90) − 1. 0% 부근 = 베이스 상단서 조이는 중(이상적). 조정은 +3%, 바닥은 +12% 초과면 '이미 돌파해 뻗음' → 셋업 통과 제외. 준비도(readiness) 점수도 이때 감소.",
  "종합점수": "평평도 점수 × 0.5 + 셋업 점수 × 0.5. '평평하면서도 좋은 자리'를 한 번에 정렬하려는 참고 지표. 열 머리글을 눌러 이걸로 정렬 가능.",
  "RS%": "스캔 유니버스 내 12개월 수익률 백분위(참고용, 점수 무관).",
  "β": "최근 1년 일간수익률의 시장(SPY) 대비 베타(참고용, 평탄도 점수엔 미포함). <1이면 시장보다 덜 움직이는 저변동, >1이면 더 크게 움직임. 0.8 미만은 강조 표시.",
};
function term(label) {
  const tip = GLOSSARY[label];
  return tip ? `<span class="term" data-tip="${esc(tip)}">${esc(label)}</span>` : esc(label);
}

// ---------- score / detail panels ----------
function scorePanel(s) {
  const parts = [
    ["Close Band", s.range_score, 35], ["Base Drift", s.slope_score, 25],
    ["Containment", s.containment_score, 20], ["Center Shift", s.center_score, 10],
    ["Outlier Ratio", s.outlier_score, 10],
  ];
  const bars = parts.map(([name, val, max]) => {
    const pct = max ? Math.max(0, Math.min(100, (val / max) * 100)) : 0;
    return `<div class="sbar">
      <span class="sbar-name">${term(name)}</span>
      <span class="sbar-track"><span class="sbar-fill" style="width:${pct}%"></span></span>
      <span class="sbar-val">${fmtNum(val, 0)}/${max}</span>
    </div>`;
  }).join("");
  return `<div class="score-total">${term("Flatness Score")} <b>${fmtNum(s.flatness_score, 0)}</b>
      <span class="badge ${GRADE_CLS[s.flatness_grade] || ""}">${esc(s.flatness_grade)}</span>
      ${s.base_category ? `<span class="badge ${CAT_CLS[s.base_category] || ""}">${esc(CAT_SHORT[s.base_category] || "")}</span>` : ""}
      <span class="badge ${STATUS_CLS[s.base_status] || ""}">${esc(STATUS_SHORT[s.base_status] || "")}</span>
    </div>${bars}`;
}

function detailPanel(s) {
  const yesno = (x) => x === true ? "✓" : x === false ? "✗" : "—";
  const row = (k, val) => `<div class="d-row"><span>${term(k)}</span><span>${val}</span></div>`;
  return `
    <div class="d-grid">
      <div class="d-card"><h4>베이스 평평도</h4>
        ${row("구간", `${esc(s.base_start_date || "-")} ~ ${esc(s.base_end_date || "-")} (${s.base_days ?? "-"}d)`)}
        ${row("Close Band", fmtPct(s.close_band, 1))}
        ${row("Raw High-Low", fmtPct(s.raw_high_low_range, 1))}
        ${row("Base Drift", fmtPct(s.base_drift, 1))}
        ${row("Containment", fmtPct(s.containment_ratio, 0))}
        ${row("Center Shift", fmtPct(s.center_shift, 1))}
        ${row("Outlier Ratio", `${fmtPct(s.outlier_ratio, 1)} (${s.outlier_days ?? 0}일)`)}
        ${row("일간변동", s.base_daily_vol == null ? "-" : (s.base_daily_vol * 100).toFixed(2) + "%")}
        ${row("Current Position", s.current_position == null ? "-" : (s.current_position * 100).toFixed(0) + "%")}
      </div>
      <div class="d-card"><h4>상태 / 유형</h4>
        ${row("Base Status", esc(s.base_status || "-"))}
        ${row("유형(위치)", `${esc(s.position_type || "-")} · 200위 ${s.position_above_200_frac == null ? "-" : Math.round(s.position_above_200_frac * 100) + "%"}`)}
        ${row("직전상승 / 조정", `${fmtPct(s.prior_run_up)} / ${fmtPct(s.base_correction)}`)}
        ${row("Base Category", esc(s.base_category || "-"))}
        ${row("밴드 Q10 / 중앙 / Q90", `${fmtPrice(s.base_low_q10)} / ${fmtPrice(s.base_median)} / ${fmtPrice(s.base_high_q90)}`)}
        ${row("이전 60일 / 120일", `${fmtPct(s.prior_60d_return)} / ${fmtPct(s.prior_120d_return)}`)}
        ${row("대표 이전수익률", fmtPct(s.representative_prior_return))}
        ${row("미달", s.accepted === false ? `✗ ${esc(s.exclude_reason || "")}` : "✓ 통과")}
      </div>
      <div class="d-card"><h4>${term("셋업(추세/이평선)")} (점수 무관)</h4>
        ${row("셋업 점수 / 통과", `${fmtNum(s.setup_score, 0)} ${s.setup_pass ? "✓ 통과" : "✗"}`)}
        ${row("종합점수", `${fmtNum(s.composite_score, 0)} (평평×0.5 + 셋업×0.5)`)}
        ${row("SMA 50 / 150 / 200", `${fmtPrice(s.sma50)} / ${fmtPrice(s.sma150)} / ${fmtPrice(s.sma200)}`)}
        ${row("이평 기울기 50/150/200", `${fmtPct(s.sma50_slope, 1)} / ${fmtPct(s.sma150_slope, 1)} / ${fmtPct(s.sma200_slope, 1)}`)}
        ${row("가격 vs 50/150/200", `${yesno(s.above_sma50)}/${yesno(s.above_sma150)}/${yesno(s.above_sma200)}`)}
        ${row("정배열 / 200일 회복", `${yesno(s.ma_aligned)} / ${yesno(s.reclaimed_sma200)}`)}
        ${row("베이스 상단 대비", `${fmtPct(s.above_base, 1)}${s.extended ? " ⚠ 돌파연장" : ""}`)}
        ${row("52주 고점 / 저점 대비", `${fmtPct(s.dist_52w_high, 0)} / ${fmtPct(s.dist_52w_low, 0)}`)}
      </div>
      <div class="d-card"><h4>과거활동성 (점수 무관)</h4>
        ${row("과거활동성(Historical Activity)", `${yesno(s.historical_activity_pass)}${s.historical_activity_insufficient ? " (데이터부족)" : ""}`)}
        ${row("이전 120일 CloseBand", fmtPct(s.prior_120_close_band, 1))}
        ${row("이전 252일 CloseBand", fmtPct(s.prior_252_close_band, 1))}
        ${row("최대 |20일| / |60일|", `${fmtPct(s.max_abs_20d_return, 0)} / ${fmtPct(s.max_abs_60d_return, 0)}`)}
        ${row("Base Distinctness", `${fmtNum(s.base_distinctness, 2)}×`)}
        ${row("만성 저변동성", yesno(s.chronically_low_vol))}
      </div>
      <div class="d-card"><h4>기본정보 · 상위 후보기간</h4>
        ${row("Security Type", esc(s.security_type || "-"))}
        ${row("섹터 / 산업", `${esc(s.sector || "-")} / ${esc(s.industry || "-")}`)}
        ${row("가격 / 시총", `${fmtPrice(s.current_price)} / ${fmtCap(s.market_cap)}`)}
        ${row("평균 거래대금(20d)", s.avg_dollar_volume_20d == null ? "-" : "$" + fmtCap(s.avg_dollar_volume_20d))}
        ${row("RS%", fmtNum(s.rs_percentile, 0))}
        ${row("β", fmtNum(s.beta, 2))}
        ${row("상위 후보기간", (s.candidate_periods || []).map((c) =>
            `${c.base_days}d:${fmtNum(c.flatness_score, 0)}${c.accepted ? "" : "*"}`).join(" · ") || "-")}
      </div>
    </div>`;
}

// ---------- chart ----------
function olsLine(closes, lo, hi) {
  // OLS on log(close) over [lo,hi]; return fitted price at each index (or null).
  const out = new Array(closes.length).fill(null);
  const xs = [], ys = [];
  for (let i = lo; i <= hi; i++) {
    if (closes[i] > 0) { xs.push(i); ys.push(Math.log(closes[i])); }
  }
  const n = xs.length;
  if (n < 3) return out;
  const xm = xs.reduce((a, b) => a + b, 0) / n;
  const ym = ys.reduce((a, b) => a + b, 0) / n;
  let num = 0, den = 0;
  for (let i = 0; i < n; i++) { num += (xs[i] - xm) * (ys[i] - ym); den += (xs[i] - xm) ** 2; }
  if (den <= 0) return out;
  const slope = num / den, intercept = ym - slope * xm;
  for (let i = lo; i <= hi; i++) out[i] = Math.exp(slope * i + intercept);
  return out;
}

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

function openChart(ticker) {
  currentTicker = ticker;
  currentRec = STOCKS.find((s) => s.ticker === ticker) || {};
  $("#chart-ticker").textContent = ticker;
  $("#chart-company").textContent = currentRec.company_name || "";
  $("#chart-external").href = `https://finance.yahoo.com/quote/${encodeURIComponent(ticker)}`;
  $("#chart-watch").textContent = WATCH.has(ticker) ? "★" : "☆";
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

function baseWindowIdx(d, rec) {
  const n = d.dates.length;
  let endI = d.dates.indexOf(rec.base_end_date);
  if (endI < 0) endI = n - 1;
  let startI = d.dates.indexOf(rec.base_start_date);
  if (startI < 0) startI = Math.max(0, endI - ((rec.base_days || 1) - 1));
  return { startI, endI };
}

function overlayTraces(d, rec) {
  const { startI, endI } = baseWindowIdx(d, rec);
  const x = d.dates;
  const traces = [];
  // Regression trend line over the base window (exact OLS on log close).
  const fit = olsLine(d.close, startI, endI);
  traces.push({ x, y: fit, name: "회귀선", type: "scatter", mode: "lines",
    line: { color: "#38bdf8", width: 1.6, dash: "solid" }, connectgaps: false,
    xaxis: "x", yaxis: "y" });
  // First-half / second-half median segments.
  const half = Math.floor((endI - startI + 1) / 2);
  const seg = (lo, hi, val, color) => {
    if (val == null || hi < lo) return;
    const y = new Array(d.dates.length).fill(null);
    for (let i = lo; i <= hi; i++) y[i] = val;
    traces.push({ x, y, name: "중간값", type: "scatter", mode: "lines",
      line: { color, width: 1.2, dash: "dot" }, connectgaps: false, showlegend: false,
      xaxis: "x", yaxis: "y" });
  };
  const firstMed = median(d.close.slice(startI, startI + half));
  const secondMed = median(d.close.slice(endI - half + 1, endI + 1));
  seg(startI, startI + half - 1, firstMed, "rgba(250,204,21,.8)");
  seg(endI - half + 1, endI, secondMed, "rgba(250,204,21,.8)");
  return traces;
}

function median(arr) {
  const a = arr.filter((x) => Number.isFinite(x)).sort((x, y) => x - y);
  if (!a.length) return null;
  const m = Math.floor(a.length / 2);
  return a.length % 2 ? a[m] : (a[m - 1] + a[m]) / 2;
}

function overlayShapes(d, rec) {
  const shapes = [];
  const { startI, endI } = baseWindowIdx(d, rec);
  shapes.push({ type: "rect", xref: "x", yref: "paper",
    x0: startI - 0.5, x1: endI + 0.5, y0: 0, y1: 1,
    fillcolor: "rgba(56,189,248,0.08)", line: { width: 0 }, layer: "below" });
  const hline = (y, color, dash) => { if (y != null) shapes.push({
    type: "line", xref: "paper", yref: "y", x0: 0, x1: 1, y0: y, y1: y,
    line: { color, width: 1, dash: dash || "dot" } }); };
  hline(rec.base_high_q90, "#a855f7", "dot");     // Q90
  hline(rec.base_low_q10, "#a855f7", "dot");      // Q10
  hline(rec.base_median, "#f59e0b", "dash");      // median center
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

  const traces = [volume, candles, ...overlayTraces(d, currentRec)];
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
  const win = Math.min(180, n);
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

// ---------- exports ----------
const EXPORT_COLS = [
  "ticker", "company_name", "security_type", "sector", "industry",
  "current_price", "market_cap", "avg_dollar_volume_20d",
  "base_start_date", "base_end_date", "base_days",
  "close_band", "raw_high_low_range", "base_drift", "containment_ratio",
  "center_shift", "outlier_days", "outlier_ratio", "current_position",
  "flatness_score", "flatness_grade",
  "composite_score", "setup_score", "setup_pass",
  "sma50", "sma150", "sma200", "sma50_slope", "sma150_slope", "sma200_slope",
  "above_sma50", "above_sma150", "above_sma200", "ma_aligned",
  "reclaimed_sma200", "above_base", "extended", "dist_52w_high", "dist_52w_low",
  "prior_60d_return", "prior_120d_return", "representative_prior_return",
  "prior_120_close_band", "prior_252_close_band",
  "max_abs_20d_return", "max_abs_60d_return", "base_distinctness",
  "historical_activity_pass", "chronically_low_vol",
  "position_type", "position_above_200_frac", "prior_run_up", "base_correction",
  "base_category", "base_status", "is_reit", "rs_percentile", "beta", "exclude_reason",
];

function exportCsv() {
  const rows = filtered();
  const q = (v) => v == null ? "" : `"${String(v).replace(/"/g, '""')}"`;
  const csv = [EXPORT_COLS.join(",")].concat(
    rows.map((s) => EXPORT_COLS.map((k) => q(s[k])).join(","))).join("\n");
  downloadBlob("﻿" + csv, "text/csv;charset=utf-8", "csv");
}

function exportXls() {
  // Client-side Excel with no dependency: an HTML table that Excel opens
  // natively (application/vnd.ms-excel). UTF-8 BOM keeps Korean intact.
  const rows = filtered();
  const th = EXPORT_COLS.map((k) => `<th>${esc(k)}</th>`).join("");
  const trs = rows.map((s) =>
    `<tr>${EXPORT_COLS.map((k) => `<td>${esc(s[k])}</td>`).join("")}</tr>`).join("");
  const html = `<html xmlns:x="urn:schemas-microsoft-com:office:excel"><head>
    <meta charset="UTF-8"></head><body><table border="1">
    <thead><tr>${th}</tr></thead><tbody>${trs}</tbody></table></body></html>`;
  downloadBlob("﻿" + html, "application/vnd.ms-excel", "xls");
}

function downloadBlob(content, mime, ext) {
  const blob = new Blob([content], { type: mime });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `flat_screen_${new Date().toISOString().slice(0, 10)}.${ext}`;
  a.click();
  URL.revokeObjectURL(a.href);
}

// ---------- events ----------
$("#refresh-btn").addEventListener("click", load);
$("#csv-btn").addEventListener("click", exportCsv);
$("#xls-btn").addEventListener("click", exportXls);
$("#watch-btn").addEventListener("click", () => { watchOnly = !watchOnly; $("#watch-btn").classList.toggle("on", watchOnly); render(); });
$("#chart-close").addEventListener("click", closeChart);
$("#chart-watch").addEventListener("click", () => { if (currentTicker) toggleWatch(currentTicker); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeChart(); });
window.addEventListener("resize", () => { if (chartData) Plotly.Plots.resize("chart-area"); });
["f-chronic", "f-reit", "f-unaccepted", "f-setup", "f-etf-only", "f-etf-ex"].forEach((id) =>
  $("#" + id).addEventListener("change", render));
["f-search"].forEach((id) =>
  $("#" + id).addEventListener("input", render));
$("#f-score").addEventListener("input", () => { $("#f-score-val").textContent = $("#f-score").value; render(); });

// saved screening presets (top-bar filters + Excel column filters)
if (window.SUHPresets) {
  SUHPresets.mount("flat", {
    container: $("#preset-bar"),
    getColFilters: () => JSON.parse(JSON.stringify(colFilters)),
    setColFilters: (c) => { colFilters = c || {}; },
    onApply: () => { $("#f-score-val").textContent = $("#f-score").value; render(); },
  });
}

window.openChart = openChart;

// ---------- cross-device watchlist sync (☁ button) ----------
if (window.SUHSync) {
  SUHSync.mount("flat", {
    container: document.querySelector(".controls"),
    getList: () => [...WATCH],
    setList: (arr) => {
      WATCH = new Set(arr);
      localStorage.setItem(WATCH_KEY, JSON.stringify([...WATCH]));
      render();
    },
  });
}

// ---------- hover tooltips ----------
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
