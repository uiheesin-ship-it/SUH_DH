/* Market Regime Lab 진입 화면.
 *
 * 이 페이지 자체는 아무 분석도 하지 않는다. 대시보드(FastAPI)가 같은 머신에서
 * Streamlit 앱을 띄우고 /regime/app/** 로 프록시해 주므로, 여기서는
 *   상태 확인 → (필요하면) 시작 → iframe 으로 대시보드 안에 띄우기
 * 세 단계만 담당한다. 정적 빌드(GitHub Pages)에서는 백엔드가 없으므로 로컬 실행
 * 방법을 안내한다.
 */
const $ = (id) => document.getElementById(id);
const statusEl = $("status");
const panel = $("panel");
const lab = $("lab");

const LAB_SRC = "app/?embed=true";
const START_POLL_MS = 1200;
const START_TIMEOUT_MS = 90000;

function setStatus(text, cls) {
  statusEl.textContent = text;
  statusEl.className = "status" + (cls ? " " + cls : "");
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
  lab.classList.add("hidden");
}

function showLab() {
  panel.classList.add("hidden");
  if (lab.src === "about:blank" || !lab.src.endsWith(LAB_SRC)) lab.src = LAB_SRC;
  lab.classList.remove("hidden");
  $("newtab").classList.remove("hidden");
  $("restart").classList.remove("hidden");
  setStatus("실행 중");
}

function button(label, onClick, cls) {
  const b = document.createElement("button");
  b.className = cls || "primary-btn";
  b.textContent = label;
  b.addEventListener("click", () => onClick(b));
  return b;
}

async function api(path, options) {
  const res = await fetch(path, options);
  const body = await res.json().catch(() => ({}));
  return { ok: res.ok, body };
}

function staticNotice() {
  setStatus("정적 빌드", "warn");
  showPanel(
    "로컬 대시보드에서 실행하세요",
    "Market Regime Lab 은 업로드한 CSV/XLSX 를 <b>브라우저 세션에서 바로</b> 계산하는 프로그램이라 " +
    "정적 사이트(GitHub Pages)에서는 동작하지 않습니다. 아래처럼 대시보드를 로컬에서 띄우면 " +
    "이 카드에서 그대로 열립니다.",
    [],
    "pip install -r requirements.txt -r requirements-regime.txt\n./run.sh\n\n" +
    "# 브라우저에서 http://127.0.0.1:8000 → 미장 → 기타 → Market Regime Lab"
  );
}

function missingNotice(missing) {
  setStatus("패키지 없음", "bad");
  showPanel(
    "필요한 패키지가 설치되어 있지 않습니다",
    "Market Regime Lab 은 Streamlit 으로 동작합니다. 아래 한 줄이면 설치됩니다: <b>" +
    missing.join(", ") + "</b>",
    [button("다시 확인", async (b) => { b.disabled = true; await refresh(); b.disabled = false; })],
    "pip install -r requirements-regime.txt\n# 설치 후 '다시 확인'"
  );
}

async function startLab(btn) {
  if (btn) { btn.disabled = true; btn.textContent = "시작하는 중… (최초 10~20초)"; }
  setStatus("시작하는 중…");
  const started = await api("/api/regime/start", { method: "POST" });
  if (!started.ok) {
    setStatus("시작 실패", "bad");
    showPanel("시작하지 못했습니다",
      (started.body && started.body.error) || "알 수 없는 오류입니다.",
      [button("다시 시도", startLab)],
      "터미널에서 직접 실행하면 원인을 볼 수 있습니다:\n./run_regime.sh");
    return;
  }
  const deadline = Date.now() + START_TIMEOUT_MS;
  while (Date.now() < deadline) {
    const { body } = await api("/api/regime/status");
    if (body && body.running) { showLab(); return; }
    await new Promise((r) => setTimeout(r, START_POLL_MS));
  }
  setStatus("응답 없음", "bad");
  showPanel("아직 준비되지 않았습니다",
    "Streamlit 이 시간 안에 응답하지 않았습니다. 잠시 후 다시 시도해 보세요.",
    [button("다시 시도", startLab)]);
}

async function refresh() {
  if (window.SUH_DH_STATIC) { staticNotice(); return; }
  let body;
  try {
    ({ body } = await api("/api/regime/status"));
  } catch (err) {
    staticNotice();
    return;
  }
  if (!body || typeof body.available === "undefined") { staticNotice(); return; }
  if (!body.available) { missingNotice(body.missing || ["streamlit"]); return; }
  if (body.running) { showLab(); return; }

  setStatus("대기 중");
  showPanel(
    "Market Regime Lab 시작",
    "현재 시장 상태를 정량화하고 과거의 비슷한 국면과 그 이후 수익률을 찾아봅니다. " +
    "데이터는 <b>자동 내려받기</b>를 쓰거나, 화면 안에서 <b>CSV/XLSX 를 직접 업로드</b>할 수 있습니다 " +
    "(업로드한 파일은 이 세션에서만 쓰이고 저장·커밋되지 않습니다).",
    [button("분석 화면 열기", startLab)]
  );
}

$("restart").addEventListener("click", async (e) => {
  const b = e.currentTarget;
  b.disabled = true;
  setStatus("다시 시작하는 중…");
  await api("/api/regime/stop", { method: "POST" });
  lab.src = "about:blank";
  await startLab(null);
  b.disabled = false;
});

refresh();
