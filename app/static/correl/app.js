"use strict";

const $ = (s) => document.querySelector(s);
const STATIC = !!window.SUH_DH_STATIC;

// 저장 포맷은 압축돼 있다(티커는 인덱스, 상관은 ×100 정수, 메타는 배열).
// 파일 하나로 유니버스 전체를 들고 있으면 티커를 바꿀 때 네트워크가 필요 없다.
let DATA = null;          // {tickers, meta, neighbors, windows, ...}
let WINDOWS = [20, 50, 120];
let ROWS = [];            // 현재 선택 종목의 이웃 행들
let SELF = null;
let NOISE = {};           // {창: 우연으로도 나오는 상관 수준}
let sortKey = "resmin", sortDir = -1;

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
function expand(ticker) {
  const i = DATA.tickers.indexOf(ticker);
  if (i < 0) return null;
  const n = WINDOWS.length;
  const meta = (j) => DATA.meta[j] || ["", "", "", 0, 0, 0];
  const base = (j) => {
    const m = meta(j);
    // is_etf 를 싣기 전 스냅샷도 산업명으로 알아본다(재수집 전에도 필터가 먹게).
    const etf = !!m[6] || m[2] === "Exchange Traded Fund";
    return { ticker: DATA.tickers[j], name: m[0],
             // ETF 는 섹터가 전부 Financial 로 붙어 나와 섹터 필터를 망친다.
             sector: etf ? "ETF" : (m[1] || "—"), industry: m[2] || "—",
             beta: (m[3] || 0) / 100, market_cap: (m[4] || 0), dollar_volume: (m[5] || 0),
             isEtf: etf };
  };
  const rows = (DATA.neighbors[i] || []).map((p) => {
    const r = base(p[0]);
    WINDOWS.forEach((w, k) => {
      r[`raw${w}`] = p[1 + k] === null ? null : p[1 + k] / 100;
      r[`res${w}`] = p[1 + n + k] === null ? null : p[1 + n + k] / 100;
    });
    r.resmin = comoveScore(r);
    return r;
  });
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
  SELF = got.self; ROWS = got.rows;
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
function render() {
  const cols = columns();
  $("#thead").innerHTML = cols.map((c) =>
    `<th class="${c.cls}${c.key === sortKey ? " on" : ""}" data-key="${c.key}">
       ${esc(c.label)}<span class="arrow">${c.key === sortKey ? (sortDir < 0 ? "▼" : "▲") : ""}</span>
     </th>`).join("");

  const rows = filtered();
  $("#f-count").textContent = ROWS.length ? `${rows.length} / ${ROWS.length}종목` : "";
  const lines = WINDOWS.map((w) => NOISE[String(w)] ? `${w}일 ±${NOISE[String(w)].toFixed(2)}` : null)
    .filter(Boolean);
  $("#f-noise").textContent = lines.length ? `잡음선 ${lines.join(" · ")}` : "";
  $("#tbody").innerHTML = rows.map((r) => `<tr>${cols.map((c) => {
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
    $("#demo-badge").classList.toggle("hidden", !raw.demo);
    const when = raw.updated ? new Date(raw.updated).toLocaleString("ko-KR") : "";
    $("#status").textContent =
      `${raw.tickers.length.toLocaleString()}종목 · 기준일 ${raw.asof || "—"} · 갱신 ${when}`;
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
