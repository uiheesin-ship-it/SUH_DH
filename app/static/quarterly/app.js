/* 분기 실적 + 12M forward PER.
 *
 * 미리 전 종목을 모으지 않는다 — 입력한 티커만 그때 백엔드에 물어본다. 그래서
 * 정적 배포(GitHub Pages)에서는 백엔드 주소가 필요하다. 없으면 그렇게 말한다.
 * 조용히 빈 화면을 주는 것보다 낫다.
 */
const API_BASE = (window.SUH_DH_API_BASE || "").replace(/\/+$/, "");
const STATIC = !!window.SUH_DH_STATIC;

const $ = (id) => document.getElementById(id);
const fmtBig = (v) => {
  if (v === null || v === undefined) return "—";
  const a = Math.abs(v);
  if (a >= 1e9) return (v / 1e9).toFixed(2) + "B";
  if (a >= 1e6) return (v / 1e6).toFixed(1) + "M";
  if (a >= 1e3) return (v / 1e3).toFixed(1) + "K";
  return v.toFixed(2);
};
const fmtPct = (v) => (v === null || v === undefined ? "—" : (v >= 0 ? "+" : "") + v.toFixed(1) + "%");

let DATA = null;

/* ------------------------------------------------------------------ 불러오기 */
async function load(ticker) {
  const t = (ticker || "").trim().toUpperCase();
  if (!t) return;
  $("status").textContent = `${t} 불러오는 중…`;
  $("empty").classList.add("hidden");
  history.replaceState(null, "", `?t=${encodeURIComponent(t)}`);

  if (STATIC && !API_BASE) {
    fail("이 페이지는 티커를 입력받은 뒤에 EDGAR·야후에서 직접 받아 옵니다. " +
         "그래서 서버가 필요합니다 — 왼쪽 위 '💻 로컬 실행법' 버튼을 눌러 보세요.");
    return;
  }
  try {
    const r = await fetch(`${API_BASE}/api/fundamentals/${encodeURIComponent(t)}`,
                          { cache: "no-store" });
    const j = await r.json().catch(() => ({}));
    if (!r.ok || j.error) { fail(...explain(r, j)); return; }
    DATA = j;
    render(j);
  } catch (e) {
    fail(`불러오지 못했습니다: ${e}`);
  }
}

/* 실패를 **행동으로 옮길 수 있는 말**로 바꾼다.
 *
 * 그냥 "HTTP 404 (Not Found)" 라고 쓰면 티커가 없다는 건지, 백엔드가 없다는 건지,
 * 주소가 틀린 건지 알 수가 없다. 실제로 그렇게 막혔다 — 백엔드는 멀쩡히 살아
 * 있는데 새 코드가 아직 안 올라가서 라우트만 없었고, 화면은 그걸 구분해 주지
 * 못했다. FastAPI 가 모르는 경로에 주는 기본 응답이 {"detail":"Not Found"} 라
 * 그 모양을 그대로 알아본다.
 */
function explain(r, j) {
  if (r.status === 404 && !j.error && j.detail === "Not Found") {
    return ["백엔드에 이 기능이 아직 배포되지 않았습니다.",
            `${API_BASE || location.origin} 는 살아 있지만 /api/fundamentals 경로를 ` +
            "모릅니다 — 서버가 옛 코드로 돌고 있습니다. 로컬이라면 서버를 끄고(Ctrl+C) " +
            "git pull 후 다시 띄우세요(왼쪽 위 '💻 로컬 실행법'). 배포된 백엔드라면 " +
            "Render 에서 Manual Deploy → Deploy latest commit"];
  }
  if (r.status === 404) return [j.error || `${$("q").value.trim().toUpperCase()} 를 찾지 못했습니다.`, j.detail];
  if (r.status === 502) return [j.error || "실적을 불러오지 못했습니다.", j.detail];
  return [j.error || `HTTP ${r.status}`, j.detail];
}

function fail(msg, detail) {
  $("status").textContent = "실패";
  $("chart-sec").classList.add("hidden");
  $("table-sec").classList.add("hidden");
  const el = $("empty");
  el.className = "error";
  el.textContent = detail ? `${msg} (${detail})` : msg;
  el.classList.remove("hidden");
}

/* -------------------------------------------------------------------- 그리기 */
function render(d) {
  DATA = d;                 // 오버라이드 저장 키가 티커를 알아야 한다
  $("status").textContent = `${d.ticker} · ${d.name || ""}`;
  const bits = [`<b>${d.name || d.ticker}</b>`];
  if (d.sic) bits.push(d.sic);
  if (d.cik) bits.push(`CIK ${d.cik}`);
  if (d.fiscal_year_end) bits.push(`결산 ${d.fiscal_year_end}`);
  let head = bits.join(" · ");
  for (const n of d.notes || []) head += `<span class="warn">⚠ ${n}</span>`;

  // 서버가 옛 코드로 돌고 있으면 화면이 스스로 말한다.
  //
  // JS·CSS 는 디스크에서 매번 읽히지만 파이썬은 **서버가 뜰 때 메모리에** 올라간다.
  // 그래서 git pull 만 하고 재시작을 안 하면 화면은 새것, 백엔드는 옛것이 된다.
  // 겉으로는 "왜 새 칸이 안 나오지?" 로만 보여서 원인을 찾기가 어렵다.
  const ms = Object.values(d.metrics || {});
  if (ms.some((m) => (m.quarters || []).length) && !ms.some((m) => m.estimates)) {
    head += `<span class="warn">⚠ <b>서버가 옛 코드로 돌고 있습니다</b> — 컨센(추정) 칸이
      안 나옵니다. 코드는 받았는데 <b>서버를 다시 안 띄운</b> 것입니다.
      서버 창에서 <b>Ctrl+C</b> → <b>./run.sh</b> 로 다시 띄우세요.
      (왼쪽 위 <b>💻 로컬 실행법</b>)</span>`;
  }
  $("head").innerHTML = head;

  renderMetrics(d.metrics || {}, d.forecast_note);
  $("table-sec").classList.remove("hidden");

  EV_DATA = d.ev || null;
  BASIS = d.per_basis || "gaap";
  // 새 종목은 **처음부터** 본다. showBasis 는 보던 창을 지키는데(기준을 바꿔도
  // 카메라가 안 움직여야 하므로), 그게 종목을 바꿀 때까지 이어지면 안 된다.
  VIEW = null;
  if (d.per && d.per.dates && d.per.dates.length) {
    BASES = d.per_bases || { [BASIS]: d.per };
    showMetric("per");
    $("chart-sec").classList.remove("hidden");
  } else if (EV_DATA && EV_DATA.dates) {
    BASES = {};
    showMetric("ev");
    $("chart-sec").classList.remove("hidden");
  } else {
    $("chart-sec").classList.add("hidden");
  }
  $("empty").classList.add("hidden");
}

/* 확정 실적 오른쪽에 **컨센 칸**을 이어 붙인다.
 *
 * 따로 표를 만들지 않고 같은 표의 오른쪽에 붙인다 — 확정과 추정을 나란히 놓고
 * 좌우로 굴려 봐야 흐름이 읽힌다. 대신 경계가 분명해야 한다: 세로 구분선과
 * 다른 배경, 그리고 열 이름에 (E).
 *
 * 성장률은 확정과 추정을 **이어 붙인 뒤** 한 번에 계산한다. 그래야 첫 추정
 * 분기의 YoY 가 1년 전 확정 실적과 비교된다(따로 계산하면 그 칸이 빈다).
 */
function growth(vals) {
  return vals.map((v, i) => {
    const g = (back) => {
      const prev = vals[i - back];
      return i >= back && prev !== null && prev !== undefined && prev > 0
             && v !== null && v !== undefined ? (v / prev - 1) * 100 : null;
    };
    return { qoq: g(1), yoy: g(4) };
  });
}

const YEAR_FALLBACK = ["올해", "내년", "내후년"];

function renderMetrics(metrics, note) {
  const out = [];
  for (const label of Object.keys(metrics)) {
    const m = metrics[label];
    const qs = m.quarters || [];
    const est = m.estimates || { quarters: [], years: [] };
    const eq = est.quarters || [];
    const ey = est.years || [];
    if (!qs.length && !eq.length && !ey.some((y) => y.val !== null)) {
      out.push(`<div class="mtable"><h3>${label}
        <span class="src">${m.source}</span></h3></div>`);
      continue;
    }
    const isRatio = label.includes("EPS");
    const fmt = (v) => (v === null || v === undefined ? "—"
                        : isRatio ? v.toFixed(2) : fmtBig(v));

    // 확정 + 추정 분기를 이어 붙여 성장률을 한 번에
    const series = [...qs.map((q) => q.val), ...eq.map((q) => q.val)];
    const g = growth(series);
    const cells = [
      ...qs.map((q, i) => ({ head: q.end, kind: "", val: q.val, ...g[i] })),
      ...eq.map((q, i) => ({ head: `${q.end} (E)`, kind: "est", val: q.val,
                             analysts: q.analysts, ...g[qs.length + i] })),
    ];
    const yv = ey.map((y) => y.val);
    const yg = yv.map((v, i) => {
      const prev = yv[i - 1];
      return i > 0 && prev > 0 && v !== null && v !== undefined
             ? (v / prev - 1) * 100 : null;
    });
    ey.forEach((y, i) => cells.push({
      head: `${y.end ? "FY" + y.end.slice(0, 4) : YEAR_FALLBACK[i]} (E)`,
      kind: "est yr", val: y.val, analysts: y.analysts, yoy: yg[i], qoq: null,
    }));
    const firstEst = qs.length;
    const hasAnalysts = cells.some((c) => c.analysts);

    // 애널리스트 수는 사람 수다 — 27.00 이 아니라 27 로.
    const cnt = (v) => (v ? String(Math.round(v)) : "—");
    const td = (c, i, text, cls) =>
      `<td class="${c.kind}${i === firstEst ? " split" : ""}${cls ? " " + cls : ""}">${text}</td>`;
    const pct = (v) => (v === null || v === undefined ? "—" : fmtPct(v));
    const row = (name, pick, isPct) =>
      `<tr><td>${name}</td>` + cells.map((c, i) => {
        const v = pick(c);
        const cls = isPct && v !== null && v !== undefined
                    ? (v > 0 ? "up" : v < 0 ? "down" : "") : (v === null ? "na" : "");
        return td(c, i, isPct ? pct(v) : fmt(v), cls);
      }).join("") + "</tr>";

    const why = est.reason ? `<p class="note">⚠ ${est.reason}</p>` : "";
    out.push(`<div class="mtable">
      <h3>${label} <span class="src">${m.source}</span>
        ${est.source && est.source !== "없음"
          ? `<span class="src est-src">컨센: ${est.source}</span>` : ""}</h3>
      ${m.note ? `<p class="note">⚠ ${m.note}</p>` : ""}
      ${m.warning ? `<p class="note">⚠ ${m.warning}</p>` : ""}
      ${why}
      <div class="scroll-hint">← 왼쪽으로 굴리면 과거 분기 · 오른쪽 끝이 컨센 칸입니다</div>
      <div class="table-wrap"><table>
        <thead><tr><th>항목</th>${cells.map((c, i) =>
          `<th class="${c.kind}${i === firstEst ? " split" : ""}">${c.head}</th>`).join("")}</tr></thead>
        <tbody>
          ${row("값", (c) => c.val, false)}
          ${row("YoY", (c) => c.yoy, true)}
          ${row("QoQ", (c) => c.qoq, true)}
          ${hasAnalysts ? `<tr><td>애널리스트</td>` + cells.map((c, i) =>
              td(c, i, cnt(c.analysts), c.analysts ? "" : "na")).join("") + `</tr>` : ""}
        </tbody>
      </table></div></div>`);
  }
  $("metrics").innerHTML =
    (note ? `<p class="sec-desc forecast-note">${note}</p>` : "") + out.join("");

  // 표를 **오른쪽 끝으로 밀어 둔다.**
  //
  // 20분기가 가로로 깔려 있어서 왼쪽 끝에서 시작하면 2021년 숫자만 보인다.
  // 컨센 칸은 맨 오른쪽이라 한참 굴려야 나오고, 그래서 "추정치 칸이 안 보인다"
  // 가 된다. 최근 분기와 컨센이 먼저 보이는 게 맞다 — 과거를 보고 싶으면
  // 왼쪽으로 굴리면 된다.
  document.querySelectorAll("#metrics .table-wrap").forEach((el) => {
    el.scrollLeft = el.scrollWidth;
  });
}

/* ------------------------------------------------- 분기 EPS 손으로 고치기
 *
 * 계절성 배분은 규칙일 뿐이라 종목에 따라 미덥지 않을 수 있다. 그럴 때 고칠
 * 수 있어야 한다. 다만 아무 값이나 넣으면 안 된다 — **한 회계연도 합이 그 해
 * 컨센을 넘을 수 없다.** 넘으면 빨갛게 표시하고 저장하지 않는다.
 *
 * 고치면 다시 받지 않고 **그 자리에서** PER 을 다시 계산한다. 각 창(window)이
 * 어느 분기들을 덮는지(marks[].ends)와 분기별 EPS(values)가 응답에 실려 온다.
 */
let OVERRIDE = {};        // {분기말: 손으로 넣은 EPS}

const ovKey = () => `suhdh.eps.${(DATA && DATA.ticker) || "?"}.${PER_DATA && PER_DATA.eps_basis}`;

function loadOverrides() {
  try { OVERRIDE = JSON.parse(localStorage.getItem(ovKey()) || "{}"); }
  catch (e) { OVERRIDE = {}; }
}
function saveOverrides() {
  try { localStorage.setItem(ovKey(), JSON.stringify(OVERRIDE)); } catch (e) { /* 사파리 시크릿 */ }
}

/** 회계연도별 한도 검사 — 확정 합 + 입력 합 ≤ 그 해 컨센. */
function checkYears(per) {
  const ed = per.editable || { years: {}, quarters: {} };
  const out = {};
  for (const [fy, y] of Object.entries(ed.years)) {
    let used = 0;
    for (const e of y.quarters) {
      const v = OVERRIDE[e] !== undefined ? OVERRIDE[e] : per.values[e];
      if (v !== null && v !== undefined) used += v;
    }
    const sum = y.booked + used;
    out[fy] = { ...y, used, sum,
                over: y.total !== null && y.total !== undefined && sum > y.total + 1e-9,
                room: y.total === null || y.total === undefined ? null : y.total - y.booked };
  }
  return out;
}

/** 고친 값으로 PER 계열을 다시 만든다 — 서버를 다시 부르지 않는다. */
function perFromOverrides(per) {
  const n = per.dates.length;
  const conf = new Array(n).fill(null), est = new Array(n).fill(null);
  const marks = per.marks || [];
  for (const w of marks) {
    const ends = w.ends || [];
    const vals = ends.map((e) => (OVERRIDE[e] !== undefined ? OVERRIDE[e] : per.values[e]));
    if (!ends.length || vals.some((v) => v === null || v === undefined)) continue;
    const eps = vals.reduce((a, b) => a + b, 0);
    const touched = ends.some((e) => OVERRIDE[e] !== undefined);
    const solid = w.confirmed && !touched;
    for (let i = 0; i < n; i++) {
      const d = per.dates[i];
      if (d < w.announced || (w.to && d >= w.to)) continue;
      (solid ? conf : est)[i] = eps > 0 ? +(per.close[i] / eps).toFixed(3) : null;
    }
  }
  return { conf, est };
}

function applyOverrides() {
  if (!PER_DATA) return;
  const { conf, est } = perFromOverrides(PER_DATA);
  PER_DATA.per_confirmed = conf;
  PER_DATA.per_estimated = est;
  redraw();
  refreshEditor();
}

/* 값이 바뀔 때는 **요약과 한도만** 고쳐 쓴다.
 *
 * 편집기를 통째로 다시 그리면 지금 포커스가 있는 input 이 DOM 에서 떨어져
 * 나가고, 크롬이 "The node to be removed is no longer a child of this node"
 * 를 뱉는다. 입력칸은 그대로 두고 숫자만 갱신한다.
 */
function refreshEditor() {
  const per = PER_DATA;
  if (!per || !per.editable) return;
  const years = checkYears(per);
  for (const [fy, y] of Object.entries(years)) {
    const box = document.querySelector(`.edit-fy[data-fy="${fy}"]`);
    if (!box) continue;
    box.classList.toggle("over", !!y.over);
    const line = box.querySelector(".fy-line");
    if (line) line.innerHTML = fyLine(y);
    for (const e of y.quarters) {
      const cell = box.querySelector(`[data-max-for="${e}"]`);
      if (cell) cell.innerHTML = maxHint(per, y, e);
      const inp = box.querySelector(`input.ov[data-end="${e}"]`);
      if (inp) {
        if (OVERRIDE[e] !== undefined) inp.dataset.edited = "1";
        else delete inp.dataset.edited;
      }
    }
  }
}

function fyLine(y) {
  const t = y.total === null || y.total === undefined ? null : y.total;
  return `<b>${y.label}</b> 확정 ${y.booked.toFixed(2)} + 추정 ${y.used.toFixed(2)}` +
    ` = <b>${y.sum.toFixed(2)}</b>` +
    (t === null ? ` <span class="na">· 연간 컨센 없음(한도 검사 안 함)</span>`
      : ` / 컨센 ${t.toFixed(2)}` +
        (y.over ? ` <span class="bad">· ${(y.sum - t).toFixed(2)} 초과 — 저장되지 않습니다</span>`
                : ` <span class="ok">· 여유 ${(t - y.sum).toFixed(2)}</span>`));
}

function maxHint(per, y, e) {
  if (y.total === null || y.total === undefined) return "";
  const others = y.quarters.reduce((a, o) => a + (o === e ? 0
    : ((OVERRIDE[o] !== undefined ? OVERRIDE[o] : per.values[o]) || 0)), 0);
  return `이 칸 최대 <b>${(y.total - y.booked - others).toFixed(2)}</b>`;
}

function renderEditor() {
  const per = PER_DATA;
  const ed = per && per.editable;
  const qs = ed ? Object.keys(ed.quarters).sort() : [];
  $("edit-sec").classList.toggle("hidden", !qs.length);
  if (!qs.length) return;
  const years = checkYears(per);

  const blocks = Object.entries(years).map(([fy, y]) => {
    const rows = y.quarters.map((e) => {
      const base = per.values[e];
      const cur = OVERRIDE[e] !== undefined ? OVERRIDE[e] : base;
      return `<tr>
        <td>${e}</td>
        <td><input class="ov" data-end="${e}" type="number" step="0.01"
                   value="${cur === null || cur === undefined ? "" : cur}"
                   ${OVERRIDE[e] !== undefined ? 'data-edited="1"' : ""} /></td>
        <td class="na">원래 ${base === null || base === undefined ? "—" : base.toFixed(2)}</td>
        <td class="na" data-max-for="${e}">${maxHint(per, y, e)}</td>
      </tr>`;
    }).join("");
    return `<div class="edit-fy ${y.over ? "over" : ""}" data-fy="${fy}">
      <div class="fy-line">${fyLine(y)}</div>
      <table><tbody>${rows}</tbody></table>
    </div>`;
  }).join("");

  $("edit-body").innerHTML = blocks;
  document.querySelectorAll(".ov").forEach((inp) => {
    inp.onchange = () => {
      const e = inp.dataset.end;
      const raw = inp.value.trim();
      if (raw === "") delete OVERRIDE[e];
      else {
        const v = Number(raw);
        if (!Number.isFinite(v)) return;
        OVERRIDE[e] = v;
      }
      const years2 = checkYears(PER_DATA);
      const bad = Object.values(years2).some((y) => y.over);
      if (!bad) saveOverrides();     // 넘으면 저장하지 않는다
      applyOverrides();
    };
  });
}

/* ---------------------------------------------------------------------- 차트 */
const W = 1000, H = 420, PAD = { l: 58, r: 62, t: 16, b: 30 };
const MIN_BARS = 20;                 // 가로로 이보다 더 확대하지는 않는다
const PER_FLOOR = 0, PER_CEIL = 50;  // PER 축 기본 창

/* PER 축은 **고정 창**으로 본다.
 *
 * 데이터에 맞춰 자동으로 늘리면, PER 이 한 번이라도 200 을 찍은 종목은 나머지
 * 구간이 바닥에 깔려 아무것도 안 보인다(NVDA 2022 가 그랬다). 어차피 100 을
 * 넘는 PER 은 읽을 의미가 거의 없다. 그래서 0–50 을 기본으로 두고, 그 위가
 * 궁금하면 창을 **위로 옮겨** 본다. 창 밖으로 나간 선은 지우지 않고 잘라낸다
 * (clipPath) — 위로 뚫고 나가는 게 보여야 "여긴 벗어났구나"를 안다.
 */
let PER_DATA = null;     // 지금 그리고 있는 계열(PER 이든 EV/EBITDA 든)
let VIEW = null;
let BASES = {};          // {"gaap": 차트, "adjusted": 차트}
let EV_DATA = null;      // EV/EBITDA 계열(또는 {error})
let METRIC = "per";      // "per" | "ev"
let BASIS = "gaap";

/* EPS 기준을 바꾼다 — 다시 받지 않고 이미 받아 둔 계열을 갈아 끼운다.
 *
 * GAAP 과 조정(non-GAAP)은 숫자가 다르다. 확정 구간을 GAAP 으로, 추정 구간을
 * 조정 컨센으로 그리면 그 경계에서 선이 인위적으로 꺾인다. 기준마다 과거·미래를
 * 한 기준으로 맞춰 따로 그려 두고 여기서 고른다.
 */
function showBasis(name) {
  const ch = BASES[name];
  const names = Object.keys(BASES);
  $("basis-group").classList.toggle("hidden", names.length < 2);
  document.querySelectorAll(".eb").forEach((b) => {
    const have = names.includes(b.dataset.basis);
    b.classList.toggle("on", b.dataset.basis === name);
    b.disabled = !have;
    b.title = have ? (BASES[b.dataset.basis].eps_basis_label || "")
                   : "이 종목은 이 기준의 이력이 없습니다";
  });
  if (!ch) return;
  const keep = VIEW ? { ...VIEW } : null;     // 보던 기간·PER 창을 지킨다
  drawChart(ch);
  if (keep) { VIEW = keep; clampView(); redraw(); }
}

/* 지표 갈아 끼우기 — PER ↔ EV/EBITDA.
 *
 * 두 계열은 모양이 같다(dates·close·per_confirmed·per_estimated·marks). 그래서
 * 그리는 코드는 하나만 두고 여기서 무엇을 그릴지만 고른다. 다른 점은 세 가지다:
 * 축 기본 창(PER 0–50 / EV 0–30), 아래 설명, 그리고 **분기 EPS 수동 수정은
 * PER 에만 있다**(EBITDA 는 손으로 고칠 대상이 아니다).
 */
function showMetric(name) {
  const evOk = EV_DATA && EV_DATA.dates && EV_DATA.dates.length;
  if (name === "ev" && !evOk) name = "per";
  if (name === "per" && !Object.keys(BASES).length) name = evOk ? "ev" : "per";
  if (METRIC !== name) VIEW = null;      // 지표가 바뀌면 축이 달라진다(0–50 / 0–30)
  METRIC = name;
  document.querySelectorAll(".mt").forEach((b) => {
    const isEv = b.dataset.metric === "ev";
    b.classList.toggle("on", b.dataset.metric === name);
    b.disabled = isEv ? !evOk : !Object.keys(BASES).length;
    b.title = isEv && !evOk
      ? ((EV_DATA && EV_DATA.error) || "이 종목은 EV/EBITDA 를 만들 수 없습니다")
      : "";
  });
  // 못 그리는 이유는 **보이게** 적는다. 비활성 버튼의 title 은 아무도 안 본다.
  $("metric-note").textContent = evOk ? ""
    : (EV_DATA && EV_DATA.error ? `EV/EBITDA 없음 — ${EV_DATA.error}` : "");
  $("basis-group").classList.toggle("hidden", name !== "per");
  $("axis-label").textContent = name === "ev" ? "배수 축" : "PER 축";
  $("chart-title").textContent = name === "ev"
    ? "주가 × 12M Forward EV/EBITDA" : "주가 × 12M Forward PER";
  $("chart-desc").innerHTML = name === "ev"
    ? `EV 는 <b>주가 × 발행주식수 + 총차입금 − 현금성자산 + 비지배지분 + 우선주</b>
       입니다. 재무상태표는 분기에 한 번 바뀌므로 <b>실적발표일마다</b> 계단을 밟고
       그 사이에는 주가만 움직입니다. <b>EBITDA 컨센은 무료 출처가 없어</b>
       점선 구간은 <b>매출 컨센 × 최근 EBITDA 마진</b>으로 만든 <b>가정치</b>입니다.`
    : `계단은 <b>실적발표일</b>에 밟습니다. 기준일(분기말)에 밟으면 아직 공개되지
       않은 실적으로 그 사이 주가를 나누게 됩니다.
       <b>실선 = 확정 실적</b>만으로 계산된 구간,
       <b>점선 = 컨센서스가 섞인</b> 구간입니다.`;
  if (name === "ev") {
    $("edit-sec").classList.add("hidden");
    drawChart(EV_DATA);
  } else {
    showBasis(BASES[BASIS] ? BASIS : Object.keys(BASES)[0]);
  }
}

function clampView() {
  const n = PER_DATA.dates.length;
  let span = Math.round(VIEW.i1 - VIEW.i0);
  span = Math.max(Math.min(MIN_BARS, n - 1), Math.min(span, n - 1));
  let i0 = Math.round(VIEW.i0);
  if (i0 + span > n - 1) i0 = n - 1 - span;
  VIEW.i0 = Math.max(0, i0);
  VIEW.i1 = VIEW.i0 + span;
  const h = Math.max(5, VIEW.perHi - VIEW.perLo);
  VIEW.perLo = Math.max(0, VIEW.perLo);
  VIEW.perHi = VIEW.perLo + h;
}

function setMonths(m) {
  const n = PER_DATA.dates.length;
  VIEW.i1 = n - 1;
  VIEW.i0 = m ? Math.max(0, n - 1 - Math.round(m * 21)) : 0;   // 월 ≈ 21거래일
  clampView();
  redraw();
}

function axisOf(per) {
  return (per && per.axis) || [PER_FLOOR, PER_CEIL];
}

function drawChart(per) {
  PER_DATA = per;
  const ax = axisOf(per);
  VIEW = { i0: 0, i1: per.dates.length - 1, perLo: ax[0], perHi: ax[1] };
  if (per.metric === "ev") {
    // EBITDA 는 손으로 고치는 대상이 아니다 — PER 의 오버라이드를 끌고 오면
    // 엉뚱한 분기 값이 섞인다.
    OVERRIDE = {};
    redraw();
    wire();
    return;
  }
  loadOverrides();
  if (Object.keys(OVERRIDE).length) {
    const { conf, est } = perFromOverrides(per);
    per.per_confirmed = conf;
    per.per_estimated = est;
  }
  redraw();
  wire();
  renderEditor();
}

function redraw() {
  const per = PER_DATA;
  const { i0, i1, perLo, perHi } = VIEW;
  const n = i1 - i0;
  const px = (i) => PAD.l + ((i - i0) / Math.max(1, n)) * (W - PAD.l - PAD.r);

  // 주가 축은 **보이는 구간에만** 맞춘다. 5년을 다 걸어 두면 확대해도 선이
  // 납작한 채라 확대한 보람이 없다.
  const vis = per.close.slice(i0, i1 + 1).filter((v) => v !== null && v !== undefined);
  if (!vis.length) return;
  const cLo = Math.min(...vis), cHi = Math.max(...vis);
  const plotH = H - PAD.t - PAD.b;
  const yC = (v) => PAD.t + (1 - (v - cLo) / Math.max(1e-9, cHi - cLo)) * plotH;
  const yP = (v) => PAD.t + (1 - (v - perLo) / Math.max(1e-9, perHi - perLo)) * plotH;

  const path = (arr, y) => {
    let d = "", pen = false;
    for (let i = i0; i <= i1; i++) {
      const v = arr[i];
      if (v === null || v === undefined) { pen = false; continue; }
      d += (pen ? "L" : "M") + px(i).toFixed(1) + " " + y(v).toFixed(1) + " ";
      pen = true;
    }
    return d.trim();
  };

  // 창 위로 벗어난 날이 며칠인지 세어 알려 준다 — 안 그러면 "왜 선이 없지" 한다.
  let over = 0, under = 0;
  for (let i = i0; i <= i1; i++) {
    const v = per.per_confirmed[i] ?? per.per_estimated[i];
    if (v === null || v === undefined) continue;
    if (v > perHi) over++;
    else if (v < perLo) under++;
  }
  const overEl = $("per-over");
  overEl.textContent = over || under
    ? `창 밖 ${over ? `위로 ${over}일` : ""}${over && under ? " · " : ""}${under ? `아래로 ${under}일` : ""}` +
      " — ▲▼ 로 옮기거나 －로 축소해서 보세요"
    : "";

  const marks = (per.marks || []).map((m) => ({ ...m, i: nearestIdx(m.announced) }))
                                 .filter((m) => m.i >= i0 && m.i <= i1);

  const step = Math.max(1, Math.floor(n / 6));
  const ticks = [];
  for (let i = i0; i <= i1; i += step) ticks.push(i);

  const grid = [0, .25, .5, .75, 1];
  // 12.5 를 "13" 으로 쓰면 창 범위를 잘못 읽는다. 정수가 아니면 소수점을 보인다.
  const fmtP = (v) => (Number.isInteger(v) ? String(v)
                       : (perHi - perLo <= 10 ? v.toFixed(2) : v.toFixed(1)));

  $("plot").innerHTML = `<svg viewBox="0 0 ${W} ${H}" role="img">
    <defs><clipPath id="plotclip">
      <rect x="${PAD.l}" y="${PAD.t}" width="${W - PAD.l - PAD.r}" height="${plotH}"/>
    </clipPath></defs>
    <g stroke="#334155" stroke-width="1">
      ${grid.map((f) => {
        const y = PAD.t + f * plotH;
        return `<line x1="${PAD.l}" x2="${W - PAD.r}" y1="${y}" y2="${y}" opacity=".45"/>`;
      }).join("")}
    </g>
    <g clip-path="url(#plotclip)">
      ${marks.map((m) => `<line x1="${px(m.i)}" x2="${px(m.i)}" y1="${PAD.t}"
          y2="${H - PAD.b}" stroke="${m.confirmed ? "#64748b" : "#f472b6"}"
          stroke-width="1" stroke-dasharray="2 4" opacity=".7"/>`).join("")}
      <path d="${path(per.close, yC)}" fill="none" stroke="var(--price)" stroke-width="1.6"/>
      <path d="${path(per.per_confirmed, yP)}" fill="none" stroke="var(--per)" stroke-width="1.8"/>
      <path d="${path(per.per_estimated, yP)}" fill="none" stroke="var(--per-est)"
            stroke-width="1.8" stroke-dasharray="5 4"/>
    </g>
    <g fill="#94a3b8" font-size="11.5">
      ${grid.map((f) => {
        const y = PAD.t + f * plotH;
        const c = cHi - f * (cHi - cLo), pv = perHi - f * (perHi - perLo);
        return `<text x="${PAD.l - 7}" y="${y + 4}" text-anchor="end" fill="var(--price)">${c.toFixed(c < 10 ? 1 : 0)}</text>` +
               `<text x="${W - PAD.r + 7}" y="${y + 4}" fill="var(--per)">${fmtP(pv)}</text>`;
      }).join("")}
      ${ticks.map((i) =>
        `<text x="${px(i)}" y="${H - 9}" text-anchor="middle">${per.dates[i].slice(0, 7)}</text>`).join("")}
    </g>
  </svg>`;

  $("per-range").textContent = `${fmtP(perLo)} – ${fmtP(perHi)}`;
  syncButtons();

  renderMarks(per);
  renderLegend(per);
}

/* 차트 아래 설명줄. 지표마다 할 말이 다르다.
 *
 * PER 은 "향후 4분기 EPS 를 어떻게 채웠나"가 궁금하고, EV/EBITDA 는 거기에
 * **EV 를 무엇으로 만들었나**가 더 붙는다 — 회사마다 태그가 달라서 어떤 항목이
 * 잡혔고 어떤 항목이 아예 없었는지 보여 주지 않으면 조용한 0 이 된다.
 */
function renderMarks(per) {
  const last = (per.marks || [])[per.marks.length - 1];
  const unit = per.metric === "ev" ? "EBITDA" : "EPS";
  const num = (v) => (v === null || v === undefined ? "—" : fmtBig(v));
  const est = (per.estimates || []).map((e) =>
    `<span class="m est">${e.end} 추정 ${unit} ${per.metric === "ev" ? num(e.eps) : e.eps}
       <small>(${e.source})</small></span>`).join("");

  let html = last
    ? `<span class="m">가장 최근 계단 — 발표 <b>${last.announced}</b> ·
       재무정보 기준일 <b>${last.basis_end}</b> · 향후 4분기 ${unit}
       ${per.metric === "ev" ? num(last.eps) : last.eps}
       (추정 ${last.estimated}분기, ${last.source})</span><br/>`
    : "";
  html += est || "";

  if (per.metric === "ev") {
    const L = per.latest;
    if (L) {
      const parts = Object.entries(L.parts || {})
        .map(([k, v]) => `${k} ${num(v)}`).join(" · ");
      html += `<br/><span class="m">EV 구성(${L.end} 재무상태표) —
        발행주식수 <b>${num(L.shares)}</b> · 차입금 <b>${num(L.debt)}</b> ·
        현금성 <b>${num(L.cash)}</b> · 기타(비지배·우선주) ${num(L.other)}
        → <b>순부채 ${num(L.net_debt)}</b></span>` +
        (parts ? `<br/><span class="m small">${parts}</span>` : "");
    }
    const gone = [
      ...(per.missing || []).map((n) => `${n}(전 기간 없음)`),
      ...((L && L.absent) || []).map((n) => `${n}(이 분기만 없음)`),
    ];
    if (gone.length) {
      html += `<br/><span class="m season warn">EV 에 <b>안 들어간 항목</b>:
        ${gone.join(", ")} — 0 으로 채우지 않고 뺐습니다.
        <a href="#" class="basis-link">산정 기준 보기</a></span>`;
    }
    if (per.estimate_note) {
      html += `<br/><span class="m season warn">${per.estimate_note}
        ${per.margin_why && per.margin_why.quarters
          ? `(최근 ${per.margin_why.quarters}분기 · 최저 ${(per.margin_why.low * 100).toFixed(1)}%
             ~ 최고 ${(per.margin_why.high * 100).toFixed(1)}%)` : ""}</span>`;
    }
    html += `<br/><span class="m small">EBITDA 출처: ${per.ebitda_source || "—"}</span>`;
  } else if (per.season) {
    html += `<br/><span class="m season ${per.season.mode === "계절성" ? "ok" : "warn"}">` +
      `연간 컨센 → 분기 배분: <b>${per.season.mode}</b>` +
      (per.season.mode === "계절성"
        ? ` (1Q ${(per.season.weights["1"] * 100).toFixed(0)}% · ` +
          `2Q ${(per.season.weights["2"] * 100).toFixed(0)}% · ` +
          `3Q ${(per.season.weights["3"] * 100).toFixed(0)}% · ` +
          `4Q ${(per.season.weights["4"] * 100).toFixed(0)}%, ` +
          `과거 ${per.season.why.years_used}개 회계연도)`
        : ` — ${per.season.why.reason || ""}`) +
      ` <a href="#" class="basis-link">산정 기준 보기</a></span>`;
  }
  if (per.consensus_sources && per.consensus_sources.length) {
    html += `<br/><span class="m">컨센 출처: ${per.consensus_sources.join(", ")}</span>`;
  }
  $("marks").innerHTML = html;
  document.querySelectorAll("#marks .basis-link").forEach((a) =>
    a.onclick = (e) => { e.preventDefault(); openModal("basis"); });
}

/* 범례는 **매번 다시 쓴다.**
 *
 * 예전에는 wire() 안에 있었는데, wire() 는 한 번만 도는 함수라(리스너가 겹쳐
 * 쌓이면 휠 한 번에 여러 번 확대된다) EPS 기준을 바꿔도 범례는 옛것 그대로였다.
 */
function renderLegend(per) {
  const ev = per.metric === "ev";
  const name = ev ? "12M forward EV/EBITDA" : "12M forward PER";
  $("legend").innerHTML = `
    <span><i style="border-color:var(--price)"></i>주가 (왼쪽 축)</span>
    <span><i style="border-color:var(--per)"></i>${name} — 확정 실적 (오른쪽 축)</span>
    <span><i style="border-color:var(--per-est);border-top-style:dashed"></i>${name} — ${
      ev ? "가정치 섞임(매출 컨센 × 마진)" : "컨센 섞임"}</span>
    <span><i style="border-color:#64748b;border-top-style:dashed"></i>실적발표일</span>
    <span class="ctrl-note">끌어서 이동 · 휠로 기간 확대</span>
    ${!ev && per.eps_basis_label
      ? `<span class="ctrl-note">EPS 기준: <b>${per.eps_basis_label}</b>` +
        ` · ${per.eps_quarters}분기</span>` : ""}
    ${ev && per.margin !== null && per.margin !== undefined
      ? `<span class="ctrl-note">EBITDA 마진(최근 중앙값): <b>${(per.margin * 100).toFixed(1)}%</b></span>` : ""}`;
}

function syncButtons() {
  const last = PER_DATA.dates.length - 1;
  document.querySelectorAll(".rng").forEach((b) => {
    const m = +b.dataset.months;
    const span = m ? Math.round(m * 21) : last;
    b.classList.toggle("on",
      VIEW.i1 === last && Math.abs(Math.min(span, last) - (VIEW.i1 - VIEW.i0)) <= 1);
  });
}

function nearestIdx(d) {
  const ds = PER_DATA.dates;
  if (!ds.length || d < ds[0] || d > ds[ds.length - 1]) return -1;
  let lo = 0, hi = ds.length - 1;
  while (lo < hi) { const m = (lo + hi) >> 1; ds[m] < d ? (lo = m + 1) : (hi = m); }
  return lo;
}

/* 조작 — 버튼, 끌기, 휠 */
let WIRED = false;

function wire() {
  // #plot 은 innerHTML 만 갈아 끼우고 자신은 살아 있다. addEventListener 를
  // 다시 부르면 티커를 바꿀 때마다 한 겹씩 쌓여 휠 한 번에 여러 번 확대된다.
  if (WIRED) { syncButtons(); return; }
  WIRED = true;
  document.querySelectorAll(".rng").forEach((b) =>
    b.onclick = () => setMonths(+b.dataset.months));

  const panPer = (dir) => {
    const h = VIEW.perHi - VIEW.perLo;
    VIEW.perLo += dir * h / 2; VIEW.perHi += dir * h / 2;
    clampView(); redraw();
  };
  const zoomPer = (f) => {
    const mid = (VIEW.perLo + VIEW.perHi) / 2, h = (VIEW.perHi - VIEW.perLo) * f / 2;
    VIEW.perLo = mid - h; VIEW.perHi = mid + h;
    clampView(); redraw();
  };
  $("per-up").onclick = () => panPer(1);
  $("per-down").onclick = () => panPer(-1);
  $("per-zin").onclick = () => zoomPer(0.5);
  $("per-zout").onclick = () => zoomPer(2);
  $("per-reset").onclick = () => {
    const ax = axisOf(PER_DATA);
    VIEW.perLo = ax[0]; VIEW.perHi = ax[1]; redraw();
  };
  $("per-auto").onclick = () => {
    const v = [];
    for (let i = VIEW.i0; i <= VIEW.i1; i++) {
      const x = PER_DATA.per_confirmed[i] ?? PER_DATA.per_estimated[i];
      if (x !== null && x !== undefined) v.push(x);
    }
    if (!v.length) return;
    // 꼬리 1% 는 버린다 — 한 점 때문에 나머지가 납작해지지 않게.
    v.sort((a, b) => a - b);
    const hi = v[Math.floor(v.length * 0.99)], lo = v[0];
    const pad = Math.max(1, (hi - lo) * 0.08);
    VIEW.perLo = Math.max(0, lo - pad); VIEW.perHi = hi + pad;
    clampView(); redraw();
  };

  const tip = $("tip");
  let drag = null;
  const svgNow = () => $("plot").querySelector("svg");

  const toIdx = (clientX) => {
    const r = svgNow().getBoundingClientRect();
    const x = ((clientX - r.left) / r.width) * W;
    const f = (x - PAD.l) / (W - PAD.l - PAD.r);
    return Math.round(VIEW.i0 + f * (VIEW.i1 - VIEW.i0));
  };

  $("plot").onmousedown = (ev) => {
    drag = { x: ev.clientX, i0: VIEW.i0, span: VIEW.i1 - VIEW.i0, moved: false };
    svgNow().classList.add("grabbing");
  };
  window.addEventListener("mouseup", () => {
    const el = $("plot").querySelector("svg");
    if (el) el.classList.remove("grabbing");
    drag = null;
  });
  $("plot").onmousemove = (ev) => {
    if (drag) {
      const r = svgNow().getBoundingClientRect();
      const dx = ((ev.clientX - drag.x) / r.width) * W;
      const shift = (dx / (W - PAD.l - PAD.r)) * drag.span;
      VIEW.i0 = drag.i0 - shift; VIEW.i1 = VIEW.i0 + drag.span;
      clampView();
      if (Math.abs(dx) > 2) { drag.moved = true; tip.classList.add("hidden"); redraw(); }
      return;
    }
    const i = toIdx(ev.clientX);
    if (i < VIEW.i0 || i > VIEW.i1) { tip.classList.add("hidden"); return; }
    const p = PER_DATA.per_confirmed[i], q = PER_DATA.per_estimated[i];
    const nm = PER_DATA.metric === "ev" ? "fwd EV/EBITDA" : "fwd PER";
    const mix = PER_DATA.metric === "ev" ? "가정 섞임" : "컨센 섞임";
    tip.innerHTML = `<b>${PER_DATA.dates[i]}</b><br/>주가 ${PER_DATA.close[i]}<br/>` +
      (p !== null && p !== undefined ? `${nm} <b>${p}</b> (확정)`
       : q !== null && q !== undefined ? `${nm} <b>${q}</b> (${mix})` : `${nm} —`);
    tip.classList.remove("hidden");
    const r = $("plot").getBoundingClientRect();
    tip.style.left = Math.min(r.width - 170, ev.clientX - r.left + 12) + "px";
    tip.style.top = (ev.clientY - r.top + 12) + "px";
  };
  $("plot").onmouseleave = () => tip.classList.add("hidden");

  // 휠로 기간 확대·축소. 커서가 가리키는 날짜를 제자리에 두고 늘렸다 줄인다.
  $("plot").onwheel = ((ev) => {
    ev.preventDefault();
    const r = svgNow().getBoundingClientRect();
    const f = Math.max(0, Math.min(1,
      (((ev.clientX - r.left) / r.width) * W - PAD.l) / (W - PAD.l - PAD.r)));
    const span = VIEW.i1 - VIEW.i0;
    const next = Math.max(MIN_BARS, Math.min(PER_DATA.dates.length - 1,
                                             Math.round(span * (ev.deltaY > 0 ? 1.3 : 0.77))));
    const anchor = VIEW.i0 + f * span;
    VIEW.i0 = anchor - f * next; VIEW.i1 = VIEW.i0 + next;
    clampView(); redraw();
  });

}

/* --------------------------------------------------------------------- 모달 */
const MODALS = {
  local: ["내 컴퓨터에서 띄우는 법 (윈도우)", `
<div class="warn">
<b>⚠ 서버가 도는 창을 닫으면 페이지가 죽습니다.</b> 그 창이 곧 서버입니다.
보는 동안에는 <b>계속 열어 두세요.</b> 최소화는 괜찮습니다.
</div>

<h4>처음 한 번 — 설치</h4>
<p class="muted">이미 돌려 보셨으면 <b>아래 "1. 폴더에서 Git Bash 열기"</b> 로 건너뛰세요.</p>
<ol>
  <li><b>Git 설치</b> — <code>git-scm.com/download/win</code> 에서 받아 설치.
      설치 중 선택지는 <b>전부 기본값(Next)</b> 으로 두면 됩니다. 이걸 깔아야
      우클릭 메뉴에 "Git Bash Here" 가 생깁니다.</li>
  <li><b>파이썬 설치</b> — <code>python.org/downloads</code> 에서 받아 설치.
      첫 화면 아래 <b>"Add python.exe to PATH" 를 반드시 체크</b>하고 Install.
      <br/><span class="muted">아나콘다가 이미 있으면 그걸 써도 됩니다. 다만
      아나콘다 파이썬과 Git Bash 의 파이썬이 <b>서로 다를 수 있어</b>,
      패키지를 깐 셸에서 실행해야 합니다.</span></li>
  <li><b>확인</b> — 아무 폴더에서 우클릭 → Git Bash Here 후:
      <pre>git --version
python --version</pre>
      둘 다 버전이 찍히면 됩니다. <code>command not found</code> 면 그 프로그램이
      아직 안 깔렸거나 PATH 에 없습니다(파이썬은 재설치하며 PATH 체크).</li>
  <li><b>코드 받기</b> — 코드를 둘 폴더(예: 바탕화면)에서 우클릭 →
      Git Bash Here 후:
      <pre>git clone https://github.com/uiheesin-ship-it/SUH_DH.git
cd SUH_DH</pre>
      <span class="muted">폴더가 하나 생깁니다. 다음부터는 그 <b>SUH_DH 폴더
      안에서</b> Git Bash 를 엽니다.</span></li>
  <li><b>패키지 설치</b> — 같은 창에서:
      <pre>pip install -r requirements.txt</pre>
      <span class="muted">몇 분 걸립니다. 한 번만 하면 됩니다.
      <code>pip</code> 가 없다고 하면 <code>python -m pip install -r requirements.txt</code>.</span></li>
  <li><b>실행</b> — <pre>./run.sh</pre></li>
</ol>
<div class="warn">
<b>이 단계에서 컴퓨터를 바꾸면 처음부터 다시 해야 합니다.</b> 코드는 GitHub 에
있으니 4번부터 하면 됩니다.
</div>

<hr/>
<h4>1. 폴더에서 <b>Git Bash</b> 열기</h4>
탐색기로 <code>SUH_DH</code> 폴더까지 들어간 다음, 빈 곳에서
<b>우클릭 → "Git Bash Here"</b>
<br/>(윈도우 11이면 우클릭 메뉴에서 <b>"추가 옵션 표시"</b> 를 먼저 눌러야 나옵니다)
<br/><br/>
제대로 열렸으면 프롬프트 끝이 이렇게 보입니다:
<pre>~/OneDrive/Desktop/주식/코딩/SUH_DH (claude/funny-carson-ent3s7)
$</pre>

<h4>2. 최신 코드 받기</h4>
<pre>git pull</pre>
<div class="warn">
<code>Already up to date.</code> 인데 바뀐 게 안 보이면 <b>다른 브랜치</b>에 있는
것입니다. <code>git branch --show-current</code> 로 확인하세요 —
<code>claude/funny-carson-ent3s7</code> 이어야 합니다.
</div>

<h4>3. 서버 띄우기</h4>
<pre>./run.sh</pre>
이게 찍히면 성공입니다:
<pre>INFO:  Application startup complete.
INFO:  Uvicorn running on http://127.0.0.1:8000</pre>

<div class="warn">
<b>꼭 Git Bash 를 직접 여세요.</b> PowerShell 에서 <code>./run.sh</code> 를 치면
윈도우가 그 파일을 <b>Git Bash 로 따로 열어</b> 검은 창이 하나 더 뜹니다.
PowerShell 쪽은 바로 프롬프트로 돌아와서 "안 돌고 있나?" 싶고, 정작 서버는 그
검은 창에 있어서 <b>그 창을 닫으면 서버가 죽습니다.</b> Git Bash 에서 바로
띄우면 <b>창이 하나</b>라 헷갈릴 일이 없습니다.
</div>

<h4>4. 브라우저에서 열기 — <code>http://</code> 를 꼭</h4>
<pre>http://localhost:8000/quarterly/</pre>
<div class="warn">
주소창에 <code>localhost:8000</code> 만 치면 요즘 브라우저가 <b>자동으로
<code>https://</code> 로 바꿔서</b> 무조건 실패합니다. <b>즐겨찾기에 넣어 두세요.</b>
</div>

<h4>끝낼 때</h4>
Git Bash 창에서 <b>Ctrl + C</b>.

<h4>코드가 바뀌었을 때</h4>
<b>받기만 하면 안 됩니다</b> — 이미 떠 있는 서버는 옛 코드를 메모리에 들고
있습니다. 껐다 다시:
<pre>Ctrl + C
git pull
./run.sh</pre>

<h4>PowerShell 로 하고 싶다면</h4>
됩니다. 다만 <b>파이썬이 두 개</b>라서 준비가 한 번 필요합니다. PowerShell 의
<code>python</code> 은 보통 아나콘다 파이썬이고, 거기엔 이 프로젝트의 패키지가
안 깔려 있습니다(<code>No module named uvicorn</code>). 처음 한 번만:
<pre>pip install -r requirements.txt</pre>
그 다음부터는
<pre>git pull
python -m uvicorn app.main:app --port 8000</pre>
<b>Git Bash 쪽이 간단합니다</b> — 이미 다 깔려 있으니까요.

<h4>안 될 때</h4>
<ol>
  <li><b>서버 창이 아직 열려 있나</b> — 제일 흔합니다.</li>
  <li><b><code>http://</code> 를 붙였나</b> — 두 번째로 흔합니다.</li>
  <li><code>No module named uvicorn</code> → 패키지가 없는 파이썬입니다.
      Git Bash 에서 <code>./run.sh</code> 로 하시거나,
      그 셸에서 <code>pip install -r requirements.txt</code>.</li>
  <li><code>bash: ./run.sh: Permission denied</code> →
      <code>bash run.sh</code> 로 하세요.</li>
  <li><code>address already in use</code> → 이미 떠 있습니다. 다른 창을 찾거나
      <code>SUH_DH_PORT=8001 ./run.sh</code> 로 포트를 바꾸세요.</li>
  <li>창을 하나 더 열어 <code>curl http://127.0.0.1:8000/api/health</code>.
      <code>{"status":"ok"}</code> 가 나오면 서버는 멀쩡하고 브라우저 문제입니다.</li>
  <li>회사 PC·VPN 이면 프록시 — Windows 설정 → 네트워크 및 인터넷 → 프록시 →
      <b>"로컬 주소에 프록시 서버 사용 안 함"</b> 체크.</li>
</ol>

<h4>처음 받는 컴퓨터라면</h4>
Git Bash 에서:
<pre>git clone https://github.com/uiheesin-ship-it/SUH_DH.git
cd SUH_DH
pip install -r requirements.txt
./run.sh</pre>

<h4>무시해도 되는 것</h4>
시작할 때 <code>eai subsystem not mounted: No module named 'sqlalchemy'</code> 가
찍힙니다. 실적 컨콜 프로그램만 안 뜨는 것이고 <b>이 페이지와는 무관합니다.</b>
`],

  basis: ["산정 기준 — EPS · EV · EBITDA · 계절성 배분", `
<p>숫자를 어떻게 만들었는지 전부 적어 둡니다. <b>기준이 바뀌면 값이 바뀝니다.</b>
바꾸고 싶은 곳이 있으면 말씀해 주세요 — 상수는 한군데 모아 뒀습니다.</p>

<h4>EPS — 두 기준을 다 씁니다</h4>
<table class="basis">
<tr><th>기준</th><th>과거</th><th>컨센</th></tr>
<tr><td><b>GAAP</b></td>
    <td>EDGAR <code>EarningsPerShareDiluted</code> (희석, 회사 제출 원본)</td>
    <td>없음 — 애널리스트는 GAAP 을 추정하지 않습니다</td></tr>
<tr><td><b>조정<br/>(non-GAAP)</b></td>
    <td>야후 <code>Reported EPS</code> — 회사가 보도자료에서 발표하고
        컨센과 대조되는 값</td>
    <td>야후 <code>earnings_estimate</code></td></tr>
</table>
<ul>
  <li><b>기본은 조정</b>입니다. 컨센과 같은 기준이라 실선→점선 경계에서 선이
      안 꺾입니다. GAAP 으로 그리면 주식보상이 큰 회사는 그 경계에서 PER 이
      인위적으로 뚝 떨어집니다(조정 EPS 가 GAAP 보다 크기 때문).</li>
  <li>조정 EPS 커버리지는 종목마다 다릅니다(실측: NVDA 49분기 / 2014년~).
      짧으면 그 구간만 GAAP 으로 물러섭니다.</li>
  <li>정정공시가 있으면 <b>실적 표는 마지막 제출본</b>, 과거 시점 계산은
      <b>첫 제출본</b>을 씁니다.</li>
</ul>

<h4>EBITDA — Adjusted EBITDA 가 <b>아닙니다</b></h4>
<pre>EBITDA = 영업이익(OperatingIncomeLoss)
       + 감가상각비(DepreciationDepletionAndAmortization 등)</pre>
<ul>
  <li><b>주식기준보상(SBC)은 되돌리지 않습니다.</b> 즉 SBC 가 <b>비용으로
      차감된 상태</b>입니다. 회사들이 말하는 "Adjusted EBITDA" 는 대개 SBC 를
      다시 더해 되돌리므로 <b>여기 값보다 큽니다.</b></li>
  <li>일회성 손익(구조조정·자산매각·소송)도 <b>빼지 않습니다.</b> 영업이익에
      들어 있으면 그대로 반영됩니다.</li>
  <li>감가상각은 현금흐름표에 <b>누적(YTD)</b> 으로 실리는 일이 많아 차분해서
      분기값을 만듭니다. 태그별로 따로 차분합니다.</li>
  <li>Adjusted EBITDA 는 비GAAP 이라 XBRL 에 없습니다(실측 4종목 전부 고유
      태그 0개). 회사마다 무엇을 빼는지 정의가 달라 비교도 안 됩니다.</li>
  <li><b>은행·보험은 영업이익 개념이 없어</b> EBITDA 도 만들지 않습니다.</li>
</ul>

<h4>EV/EBITDA — 어떻게 만드나</h4>
<pre>EV(t) = 주가(t) × 발행주식수
      + 총차입금 − 현금성자산 + 비지배지분 + 우선주

12M forward EV/EBITDA = EV(t) ÷ (t 이후 4개 분기 EBITDA 합)</pre>
<p>재무상태표는 분기에 한 번 바뀌므로 <b>PER 과 같은 실적발표일에 계단을 밟고</b>,
그 사이에는 주가만 움직입니다. 분기말에 밟으면 아직 공개되지 않은 재무상태표로
그 사이 주가를 나누게 됩니다.</p>
<table class="basis">
<tr><th>항목</th><th>포함</th><th>비고</th></tr>
<tr><td>시가총액</td><td>주가 × <b>기말 발행주식수</b></td>
    <td><code>CommonStockSharesOutstanding</code> → <code>CommonStockSharesIssued</code>
        → 표지의 <code>dei:EntityCommonStockSharesOutstanding</code> 순.
        가중평균주식수가 <b>아닙니다</b></td></tr>
<tr><td>장기차입금</td><td>✅ 유동·비유동 전부</td>
    <td><code>LongTermDebtNoncurrent</code> / <code>…Current</code></td></tr>
<tr><td><b>전환사채</b></td><td>✅ 포함 — <b>금액으로 판정</b>해서 더합니다</td>
    <td>대개 <code>LongTermDebtNoncurrent</code> 안에 이미 들어 있어 또 더하면
        <b>이중계상</b>입니다. 그렇다고 늘 빼면 반대로 누락됩니다 — 실측(SMCI)에서
        장·단기 합계 4.06B 과 전환사채 4.66B 이 <b>별개로</b> 잡혔고, 둘을 더해야
        야후 값과 맞았습니다. 그래서 <b>합계 ≥ 전환사채면 안에 있다고 보고 빼고,
        합계 &lt; 전환사채면 별개로 보고 더합니다</b> — 합계가 부분보다 작을 수는
        없다는 산수 하나에 기대는 규칙이라 태그 이름 추측보다 튼튼합니다.
        전환을 가정해 주식수에 더하지는 <b>않습니다</b></td></tr>
<tr><td><b>단기사채·CP</b></td><td>✅ 포함</td>
    <td><code>ShortTermBorrowings</code> / <code>CommercialPaper</code> — 이자부 부채</td></tr>
<tr><td><b>운용리스부채</b></td><td>✅ 포함</td>
    <td>ASC842 이후 재무상태표에 올라오므로 차입금으로 봅니다</td></tr>
<tr><td><b>금융리스부채</b></td><td>✅ 포함(중복이면 제외)</td>
    <td>회사가 <code>LongTermDebtAndCapitalLeaseObligations</code> 를 썼다면 그 안에
        이미 들어 있으므로 <b>따로 더하지 않습니다</b></td></tr>
<tr><td>현금성자산</td><td>➖ 차감</td>
    <td>현금 + <b>단기투자자산</b>. 장기투자·지분증권은 빼지 않습니다.
        실측(AAPL 2026-06-27)으로 이 조합이 야후 <code>totalCash</code> 와
        <b>정확히 일치</b>했습니다</td></tr>
<tr><td>비지배지분</td><td>✅ 가산</td>
    <td><code>MinorityInterest</code> <b>하나만</b> 씁니다.
        <code>StockholdersEquityIncluding…NoncontrollingInterest</code> 는 이름이
        비슷하지만 <b>자본 총계</b>라, 쓰면 EV 가 자본만큼 부풀어 오릅니다</td></tr>
<tr><td>우선주</td><td>✅ 가산</td><td><code>PreferredStockValue</code> 장부금액</td></tr>
<tr><td>연금부채</td><td>❌ 제외</td><td>넣는 유파도 있지만 안 넣습니다</td></tr>
</table>
<p><b>개념마다 버킷을 두고, 한 버킷에서는 그 날짜에 잡히는 첫 태그 하나만
씁니다.</b> 한 날짜에 태그 하나만 쓰는 것이 이중계상을 막는 규칙입니다.
회사 전체에서 태그 하나를 골라 통째로 쓰면, <b>회사가 자금조달 수단을 바꾼
구간이 통째로 0</b> 이 됩니다 — 실측(SMCI)에서 옛 은행 차입 태그가 버킷을
차지하는 바람에 지금의 전환사채 9B 가 통째로 빠져 EV 가 야후보다 41% 작게
나왔습니다. 날짜별로 우선순위를 다시 매기면 양쪽 구간이 다 맞고, 같은 날짜에
합계와 전환사채가 둘 다 있으면 합계가 이기므로 이중계상도 그대로 막힙니다.</p>
<p>분기말 <b>이전 100일</b> 안의 값만 그 분기 것으로 봅니다. <b>이후는 45일</b>
까지만 엽니다 — 뒤로 한 분기를 열면 <b>다음 분기 재무상태표</b>가 끌려 들어와
그 발표 시점에 몰랐던 값이 과거 차트에 새어 듭니다. 45일을 여는 건 표지(dei)의
발행주식수가 제출일 기준이라 분기말보다 2~4주 늦게 찍히기 때문입니다(그건 그
분기 보고서와 같이 공개되므로 발표 시점에 알 수 있습니다).</p>
<div class="warn">
<b>없는 항목은 0 으로 채우지 않습니다.</b> 회사마다 쓰는 태그가 천차만별입니다
(실측: PLD 는 <code>LongTermDebt</code> 하나뿐이고 유동차입금·CP·전환사채·리스부채
태그가 <b>아예 없습니다</b>). 무엇이 없었는지 차트 아래에 그대로 적어 둡니다.
</div>
<p>야후의 <code>totalDebt</code> 와는 <b>일부러 다릅니다</b> — 야후는 리스부채를
빼고, 여기는 넣습니다(실측 AAPL 기준 12.5B 차이). <b>EBITDA 에서 리스비용을
되돌리지는 않으므로</b> 리스가 큰 회사(유통·항공)의 EV/EBITDA 는 <b>높게</b>
나옵니다. 야후의 분기 재무상태표는 7분기뿐이라 5년을 못 그립니다 — EDGAR 는
59~70분기가 잡혀서 EDGAR 를 씁니다.</p>

<h4>EV/EBITDA 의 점선 — <b>컨센이 아니라 가정</b>입니다</h4>
<p><b>EBITDA 컨센을 주는 무료 출처가 없습니다</b>(야후·Alpha Vantage 에는 항목
자체가 없고 FMP 는 유료). 그렇다고 가장 궁금한 최근 1년을 통째로 비워 둘 수는
없어서, 이렇게 만듭니다.</p>
<pre>① 매출 컨센을 <b>PER 과 똑같은 계절성 규칙</b>으로 분기에 나눈다
② 마진 = 최근 8분기 (EBITDA ÷ 매출) 의 <b>중앙값</b>   ← 평균 아님
③ 추정 분기 EBITDA = 분기 매출 컨센 × 마진</pre>
<ul>
  <li>그래서 점선 구간은 <b>컨센이 아니라 가정</b>입니다. 차트 아래에 쓰인 마진과
      그 마진의 최근 최저~최고 범위를 같이 보세요 — 마진이 흔들리는 회사면
      그만큼 빗나갑니다.</li>
  <li>매출 컨센이 없거나 마진을 못 구하면 <b>점선을 아예 그리지 않습니다.</b></li>
  <li>EBITDA 합이 0 이하이거나 EV 가 음수(순현금이 시총보다 큰 회사)면 그 구간의
      배수를 <b>비웁니다</b> — 음수 배수는 읽는 사람을 속입니다.</li>
  <li><b>은행·보험은 영업이익 개념이 없어</b> EBITDA 도, EV/EBITDA 도 만들지 않습니다.</li>
</ul>

<h4>계절성 배분 — 연간 컨센을 분기에 나누는 법</h4>
<p>야후는 분기 컨센을 <b>두 개</b>만 줍니다. 12개월을 채우려면 나머지는 연간
추정에서 만들어야 하는데, <b>÷4 는 계절성이 큰 회사를 크게 틀어지게</b> 합니다
(애플 4분기, 유통 연말). 그래서 과거 비중으로 나눕니다.</p>
<pre>① 비중 구하기 — 최근 3개 완결 회계연도
     w[해][분기] = 그 분기 실적 ÷ 그 해 4분기 합
     w[분기]     = 연도별 w 의 <b>중앙값</b>   ← 평균 아님(한 해 이상치 방어)
     정규화: w[분기] ← w[분기] ÷ Σw

   버리는 해: 네 분기가 다 없는 해 · 연간 합이 0 이하인 해(적자)

② 믿을 수 있나
     spread[분기] = max(연도별 w) − min(연도별 w)
     max(spread) > <b>0.15</b>          → 계절성이 해마다 달라 못 믿음 → <b>균등</b>
     쓸 수 있는 해 < <b>2개</b>          → <b>균등</b>

③ 나누기
     잔여 = 연간 컨센 − 이미 확정된 그 해 분기 합
     분기 추정 = 잔여 × w[그 분기] ÷ Σ(남은 분기들의 w)

     잔여 ≤ 0 이면 <b>배분하지 않습니다</b> — 음수를 지어내는 대신 비워 두고
     "이미 확정된 분기 합이 연간 추정을 넘었습니다" 라고 적습니다.</pre>
<p><b>성장 추세는 여기서 다루지 않습니다.</b> 추세는 연간 컨센이 이미 담고
있고, 여기서는 한 해 <b>안의 배분</b>만 봅니다. 그래서 꾸준히 성장하는 회사도
뒤 분기 비중이 자연히 커집니다.</p>
<p>손잡이 세 개는 <code>app/forwardper.py</code> 맨 위에 모여 있습니다 —
<code>SEASON_YEARS = 3</code>, <code>SEASON_TOL = 0.15</code>,
<code>SEASON_MIN_YEARS = 2</code>. 바꾸고 싶으시면 말씀해 주세요.</p>
<p>차트 위에 이번 종목이 <b>계절성</b>으로 나뉘었는지 <b>균등</b>으로 물러섰는지,
그리고 그 이유가 표시됩니다.</p>

<h4>손으로 고칠 때의 규칙</h4>
<p>배분이 미덥지 않으면 차트 아래 <b>"추정 분기 EPS"</b> 에서 직접 고칠 수
있습니다. 고치면 PER 차트가 그 자리에서 다시 그려집니다(서버를 다시 부르지
않습니다). 규칙은 하나입니다.</p>
<pre>한 회계연도 안에서
   (확정 분기 합) + (손으로 넣은 값 합)  ≤  그 해 FY 컨센</pre>
<ul>
  <li>넘으면 <b>빨갛게</b> 표시되고 <b>저장되지 않습니다.</b> 화면에는 계속
      반영되므로 얼마나 넘었는지 보면서 되돌릴 수 있습니다.</li>
  <li>칸마다 <b>"이 칸 최대 X"</b> 가 같이 뜹니다 — 그 해 다른 칸 값을 고려한
      잔여입니다.</li>
  <li>연간 컨센이 없는 해는 <b>한도 검사를 하지 않습니다</b>(비교할 기준이 없음).</li>
  <li>고친 값은 <b>이 브라우저에 티커·EPS 기준별로</b> 저장됩니다. GAAP 과 조정을
      따로 기억합니다. <b>원래대로</b> 버튼으로 지웁니다.</li>
  <li>손댄 분기가 들어간 창은 <b>더 이상 확정으로 치지 않습니다</b> — 실선이던
      구간도 점선으로 바뀝니다.</li>
</ul>
`],

  per: ["12M Forward PER 을 어떻게 구하나", `
<h4>정의</h4>
어떤 과거 시점 T 의 12M forward PER 은 <code>T 시점 주가 ÷ (T 이후 4개 분기 EPS 합)</code>
입니다. 2024년 1분기 실적이 발표된 날이라면, 그 시점부터 앞으로 네 분기
(2024 Q2·Q3·Q4 + 2025 Q1)의 EPS 를 더해 나눕니다.

<h4>왜 <b>실적발표일</b>인가</h4>
2024년 1분기는 3월 31일에 끝나지만 시장이 그 숫자를 아는 건 4월 하순입니다.
재무정보 기준일(분기말)에 계단을 밟으면 <b>아직 공개되지 않은 실적으로 그 사이
주가를 나누게</b> 됩니다 — 미래 정보가 과거 차트에 새어 듭니다. 그래서 계단은
발표일에 밟고, 기준일은 차트에 <b>같이 표시만</b> 합니다.
<ul>
  <li>발표일은 야후의 실제 발표일(<code>get_earnings_dates</code>)을 씁니다.</li>
  <li>없으면 EDGAR 제출일로 물러섭니다 — 보도자료보다 며칠 늦지만 기준일보다는 훨씬 낫습니다.</li>
</ul>

<h4>실선과 점선</h4>
네 분기가 <b>모두 확정 실적</b>이면 실선, <b>한 분기라도 컨센서스</b>가 섞이면
점선입니다. 컨센이 섞이는 건 마지막 1년 남짓뿐입니다 — T 가 1년보다 예전이면
그 네 분기는 이미 다 발표됐기 때문입니다.

<h4>여기서 솔직히 말해 둘 것</h4>
과거 시점의 <b>그 당시</b> 컨센서스는 무료로 구할 수 없습니다. 그래서 과거 구간의
실선은 "그때 시장이 기대하던 PER" 이 아니라 <b>"지나고 보니 그때 주가가 실제
향후 4분기 이익의 몇 배였나"</b> 입니다. 다른 이야기라 그대로 적어 둡니다.

<h4>PER 이 비는 구간</h4>
향후 4분기 EPS 합이 <b>0 이하면 PER 을 내지 않습니다</b>. 적자 구간의 PER 은
음수로 나와 차트도 독해도 망가뜨립니다. 차트에서 선이 끊긴 자리가 그곳입니다.
`],
  src: ["실적과 컨센을 어디서 가져오나", `
<h4>실적 — EDGAR XBRL</h4>
<code>data.sec.gov/api/xbrl/companyfacts</code> 에서 받습니다. 회사가 SEC 에 제출한
원본이라 가장 신뢰할 수 있고 무료입니다. 미리 전 종목을 모으지 않고 <b>입력한
티커만</b> 그때 받습니다.
<ul>
  <li><b>10-Q 는 3개월·9개월 수치를 같이 싣습니다</b> → 기간 길이(80~100일)로 거릅니다.</li>
  <li><b>10-K 는 4분기를 따로 안 싣습니다</b> → Q4 = 연간 − (Q1+Q2+Q3) 로 역산합니다.
      단 가중평균주식수는 합이 아니라 평균이라 4×연평균 − 3분기 로 되돌립니다.</li>
  <li><b>회사가 중간에 태그를 갈아탑니다</b> → 한 태그에서 멈추지 않고 빈 분기를 메웁니다.</li>
  <li><b>정정공시</b>가 있습니다 → 분기마다 첫 제출본과 마지막 제출본을 둘 다 들고 있습니다.</li>
</ul>

<h4>계산해서 만드는 항목</h4>
<b>EBITDA 는 Adjusted EBITDA 가 아닙니다.</b> Adjusted EBITDA 는 비GAAP 이라
XBRL 에 없고(실측 4종목 전부 고유 태그 0개) 회사마다 무엇을 빼는지 정의가
다릅니다. 여기 값은 <b>영업이익 + 감가상각</b>인 순수 계산값입니다. 감가상각도
현금흐름표에 누적(YTD)으로 실리는 일이 많아 차분해서 분기값을 만듭니다.
<br/><br/>
<b>은행·보험은 매출·영업이익 태그가 아예 없습니다.</b> 매출은 총수익
(순이자이익 + 비이자이익)으로 만들고, 영업이익은 개념이 없어 "해당 없음" 으로
둡니다 — 억지로 채우지 않습니다.

<h4>컨센서스 — 야후</h4>
실측(8종목, 2026-09-17) 결과 무료로 모두 받을 수 있었습니다.
<ul>
  <li><code>earnings_estimate</code> — 분기 EPS 컨센 <b>0q·+1q</b>, 연간 <b>0y·+1y</b>, 애널리스트 수까지</li>
  <li><code>get_earnings_dates</code> — 과거 <b>실제 발표일</b> 12~50개 + 다가올 예정일</li>
  <li><code>revenue_estimate</code> — 같은 모양의 매출 컨센</li>
</ul>
분기 컨센은 <b>둘뿐</b>이라 12개월을 채우려면 둘이 모자랍니다. 나머지는 연간
추정에서 <b>이미 발표된 분기를 빼고</b> 남은 분기에 고르게 나눕니다 — 연간÷4 로
하면 계절성이 큰 회사가 크게 틀어집니다.

<h4>주가</h4>
야후 일봉 종가(최근 5년). 컨센이나 주가를 못 받아도 확정 구간은 그려집니다.
`],
};

function openModal(key) {
  const [title, body] = MODALS[key];
  $("modal-title").textContent = title;
  $("modal-body").innerHTML = body;
  $("modal").classList.remove("hidden");
}

/* --------------------------------------------------------------------- 시작 */
$("go").addEventListener("click", () => load($("q").value));
$("q").addEventListener("keydown", (e) => { if (e.key === "Enter") load($("q").value); });
$("per-btn").addEventListener("click", () => openModal("per"));
$("src-btn").addEventListener("click", () => openModal("src"));
$("local-btn").addEventListener("click", () => openModal("local"));
$("basis-btn").addEventListener("click", () => openModal("basis"));
document.querySelectorAll(".eb").forEach((b) =>
  b.addEventListener("click", () => { BASIS = b.dataset.basis; showBasis(BASIS); }));
document.querySelectorAll(".mt").forEach((b) =>
  b.addEventListener("click", () => showMetric(b.dataset.metric)));
$("edit-reset").addEventListener("click", () => {
  OVERRIDE = {};
  saveOverrides();
  if (PER_DATA && BASES[PER_DATA.eps_basis]) showBasis(PER_DATA.eps_basis);
});
$("edit-toggle").addEventListener("click", () => {
  const body = $("edit-body");
  const open = body.classList.toggle("hidden");
  $("edit-toggle").textContent = open ? "펼치기" : "접기";
  $("edit-toggle").classList.toggle("on", !open);
});
$("modal-close").addEventListener("click", () => $("modal").classList.add("hidden"));
$("modal").addEventListener("click", (e) => {
  if (e.target === $("modal")) $("modal").classList.add("hidden");
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") $("modal").classList.add("hidden");
});

const initial = new URLSearchParams(location.search).get("t");
if (initial) { $("q").value = initial; load(initial); }
