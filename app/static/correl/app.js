"use strict";

const $ = (s) => document.querySelector(s);
const STATIC = !!window.SUH_DH_STATIC;

// 파일에는 상관이 아니라 **수익률 행렬**이 들어 있다(int16 ×10000, base64).
// 상관은 여기서 계산한다 — 행 하나와 전체 행렬의 내적이라 3,000종목이어도
// 수 밀리초다. 그래서 이웃 수 상한이 없다: 유니버스 전체가 표에 들어온다.
let DATA = null;          // {tickers, meta, returns, market_returns, ...}
let WINDOWS = [20, 50, 120];
let PREP = null;          // {Z: {"res50": Float32Array, ...}, ok: {...}, n, cols}
let ROWS = [];            // 현재 선택 종목 대비 유니버스 전체
let SELF = null;
let NOISE = {};           // {창: 우연으로도 나오는 상관 수준}
let sortKey = "resmin", sortDir = -1;

// 표는 정렬·필터를 통과한 위에서부터 이만큼씩 그린다. 계산은 전부 하지만
// 3,000행 × 14열을 한 번에 DOM 에 넣으면 브라우저가 버벅인다.
const RENDER_STEP = 300;
let shown = RENDER_STEP;

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const fmtCorr = (v) => (v === null || v === undefined) ? "—" : (v >= 0 ? "+" : "") + v.toFixed(2);
const fmtNum = (v, d = 0) => (v === null || v === undefined || !isFinite(v))
  ? "—" : Number(v).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });

function columns() {
  const cols = [
    { key: "ticker", label: "티커", cls: "t", num: false },
    { key: "name", label: "회사", cls: "n", num: false },
    { key: "sector", label: "섹터", cls: "s", num: false },
    { key: "industry", label: "산업", cls: "s", num: false },
  ];
  // 동행 점수 먼저 — 한 기간만 보고 줄 세우면 상위권이 우연으로 찬다.
  cols.push({ key: "resmin", label: "동행 점수", cls: "c res score", num: true });
  for (const w of WINDOWS) cols.push({ key: `res${w}`, label: `잔차 ${w}일`, cls: "c res", num: true, win: w });
  for (const w of WINDOWS) cols.push({ key: `raw${w}`, label: `원시 ${w}일`, cls: "c raw", num: true, win: w });
  cols.push({ key: "beta", label: "베타", cls: "c", num: true });
  cols.push({ key: "market_cap", label: "시총", cls: "c", num: true });
  cols.push({ key: "dollar_volume", label: "거래대금", cls: "c", num: true });
  return cols;
}

// 상관계수를 색으로 — 양수는 초록, 음수는 빨강, 0 부근은 회색.
function corrStyle(v, win) {
  if (v === null || v === undefined) return "";
  // 잡음선 아래면 색을 빼고 흐리게 — 우연으로도 나오는 크기라는 표시.
  const line = win ? NOISE[String(win)] : null;
  if (line && Math.abs(v) < line) return "color:#6b7280";
  const a = Math.min(1, Math.abs(v) / 0.8);
  const c = v >= 0 ? "74,222,128" : "248,113,113";
  return `background:rgba(${c},${(a * 0.22).toFixed(3)});color:${v >= 0 ? "#86efac" : "#fca5a5"}`;
}

// 동행 점수 = 세 기간 잔차 상관의 최솟값. 한 기간이라도 비면 점수가 없다.
function comoveScore(r) {
  const v = WINDOWS.map((w) => r[`res${w}`]);
  return v.some((x) => x === null || x === undefined) ? null : Math.min(...v);
}

// 한 기간이라도 잡음선 위인가 — "잡음선 위만" 필터가 쓴다.
//
// 세 기간을 모두 요구하면 필터가 죽는다: 20일 선이 +0.71 이라 사실상 20일
// 필터가 되고, 실측으로 종목의 39%가 아무것도 남지 않았다(중앙값 1개).
// 한 기간만 요구하면 57개 중 34개가 남아 "믿을 구석이 하나라도 있는 행"을
// 고르는 필터가 된다.
function aboveNoise(r) {
  return WINDOWS.some((w) => {
    const line = NOISE[String(w)];
    const v = r[`res${w}`];
    return !line || (v !== null && v !== undefined && Math.abs(v) >= line);
  });
}

// ---------- 데이터 ----------
// base64(int16) → Float32Array. 결측(-32768)은 NaN 으로 편다.
function decodeReturns(b64, rows, cols, scale) {
  const bin = atob(b64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  const q = new Int16Array(bytes.buffer, 0, rows * cols);
  const out = new Float32Array(rows * cols);
  for (let i = 0; i < out.length; i++) out[i] = q[i] === -32768 ? NaN : q[i] / scale;
  return out;
}

// 마지막 win 일을 표준화해 둔다. 그러면 상관은 내적 한 번이다(Z·Z[i]).
function standardize(M, n, cols, win) {
  const Z = new Float32Array(n * win);
  const ok = new Uint8Array(n);
  const off = cols - win;
  for (let i = 0; i < n; i++) {
    let sum = 0, bad = false;
    for (let t = 0; t < win; t++) {
      const v = M[i * cols + off + t];
      if (!isFinite(v)) { bad = true; break; }
      sum += v;
    }
    if (bad) continue;
    const mean = sum / win;
    let ss = 0;
    for (let t = 0; t < win; t++) { const d = M[i * cols + off + t] - mean; ss += d * d; }
    const sd = Math.sqrt(ss / win) || 1;
    const k = sd * Math.sqrt(win);
    for (let t = 0; t < win; t++) Z[i * win + t] = (M[i * cols + off + t] - mean) / k;
    ok[i] = 1;
  }
  return { Z, ok };
}

// 파일을 받은 직후 한 번만: 수익률 → 잔차 → 창별 표준화.
function prepare(raw) {
  const n = raw.tickers.length;
  const cols = raw.days;
  const scale = raw.scale || 10000;
  const R = decodeReturns(raw.returns, n, cols, scale);
  const mkt = decodeReturns(raw.market_returns, 1, cols, scale);
  for (let t = 0; t < cols; t++) if (!isFinite(mkt[t])) mkt[t] = 0;

  // 잔차 = 실제 − 베타 × 시장. 베타는 수집 때 1년치로 구한 값을 그대로 쓴다.
  const E = new Float32Array(n * cols);
  for (let i = 0; i < n; i++) {
    const beta = ((raw.meta[i] || [])[3] || 0) / 100;
    for (let t = 0; t < cols; t++) E[i * cols + t] = R[i * cols + t] - beta * mkt[t];
  }

  const Z = {}, ok = {};
  for (const [kind, M] of [["raw", R], ["res", E]]) {
    for (const w of WINDOWS) {
      const s = standardize(M, n, cols, w);
      Z[kind + w] = s.Z; ok[kind + w] = s.ok;
    }
  }
  return { Z, ok, n, cols };
}

// 선택한 종목과 유니버스 전체의 상관. 이웃을 고르지 않는다 — 전부 준다.
function expand(ticker) {
  const i = DATA.tickers.indexOf(ticker);
  if (i < 0 || !PREP) return null;
  const { Z, ok, n } = PREP;

  const corr = {};
  for (const kind of ["raw", "res"]) {
    for (const w of WINDOWS) {
      const key = kind + w, zz = Z[key], okk = ok[key];
      const out = new Float32Array(n).fill(NaN);
      if (okk[i]) {
        const base = i * w;
        for (let j = 0; j < n; j++) {
          if (!okk[j]) continue;
          let acc = 0;
          for (let t = 0; t < w; t++) acc += zz[j * w + t] * zz[base + t];
          out[j] = Math.max(-1, Math.min(1, acc));
        }
      }
      corr[key] = out;
    }
  }

  const meta = (j) => DATA.meta[j] || ["", "", "", 0, 0, 0, 0];
  const base = (j) => {
    const m = meta(j);
    // is_etf 를 싣기 전 스냅샷도 산업명으로 알아본다.
    const etf = !!m[6] || m[2] === "Exchange Traded Fund";
    const r = { ticker: DATA.tickers[j], name: m[0],
                // ETF 는 섹터가 전부 Financial 로 붙어 나와 섹터 필터를 망친다.
                sector: etf ? "ETF" : (m[1] || "—"), industry: m[2] || "—",
                beta: (m[3] || 0) / 100, market_cap: (m[4] || 0),
                dollar_volume: (m[5] || 0), isEtf: etf };
    for (const key of Object.keys(corr)) {
      const v = corr[key][j];
      r[key] = isFinite(v) ? v : null;
    }
    r.resmin = comoveScore(r);
    return r;
  };

  const rows = [];
  for (let j = 0; j < n; j++) if (j !== i) rows.push(base(j));
  return { self: base(i), rows };
}

function select(ticker) {
  const t = (ticker || "").toUpperCase().trim();
  const got = t && DATA ? expand(t) : null;
  if (!got) {
    SELF = null; ROWS = [];
    $("#self").innerHTML = t
      ? `<div class="miss"><b>${esc(t)}</b> 는 유니버스에 없습니다.
         가격 $5 이상 · 60일 평균 거래대금 $10M 이상 종목만 담고 있습니다.</div>` : "";
    render();
    return;
  }
  SELF = got.self; ROWS = got.rows; shown = RENDER_STEP;
  $("#q").value = SELF.ticker;
  $("#self").innerHTML = `
    <div class="self-card">
      <span class="self-t">${esc(SELF.ticker)}</span>
      <span class="self-n">${esc(SELF.name || "")}</span>
      <span class="self-meta">${esc(SELF.sector)} · ${esc(SELF.industry)}</span>
      <span class="self-meta">베타 ${SELF.beta.toFixed(2)}</span>
      <span class="self-meta">시총 $${fmtNum(SELF.market_cap / 1000, 1)}B</span>
    </div>`;
  fillSectors();
  try { localStorage.setItem("suh_correl_last", SELF.ticker); } catch (_) { /* 무시 */ }
  render();
}

function fillSectors() {
  const sel = $("#f-sector");
  const cur = sel.value;
  const list = [...new Set(ROWS.map((r) => r.sector))].sort();
  sel.innerHTML = `<option value="">전체</option>` +
    list.map((s) => `<option${s === cur ? " selected" : ""}>${esc(s)}</option>`).join("");
}

// ---------- 필터 · 정렬 ----------
function filtered() {
  const txt = $("#f-text").value.trim().toUpperCase();
  const sec = $("#f-sector").value;
  const res = parseFloat($("#f-res").value);
  const raw = parseFloat($("#f-raw").value);
  const dv = parseFloat($("#f-dv").value);
  const xsec = $("#f-xsector").checked;
  const xetf = $("#f-xetf").checked;
  const sig = $("#f-signal").checked;

  return ROWS.filter((r) => {
    if (txt && !(r.ticker.includes(txt) || (r.name || "").toUpperCase().includes(txt))) return false;
    if (sec && r.sector !== sec) return false;
    if (isFinite(res) && !(r.res50 !== null && r.res50 >= res)) return false;
    if (isFinite(raw) && !(r.raw50 !== null && r.raw50 <= raw)) return false;
    if (isFinite(dv) && !(r.dollar_volume >= dv)) return false;
    if (xsec && SELF && r.sector === SELF.sector) return false;
    // ETF 는 그 종목을 담고 있어서 상관이 높은 게 당연하다 — 기본으로 숨긴다.
    if (xetf && r.isEtf) return false;
    if (sig && !aboveNoise(r)) return false;
    return true;
  }).sort((a, b) => {
    const av = a[sortKey], bv = b[sortKey];
    const an = av === null || av === undefined, bn = bv === null || bv === undefined;
    if (an && bn) return 0;
    if (an) return 1;                 // 값 없는 행은 항상 아래로
    if (bn) return -1;
    if (typeof av === "string") return sortDir * av.localeCompare(bv);
    return sortDir * (av - bv);
  });
}

// ---------- 그리기 ----------
function render(keepShown) {
  if (!keepShown) shown = RENDER_STEP;
  const cols = columns();
  $("#thead").innerHTML = cols.map((c) =>
    `<th class="${c.cls}${c.key === sortKey ? " on" : ""}" data-key="${c.key}">
       ${esc(c.label)}<span class="arrow">${c.key === sortKey ? (sortDir < 0 ? "▼" : "▲") : ""}</span>
     </th>`).join("");

  const rows = filtered();
  const view = rows.slice(0, shown);
  $("#f-count").textContent = ROWS.length ? `${rows.length} / ${ROWS.length}종목` : "";
  const lines = WINDOWS.map((w) => NOISE[String(w)] ? `${w}일 ±${NOISE[String(w)].toFixed(2)}` : null)
    .filter(Boolean);
  $("#f-noise").textContent = lines.length ? `잡음선 ${lines.join(" · ")}` : "";
  $("#tbody").innerHTML = view.map((r) => `<tr>${cols.map((c) => {
    const v = r[c.key];
    if (c.key === "ticker")
      return `<td class="t"><a href="#" data-go="${esc(v)}">${esc(v)}</a>${
        r.isEtf ? ` <span class="etf">ETF</span>` : ""}</td>`;
    if (!c.num) return `<td class="${c.cls}">${esc(v)}</td>`;
    if (c.key === "beta") return `<td class="c">${v.toFixed(2)}</td>`;
    if (c.key === "market_cap") return `<td class="c">$${fmtNum(v / 1000, 1)}B</td>`;
    if (c.key === "dollar_volume") return `<td class="c">$${fmtNum(v)}M</td>`;
    return `<td class="${c.cls}" style="${corrStyle(v, c.win)}">${fmtCorr(v)}</td>`;
  }).join("")}</tr>`).join("");

  // 계산은 전부 하고 그리기만 끊는다 — 3,000행을 한 번에 DOM 에 넣으면 버벅인다.
  const rest = rows.length - view.length;
  $("#more").classList.toggle("hidden", rest <= 0);
  if (rest > 0) $("#more").textContent = `${rest.toLocaleString()}개 더 보기`;
  $("#empty").textContent = !SELF ? "티커를 입력하세요."
    : rows.length ? "" : "조건에 맞는 종목이 없습니다. 필터를 풀어 보세요.";
}

// ---------- 자동완성 ----------
function suggest() {
  const q = $("#q").value.trim().toUpperCase();
  const box = $("#suggest");
  if (!q || !DATA) { box.classList.add("hidden"); return; }
  const hits = [];
  for (let i = 0; i < DATA.tickers.length && hits.length < 12; i++) {
    const t = DATA.tickers[i], n = (DATA.meta[i] || [""])[0] || "";
    if (t.startsWith(q) || t.includes(q) || n.toUpperCase().includes(q)) hits.push([t, n]);
  }
  box.innerHTML = hits.map(([t, n]) =>
    `<button data-go="${esc(t)}"><b>${esc(t)}</b> <span>${esc(n)}</span></button>`).join("");
  box.classList.toggle("hidden", !hits.length);
}

// ---------- 이벤트 ----------
$("#q").addEventListener("input", suggest);
$("#q").addEventListener("keydown", (e) => {
  if (e.key === "Enter") { $("#suggest").classList.add("hidden"); select($("#q").value); }
});
$("#go").addEventListener("click", () => { $("#suggest").classList.add("hidden"); select($("#q").value); });
document.addEventListener("click", (e) => {
  const go = e.target.closest("[data-go]");
  if (go) {
    e.preventDefault();
    $("#suggest").classList.add("hidden");
    select(go.dataset.go);
    window.scrollTo({ top: 0, behavior: "smooth" });
    return;
  }
  if (!e.target.closest(".search")) $("#suggest").classList.add("hidden");
});
$("#more").addEventListener("click", () => { shown += RENDER_STEP; render(true); });
$("#thead").addEventListener("click", (e) => {
  const th = e.target.closest("th[data-key]");
  if (!th) return;
  const k = th.dataset.key;
  // 같은 열을 다시 누르면 방향만 뒤집는다. 새 열은 숫자면 내림차순부터.
  if (k === sortKey) sortDir = -sortDir;
  else { sortKey = k; sortDir = columns().find((c) => c.key === k).num ? -1 : 1; }
  render();
});
for (const id of ["#f-text", "#f-sector", "#f-res", "#f-raw", "#f-dv", "#f-xsector",
                  "#f-xetf", "#f-signal"])
  $(id).addEventListener("input", render);
$("#f-clear").addEventListener("click", () => {
  for (const id of ["#f-text", "#f-res", "#f-raw", "#f-dv"]) $(id).value = "";
  $("#f-sector").value = ""; $("#f-xsector").checked = false;
  $("#f-xetf").checked = true; $("#f-signal").checked = false;
  render();
});
$(".presets").addEventListener("click", (e) => {
  const b = e.target.closest("[data-preset]");
  if (!b) return;
  // 두 용도가 쓰는 정렬이 서로 반대라 버튼 하나로 맞춰 준다.
  if (b.dataset.preset === "theme") { sortKey = "resmin"; sortDir = -1; }
  else { sortKey = "raw50"; sortDir = 1; }
  render();
});

// ---------- 계산 로직 모달 ----------
(function () {
  const modal = $("#logic-modal");
  if (!modal) return;
  const close = () => modal.classList.add("hidden");
  $("#logic-btn").addEventListener("click", () => modal.classList.remove("hidden"));
  $("#logic-close").addEventListener("click", close);
  // 바깥을 누르거나 Esc 로도 닫는다.
  modal.addEventListener("click", (e) => { if (e.target === modal) close(); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") close(); });
})();

// ---------- 로드 ----------
async function load() {
  try {
    const res = STATIC ? await SUHData.fetch("correl.json", true)
                       : await fetch("/api/correl", { cache: "no-store" });
    const raw = await res.json();
    if (!res.ok || raw.error || !raw.tickers) {
      $("#status").textContent = "오류";
      $("#empty").innerHTML = `<b>${esc(raw.error || "상관 데이터를 불러오지 못했습니다.")}</b>`;
      return;
    }
    DATA = raw;
    WINDOWS = raw.windows || WINDOWS;
    NOISE = raw.noise || {};
    const t0 = performance.now();
    PREP = prepare(raw);
    console.info(`correl: ${raw.tickers.length}종목 × ${raw.days}일 준비 ` +
                 `${(performance.now() - t0).toFixed(0)}ms`);
    $("#demo-badge").classList.toggle("hidden", !raw.demo);
    const when = raw.updated ? new Date(raw.updated).toLocaleString("ko-KR") : "";
    $("#status").textContent =
      `${raw.tickers.length.toLocaleString()}종목 전체와 비교 · 기준일 ${raw.asof || "—"} · 갱신 ${when}`;
    let last = null;
    try { last = localStorage.getItem("suh_correl_last"); } catch (_) { /* 무시 */ }
    const initial = new URLSearchParams(location.search).get("t") || last;
    if (initial && DATA.tickers.includes(initial.toUpperCase())) select(initial);
    else render();
  } catch (e) {
    $("#status").textContent = "오류";
    $("#empty").innerHTML = `<b>상관 데이터를 불러오지 못했습니다</b><br><small>${esc(e.message)}</small>`;
  }
}

load();
