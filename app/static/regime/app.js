/* Market Regime Lab 진입 화면.
 *
 * 이 페이지는 분석을 하지 않는다. 실제 앱(Streamlit)을 이 자리(iframe)에 그대로
 * 띄워 주는 역할만 하고, 앱이 어디서 도는지는 세 곳에서 순서대로 찾는다.
 *
 *   1) ?app=<url>          — 주소창으로 한 번 지정(그 브라우저에 저장된다)
 *   2) localStorage        — 이전에 지정한 주소
 *   3) SUH_DH_REGIME_URL   — 빌드 때 심어 둔 기본 주소 (GitHub Pages 배포용)
 *   4) 같은 서버의 백엔드   — 로컬 대시보드(./run.sh)가 Streamlit 을 띄우고 프록시
 *
 * 1~3 은 GitHub Pages 처럼 파이썬을 돌릴 수 없는 곳에서 원격 인스턴스를 붙이는
 * 경로이고, 4 는 로컬에서 대시보드를 띄웠을 때의 경로다. 어느 쪽이든 사용자는
 * 이 페이지를 떠나지 않는다.
 */
const $ = (id) => document.getElementById(id);
const statusEl = $("status");
const panel = $("panel");
const lab = $("lab");
const overlay = $("overlay");

const STORE_KEY = "suh_dh_regime_url";
const START_POLL_MS = 1200;
const START_TIMEOUT_MS = 90000;
const WAKE_HINT_MS = 25000;      // 무료 플랜은 잠들어 있다가 깨어난다

let wakeTimer = null;

function setStatus(text, cls) {
  statusEl.textContent = text;
  statusEl.className = "status" + (cls ? " " + cls : "");
}

function button(label, onClick, cls) {
  const b = document.createElement("button");
  b.className = cls || "primary-btn";
  b.textContent = label;
  b.addEventListener("click", () => onClick(b));
  return b;
}

function showPanel(title, desc, actions, code) {
  $("panel-title").textContent = title;
  $("panel-desc").innerHTML = desc;
  const box = $("panel-actions");
  box.innerHTML = "";
  (actions || []).forEach((a) => box.appendChild(a));
  const pre = $("panel-code");
  if (code) { pre.textContent = code; pre.classList.remove("hidden"); }
  else { pre.classList.add("hidden"); }
  panel.classList.remove("hidden");
  $("setup").classList.add("hidden");
  hideLab();
}

function hideLab() {
  lab.classList.add("hidden");
  overlay.classList.add("hidden");
  if (wakeTimer) { clearTimeout(wakeTimer); wakeTimer = null; }
}

function storedUrl() {
  try { return localStorage.getItem(STORE_KEY) || ""; } catch (e) { return ""; }
}

function storeUrl(url) {
  try { url ? localStorage.setItem(STORE_KEY, url) : localStorage.removeItem(STORE_KEY); }
  catch (e) { /* 프라이빗 모드 등 — 저장 못 해도 이번 세션은 동작한다 */ }
}

function normalise(url) {
  const trimmed = (url || "").trim().replace(/\/+$/, "");
  if (!trimmed) return "";
  return /^https?:\/\//i.test(trimmed) ? trimmed : "https://" + trimmed;
}

function resolveRemote() {
  const fromQuery = new URLSearchParams(location.search).get("app");
  if (fromQuery) {
    const url = normalise(fromQuery);
    storeUrl(url);
    return url;
  }
  return storedUrl() || normalise(window.SUH_DH_REGIME_URL || "");
}

/** iframe 으로 실제 앱을 이 자리에 띄운다. */
function showLab(src, remoteUrl) {
  panel.classList.add("hidden");
  $("setup").classList.add("hidden");
  if (lab.getAttribute("src") !== src) lab.setAttribute("src", src);
  lab.classList.remove("hidden");
  overlay.classList.remove("hidden");
  $("overlay-text").textContent = "Market Regime Lab 을 불러오는 중…";
  $("overlay-note").textContent = "";
  setStatus("불러오는 중…");

  const openLink = $("newtab");
  openLink.href = remoteUrl ? remoteUrl + "/" : "app/";
  openLink.classList.remove("hidden");
  $("settings-btn").classList.remove("hidden");

  if (wakeTimer) clearTimeout(wakeTimer);
  wakeTimer = setTimeout(() => {
    $("overlay-note").textContent =
      "무료 서버는 쉬고 있다가 깨어나는 데 30~60초가 걸릴 수 있습니다. 조금만 기다려 주세요.";
  }, WAKE_HINT_MS);

  lab.onload = () => {
    overlay.classList.add("hidden");
    if (wakeTimer) { clearTimeout(wakeTimer); wakeTimer = null; }
    setStatus(remoteUrl ? "실행 중 · 원격" : "실행 중 · 로컬");
  };
}

function showSetup(current) {
  panel.classList.add("hidden");
  hideLab();
  $("setup").classList.remove("hidden");
  $("regime-url").value = current || storedUrl() || normalise(window.SUH_DH_REGIME_URL || "");
  setStatus("주소 설정 필요", "warn");
}

async function api(path, options) {
  const res = await fetch(path, options);
  const body = await res.json().catch(() => ({}));
  return { ok: res.ok, body };
}

/* ---------- 로컬 대시보드(백엔드가 있는 경우) ---------- */

async function startLocal(btn) {
  if (btn) { btn.disabled = true; btn.textContent = "시작하는 중… (최초 10~20초)"; }
  setStatus("시작하는 중…");
  const started = await api("/api/regime/start", { method: "POST" });
  if (!started.ok) {
    showPanel("시작하지 못했습니다",
      (started.body && started.body.error) || "알 수 없는 오류입니다.",
      [button("다시 시도", startLocal),
       button("원격 주소 사용", () => showSetup(), "ghost-btn")]);
    return;
  }
  const deadline = Date.now() + START_TIMEOUT_MS;
  while (Date.now() < deadline) {
    const { body } = await api("/api/regime/status");
    if (body && body.running) { showLab("app/?embed=true", ""); return; }
    await new Promise((r) => setTimeout(r, START_POLL_MS));
  }
  showPanel("아직 준비되지 않았습니다",
    "Streamlit 이 시간 안에 응답하지 않았습니다. 잠시 후 다시 시도해 보세요.",
    [button("다시 시도", startLocal)]);
}

async function localBackend() {
  try {
    const { body } = await api("/api/regime/status");
    if (!body || typeof body.available === "undefined") return null;
    return body;
  } catch (err) {
    return null;                       // 정적 호스팅 — 백엔드가 아예 없다
  }
}

/* ---------- 진입 ---------- */

async function boot() {
  const remote = resolveRemote();
  if (remote) { showLab(remote + "/?embed=true", remote); return; }

  const local = await localBackend();
  if (local && local.available) {
    if (local.running) { showLab("app/?embed=true", ""); return; }
    setStatus("대기 중");
    showPanel(
      "Market Regime Lab 시작",
      "현재 시장 상태를 정량화하고 과거의 비슷한 국면과 그 이후 수익률을 찾아봅니다. " +
      "데이터는 <b>자동 내려받기</b>를 쓰거나, 화면 안에서 <b>CSV/XLSX 를 직접 업로드</b>할 수 있습니다 " +
      "(업로드한 파일은 이 세션에서만 쓰이고 저장·커밋되지 않습니다).",
      [button("분석 화면 열기", startLocal),
       button("원격 주소 사용", () => showSetup(), "ghost-btn")]);
    return;
  }
  if (local && !local.available) {
    showPanel("필요한 패키지가 설치되어 있지 않습니다",
      "이 대시보드에 Streamlit 이 없습니다: <b>" + (local.missing || []).join(", ") + "</b>. " +
      "설치하거나, 이미 배포해 둔 Regime Lab 주소를 연결하세요.",
      [button("원격 주소 연결", () => showSetup()),
       button("다시 확인", async (b) => { b.disabled = true; await boot(); b.disabled = false; }, "ghost-btn")],
      "pip install -r requirements-regime.txt");
    return;
  }
  showSetup();                          // 정적 호스팅 + 주소 미설정
}

$("settings-btn").addEventListener("click", () => showSetup(storedUrl()));

$("setup-save").addEventListener("click", () => {
  const url = normalise($("regime-url").value);
  if (!url) { $("setup-error").textContent = "주소를 입력하세요."; return; }
  $("setup-error").textContent = "";
  storeUrl(url);
  showLab(url + "/?embed=true", url);
});

$("setup-clear").addEventListener("click", () => {
  storeUrl("");
  $("regime-url").value = "";
  boot();
});

$("regime-url").addEventListener("keydown", (e) => {
  if (e.key === "Enter") $("setup-save").click();
});

boot();
