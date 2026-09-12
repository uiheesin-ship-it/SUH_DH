"use strict";

const $ = (sel) => document.querySelector(sel);

// Two run modes (see config.js):
//   STATIC=false -> live FastAPI backend (/api/breadth), used when running locally
//   STATIC=true  -> committed snapshot data/breadth_us.json (GitHub Pages)
const STATIC = !!window.SUH_DH_STATIC;
const BUILT = window.SUH_DH_BUILT || null;

// TradingView 차트 탭.
//
// 숫자 카드는 구성종목에서 직접 계산한 값이고, 여기 위젯은 시장이 계산해 둔
// 원본이다. 특히 NYSE 전체(약 3,000 종목) 기준 A/D · 신고가 · 맥클렐란 ·
// 상승하락 거래량은 공개 조회 경로가 없어 카드로는 못 만들었으므로, 그 지표를
// 보는 유일한 자리가 이 탭이다.
const TV_SYMBOLS = [
  ["INDEX:S5FI", "S&P 50일선 위 %"],
  ["INDEX:S5TW", "S&P 20일선 위 %"],
  ["INDEX:S5TH", "S&P 200일선 위 %"],
  ["INDEX:NDFI", "나스닥100 50일"],
  ["INDEX:NDTH", "나스닥100 200일"],
  ["INDEX:NCTH", "나스닥종합 200일"],
  ["INDEX:ADDN", "NYSE 상승−하락"],
  ["INDEX:ADRN", "NYSE 등락비율"],
  ["INDEX:MAHN", "NYSE 신고가"],
  ["INDEX:MALN", "NYSE 신저가"],
  ["INDEX:NYMO", "맥클렐란 오실"],
  ["INDEX:NYSI", "맥클렐란 총계"],
  ["INDEX:UVOL", "상승 거래량"],
  ["INDEX:DVOL", "하락 거래량"],
];
function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function fmt(v, decimals) {
  if (v === null || v === undefined) return "—";
  const d = decimals ?? 1;
  return Number(v).toLocaleString("en-US", {
    minimumFractionDigits: d, maximumFractionDigits: d,
  });
}

// 전일대비. 단위가 %인 지표의 변화는 %p 로 표기해야 오해가 없다.
function fmtChange(m) {
  if (m.change === null || m.change === undefined) return "";
  const unit = m.unit === "%" ? "%p" : "";
  const sign = m.change > 0 ? "+" : "";
  const cls = m.change > 0 ? "up" : m.change < 0 ? "down" : "flat";
  return `<span class="card-chg ${cls}">${sign}${fmt(m.change, m.decimals)}${unit}</span>`;
}

// ---------- sparkline ----------
// 값 하나만 보면 구간 판정에 그치고, 방향을 봐야 다이버전스가 보인다. 그래서
// 모든 카드에 최근 90거래일 미니 차트를 붙인다.
function sparkline(points, tone, w = 240, h = 34) {
  const vals = points.map((p) => p[1]);
  if (vals.length < 2) return "";
  const min = Math.min(...vals), max = Math.max(...vals);
  const span = max - min || 1;
  const x = (i) => (i / (vals.length - 1)) * w;
  const y = (v) => h - 3 - ((v - min) / span) * (h - 6);
  const d = vals.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join("");
  const color = `var(--${tone || "mid"})`;
  const area = `${d}L${w},${h}L0,${h}Z`;
  const id = "g" + Math.random().toString(36).slice(2, 8);
  return `<svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" aria-hidden="true">
    <defs><linearGradient id="${id}" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="${color}" stop-opacity=".28"/>
      <stop offset="100%" stop-color="${color}" stop-opacity="0"/>
    </linearGradient></defs>
    <path d="${area}" fill="url(#${id})"/>
    <path d="${d}" fill="none" stroke="${color}" stroke-width="1.6"
          stroke-linejoin="round" stroke-linecap="round"/>
  </svg>`;
}

// ---------- hero ----------
function renderHero(data) {
  const c = data.composite || {};
  if (c.score === null || c.score === undefined) {
    $("#hero").innerHTML = `<div class="loading" style="grid-column:1/-1">${esc(c.note || "데이터 없음")}</div>`;
    $("#hero").style.gridTemplateColumns = "1fr";
    return;
  }
  const tone = c.tone || "mid";
  const parts = (c.parts || []).map((p) =>
    `<span class="part" title="가중치 ${p.weight}">${esc(p.label)} <b>${fmt(p.score, 0)}</b></span>`).join("");
  const hist = (data.score_history || []).map((p) => [p[0], p[1]]);

  $("#hero").innerHTML = `
    <div class="gauge">
      <div class="gauge-num" style="color:var(--${tone})">${fmt(c.score, 0)}<span class="gauge-max"> / 100</span></div>
      <div class="gauge-regime" style="color:var(--${tone})">${esc(c.regime)}</div>
      <div class="gauge-bar"><span class="gauge-pin" style="left:calc(${c.score}% - 2px)"></span></div>
      <div class="gauge-scale"><span>위험</span><span>중립</span><span>과열</span></div>
    </div>
    <div class="hero-body">
      <h2>시장 폭 종합 ${esc(c.regime)}</h2>
      <p class="hero-note">${esc(c.note)}</p>
      <div class="hero-meta">
        <span>기준일 ${esc(data.asof || "—")}</span>
        <span>수집 ${data.count}/${data.total} 지표</span>
        <span>점수 커버리지 ${fmt(c.coverage, 0)}%</span>
        <span>시계열 ${data.days}일</span>
      </div>
      <div class="hero-chart" title="종합점수 최근 추이">${sparkline(hist, tone, 600, 56)}</div>
      <div class="hero-parts">${parts}</div>
    </div>`;
  $("#hero").style.gridTemplateColumns = "";
}

// ---------- alerts ----------
function renderAlerts(data) {
  const items = data.alerts || [];
  if (!items.length) {
    $("#alerts").innerHTML = "";
    return;
  }
  $("#alerts").innerHTML = items.map((a) => `
    <div class="alert ${esc(a.level)}">
      <h3>${esc(a.title)}</h3>
      <p>${esc(a.detail)}</p>
    </div>`).join("");
}

// ---------- metric cards ----------
function card(m) {
  const na = m.value === null || m.value === undefined;
  const zone = m.zone
    ? `<span class="card-zone" style="color:var(--${m.tone || "mid"})">${esc(m.zone)}</span>` : "";
  const d20 = (m.d20 !== null && m.d20 !== undefined)
    ? `<span class="card-d20">20일 ${m.d20 > 0 ? "+" : ""}${fmt(m.d20, m.decimals)}${m.unit === "%" ? "%p" : ""}</span>`
    : "";
  // 원천마다 마지막 거래일이 다르다. 기준일보다 오래된 값이면 그 날짜를 붙여
  // "왜 어제 값이지?" 를 묻지 않게 한다(빈 칸으로 버리는 것보다 낫다).
  const stale = m.stale && m.asof
    ? `<span class="card-stale" title="이 지표의 최신 수집일">${esc(m.asof)}</span>` : "";
  return `<article class="card${na ? " na" : ""}" title="${esc(m.desc)}">
    <div class="card-head">
      <span class="card-label">${esc(m.label)}${stale}</span>
      <span class="card-src" title="출처">${esc(m.source || "")}</span>
    </div>
    <div class="card-val">
      <span class="card-num" style="color:var(--${m.tone || "mid"})">${fmt(m.value, m.decimals)}</span>
      <span class="card-unit">${esc(m.unit)}</span>
      ${fmtChange(m)}
    </div>
    <div>${zone} ${d20}</div>
    <div class="card-spark">${sparkline(m.spark || [], m.tone)}</div>
    <div class="card-foot">${esc(m.use || m.desc)}
      <div class="sym">${esc(m.symbol)}</div>
    </div>
  </article>`;
}

function renderGroups(data) {
  const html = (data.groups || []).map((g) => {
    const mine = (data.metrics || []).filter((m) => m.group === g.key);
    if (!mine.length) return "";
    return `<div class="sec-head">
        <h2>${esc(g.label)}</h2>
        <p class="sec-desc">${esc(g.desc)}</p>
      </div>
      <div class="cards">${mine.map(card).join("")}</div>`;
  }).join("");
  $("#groups").innerHTML = html;
}

// ---------- TradingView widget ----------
// 우리 수집 파이프라인과 완전히 독립적인 경로. 스크립트가 차단되면 링크로 대체한다.
let tvReady = null;
function loadTv() {
  if (tvReady) return tvReady;
  tvReady = new Promise((resolve, reject) => {
    const s = document.createElement("script");
    s.src = "https://s3.tradingview.com/tv.js";
    s.onload = resolve;
    s.onerror = reject;
    document.head.appendChild(s);
  });
  return tvReady;
}

async function showTv(symbol) {
  $("#tv-link").href = `https://www.tradingview.com/chart/?symbol=${encodeURIComponent(symbol)}`;
  try {
    await loadTv();
    $("#tv-chart").innerHTML = "";
    new window.TradingView.widget({
      container_id: "tv-chart",
      symbol,
      interval: "D",
      timezone: "Asia/Seoul",
      theme: "dark",
      style: "2",          // line — breadth 지수는 캔들이 의미 없다
      locale: "kr",
      hide_side_toolbar: true,
      allow_symbol_change: false,
      autosize: true,
    });
    $("#tv-fallback").classList.remove("show");
  } catch (_) {
    $("#tv-fallback").classList.add("show");
  }
}

function renderTvTabs() {
  $("#tv-tabs").innerHTML = TV_SYMBOLS.map(([sym, label], i) =>
    `<button class="tv-tab${i === 0 ? " on" : ""}" data-sym="${esc(sym)}">${esc(label)}</button>`).join("");
  $("#tv-tabs").addEventListener("click", (e) => {
    const btn = e.target.closest(".tv-tab");
    if (!btn) return;
    $("#tv-tabs").querySelectorAll(".tv-tab").forEach((b) => b.classList.toggle("on", b === btn));
    showTv(btn.dataset.sym);
  });
  showTv(TV_SYMBOLS[0][0]);
}

// ---------- load ----------
async function load() {
  $("#status").textContent = "불러오는 중…";
  try {
    // 정적/라이브 모두 "판정이 끝난 뷰"를 받는다. 구간 임계값과 종합점수 공식은
    // app/breadth.py 한 곳에만 있고, 수집기가 data/breadth.json 으로 구워 둔다.
    const res = STATIC ? await SUHData.fetch("breadth.json", true)
                       : await fetch("/api/breadth", { cache: "no-store" });
    const raw = await res.json();
    if (!res.ok || raw.error) {
      renderError(raw.error || "브레스 데이터를 불러오지 못했습니다.", raw.detail);
      return;
    }
    render(raw);
  } catch (e) {
    renderError("브레스 데이터를 불러오지 못했습니다", e.message);
  }
}

function render(data) {
  renderHero(data);
  renderAlerts(data);
  renderGroups(data);
  $("#demo-badge").classList.toggle("hidden", !data.demo);
  const when = data.updated ? new Date(data.updated).toLocaleString("ko-KR")
                            : (BUILT ? new Date(BUILT).toLocaleString("ko-KR") : "최근");
  $("#status").textContent = `기준일 ${data.asof || "—"} · 갱신 ${when}`;
}

function renderError(msg, detail) {
  $("#hero").innerHTML =
    `<div class="error" style="grid-column:1/-1"><b>${esc(msg)}</b>${detail ? "<br><small>" + esc(detail) + "</small>" : ""}</div>`;
  $("#status").textContent = "오류";
}

$("#refresh-btn").addEventListener("click", load);
renderTvTabs();
load();
