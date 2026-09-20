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

/* 백엔드가 보내는 설명 문장의 **강조**를 굵게 바꾼다.
 *
 * 파이썬 쪽 문장은 로그·프로브에서도 그대로 읽히므로 마크다운 표기를 쓴다.
 * 그런데 화면은 그걸 innerHTML 에 그냥 넣고 있어서 별표가 **그대로 찍혔다.**
 * 여기서 한 번만 바꾼다. 우리 문장이라 이스케이프는 하지 않는다.
 */
const md = (t) => (t == null ? "" : String(t).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>"));

/* 원화는 조·억으로 읽는다.
 *
 * 국장 금액을 B/M 로 보여 주면 읽을 수가 없다(삼성전자 분기 매출 86.06B 원).
 * 조·억은 한국에서 실제로 쓰는 자릿수라 그대로 쓴다.
 */
const fmtKrw = (v) => {
  if (v === null || v === undefined) return "—";
  const a = Math.abs(v);
  if (a >= 1e12) return (v / 1e12).toFixed(2) + "조";
  if (a >= 1e8) return (v / 1e8).toFixed(0) + "억";
  if (a >= 1e4) return (v / 1e4).toFixed(1) + "만";
  return v.toFixed(0);
};

let DATA = null;
let MARKET = "us";               // "us" | "kr"
const isKR = () => MARKET === "kr";

/* ------------------------------------------------------------------ 불러오기 */
async function load(ticker) {
  const t = (ticker || "").trim().toUpperCase();
  if (!t) return;
  if (isKR() && !/^\d{6}$/.test(t)) {
    fail("국장은 **여섯 자리 종목코드**로 찾습니다.",
         "예: 삼성전자 005930 · SK하이닉스 000660 · NAVER 035420");
    return;
  }
  $("status").textContent = `${t} 불러오는 중…`;
  $("empty").classList.add("hidden");
  history.replaceState(null, "", `?t=${encodeURIComponent(t)}&m=${MARKET}`);

  if (STATIC && !API_BASE) {
    fail("이 페이지는 티커를 입력받은 뒤에 EDGAR·야후에서 직접 받아 옵니다. " +
         "그래서 서버가 필요합니다 — 왼쪽 위 '💻 로컬 실행법' 버튼을 눌러 보세요.");
    return;
  }
  try {
    const path = isKR() ? "/api/kr/fundamentals/" : "/api/fundamentals/";
    const r = await fetch(`${API_BASE}${path}${encodeURIComponent(t)}`,
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
  MARKET = d.market === "kr" ? "kr" : "us";
  syncMarket();
  $("status").textContent = `${d.ticker} · ${d.name || ""}`;
  const bits = [`<b>${d.name || d.ticker}</b>`];
  if (d.sic) bits.push(d.sic);
  if (d.cik) bits.push(`CIK ${d.cik}`);
  if (d.corp_code) bits.push(`DART ${d.corp_code}`);
  if (isKR()) bits.push("단위 원");
  if (d.backend && d.backend.rev) {
    // 브랜치까지 적는다 — "pull 했는데 왜 그대로지" 의 진짜 원인이 대개 이것이다.
    bits.push(`서버 ${d.backend.branch ? d.backend.branch + " " : ""}${d.backend.rev}`);
  }
  if (d.fiscal_year_end) bits.push(`결산 ${d.fiscal_year_end}`);
  let head = bits.join(" · ");
  for (const n of d.notes || []) head += `<span class="warn">⚠ ${md(n)}</span>`;

  // 서버가 옛 코드로 돌고 있으면 화면이 **사실로** 말한다.
  //
  // JS·CSS 는 디스크에서 매번 읽히지만 파이썬은 **서버가 뜰 때 메모리에** 올라간다.
  // git pull 만 하고 재시작을 안 하면 화면은 새것, 백엔드는 옛것이 된다. 겉으로는
  // "왜 새 칸이 안 나오지?" 로만 보여서 매번 한참 헤맸다.
  //
  // 예전에는 "컨센 칸이 없으면 옛 코드겠거니" 로 **짐작**했다. 그러면 그 기능만
  // 잡고 다음 기능은 또 못 잡는다. 이제 백엔드가 뜬 시각과 파일 수정 시각을 같이
  // 보내므로(app/buildinfo.py) 시계 두 개를 비교해 확실히 안다.
  const bi = d.backend;
  if (bi && bi.stale) {
    head += `<span class="warn">⚠ <b>서버가 옛 코드로 돌고 있습니다</b> —
      코드 파일이 서버보다 <b>${bi.stale_by_min}분</b> 새것입니다.
      <code>git pull</code> 은 됐는데 <b>서버를 다시 안 띄운</b> 것입니다.
      서버 창에서 <b>Ctrl+C</b> → <b>./run.sh</b>.
      그래도 그대로면 브라우저에서 <b>Ctrl+Shift+R</b>(강력 새로고침).
      <small>서버 시작 ${(bi.started_at || "").replace("T", " ").slice(0, 16)} ·
      코드 ${(bi.code_mtime || "").replace("T", " ").slice(0, 16)}</small></span>`;
  } else if (!bi) {
    // backend 자체가 안 오면 그 기능이 생기기 전 코드다 — 그것도 옛 코드다.
    head += `<span class="warn">⚠ <b>서버가 옛 코드로 돌고 있습니다</b>(버전 정보를
      안 보냅니다). <code>git pull</code> 후 서버 창에서 <b>Ctrl+C</b> →
      <b>./run.sh</b> 로 다시 띄우세요. (왼쪽 위 <b>💻 로컬 실행법</b>)</span>`;
  }
  $("head").innerHTML = head;

  // 표의 기준은 차트 기본값을 따른다. 응답에 차트가 없어도(표만 나오는 종목)
  // 표 자체가 기준을 알고 있으므로 거기서 받는다.
  BASIS = d.per_basis || (d.metrics && d.metrics["희석EPS"] || {}).basis || "gaap";
  renderMetrics(d.metrics || {}, d.forecast_note);
  $("table-sec").classList.remove("hidden");

  EV_DATA = d.ev || null;
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

/* 기준이 여러 벌인 항목은 **고른 기준의 자료**를 쓴다.
 *
 * 희석EPS 가 그렇다. 차트는 진작 GAAP·조정을 따로 그렸는데 표는 한 줄이었고,
 * 그 한 줄이 확정은 GAAP·추정은 조정 컨센이라 기준이 섞여 있었다 — 차트에서
 * 없앤 바로 그 문제다. 기준은 차트 토글과 **같은 값**을 쓴다. 한 페이지에
 * 기준이 두 개 떠 있으면 어느 쪽을 보고 있는지 알 수가 없다.
 */
function basisOf(m) {
  if (!m.bases) return m;
  return m.bases[BASIS] || m.bases[m.basis] || Object.values(m.bases)[0];
}

function renderMetrics(metrics, note) {
  const out = [];
  for (const label of Object.keys(metrics)) {
    const m0 = metrics[label];
    const m = { ...m0, ...basisOf(m0) };
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
    // 국장은 원 단위다 — EPS 는 원 단위 정수, 금액은 조·억.
    const fmt = (v) => (v === null || v === undefined ? "—"
                        : isRatio ? (isKR() ? Math.round(v).toLocaleString() : v.toFixed(2))
                        : isKR() ? fmtKrw(v) : fmtBig(v));

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

    const why = est.reason ? `<p class="note">⚠ ${md(est.reason)}</p>` : "";
    // 기준이 여러 벌이면 제목 옆에서 고른다. 차트 토글과 같은 값을 움직인다.
    // 차트 토글과 **같은 순서**로 둔다 — 같은 개념이 자리를 바꾸면 눈이 헤맨다.
    const ORDER = ["adjusted", "gaap"];
    const names = Object.keys(m0.bases || {})
      .sort((a, b) => (ORDER.indexOf(a) + 1 || 9) - (ORDER.indexOf(b) + 1 || 9));
    const picker = names.length < 2 ? "" :
      `<span class="mbasis">${names.map((n) =>
        `<button class="mb${n === BASIS ? " on" : ""}" data-basis="${n}"
           title="${(m0.bases[n].label || "").replace(/"/g, "")}">${
          n === "adjusted" ? "조정" : n === "gaap" ? "GAAP" : n}</button>`).join("")}</span>`;
    out.push(`<div class="mtable">
      <h3>${label} ${picker}<span class="src">${m.source}</span>
        ${est.source && est.source !== "없음"
          ? `<span class="src est-src">컨센: ${est.source}</span>` : ""}</h3>
      ${m0.basis_note && names.length > 1
        ? `<p class="note">${md(m0.basis_note)}</p>` : ""}
      ${m.note ? `<p class="note">⚠ ${md(m.note)}</p>` : ""}
      ${m.warning ? `<p class="note">⚠ ${md(m.warning)}</p>` : ""}
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
    (note ? `<p class="sec-desc forecast-note">${md(note)}</p>` : "") + out.join("");

  // 표를 **오른쪽 끝으로 밀어 둔다.**
  //
  // 20분기가 가로로 깔려 있어서 왼쪽 끝에서 시작하면 2021년 숫자만 보인다.
  // 컨센 칸은 맨 오른쪽이라 한참 굴려야 나오고, 그래서 "추정치 칸이 안 보인다"
  // 가 된다. 최근 분기와 컨센이 먼저 보이는 게 맞다 — 과거를 보고 싶으면
  // 왼쪽으로 굴리면 된다.
  // **레이아웃이 끝난 뒤에** 민다. innerHTML 직후에는 scrollWidth 가 아직
  // 제자리를 못 잡아 첫 로드에서만 안 밀리는 일이 있었다(그게 "추정치 칸이 안
  // 보여" 의 남은 절반이었다). 다음 프레임에 한 번 더 민다.
  const toRight = () => document.querySelectorAll("#metrics .table-wrap")
    .forEach((el) => { el.scrollLeft = el.scrollWidth; });
  toRight();
  requestAnimationFrame(toRight);
  document.querySelectorAll("#metrics .mb").forEach((b) =>
    b.onclick = () => setBasis(b.dataset.basis));
}

/* 기준 하나를 페이지 전체에 건다 — 차트와 표가 따로 놀면 안 된다. */
function setBasis(name) {
  if (BASIS === name) return;
  BASIS = name;
  if (DATA) renderMetrics(DATA.metrics || {}, DATA.forecast_note);
  if (BASES[name]) showBasis(name);
  else document.querySelectorAll(".eb").forEach((b) =>
    b.classList.toggle("on", b.dataset.basis === name));
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
  const num = (v) => (v === null || v === undefined ? "—"
                      : isKR() ? fmtKrw(v) : fmtBig(v));
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
    if (per.live_shares) {
      const L2 = per.live_shares;
      html += `<br/><span class="m season warn">가장 최근 구간만 <b>오늘 주식수</b>로
        계산했습니다 — 분기말 ${num(L2.from)} → 오늘 <b>${num(L2.to)}</b>
        (${(L2.change * 100).toFixed(1)}%). 분기말 이후 증자·자사주 소각이 있으면
        그 구간 시총이 틀어지기 때문입니다. <b>과거 구간은 그대로</b> 그때의
        주식수를 씁니다.</span>`;
    }
    if (per.estimate_note) {
      html += `<br/><span class="m season warn">${md(per.estimate_note)}
        ${per.margin_why && per.margin_why.quarters
          ? `(최근 ${per.margin_why.quarters}분기 · 최저 ${(per.margin_why.low * 100).toFixed(1)}%
             ~ 최고 ${(per.margin_why.high * 100).toFixed(1)}%)` : ""}</span>`;
    }
    html += `<br/><span class="m small">EBITDA 출처: ${per.ebitda_source || "—"}</span>`;
  } else if (per.kr_fill) {
    // 국장은 컨센 지평이 좁아서 **무엇으로 채웠는지**가 곧 신뢰도다.
    const f = per.kr_fill;
    const bits = Object.entries(f).filter(([, n]) => n)
      .map(([k, n]) => `${k} ${n}분기`);
    html += `<br/><span class="m season ${f["직전 해 × 성장률"] ? "warn" : "ok"}">` +
      `추정 분기를 채운 방법: <b>${bits.join(" · ") || "없음"}</b>` +
      (per.kr_growth ? ` · 성장률 ${per.kr_growth}배` : "") +
      (per.kr_growth_capped
        ? ` <b>(올해 성장률 ${per.kr_raw_growth}배는 내년까지 이어 쓰기엔 지나쳐
            성장 없음으로 물러섰습니다)</b>` : "") +
      ` <a href="#" class="basis-link">산정 기준 보기</a></span>`;
    if (per.season) {
      html += `<br/><span class="m season ${per.season.mode === "계절성" ? "ok" : "warn"}">` +
        `연간 컨센 → 분기 배분: <b>${per.season.mode}</b>` +
        (per.season.mode === "계절성"
          ? ` (1Q ${(per.season.weights["1"] * 100).toFixed(0)}% · ` +
            `2Q ${(per.season.weights["2"] * 100).toFixed(0)}% · ` +
            `3Q ${(per.season.weights["3"] * 100).toFixed(0)}% · ` +
            `4Q ${(per.season.weights["4"] * 100).toFixed(0)}%)`
          : ` — ${(per.season.why || {}).reason || ""}`) + `</span>`;
    }
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

/* 시장 고르기. 티커 체계가 달라서 서로 남은 입력을 지운다 —
 * "005930" 을 미장에서, "NVDA" 를 국장에서 찾는 건 늘 실패다. */
function syncMarket() {
  document.querySelectorAll(".mk").forEach((b) =>
    b.classList.toggle("on", b.dataset.market === MARKET));
  $("q").placeholder = isKR() ? "종목코드 여섯 자리 (예: 005930)" : "티커 입력 (예: NVDA)";
}

function setMarket(m) {
  if (MARKET === m) return;
  MARKET = m;
  syncMarket();
  $("q").value = "";
  $("q").focus();
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
제대로 열렸으면 프롬프트 끝이 이렇게 보입니다(괄호 안은 지금 서 있는 브랜치):
<pre>~/OneDrive/Desktop/주식/코딩/SUH_DH (브랜치이름)
$</pre>

<h4>2. 최신 코드 받기</h4>
<pre>git pull</pre>
<div class="warn">
<b><code>Already up to date.</code> 인데 바뀐 게 안 보이면 브랜치 문제입니다.</b>
<code>git pull</code> 은 <b>지금 서 있는 브랜치</b>만 따라갑니다. 새 작업이 다른
브랜치에 있으면 pull 은 "받을 게 없다" 고 답하고, 서버를 아무리 다시 띄워도
옛 코드가 돕니다.
<pre>git branch --show-current   # 지금 어디에 서 있나
git fetch --all
git branch -r --sort=-committerdate | head   # 최근에 올라간 브랜치들</pre>
다른 브랜치로 옮기려면:
<pre>git checkout -B &lt;브랜치이름&gt; origin/&lt;브랜치이름&gt;</pre>
<b>지금 서버가 어느 브랜치·커밋으로 도는지는 화면이 말해 줍니다</b> — 종목을
조회하면 이름 줄 끝에 <code>서버 &lt;브랜치&gt; &lt;해시&gt;</code> 가 붙습니다.
그게 GitHub 에서 본 최신 커밋과 다르면 아직 그 코드가 아닙니다.
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

<h4>3-1. 국장(🇰🇷)을 쓰려면 — DART 키 한 줄</h4>
<p>미장은 키가 필요 없습니다. <b>국장만</b> DART 무료 API 키가 필요합니다
(<code>opendart.fss.or.kr</code> → 가입 → 인증키 신청, 1분·무료).
받은 키를 서버 띄우기 <b>전에</b> 한 줄 넣으세요.</p>
<pre>export DART_API_KEY=여기에받은키
./run.sh</pre>
<p class="muted">창을 닫으면 사라집니다. 매번 치기 싫으면 <code>SUH_DH</code> 폴더의
<code>~/.bashrc</code> 에 그 줄을 넣어 두면 됩니다. 키를 안 넣고 국장을 조회하면
화면이 "DART_API_KEY 가 없습니다" 라고 말해 줍니다 — 조용히 빈 화면이 되지는
않습니다.</p>

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
<div class="warn">
<b>"다시 띄웠는데 왜 그대로지"</b> 의 원인은 거의 둘입니다.
<ol>
  <li><b>서버 창이 두 개</b>입니다. 한쪽만 껐고 브라우저는 옛 코드가 도는 쪽을
      보고 있습니다. 이제 <code>./run.sh</code> 가 먼저 확인해서
      <b>"이미 …에서 서버가 돌고 있습니다"</b> 라고 말하고 멈춥니다.</li>
  <li><b>브라우저가 옛 화면을 캐시</b>하고 있습니다 →
      <b>Ctrl + Shift + R</b>(강력 새로고침).</li>
</ol>
둘 다 아니면 화면 맨 위 종목 이름 줄에 <b>⚠ 서버가 옛 코드로 돌고 있습니다</b>
가 뜹니다 — 코드 파일이 서버보다 몇 분 새것인지까지 적혀 나옵니다.
</div>

<h4>지금 도는 서버가 새 코드인지 한 줄로 확인</h4>
<pre>curl -s http://127.0.0.1:8000/api/health</pre>
<p><code>"backend"</code> 안의 <code>branch</code>·<code>rev</code>(커밋 해시)와
<code>stale</code> 을 보세요. <code>"stale": true</code> 면 <b>파일이 서버보다 새것</b> — 재시작이
필요합니다. <code>backend</code> 항목 자체가 없으면 그것도 옛 코드입니다.
화면 맨 위 종목 이름 줄에도 <b>서버 &lt;해시&gt;</b> 로 같이 뜹니다.</p>

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

  basis: ["산정 기준 — EPS · EV · EBITDA · 계절성 배분 · 국장", `
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
<tr><td>우선주</td><td>✅ 가산</td>
    <td><b>액면이 아니라 장부금액</b>입니다.
        <code>PreferredStockIncludingAdditionalPaidInCapital</code> 을 먼저 쓰고
        없으면 <code>PreferredStockValue</code>(액면). 액면만 보면 우선주가 있어도
        0 으로 잡힙니다 — 실측(SMCI)에서 액면 0 · 장부 4.23B 이었고, 그 4.23B 이
        야후 EV 와의 차이와 <b>정확히 같았습니다</b>.
        상환우선주 등 <b>임시자본</b>(<code>TemporaryEquityCarryingAmount…</code>)도
        따로 더합니다</td></tr>
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

<h4>국장(한국) — 재료가 어디서 오나</h4>
<table class="basis">
<tr><th></th><th>미장</th><th>국장</th></tr>
<tr><td>분기 실적</td><td>EDGAR XBRL companyfacts</td>
    <td>DART 정기보고서 <code>fnlttSinglAcntAll</code> (연결 CFS, 없으면 별도 OFS).
        실측 5년 <b>18/20 보고서</b></td></tr>
<tr><td>실적발표일</td><td>야후 <code>get_earnings_dates</code></td>
    <td><b>거래소 〈연결재무제표기준영업(잠정)실적〉 공시일.</b> 정기보고서
        접수일보다 <b>2~5주 빠릅니다</b>(실측: 에코프로비엠 잠정 2025-04-29 vs
        분기보고서 2025-05-14). 없으면 정기보고서 접수일로 물러섭니다</td></tr>
<tr><td>컨센서스</td><td>야후 — 분기 <b>2</b> + 연간 <b>2</b></td>
    <td>네이버 — 분기 <b>1</b> + 연간 <b>1</b> (실측 2026-09-19).
        대신 <b>영업이익 컨센이 나옵니다</b> — 미장에서는 무료로 못 구합니다</td></tr>
<tr><td>주가</td><td>야후 일봉</td><td>네이버/KRX 일봉(FinanceDataReader)</td></tr>
</table>
<h5>국장에서 다르게 다루는 것</h5>
<ul>
  <li><b>손익의 <code>thstrm_amount</code> 는 당기 3개월</b>입니다(누적이 아닙니다).
      실측으로 반기 누적 = 1분기 + 당기가 딱 맞습니다. 누적으로 착각하면 2·3분기가
      부풀어 오릅니다.</li>
  <li><b>사업보고서는 당기가 연간</b>이라 미장과 똑같이 <code>Q4 = 연간 − 3분기 누적</code>
      으로 역산합니다.</li>
  <li><b>현금흐름표는 누적</b>이라 차분합니다. 감가상각이 거기 있어 EBITDA 에
      영향을 줍니다. 감가상각을 따로 싣지 않는 회사는 EBITDA 가 빕니다.</li>
  <li>같은 이름이 여러 재무제표에 나옵니다(비지배지분은 BS·CIS·CF 에 다 있습니다).
      그래서 계정을 고를 때 <b>어느 재무제표인지를 반드시 좁힙니다.</b></li>
  <li>표준 계정코드(<code>ifrs-full_…</code>)를 이름보다 먼저 씁니다. 미장과 달리
      회사가 태그를 갈아타지 않아 오히려 깔끔합니다.</li>
</ul>
<h5>컨센이 모자란 구간을 채우는 세 단계</h5>
<p>12개월이면 네 분기가 필요한데 네이버는 <b>앞으로 한 분기와 한 회계연도</b>만
줍니다. 그래서 뒤로 갈수록 가정이 세지고, 차트 아래에 <b>무엇으로 몇 분기를
채웠는지</b>가 그대로 표시됩니다.</p>
<pre>① 네이버 <b>분기 컨센</b>이 있는 분기는 그대로            (가정 없음)
② 올해 <b>FY 컨센</b>의 잔여를 계절성 비중으로 배분      (미장과 같은 규칙)
   잔여 = FY 컨센 − (확정 분기 합 + ①에서 배정한 합)
③ <b>그다음 회계연도</b> 분기 = 같은 분기 1년 전 × 성장률  (<b>가정</b>)
   성장률 g = 올해 FY 컨센 ÷ 작년 FY 실적 합</pre>
<ul>
  <li>③ 은 <b>컨센이 아니라 가정</b>입니다. 미장은 연간 컨센을 둘 주니 여기까지
      갈 일이 없었는데, 국장은 하나뿐이라 안 그러면 <b>가장 최근 1년이 통째로
      빕니다</b>. 성장률을 그대로 이어 쓴다는 뜻이라, 성장률이 꺾이는 해에는
      빗나갑니다.</li>
  <li><b>성장률이 0.5~2.0배 밖이면 성장 없음(1.0배)으로 물러섭니다.</b>
      실측(삼성전자 2026-09-19)에서 올해 성장률이 <b>7.25배</b>로 나왔습니다 —
      메모리 사이클 정점이라 실제로 그렇습니다. 그런데 그 배수를 내년에도 그대로
      곱하면 2028년 분기 EPS 가 56만 원이 됩니다. 컨센이 한 번도 말한 적 없는
      숫자이고, 한 해의 정점을 영구 성장률로 바꿔 쓰는 셈입니다. 그럴 땐 "그
      수준이 유지된다" 로 두고 화면에 그렇게 적습니다 — 이 가정이 틀리면 forward
      PER 이 <b>보수적으로(높게)</b> 나옵니다. 낙관 쪽으로 틀리는 것보다 낫습니다.
      범위는 <code>app/krquarterly.py</code> 의 <code>GROWTH_BAND</code> 한 줄입니다.</li>
  <li>③ 의 재료(1년 전 같은 분기)도 없으면 <b>그 분기는 비웁니다</b> — 지어내지
      않습니다. 그러면 그 구간의 PER 선이 끊깁니다.</li>
  <li>확정 합이 연간 컨센을 넘으면 미장과 똑같이 비우고 이유를 적습니다.</li>
</ul>
<p><b>EV/EBITDA 는 국장에 아직 없습니다.</b> 재료(차입금·리스부채·현금·비지배지분·
우선주자본금)는 DART 전체 재무제표에 표준 계정코드로 다 있는 것을 확인했지만,
발행주식수는 따로 받아야 해서(<code>stockTotqySttus</code>) 다음 차례입니다.</p>

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
  src: ["실적과 컨센을 어디서 가져오나 — 미장 · 국장", `
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

<hr/>
<h4>국장(한국)은 어디서 — <b>🇰🇷 한국</b> 토글</h4>
<table class="basis">
<tr><th></th><th>어디서</th><th>실측</th></tr>
<tr><td>분기 실적</td><td>DART <code>fnlttSinglAcntAll</code> (연결 CFS, 없으면 별도 OFS)</td>
    <td>5년 <b>18/20 보고서</b>. 주당이익·차입금·리스부채·현금·비지배지분까지
        표준 계정코드로 옵니다</td></tr>
<tr><td>실적발표일</td><td>DART 공시목록 —
        <b>〈연결재무제표기준영업(잠정)실적〉</b> 접수일</td>
    <td>정기보고서보다 <b>2~5주 빠릅니다</b>. 없으면 정기보고서 접수일</td></tr>
<tr><td>컨센서스</td><td>네이버 모바일
        <code>m.stock.naver.com/api/stock/{코드}/finance/{quarter|annual}</code></td>
    <td>확정과 추정이 <b>한 응답에</b> 옵니다(<code>isConsensus</code>).
        앞으로 <b>분기 1 · 연간 1</b> 뿐입니다 — 미장(야후)은 2·2</td></tr>
<tr><td>주가</td><td>네이버/KRX(FinanceDataReader)</td><td>당일 종가가 바로 반영됩니다</td></tr>
</table>
<p><b>국장이 미장보다 나은 점도 있습니다 — 영업이익 컨센이 나옵니다.</b> 미장에서는
야후·Alpha Vantage 에 항목 자체가 없고 FMP 는 유료라 비워 뒀던 칸입니다.</p>
<p><b>키가 필요합니다.</b> DART 는 무료 API 키(<code>DART_API_KEY</code>)를 환경변수로
읽습니다. 네이버는 키가 없습니다.</p>
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
  b.addEventListener("click", () => setBasis(b.dataset.basis)));
document.querySelectorAll(".mt").forEach((b) =>
  b.addEventListener("click", () => showMetric(b.dataset.metric)));
document.querySelectorAll(".mk").forEach((b) =>
  b.addEventListener("click", () => setMarket(b.dataset.market)));
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

const params = new URLSearchParams(location.search);
if (params.get("m") === "kr") MARKET = "kr";
syncMarket();
const initial = params.get("t");
if (initial) { $("q").value = initial; load(initial); }
