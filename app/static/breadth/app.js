"use strict";

const $ = (sel) => document.querySelector(sel);

// Two run modes (see config.js):
//   STATIC=false -> live FastAPI backend (/api/breadth), used when running locally
//   STATIC=true  -> committed snapshot data/breadth_us.json (GitHub Pages)
const STATIC = !!window.SUH_DH_STATIC;
let VIEW = { metrics: [], axes: [] };
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

// ---------- 공유 시계열 ----------
// 카드의 미니 차트와 아래 큰 차트가 같은 배열을 본다(뷰가 날짜축을 공유해서 보낸다).
let CHART = { dates: [], values: {} };

// 계열 색 — dataviz 기본 팔레트의 다크 스텝 1~5번을 순서대로. 순서는 고정이고
// 돌려쓰지 않는다(한 축에 최대 5계열이라 8슬롯 안에 들어온다).
const SERIES_COLORS = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181"];

function seriesPoints(key, days) {
  const vals = CHART.values[key] || [];
  const n = CHART.dates.length;
  const from = days ? Math.max(0, n - days) : 0;
  const out = [];
  for (let i = from; i < n; i++) {
    if (vals[i] !== null && vals[i] !== undefined) out.push([i, vals[i]]);
  }
  return out;
}

// ---------- sparkline ----------
// 값 하나만 보면 구간 판정에 그치고, 방향을 봐야 다이버전스가 보인다. 그래서
// 모든 카드에 최근 90거래일 미니 차트를 붙인다(축은 없다 — 방향만 읽는 용도).
function sparkline(key, tone, w = 240, h = 34) {
  const pts = seriesPoints(key, 90);
  if (pts.length < 2) return "";
  const vals = pts.map((p) => p[1]);
  const min = Math.min(...vals), max = Math.max(...vals);
  const span = max - min || 1;
  const x = (i) => (i / (vals.length - 1)) * w;
  const y = (v) => h - 3 - ((v - min) / span) * (h - 6);
  const d = vals.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join("");
  const color = `var(--${tone || "mid"})`;
  const id = "g" + Math.random().toString(36).slice(2, 8);
  return `<svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" aria-hidden="true">
    <defs><linearGradient id="${id}" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="${color}" stop-opacity=".28"/>
      <stop offset="100%" stop-color="${color}" stop-opacity="0"/>
    </linearGradient></defs>
    <path d="${d}L${w},${h}L0,${h}Z" fill="url(#${id})"/>
    <path d="${d}" fill="none" stroke="${color}" stroke-width="1.6"
          stroke-linejoin="round" stroke-linecap="round"/>
  </svg>`;
}

// 점수 추이용(값 배열을 직접 받는다).
function scoreSpark(vals, tone, w = 600, h = 56) {
  if (vals.length < 2) return "";
  const min = Math.min(...vals), max = Math.max(...vals);
  const span = max - min || 1;
  const x = (i) => (i / (vals.length - 1)) * w;
  const y = (v) => h - 3 - ((v - min) / span) * (h - 6);
  const d = vals.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join("");
  const color = `var(--${tone || "mid"})`;
  return `<svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" aria-hidden="true">
    <path d="${d}" fill="none" stroke="${color}" stroke-width="1.8"
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
  const hist = (data.score_history || []).map((p) => p[1]);

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
      <div class="hero-chart" title="종합점수 최근 추이">${scoreSpark(hist, tone)}</div>
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
  // 며칠 어긋나는 건 정상이고, 오래 멈춰 있으면 원천이 죽은 것 — 후자는 점수에서
  // 빠지므로(usable=false) 카드도 흐리게 해서 "값은 있지만 못 믿는다"를 보여준다.
  const dead = m.value !== null && m.usable === false;
  const stale = m.stale && m.asof
    ? `<span class="card-stale${dead ? " dead" : ""}" title="${dead
        ? "값이 오래 멈춰 있어 종합점수에서 제외했습니다" : "이 지표의 최신 수집일"}"
       >${esc(m.asof)}</span>` : "";
  return `<article class="card${na ? " na" : ""}${dead ? " dead" : ""}" data-key="${esc(m.key)}"
    title="${esc(m.desc)}\n\n(눌러서 아래 차트에서 보기)">
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
    <div class="card-spark">${sparkline(m.key, m.tone)}</div>
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


// ---------- 시계열 차트 ----------
// 카드의 미니 차트는 방향만 보여 준다. "50일선 비율과 200일선 비율이 언제
// 벌어졌나" 같은 건 같은 좌표계에 겹쳐 봐야 보이므로 축·눈금·호버가 있는
// 차트를 따로 둔다.
//
// 단위가 다른 지표를 한 그림에 겹치면(이중 y축) 교차점이 아무 의미가 없어지므로
// 같은 단위끼리 묶은 탭(axes)으로만 겹쳐 그린다.
const RANGES = [[60, "3개월"], [120, "6개월"], [250, "1년"], [0, "전체"]];
const CH = { axis: null, range: 120, hidden: new Set(), hover: null };

function axisMetrics(axisKey) {
  return (VIEW.metrics || []).filter((m) => m.axis === axisKey);
}

function niceTicks(min, max, count = 5) {
  const span = (max - min) || 1;
  const raw = span / count;
  const mag = Math.pow(10, Math.floor(Math.log10(raw)));
  const step = [1, 2, 2.5, 5, 10].find((f) => f * mag >= raw) * mag;
  const out = [];
  for (let t = Math.ceil(min / step) * step; t <= max + 1e-9; t += step) out.push(t);
  return out;
}

// 탭·범위·범례는 선택이 바뀔 때만, 그림은 호버마다 — 마우스가 움직일 때마다
// 컨트롤까지 새로 만들면 낭비다.
function renderChart() {
  renderChartChrome();
  renderPlot();
}

function renderChartChrome() {
  const axis = (VIEW.axes || []).find((a) => a.key === CH.axis);
  if (!axis) return;
  const metrics = axisMetrics(axis.key);

  $("#ts-tabs").innerHTML = (VIEW.axes || []).map((a) =>
    `<button class="tv-tab${a.key === CH.axis ? " on" : ""}" data-axis="${esc(a.key)}"
     >${esc(a.label)}</button>`).join("");
  $("#ts-ranges").innerHTML = RANGES.map(([d, lab]) =>
    `<button class="ts-range${d === CH.range ? " on" : ""}" data-range="${d}">${lab}</button>`).join("");
  $("#ts-legend").innerHTML = metrics.map((m, i) => {
    const off = CH.hidden.has(m.key);
    return `<button class="ts-key${off ? " off" : ""}" data-key="${esc(m.key)}"
      title="눌러서 숨기기/보이기">
      <span class="ts-swatch" style="background:${SERIES_COLORS[i % SERIES_COLORS.length]}"></span>
      ${esc(m.label)}</button>`;
  }).join("");
}

function renderPlot() {
  const axis = (VIEW.axes || []).find((a) => a.key === CH.axis);
  if (!axis) return;
  const metrics = axisMetrics(axis.key);
  const shown = metrics.filter((m) => !CH.hidden.has(m.key));

  // --- 데이터 범위 ------------------------------------------------------
  const n = CHART.dates.length;
  const from = CH.range ? Math.max(0, n - CH.range) : 0;
  const series = shown.map((m) => ({
    metric: m,
    color: SERIES_COLORS[metrics.indexOf(m) % SERIES_COLORS.length],
    pts: seriesPoints(m.key, CH.range),
  })).filter((s) => s.pts.length > 1);

  if (!series.length) {
    $("#ts-plot").innerHTML = `<div class="loading">표시할 계열을 하나 이상 선택하세요.</div>`;
    return;
  }

  const all = series.flatMap((s) => s.pts.map((p) => p[1]));
  let lo = Math.min(...all), hi = Math.max(...all);
  if (axis.zero) { lo = Math.min(lo, 0); hi = Math.max(hi, 0); }
  const pad = (hi - lo || 1) * 0.08;
  lo -= pad; hi += pad;
  if (axis.unit === "%" && axis.key === "pct_ma") { lo = Math.max(0, lo); hi = Math.min(100, hi); }

  // --- 좌표계 -----------------------------------------------------------
  const W = 1000, H = 340, L = 52, R = 14, T = 14, B = 30;
  const px = (i) => L + ((i - from) / Math.max(1, n - 1 - from)) * (W - L - R);
  const py = (v) => T + (1 - (v - lo) / (hi - lo)) * (H - T - B);

  const ticks = niceTicks(lo, hi);
  const grid = ticks.map((t) =>
    `<line class="ts-grid" x1="${L}" x2="${W - R}" y1="${py(t).toFixed(1)}" y2="${py(t).toFixed(1)}"/>
     <text class="ts-ylab" x="${L - 8}" y="${(py(t) + 4).toFixed(1)}">${fmt(t, t % 1 ? 1 : 0)}</text>`).join("");

  const zeroLine = axis.zero && lo < 0 && hi > 0
    ? `<line class="ts-zero" x1="${L}" x2="${W - R}" y1="${py(0).toFixed(1)}" y2="${py(0).toFixed(1)}"/>` : "";

  // x축 날짜 라벨 5개
  const xlabs = [];
  for (let k = 0; k <= 4; k++) {
    const i = Math.round(from + (k / 4) * (n - 1 - from));
    const d = CHART.dates[i];
    if (!d) continue;
    xlabs.push(`<text class="ts-xlab" x="${px(i).toFixed(1)}" y="${H - 8}"
      text-anchor="${k === 0 ? "start" : k === 4 ? "end" : "middle"}">${d.slice(2)}</text>`);
  }

  const paths = series.map((s) => {
    const d = s.pts.map(([i, v], k) => `${k ? "L" : "M"}${px(i).toFixed(1)},${py(v).toFixed(1)}`).join("");
    const last = s.pts[s.pts.length - 1];
    return `<path d="${d}" fill="none" stroke="${s.color}" stroke-width="2"
              stroke-linejoin="round" stroke-linecap="round"/>
            <circle cx="${px(last[0]).toFixed(1)}" cy="${py(last[1]).toFixed(1)}" r="3.5"
              fill="${s.color}" stroke="var(--panel)" stroke-width="2"/>`;
  }).join("");

  // 호버 크로스헤어 + 값 표시
  let hover = "";
  if (CH.hover !== null && CH.hover >= from && CH.hover < n) {
    const i = CH.hover;
    hover = `<line class="ts-cross" x1="${px(i).toFixed(1)}" x2="${px(i).toFixed(1)}" y1="${T}" y2="${H - B}"/>`
      + series.map((s) => {
          const hit = s.pts.reduce((a, b) => (Math.abs(b[0] - i) < Math.abs(a[0] - i) ? b : a));
          return `<circle cx="${px(hit[0]).toFixed(1)}" cy="${py(hit[1]).toFixed(1)}" r="4.5"
                    fill="${s.color}" stroke="var(--panel)" stroke-width="2"/>`;
        }).join("");
  }

  $("#ts-plot").innerHTML =
    `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" id="ts-svg">
       ${grid}${zeroLine}${xlabs.join("")}${paths}${hover}
     </svg>`;

  // 툴팁(HTML) — 선택된 계열의 그날 값을 한 번에.
  const tip = $("#ts-tip");
  if (CH.hover !== null && CH.hover >= from && CH.hover < n) {
    const i = CH.hover;
    tip.innerHTML = `<div class="ts-tip-date">${esc(CHART.dates[i])}</div>` +
      series.map((s) => {
        const v = (CHART.values[s.metric.key] || [])[i];
        return `<div class="ts-tip-row">
          <span class="ts-swatch" style="background:${s.color}"></span>
          <span class="ts-tip-name">${esc(s.metric.label)}</span>
          <b>${v === null || v === undefined ? "—" : fmt(v, s.metric.decimals)}${esc(axis.unit)}</b>
        </div>`;
      }).join("");
    tip.style.left = `${(px(i) / W) * 100}%`;
    tip.classList.add("on");
    tip.classList.toggle("flip", px(i) / W > 0.6);
  } else {
    tip.classList.remove("on");
  }
}

function bindChart() {
  $("#ts-tabs").addEventListener("click", (e) => {
    const b = e.target.closest("[data-axis]");
    if (!b) return;
    CH.axis = b.dataset.axis; CH.hidden.clear(); renderChart();
  });
  $("#ts-ranges").addEventListener("click", (e) => {
    const b = e.target.closest("[data-range]");
    if (!b) return;
    CH.range = parseInt(b.dataset.range, 10); renderChart();
  });
  $("#ts-legend").addEventListener("click", (e) => {
    const b = e.target.closest("[data-key]");
    if (!b) return;
    const k = b.dataset.key;
    // 마지막 한 계열까지 끄면 빈 그림이 되므로 그건 막는다.
    if (CH.hidden.has(k)) CH.hidden.delete(k);
    else if (axisMetrics(CH.axis).length - CH.hidden.size > 1) CH.hidden.add(k);
    renderChart();
  });
  const plot = $("#ts-plot");
  plot.addEventListener("mousemove", (e) => {
    const r = plot.getBoundingClientRect();
    const W = 1000, L = 52, R = 14;
    const n = CHART.dates.length;
    const from = CH.range ? Math.max(0, n - CH.range) : 0;
    const xr = ((e.clientX - r.left) / r.width) * W;
    const t = (xr - L) / (W - L - R);
    const i = Math.round(from + t * (n - 1 - from));
    const clamped = Math.max(from, Math.min(n - 1, i));
    if (clamped !== CH.hover) { CH.hover = clamped; renderPlot(); }
  });
  plot.addEventListener("mouseleave", () => { CH.hover = null; renderPlot(); });
}

// 카드를 누르면 그 지표가 속한 탭으로 차트를 바꾸고 그 계열만 남긴다.
function focusMetric(key) {
  const m = (VIEW.metrics || []).find((x) => x.key === key);
  if (!m || !m.axis) return;
  CH.axis = m.axis;
  CH.hidden = new Set(axisMetrics(m.axis).map((x) => x.key).filter((k) => k !== key));
  renderChart();
  document.getElementById("ts-section").scrollIntoView({ behavior: "smooth", block: "start" });
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
  VIEW = data;
  CHART = data.chart || { dates: [], values: {} };
  if (!CH.axis) CH.axis = (data.axes || [{}])[0].key;
  renderHero(data);
  renderAlerts(data);
  renderGroups(data);
  renderChart();
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

$("#groups").addEventListener("click", (e) => {
  const card = e.target.closest(".card[data-key]");
  if (card) focusMetric(card.dataset.key);
});

$("#refresh-btn").addEventListener("click", load);
bindChart();
renderTvTabs();
load();
