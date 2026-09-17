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
  $("status").textContent = `${d.ticker} · ${d.name || ""}`;
  const bits = [`<b>${d.name || d.ticker}</b>`];
  if (d.sic) bits.push(d.sic);
  if (d.cik) bits.push(`CIK ${d.cik}`);
  if (d.fiscal_year_end) bits.push(`결산 ${d.fiscal_year_end}`);
  let head = bits.join(" · ");
  for (const n of d.notes || []) head += `<span class="warn">⚠ ${n}</span>`;
  $("head").innerHTML = head;

  renderMetrics(d.metrics || {});
  $("table-sec").classList.remove("hidden");

  if (d.per && d.per.dates && d.per.dates.length) {
    drawChart(d.per);
    $("chart-sec").classList.remove("hidden");
  } else {
    $("chart-sec").classList.add("hidden");
  }
  $("empty").classList.add("hidden");
}

function renderMetrics(metrics) {
  const labels = Object.keys(metrics);
  const out = [];
  for (const label of labels) {
    const m = metrics[label];
    const qs = m.quarters || [];
    if (!qs.length) {
      out.push(`<div class="mtable"><h3>${label}
        <span class="src">${m.source}</span></h3></div>`);
      continue;
    }
    const isRatio = label.includes("EPS");
    const head = ["항목", ...qs.map((q) => q.end)];
    const row = (name, get, cls) =>
      `<tr><td>${name}</td>` + qs.map((q) => {
        const v = get(q);
        if (v === null || v === undefined) return `<td class="na">—</td>`;
        const k = cls ? (v > 0 ? "up" : v < 0 ? "down" : "") : "";
        return `<td class="${k}">${cls ? fmtPct(v) : (isRatio ? v.toFixed(2) : fmtBig(v))}</td>`;
      }).join("") + "</tr>";

    out.push(`<div class="mtable">
      <h3>${label} <span class="src">${m.source}</span></h3>
      ${m.note ? `<p class="note">⚠ ${m.note}</p>` : ""}
      ${m.warning ? `<p class="note">⚠ ${m.warning}</p>` : ""}
      <div class="table-wrap"><table>
        <thead><tr>${head.map((h) => `<th>${h}</th>`).join("")}</tr></thead>
        <tbody>
          ${row("값", (q) => q.val, false)}
          ${row("YoY", (q) => q.yoy, true)}
          ${row("QoQ", (q) => q.qoq, true)}
        </tbody>
      </table></div></div>`);
  }
  $("metrics").innerHTML = out.join("");
}

/* ---------------------------------------------------------------------- 차트 */
const W = 980, H = 380, PAD = { l: 52, r: 58, t: 14, b: 26 };

function drawChart(per) {
  const n = per.dates.length;
  const px = (i) => PAD.l + (i / Math.max(1, n - 1)) * (W - PAD.l - PAD.r);

  const closes = per.close.filter((v) => v !== null);
  const pers = [...per.per_confirmed, ...per.per_estimated].filter((v) => v !== null && v > 0);
  if (!closes.length) return;
  const cLo = Math.min(...closes), cHi = Math.max(...closes);
  // PER 은 꼬리가 길다 — 상위 1% 를 잘라야 나머지가 납작해지지 않는다.
  const sorted = [...pers].sort((a, b) => a - b);
  const pLo = sorted.length ? sorted[0] : 0;
  const pHi = sorted.length ? sorted[Math.floor(sorted.length * 0.99)] : 1;

  const yC = (v) => PAD.t + (1 - (v - cLo) / Math.max(1e-9, cHi - cLo)) * (H - PAD.t - PAD.b);
  const yP = (v) => PAD.t + (1 - (Math.min(v, pHi) - pLo) / Math.max(1e-9, pHi - pLo)) * (H - PAD.t - PAD.b);

  const path = (arr, y) => {
    let d = "", pen = false;
    arr.forEach((v, i) => {
      if (v === null || v === undefined || !(v > 0)) { pen = false; return; }
      d += (pen ? "L" : "M") + px(i).toFixed(1) + " " + y(v).toFixed(1) + " ";
      pen = true;
    });
    return d.trim();
  };

  // 실적발표일 세로선. 추정이 섞인 구간은 색을 달리한다.
  const idx = new Map(per.dates.map((d, i) => [d, i]));
  const nearest = (d) => {
    if (idx.has(d)) return idx.get(d);
    let lo = 0, hi = per.dates.length - 1;
    if (d < per.dates[0] || d > per.dates[hi]) return -1;
    while (lo < hi) { const m = (lo + hi) >> 1; per.dates[m] < d ? (lo = m + 1) : (hi = m); }
    return lo;
  };
  const marks = (per.marks || []).map((m) => ({ ...m, i: nearest(m.announced) }))
                                 .filter((m) => m.i >= 0);

  const ticks = [];
  for (let i = 0; i < n; i += Math.max(1, Math.floor(n / 6))) ticks.push(i);

  $("plot").innerHTML = `<svg viewBox="0 0 ${W} ${H}" role="img">
    <g stroke="#334155" stroke-width="1">
      ${[0, .25, .5, .75, 1].map((f) => {
        const y = PAD.t + f * (H - PAD.t - PAD.b);
        return `<line x1="${PAD.l}" x2="${W - PAD.r}" y1="${y}" y2="${y}" opacity=".45"/>`;
      }).join("")}
    </g>
    <g>${marks.map((m) => `<line x1="${px(m.i)}" x2="${px(m.i)}" y1="${PAD.t}"
        y2="${H - PAD.b}" stroke="${m.confirmed ? "#64748b" : "#f472b6"}"
        stroke-width="1" stroke-dasharray="2 4" opacity=".7"/>`).join("")}</g>
    <path d="${path(per.close, yC)}" fill="none" stroke="var(--price)" stroke-width="1.6"/>
    <path d="${path(per.per_confirmed, yP)}" fill="none" stroke="var(--per)" stroke-width="1.8"/>
    <path d="${path(per.per_estimated, yP)}" fill="none" stroke="var(--per-est)"
          stroke-width="1.8" stroke-dasharray="5 4"/>
    <g fill="#94a3b8" font-size="10">
      ${[cHi, (cHi + cLo) / 2, cLo].map((v, k) =>
        `<text x="${PAD.l - 6}" y="${yC(v) + 3}" text-anchor="end">${v.toFixed(0)}</text>`).join("")}
      ${[pHi, (pHi + pLo) / 2, pLo].map((v) =>
        `<text x="${W - PAD.r + 6}" y="${yP(v) + 3}">${v.toFixed(0)}</text>`).join("")}
      ${ticks.map((i) =>
        `<text x="${px(i)}" y="${H - 8}" text-anchor="middle">${per.dates[i].slice(0, 7)}</text>`).join("")}
    </g>
    <rect id="hit" x="${PAD.l}" y="${PAD.t}" width="${W - PAD.l - PAD.r}"
          height="${H - PAD.t - PAD.b}" fill="transparent"/>
  </svg>`;

  $("legend").innerHTML = `
    <span><i style="border-color:var(--price)"></i>주가 (왼쪽 축)</span>
    <span><i style="border-color:var(--per)"></i>12M forward PER — 확정 실적 (오른쪽 축)</span>
    <span><i style="border-color:var(--per-est);border-top-style:dashed"></i>12M forward PER — 컨센 섞임</span>
    <span><i style="border-color:#64748b;border-top-style:dashed"></i>실적발표일</span>`;

  const est = (per.estimates || []).map((e) =>
    `<span class="m est">${e.end} 추정 EPS ${e.eps} <small>(${e.source})</small></span>`).join("");
  const last = marks[marks.length - 1];
  $("marks").innerHTML =
    (last ? `<span class="m">가장 최근 계단 — 발표 <b>${last.announced}</b> ·
       재무정보 기준일 <b>${last.basis_end}</b> · 향후 4분기 EPS ${last.eps}
       (추정 ${last.estimated}분기, ${last.source})</span><br/>` : "") +
    (est || "") +
    (per.consensus_sources && per.consensus_sources.length
      ? `<br/><span class="m">컨센 출처: ${per.consensus_sources.join(", ")}</span>` : "");

  // 툴팁
  const svg = $("plot").querySelector("svg");
  const tip = $("tip");
  svg.addEventListener("mousemove", (ev) => {
    const r = svg.getBoundingClientRect();
    const x = ((ev.clientX - r.left) / r.width) * W;
    const i = Math.round(((x - PAD.l) / (W - PAD.l - PAD.r)) * (n - 1));
    if (i < 0 || i >= n) { tip.classList.add("hidden"); return; }
    const p = per.per_confirmed[i], q = per.per_estimated[i];
    tip.innerHTML = `<b>${per.dates[i]}</b><br/>주가 ${per.close[i]}<br/>` +
      (p !== null ? `fwd PER <b>${p}</b> (확정)` :
       q !== null ? `fwd PER <b>${q}</b> (컨센 섞임)` : "fwd PER —");
    tip.classList.remove("hidden");
    tip.style.left = Math.min(r.width - 170, ev.clientX - r.left + 12) + "px";
    tip.style.top = (ev.clientY - r.top + 12) + "px";
  });
  svg.addEventListener("mouseleave", () => tip.classList.add("hidden"));
}

/* --------------------------------------------------------------------- 모달 */
const MODALS = {
  local: ["내 컴퓨터에서 띄우는 법", `
<div class="warn">
<b>⚠ 검은 창(Git Bash)을 닫으면 서버가 꺼집니다.</b> 그 창이 곧 서버입니다.
페이지를 보는 동안에는 <b>계속 열어 두세요.</b> 최소화는 괜찮습니다.
</div>

<h4>왜 서버가 필요한가</h4>
이 페이지는 다른 화면들과 다릅니다. 신고가·평평·상관관계는 밤에 미리 계산해 둔
파일을 내려받기만 하면 되지만, 여기는 <b>티커를 입력받은 그 순간</b> EDGAR 와
야후에 물어봅니다. 브라우저가 직접 물어볼 수는 없습니다 —
<code>data.sec.gov</code> 가 브라우저에서 오는 요청을 거부하고(CORS), 야후는 애초에
공개 API 가 아니라 파이썬이 필요합니다. 그 심부름을 해 주는 게 서버입니다.

<h4>띄우기</h4>
<b>Git Bash</b> 를 열고(폴더에서 우클릭 → Git Bash Here), 이 두 줄:
<pre>cd ~/OneDrive/Desktop/주식/코딩/SUH_DH
./run.sh</pre>
이렇게 찍히면 성공입니다:
<pre>INFO:  Application startup complete.
INFO:  Uvicorn running on http://127.0.0.1:8000</pre>

<h4>열기 — <code>http://</code> 를 꼭 붙이세요</h4>
<pre>http://localhost:8000/quarterly/</pre>
<div class="warn">
주소창에 <code>localhost:8000</code> 만 치면 요즘 브라우저가 <b>자동으로
<code>https://</code> 로 바꿉니다.</b> 우리 서버는 <code>http</code> 라 그러면 무조건
실패합니다. 즐겨찾기에 넣어 두시는 게 제일 편합니다.
</div>

<h4>끝낼 때</h4>
검은 창에서 <b>Ctrl+C</b>. 그냥 창을 닫아도 됩니다 — 어차피 서버가 같이 꺼집니다.

<h4>코드가 업데이트됐을 때</h4>
서버를 끄고(<b>Ctrl+C</b>), 받고, 다시 띄웁니다. <b>받기만 하면 안 됩니다</b> —
이미 떠 있는 서버는 옛 코드를 메모리에 들고 있습니다.
<pre>git pull
./run.sh</pre>

<h4>안 들어가질 때</h4>
<ol>
  <li><b>검은 창이 아직 열려 있나</b> — 제일 흔한 원인입니다.</li>
  <li><b><code>http://</code> 를 붙였나</b> — 두 번째로 흔합니다.</li>
  <li>창을 <b>하나 더</b> 열어 <code>curl http://127.0.0.1:8000/api/health</code>.
      <code>{"status":"ok"}</code> 가 나오면 서버는 멀쩡하고 브라우저 문제입니다.</li>
  <li><code>127.0.0.1</code> 대신 <code>localhost</code> 로도 해 보세요.</li>
  <li>회사 PC·VPN 이면 프록시일 수 있습니다 — Windows 설정 → 네트워크 및 인터넷 →
      프록시 → <b>"로컬 주소에 프록시 서버 사용 안 함"</b> 체크.</li>
  <li><code>Address already in use</code> 가 뜨면 이미 떠 있는 겁니다. 다른 창을
      찾아 쓰거나, 다 닫고 다시 띄우세요.</li>
</ol>

<h4>참고로 무시해도 되는 것</h4>
시작할 때 <code>eai subsystem not mounted: No module named 'sqlalchemy'</code> 가
찍힙니다. 실적 컨콜 프로그램만 안 뜨는 것이고 <b>이 페이지와는 무관합니다.</b>

<h4>배포된 사이트(GitHub Pages)에서는</h4>
백엔드가 연결돼 있으면 로컬 실행 없이 그대로 됩니다. 무료 서버라 15분 쉬면
잠들기 때문에 <b>첫 조회가 30~60초</b> 걸릴 수 있습니다 — 멈춘 게 아니라 깨는
중입니다.
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
$("modal-close").addEventListener("click", () => $("modal").classList.add("hidden"));
$("modal").addEventListener("click", (e) => {
  if (e.target === $("modal")) $("modal").classList.add("hidden");
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") $("modal").classList.add("hidden");
});

const initial = new URLSearchParams(location.search).get("t");
if (initial) { $("q").value = initial; load(initial); }
