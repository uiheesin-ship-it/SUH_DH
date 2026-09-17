"use strict";

/* Market Regime Lab — 대시보드 안의 정적 프로그램.
 *
 * 이 파일은 화면만 담당한다. 모든 계산은 기존 분석 엔진(app/regime/*)을 그대로
 * 호출하는 백엔드 /api/regime/* 가 수행하고, 차트도 백엔드가 만든 Plotly figure
 * JSON 을 그리기만 한다 — Streamlit 판과 같은 그림, 같은 숫자.
 *
 *   STATIC=false  -> 같은 서버의 FastAPI (/api/regime/*)
 *   STATIC=true   -> 정적 빌드. SUH_DH_API_BASE(호스팅된 백엔드)로 호출
 */

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

const STATIC = !!window.SUH_DH_STATIC;
const API_STORE_KEY = "suh_dh_regime_api";

/** 분석 백엔드 주소: ?api=<url> → 브라우저에 저장된 값 → 빌드/저장소 기본값.
 *  로컬 대시보드에서는 셋 다 비어 있어 같은 서버(/api/...)를 그대로 쓴다. */
function normaliseUrl(url) {
  const trimmed = (url || "").trim().replace(/\/+$/, "");
  if (!trimmed) return "";
  return /^https?:\/\//i.test(trimmed) ? trimmed : "https://" + trimmed;
}
function storedApiBase() {
  try { return localStorage.getItem(API_STORE_KEY) || ""; } catch (e) { return ""; }
}
function storeApiBase(url) {
  try { url ? localStorage.setItem(API_STORE_KEY, url) : localStorage.removeItem(API_STORE_KEY); }
  catch (e) { /* 프라이빗 모드 — 이번 세션만 쓰인다 */ }
}
function resolveApiBase() {
  const fromQuery = new URLSearchParams(location.search).get("api");
  if (fromQuery) {
    const url = normaliseUrl(fromQuery);
    storeApiBase(url);
    return url;
  }
  return storedApiBase() || builtinApiBase();
}

/** 브라우저에 저장된 값을 뺀, 이 빌드가 원래 가리키는 주소.
 *  저장소 기본값은 파이썬이 없는 정적 사이트에서만 쓴다 — 로컬 대시보드(STATIC=false)는
 *  같은 서버의 /api/regime/* 를 써야 하고, 남의 백엔드로 나가면 안 된다. */
function builtinApiBase() {
  return normaliseUrl(window.SUH_DH_API_BASE || "")
    || (STATIC ? normaliseUrl(window.SUH_DH_REGIME_API_DEFAULT || "") : "");
}

/* --------------------------------------------------------- 백엔드 깨우기
 *
 * 무료 인스턴스는 15분만 놀아도 잠든다. 잠든 동안 오는 요청은 (a) 그냥 오래 매달려
 * 있거나 (b) Render 의 "waking up" HTML 안내 페이지를 받거나 (c) 502/503 을 받는다.
 * 셋 다 "주소가 틀렸다"가 아니라 "아직 일어나는 중"이다 — 그래서 한 번 찔러 보고
 * 포기하지 않고, 깨어날 때까지(최대 WAKE_BUDGET_MS) 짧게 되물으며 기다린다.
 *
 * 반대로 살아 있는 엉뚱한 서비스(예: 옛 Streamlit)는 /api/health 에 곧바로 404 를
 * 준다 — 그건 기다릴 이유가 없으니 즉시 "주소가 다르다"고 알려 준다.
 */
const WAKE_BUDGET_MS = 150000;        // 최대 2분 30초 (Render 무료는 보통 30~60초)
const WAKE_PROBE_MS = 25000;          // 한 번 찌를 때 기다리는 시간
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function fetchTimeout(url, ms, opts) {
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), ms);
  return fetch(url, { cache: "no-store", signal: ctl.signal, ...(opts || {}) })
    .finally(() => clearTimeout(timer));
}

let BACKEND_READY = false;
let WAKE_RUN = null;                    // 진행 중인 깨우기 (동시에 두 번 하지 않는다)
let WAKE_LISTENERS = [];

/** 백엔드가 준비될 때까지 기다린다 — 여러 곳에서 불러도 깨우기는 한 번만 돈다.
 *
 *  이게 없으면 페이지가 잠든 백엔드로 요청을 제각각 쏜다: init 은 /api/health 를
 *  되묻고, 파일 업로드는 응답 없는 POST 에 매달리고, 분석 실행은 그 업로드를
 *  기다린다 — 화면에는 타이머 두 개가 따로 돌고 아무것도 끝나지 않는다.
 *  요청은 전부 이 문을 지나게 하고, 기다리는 쪽에는 같은 진행 상황을 알려 준다. */
async function ensureBackend(onTick) {
  if (!API_BASE || BACKEND_READY) return { ok: true };
  if (onTick) WAKE_LISTENERS.push(onTick);
  if (!WAKE_RUN) {
    WAKE_RUN = wakeBackend(API_BASE, (sec) => WAKE_LISTENERS.forEach((fn) => {
      try { fn(sec); } catch (e) { /* 화면 갱신 실패가 깨우기를 막지 않게 */ }
    })).finally(() => { WAKE_RUN = null; WAKE_LISTENERS = []; });
  }
  return WAKE_RUN;
}

/** 백엔드가 응답할 때까지 기다린다. onTick(초) 으로 진행 상황을 알려 준다. */
async function wakeBackend(base, onTick) {
  if (!base) { BACKEND_READY = true; return { ok: true }; }   // 로컬: 같은 서버를 쓴다
  const started = Date.now();
  const elapsed = () => Math.round((Date.now() - started) / 1000);
  let lastWhy = "연결하지 못했습니다.";
  let sawServer = false;                 // 서버는 살아 있는데 응답이 우리 것이 아니다
  while (Date.now() - started < WAKE_BUDGET_MS) {
    if (onTick) onTick(elapsed());
    try {
      const res = await fetchTimeout(base + "/api/health", WAKE_PROBE_MS);
      if (res.status === 404 || res.status === 405 || res.status === 403) {
        return { ok: false, wrong: true,
                 why: `/api/health 가 ${res.status} 를 돌려줬습니다 — 서버는 살아 있지만 대시보드 백엔드가 아닙니다.` };
      }
      if (res.ok) {
        const text = await res.text();
        let body = null;
        try { body = JSON.parse(text); } catch (e) { /* Render 안내 페이지(HTML) */ }
        if (body && body.status === "ok") {
          // 백엔드는 살아 있지만 Regime Lab 만 안 붙어 있을 수 있다(의존성 누락 등).
          // 그냥 두면 /api/regime/* 가 404 로만 보여서 '주소가 틀렸나' 로 오해하게 된다.
          if (body.regime && body.regime.ok === false) {
            return { ok: false, wrong: true,
                     why: "백엔드는 살아 있지만 Regime Lab 분석 API 가 올라가 있지 않습니다 — " +
                          (body.regime.error || "원인 불명") +
                          " (로컬이라면 pip install -r requirements.txt 를 다시 실행하세요.)" };
          }
          if (!body.regime) {
            // regime 항목이 없는 응답 = Regime Lab 보다 오래된 빌드일 수 있다.
            // 바로 단정하지 말고 실제로 있는지 한 번 확인한다 — 여기서 걸러 내지 않으면
            // 7,000줄짜리 파일을 다 올린 뒤에야 'Method Not Allowed' 를 보게 된다.
            const probe = await fetchTimeout(base + "/api/regime/defaults", WAKE_PROBE_MS)
              .catch(() => null);
            if (!probe || probe.status === 404 || probe.status === 405) {
              return { ok: false, wrong: true,
                       why: "이 백엔드에는 Regime Lab 분석 API(/api/regime/*)가 없습니다 — " +
                            "배포가 Regime Lab 추가 이전 버전에 멈춰 있습니다. " +
                            "백엔드를 최신으로 배포하거나, 내 컴퓨터에서 직접 실행해 쓰세요 " +
                            "(위 '🖥 설치·실행' 버튼)." };
            }
          }
          BACKEND_READY = true;
          return { ok: true, seconds: elapsed() };
        }
        sawServer = true;                // 200 인데 JSON 이 아니다 — 깨는 중이거나 다른 서비스
        lastWhy = "응답이 대시보드 백엔드의 것이 아닙니다 (/api/health 가 JSON 을 주지 않습니다).";
      } else {
        lastWhy = `/api/health 가 ${res.status} 를 돌려줬습니다.`;   // 502/503 = 깨는 중
      }
    } catch (err) {
      lastWhy = "연결하지 못했습니다 — 주소가 맞는지, 서버가 살아 있는지 확인하세요.";
    }
    await sleep(3000);
  }
  return { ok: false, wrong: sawServer,
           why: lastWhy + ` (${elapsed()}초 기다렸습니다)` };
}
let API_BASE = resolveApiBase();
const api = (path) => (API_BASE ? API_BASE + path : path);

const SMA_CHOICES = [10, 20, 50, 100, 150, 200];
const RET_CHOICES = [5, 10, 20, 60, 120, 250];
const HORIZON_CHOICES = [5, 10, 20, 60, 120, 250];
const OPS = ["<=", "<", ">=", ">", "between"];

let DEFAULTS = null;         // /api/regime/defaults 응답
let FEATURES = [];           // feature 설명(라벨·그룹·기본 가중치)
let LAST = null;             // 마지막 분석 결과
let SESSION = null;          // 서버가 들고 있는 데이터 세션
const UPLOADS = { price: null, volume: null, yield: null };

/* ------------------------------------------------------------------ utils */

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
function num(v, d = 2) {
  if (v === null || v === undefined || Number.isNaN(v)) return "–";
  return typeof v === "number" ? v.toFixed(d) : esc(v);
}
function signed(v, d = 2, suffix = "%") {
  if (v === null || v === undefined || Number.isNaN(v)) return "–";
  return (v >= 0 ? "+" : "") + v.toFixed(d) + suffix;
}
function setStatus(text, cls) {
  const el = $("#status");
  el.textContent = text;
  el.className = "status" + (cls ? " " + cls : "");
}
let busyTimer = null;
let busyLabel = "";

/** 오버레이 문구만 바꾼다(경과 시간 표시는 그대로 이어진다). */
function busyText(text) {
  busyLabel = text || "";
  const el = $("#overlay-text");
  if (el) el.textContent = busyLabel;
}

/** 진행 중에는 경과 초를 세어 준다 — 멈춘 것인지 도는 것인지 보이게 한다.
 *  무료 인스턴스는 잠에서 깨는 데만 30~60초가 걸려서, 이게 없으면 '먹통'처럼 보인다. */
function busy(on, text) {
  $("#overlay").classList.toggle("hidden", !on);
  if (busyTimer) { clearInterval(busyTimer); busyTimer = null; }
  busyText(text);
  if (!on) return;
  const started = Date.now();
  busyTimer = setInterval(() => {
    const sec = Math.round((Date.now() - started) / 1000);
    const el = $("#overlay-text");
    if (!el) return;
    let line = busyLabel;
    if (sec >= 3) line += `  ·  ${sec}초`;
    if (sec >= 10 && API_BASE && !BACKEND_READY) line += " (백엔드를 깨우는 중 — 최대 1분)";
    el.textContent = line;
  }, 1000);
}
function tableHtml(frame, decimals = 2) {
  if (!frame || !frame.columns || !frame.columns.length) return '<p class="muted small">표시할 내용이 없습니다.</p>';
  const head = frame.columns.map((c) => `<th>${esc(c)}</th>`).join("");
  const body = frame.rows.map((row) => "<tr>" + row.map((v) => {
    if (typeof v === "number") return `<td>${num(v, decimals)}</td>`;
    if (v === true) return "<td>예</td>";
    if (v === false) return "<td>아니오</td>";
    return `<td>${esc(v ?? "–")}</td>`;
  }).join("") + "</tr>").join("");
  return `<div class="table-wrap"><table class="data"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
}
function note(kind, html) { return `<div class="note ${kind}">${html}</div>`; }

/** Plotly figure JSON 을 그린다. 차트 라이브러리를 못 불러왔거나 한 차트가
 *  실패해도 표와 나머지 화면은 그대로 보여야 하므로 여기서 막아 준다. */
function plot(el, fig) {
  if (!el) return;
  if (!window.Plotly || !fig || !fig.data) {
    el.innerHTML = note("warn", "차트 라이브러리를 불러오지 못해 그래프를 생략했습니다 (표는 그대로 사용할 수 있습니다).");
    return;
  }
  try {
    Plotly.react(el, fig.data, fig.layout, { responsive: true, displaylogo: false });
  } catch (err) {
    el.innerHTML = note("warn", "차트를 그리지 못했습니다: " + esc(err.message || err));
  }
}
function metric(k, v) { return `<div class="metric"><div class="k">${esc(k)}</div><div class="v">${esc(v)}</div></div>`; }

const REQUEST_TIMEOUT_MS = 300000;      // 5분 — 잠든 인스턴스가 깨서 계산까지 하는 시간

async function rawPost(path, body) {
  const wake = await ensureBackend((sec) => busyText(`백엔드를 깨우는 중… ${sec}초`));
  if (!wake.ok) throw new Error(wake.why);
  const res = await fetchTimeout(api(path), REQUEST_TIMEOUT_MS, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const json = await res.json().catch(() => ({ error: "응답을 읽지 못했습니다." }));
  if (!res.ok || json.error) throw new Error((json.error || "요청 실패") + (json.detail ? " — " + json.detail : ""));
  return json;
}

function looksOffline(err) {
  const msg = String((err && err.message) || err);
  return (err && (err.name === "TypeError" || err.name === "AbortError"))
    || /Failed to fetch|NetworkError|network|aborted|Load failed/i.test(msg);
}

/** 요청을 '되살려 가며' 보낸다. 무료 백엔드에서 실제로 일어나는 두 가지를 덮는다:
 *   1) 그 사이 인스턴스가 잠들었다 → 깨우고 한 번 더 보낸다.
 *   2) 인스턴스가 재시작돼 업로드 토큰이 사라졌다 → 기억해 둔 파일을 다시 올리고 한 번 더.
 *  makeBody 를 함수로 주면 재시도할 때 새 토큰으로 본문을 다시 만든다. */
async function post(path, makeBody) {
  const build = () => (typeof makeBody === "function" ? makeBody() : makeBody);
  try {
    return await rawPost(path, build());
  } catch (err) {
    const msg = String((err && err.message) || err);

    if (looksOffline(err) && API_BASE) {
      BACKEND_READY = false;                 // 그 사이 잠들었거나 재시작했다
      const wake = await ensureBackend((sec) =>
        busyText(`백엔드가 잠들어 있었습니다 — 깨우는 중… ${sec}초`));
      if (!wake.ok) throw new Error(wake.why);
      busyText("다시 요청하는 중…");
      return await rawPost(path, build());
    }

    if (/업로드 세션이 만료|세션이 만료/.test(msg)) {
      busyText("백엔드가 다시 시작돼 파일을 다시 올리는 중…");
      if (await reuploadSaved()) return await rawPost(path, build());
      throw new Error(msg + " ('이 브라우저에 데이터 기억'을 켜 두면 다음부터는 자동으로 다시 올립니다.)");
    }
    throw err;
  }
}

/** IndexedDB 에 기억해 둔 파일을 조용히 다시 올려 새 토큰을 받는다. */
async function reuploadSaved() {
  const saved = await savedSummary();
  if (!saved.length) return false;
  let done = 0;
  for (const rec of saved) {
    try {
      const file = new File([rec.buffer], rec.name, { type: rec.type || "text/csv" });
      const info = await inspectFile(rec.kind, file);
      info.mapping = { ...info.mapping, ...(rec.mapping || {}) };
      renderMapping(rec.kind, info);
      done += 1;
    } catch (err) { /* 하나라도 실패하면 아래에서 false 로 떨어진다 */ }
  }
  return done > 0;
}

function download(name, text, type = "text/csv;charset=utf-8") {
  const blob = new Blob(["﻿" + text], { type });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = name;
  a.click();
  URL.revokeObjectURL(a.href);
}

/* ------------------------------------------------------- parameter widgets */

function chips(container, name, values, selected) {
  container.classList.add("chips");
  container.innerHTML = values.map((v) =>
    `<label><input type="checkbox" name="${name}" value="${v}"${selected.includes(v) ? " checked" : ""}/>${v}</label>`
  ).join("");
}
function chipValues(name) {
  return $$(`input[name="${name}"]:checked`).map((el) => Number(el.value)).sort((a, b) => a - b);
}

function buildWeights(cfg) {
  const box = $("#weights");
  const groups = {};
  FEATURES.forEach((f) => { (groups[f.group] = groups[f.group] || []).push(f); });
  const saved = (cfg.similarity && cfg.similarity.weights) || {};
  box.innerHTML = '<div class="sub">Feature 가중치 (0 = 사용 안 함)</div>' +
    Object.entries(groups).map(([group, items]) => (
      `<div class="wgroup">${esc(group)}</div>` + items.map((f) => {
        const w = saved[f.key] !== undefined ? saved[f.key] : f.default_weight;
        return `<div class="wrow" title="${esc(f.description || "")}">
          <span>${esc(f.label)}</span>
          <input type="number" class="w" data-key="${f.key}" min="0" max="3" step="0.25" value="${w}" />
        </div>`;
      }).join("")
    )).join("");
}

function readWeights() {
  const out = {};
  $$("#weights input.w").forEach((el) => { out[el.dataset.key] = Number(el.value) || 0; });
  return out;
}

function strictRow(feature) {
  const options = FEATURES.map((f) =>
    `<option value="${f.key}"${f.key === feature ? " selected" : ""}>${esc(f.label)}</option>`).join("");
  const ops = OPS.map((o) => `<option>${o}</option>`).join("");
  const row = document.createElement("div");
  row.className = "strict-row";
  row.innerHTML = `<select class="s-key">${options}</select><select class="s-op">${ops}</select>
    <input type="number" class="s-val" step="0.1" value="0" /><button class="s-del small">×</button>`;
  row.querySelector(".s-del").addEventListener("click", () => row.remove());
  return row;
}

function readConditions() {
  return $$("#strict-list .strict-row").map((row) => ({
    key: row.querySelector(".s-key").value,
    op: row.querySelector(".s-op").value,
    value: Number(row.querySelector(".s-val").value) || 0,
  }));
}

function readParams() {
  return {
    market: { ticker: $("#p-ticker").value.trim() || "^IXIC", years: Number($("#p-years").value) || 20 },
    features: {
      sma_windows: chipValues("sma"),
      slope_window: Number($("#p-slope").value) || 20,
      return_windows: chipValues("ret"),
      high_window: Number($("#p-high").value) || 252,
      vol_window: Number($("#p-vol").value) || 20,
      atr_window: Number($("#p-atr").value) || 14,
    },
    distribution_day: {
      lookback: Number($("#p-dd-lb").value) || 25,
      drop_pct: Number($("#p-dd-drop").value),
      volume_bump_pct: Number($("#p-dd-vol").value),
      clv_max: Number($("#p-dd-clv").value),
    },
    similarity: {
      top_n: Number($("#p-topn").value) || 25,
      min_gap: Number($("#p-gap").value) || 20,
      episode_pick: $("#p-pick").value,
      exclude_recent: Number($("#p-exclude").value),
      normalization: $("#p-norm").value,
      require_full_horizon: $("#p-fullh").checked,
      weights: readWeights(),
    },
    forward: {
      horizons: chipValues("horizon"),
      bootstrap_samples: Number($("#p-boot").value),
      ci_level: Number($("#p-ci").value),
      min_sample_warn: Number($("#p-warn").value),
      independence: $("#p-indep").value,
      ci_method: $("#p-cimethod").value,
    },
    validation: {
      mode: $("#p-val-mode").value,
      train_end: $("#p-val-train").value,
      validation_end: $("#p-val-valid").value,
      step: Number($("#p-val-step").value) || 5,
      horizon: Number($("#p-val-h").value) || 20,
    },
  };
}

function dataMode() {
  const checked = $('input[name="dmode"]:checked');
  return checked ? checked.value : "auto";
}

function readData(useSession) {
  if (useSession && SESSION) return { session: SESSION };
  const mode = dataMode();
  const data = { mode, offline: $("#p-offline").checked };
  if (mode === "manual") {
    ["price", "volume", "yield"].forEach((kind) => {
      const up = UPLOADS[kind];
      if (!up || !up.token) return;
      data[kind] = { token: up.token, mapping: readMapping(kind) };
      if (kind === "yield") data[kind].unit = $("#p-yield-unit").value;
    });
  }
  return data;
}

function requestBody(useSession) {
  const mode = ($('input[name="mmode"]:checked') || {}).value || "similarity";
  return {
    params: readParams(),
    data: readData(useSession),
    mode,
    conditions: mode === "strict" ? readConditions() : [],
    anchor: $("#anchor").value || "",
    shade: Number($("#p-shade").value) || undefined,
    log_scale: $("#p-log").checked,
    show_sma: chipValues("showsma"),
    hist_horizon: Number($("#hist-h").value) || undefined,
  };
}

/* ------------------------------------------------- 브라우저에 데이터 기억하기
 *
 * 20년치 CSV 를 매번 다시 고르는 건 번거롭다. 올린 파일(원본 바이트)과 컬럼 매핑을
 * IndexedDB 에 담아 두고, 다음에 페이지를 열면 그대로 복원한다. 서버에는 아무것도
 * 저장하지 않는다 — 브라우저 밖으로 나가지 않는 보관이다.
 */
const DB_NAME = "suh_dh_regime";
const DB_STORE = "uploads";

function idb() {
  return new Promise((resolve, reject) => {
    if (!window.indexedDB) { reject(new Error("이 브라우저는 IndexedDB 를 지원하지 않습니다.")); return; }
    const req = indexedDB.open(DB_NAME, 1);
    req.onupgradeneeded = () => req.result.createObjectStore(DB_STORE);
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}
async function idbSet(key, value) {
  const db = await idb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(DB_STORE, "readwrite");
    tx.objectStore(DB_STORE).put(value, key);
    tx.oncomplete = () => resolve(true);
    tx.onerror = () => reject(tx.error);
  });
}
async function idbGet(key) {
  const db = await idb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(DB_STORE, "readonly");
    const req = tx.objectStore(DB_STORE).get(key);
    req.onsuccess = () => resolve(req.result || null);
    req.onerror = () => reject(req.error);
  });
}
async function idbDel(key) {
  const db = await idb();
  return new Promise((resolve) => {
    const tx = db.transaction(DB_STORE, "readwrite");
    tx.objectStore(DB_STORE).delete(key);
    tx.oncomplete = () => resolve(true);
    tx.onerror = () => resolve(false);
  });
}

function remembering() { return $("#p-remember").checked; }

async function remember(kind, file, info) {
  if (!remembering()) return;
  try {
    await idbSet(kind, {
      name: file.name, type: file.type || "", buffer: await file.arrayBuffer(),
      mapping: info.mapping, rows: info.rows, savedAt: new Date().toISOString(),
      unit: kind === "yield" ? $("#p-yield-unit").value : undefined,
    });
    renderSaved();
  } catch (err) {
    setStatus("이 브라우저에 저장하지 못했습니다 (분석은 그대로 됩니다)", "warn");
  }
}

/* ---------------------------------------------- 마지막 분석 결과 기억하기
 *
 * 올린 파일은 IndexedDB 에 남아 새로고침해도 복원되는데, 정작 분석 결과는 매번
 * 사라져서 "다시 올려야 하나" 싶게 만든다. 결과도 같이 담아 두고, 다음에 열면
 * 곧바로 되살린다 — 다만 "언제 실행한 결과"인지 분명히 밝힌다(최신 값이 아니다).
 * 파일이 바뀌면 지난 결과는 버린다.
 */
const RESULT_KEY = "last_result";

function dataFingerprint() {
  // 어떤 데이터로 낸 결과인지 — 파일이 바뀌면 지난 결과를 쓰지 않기 위한 지문.
  const parts = [dataMode(), $("#p-offline").checked ? "demo" : "live"];
  ["price", "volume", "yield"].forEach((kind) => {
    const up = UPLOADS[kind];
    if (up) parts.push(`${kind}:${up.name}:${up.rows}`);
  });
  return parts.join("|");
}

async function rememberResult(json) {
  if (!remembering()) return;
  try {
    await idbSet(RESULT_KEY, {
      json, fingerprint: dataFingerprint(), savedAt: new Date().toISOString(),
    });
  } catch (err) { /* 용량 초과 등 — 분석 자체에는 영향 없다 */ }
}

async function restoreResult() {
  if (!remembering()) return false;
  let rec = null;
  try { rec = await idbGet(RESULT_KEY); } catch (err) { return false; }
  if (!rec || !rec.json) return false;
  if (rec.fingerprint !== dataFingerprint()) {      // 데이터가 바뀌었다 — 옛 결과는 버린다
    try { await idbDel(RESULT_KEY); } catch (err) { /* 무시 */ }
    return false;
  }
  try {
    renderAll(rec.json);
    SESSION = null;                  // 서버 세션은 살아 있지 않을 수 있다 — 새로 만들게 둔다
    const when = new Date(rec.savedAt);
    const stamp = isNaN(when) ? "" : when.toLocaleString("ko-KR");
    $("#result-age").innerHTML =
      `지난 실행 결과입니다 (${esc(stamp)} · 기준일 ${esc(rec.json.anchor)}). ` +
      "최신 데이터·파라미터로 다시 보려면 <b>분석 실행</b>을 누르세요.";
    $("#result-age").classList.remove("hidden");
    setStatus(`지난 결과 복원 · ${rec.json.matches.rows.length}개 match`, "warn");
    return true;
  } catch (err) { return false; }
}

async function savedSummary() {
  const out = [];
  for (const kind of ["price", "volume", "yield"]) {
    try {
      const rec = await idbGet(kind);
      if (rec) out.push({ kind, ...rec });
    } catch (err) { /* 저장소를 못 열면 없는 것으로 본다 */ }
  }
  return out;
}

async function renderSaved() {
  const saved = await savedSummary();
  const box = $("#saved-box");
  if (!saved.length) { box.classList.add("hidden"); return; }
  box.classList.remove("hidden");
  $("#saved-text").innerHTML = "이 브라우저에 저장됨 — " + saved.map((r) =>
    `<b>${esc(r.name)}</b> (${(r.rows || 0).toLocaleString()}행)`).join(" · ");
}

async function clearSaved() {
  try { await idbDel(RESULT_KEY); } catch (err) { /* 무시 */ }
  for (const kind of ["price", "volume", "yield"]) await idbDel(kind);
  ["price", "volume", "yield"].forEach((kind) => { UPLOADS[kind] = null; renderMapping(kind, null); });
  SESSION = null;
  renderSaved();
  setStatus("저장된 데이터를 지웠습니다");
}

/** 저장해 둔 파일을 서버에 다시 올려(세션 토큰만 새로 받아) 매핑까지 복원한다. */
async function restoreSaved() {
  const saved = await savedSummary();
  if (!saved.length) return false;
  let restored = 0;
  for (const rec of saved) {
    try {
      const file = new File([rec.buffer], rec.name, { type: rec.type || "text/csv" });
      // 저장된 매핑으로 화면부터 즉시 되살리고, 서버 업로드(토큰)는 뒤에서 진행한다.
      const quick = await quickInspect(rec.kind, file);
      if (quick) {
        quick.mapping = { ...quick.mapping, ...(rec.mapping || {}) };
        UPLOADS[rec.kind] = quick;
        renderMapping(rec.kind, quick);
      }
      PENDING[rec.kind] = inspectFile(rec.kind, file).then((info) => {
        info.mapping = { ...info.mapping, ...(rec.mapping || {}) };
        renderMapping(rec.kind, info);
        PENDING[rec.kind] = null;
        return info;
      }).catch((err) => { PENDING[rec.kind] = null; throw err; });
      if (!quick) await PENDING[rec.kind];          // XLSX 는 서버 응답이 필요하다
      if (rec.kind === "yield" && rec.unit) $("#p-yield-unit").value = rec.unit;
      restored += 1;
    } catch (err) { /* 파일이 깨졌거나 백엔드가 없으면 조용히 넘어간다 */ }
  }
  if (restored) {
    document.querySelector('input[name="dmode"][value="manual"]').checked = true;
    $("#upload-box").classList.remove("hidden");
    $("#params details").open = true;
    setStatus(`저장된 데이터 ${restored}개를 복원했습니다 — 분석 실행을 누르세요`);
  }
  renderSaved();
  return restored > 0;
}

/* ------------------------------------------------------------- file upload
 *
 * 파일을 고르면 **브라우저에서 헤더만 먼저 읽어** 컬럼 매핑을 즉시 보여 주고,
 * 서버 업로드(토큰 확보)는 그동안 뒤에서 진행한다. 무료 백엔드가 잠들어 있으면
 * 첫 요청이 30~60초 걸리는데, 그 시간을 사용자가 매핑을 확인하는 데 쓰게 하는 것이다.
 * XLSX 는 브라우저에서 못 읽으므로 서버 응답을 기다린다.
 */

// 파이썬 upload.ALIASES 와 같은 별칭 — 화면에 먼저 보여 주기 위한 것이고,
// 서버 응답이 오면 그쪽 추정으로 맞춰 준다(최종 매핑은 사용자가 확정).
const ALIASES = {
  date: ["date", "날짜", "일자", "기준일", "datetime", "time", "timestamp", "일시",
         "tradedate", "dt", "index", "observationdate", "period"],
  open: ["open", "시가", "openprice", "시작가", "o"],
  high: ["high", "고가", "highprice", "h"],
  low: ["low", "저가", "lowprice", "l"],
  close: ["close", "종가", "closelast", "adjclose", "adjustedclose", "last",
          "lastprice", "closeprice", "price", "c", "settle"],
  volume: ["volume", "거래량", "vol", "totalvolume", "shares", "v", "거래수량"],
  yield: ["yield", "금리", "수익률", "rate", "dgs10", "value", "close", "종가",
          "10y", "tnx", "yieldpct", "국채금리"],
};
const FIELDS = { price: ["date", "open", "high", "low", "close", "volume"],
                 volume: ["date", "volume"], yield: ["date", "yield"] };
const PENDING = {};              // kind → 서버 업로드 Promise

function normKey(name) {
  return String(name || "").toLowerCase().replace(/[^0-9a-z가-힣]/g, "");
}
function suggestMappingLocal(columns, fields) {
  const norm = columns.map(normKey);
  const used = new Set();
  const out = {};
  fields.forEach((field) => {
    const aliases = ALIASES[field] || [field];
    let pick = null;
    for (const alias of aliases) {                       // 1) 정확히 일치
      const i = norm.findIndex((n, idx) => n === alias && !used.has(columns[idx]));
      if (i >= 0) { pick = columns[i]; break; }
    }
    if (!pick) {                                         // 2) 부분 일치 (3글자 이상만)
      for (const alias of aliases.filter((a) => a.length >= 3)) {
        const i = norm.findIndex((n, idx) => n.includes(alias) && !used.has(columns[idx]));
        if (i >= 0) { pick = columns[i]; break; }
      }
    }
    if (pick) used.add(pick);
    out[field] = pick || null;
  });
  return out;
}
function splitLine(line, delim) {
  const out = [];
  let cur = "", quoted = false;
  for (const ch of line) {
    if (ch === '"') { quoted = !quoted; continue; }
    if (ch === delim && !quoted) { out.push(cur); cur = ""; continue; }
    cur += ch;
  }
  out.push(cur);
  return out.map((c) => c.replace(/^\ufeff/, "").trim());
}

/** CSV 한정: 브라우저에서 헤더를 읽어 즉시 매핑 후보를 만든다. */
async function quickInspect(kind, file) {
  if (!/\.(csv|txt|tsv)$/i.test(file.name)) return null;
  try {
    const text = await file.text();
    const lines = text.split(/\r?\n/).filter((l) => l.trim().length);
    if (!lines.length) return null;
    const delim = [",", "\t", ";"].reduce((best, d) =>
      (lines[0].split(d).length > lines[0].split(best).length ? d : best), ",");
    const columns = splitLine(lines[0], delim);
    if (columns.length < 2) return null;
    const fields = FIELDS[kind] || FIELDS.price;
    return { name: file.name, rows: lines.length - 1, columns, fields,
             mapping: suggestMappingLocal(columns, fields), local: true };
  } catch (err) {
    return null;                                          // 못 읽으면 서버에 맡긴다
  }
}

async function inspectFile(kind, file) {
  // 업로드는 화면에서 제일 먼저 나가는 요청이라, 잠든 백엔드에 그대로 던지면
  // 응답 없이 매달린 채 '분석 실행'까지 같이 묶여 버린다. 문을 지나게 하고,
  // 시간 제한과 한 번의 재시도를 준다.
  const send = async () => {
    const form = new FormData();
    form.append("file", file);
    form.append("kind", kind);
    const res = await fetchTimeout(api("/api/regime/inspect"), REQUEST_TIMEOUT_MS,
                                   { method: "POST", body: form });
    const json = await res.json();
    if (!res.ok || json.error) throw new Error(json.error + (json.detail ? " — " + json.detail : ""));
    return json;
  };

  const wake = await ensureBackend((sec) => setStatus(`백엔드를 깨우는 중… ${sec}초`, "warn"));
  if (!wake.ok) throw new Error(wake.why);

  let json;
  try {
    json = await send();
  } catch (err) {
    if (!looksOffline(err)) throw err;
    BACKEND_READY = false;
    const again = await ensureBackend((sec) => setStatus(`백엔드를 다시 깨우는 중… ${sec}초`, "warn"));
    if (!again.ok) throw new Error(again.why);
    json = await send();
  }
  UPLOADS[kind] = json;
  SESSION = null;                         // 데이터가 바뀌면 세션을 새로 만든다
  renderMapping(kind, json);
  return json;
}

async function onFile(kind, file) {
  if (!file) return;
  const quick = await quickInspect(kind, file);
  if (quick) {
    // 서버를 기다리지 않고 바로 컬럼 매핑을 보여 준다.
    UPLOADS[kind] = quick;
    SESSION = null;
    renderMapping(kind, quick);
    const hasVolume = kind === "price" && quick.mapping.volume;
    setStatus(`${quick.name} · ${quick.rows.toLocaleString()}행 인식` +
              (hasVolume ? " (거래량 포함)" : "") + " · 업로드 중…");
  } else {
    busy(true, `${file.name} 읽는 중…`);
  }

  const upload = inspectFile(kind, file).then(async (json) => {
    if (quick) {
      // 사용자가 고른 값은 유지하고, 서버 추정은 비어 있는 칸만 채운다.
      const chosen = readMapping(kind);
      json.mapping = { ...json.mapping, ...Object.fromEntries(
        Object.entries(chosen).filter(([, v]) => v)) };
      renderMapping(kind, json);
    }
    await remember(kind, file, json);
    setStatus(`${json.name} · ${json.rows.toLocaleString()}행 준비됨`);
    return json;
  });
  PENDING[kind] = upload;

  try {
    await upload;
  } catch (err) {
    UPLOADS[kind] = null;
    const backendMissing = !API_BASE && STATIC;
    renderMapping(kind, null, backendMissing
      ? "분석 백엔드 주소가 연결되지 않아 파일을 읽을 수 없습니다 — 화면 위의 '분석 백엔드 주소'에 주소를 넣어 주세요."
      : String(err.message || err));
    setStatus("파일을 읽지 못했습니다", "bad");
  } finally {
    PENDING[kind] = null;
    busy(false);
  }
}

function readMapping(kind) {
  const out = {};
  $$(`.map[data-kind="${kind}"] select`).forEach((sel) => { out[sel.dataset.field] = sel.value || null; });
  return out;
}

function renderMapping(kind, info, error) {
  const box = document.querySelector(`.map[data-kind="${kind}"]`);
  if (error) { box.innerHTML = `<p class="hint" style="color:var(--bad)">${esc(error)}</p>`; return; }
  if (!info) { box.innerHTML = ""; return; }
  const options = (sel) => ['<option value="">(없음)</option>']
    .concat(info.columns.map((c) => `<option value="${esc(c)}"${c === sel ? " selected" : ""}>${esc(c)}</option>`))
    .join("");
  box.innerHTML = info.fields.map((f) =>
    `<label>${esc(f)}<select data-field="${f}">${options(info.mapping[f])}</select></label>`).join("") +
    `<p class="hint" style="grid-column:1/-1">${esc(info.name)} · ${info.rows.toLocaleString()}행 · 컬럼 매핑을 확인하세요.</p>`;
  box.querySelectorAll("select").forEach((sel) => sel.addEventListener("change", () => { SESSION = null; }));
}

/* ------------------------------------------------------------- rendering */

function renderSources(j) {
  $("#data-review").classList.remove("hidden");
  const series = Object.entries(j.series || {}).map(([sym, info]) =>
    metric(`${info.label || sym} 최종 업데이트`, info.last_date || "–")).join("");
  $("#sources").innerHTML = `<div class="metrics">${series}</div>` + tableHtml(j.sources, 0);

  const q = j.quality || {};
  const kind = q.status === "fail" ? "fail" : (q.status === "warn" ? "warn" : "ok");
  const msg = { fail: "데이터에 치명적인 문제가 있습니다 — 결과를 신뢰하기 어렵습니다.",
                warn: `주의 항목 ${(q.problems || []).length}건 — 내용을 확인하세요.`,
                ok: "데이터 품질 검사 통과 (기간 · 중복 · 공백 · 결측 · 최신성 · OHLC · 거래량 · 금리 단위)" }[kind];
  $("#quality-banner").innerHTML = note(kind, msg);
  const problems = (q.problems || []).map((p) =>
    `<li><b>[${esc(p.series)}] ${esc(p.label)}</b> — ${esc(p.detail)}${p.suggestion ? ` <span class="muted">(${esc(p.suggestion)})</span>` : ""}</li>`).join("");
  $("#quality-problems").innerHTML = problems ? `<ul class="method small">${problems}</ul>` : "";
  (j.notes || []).forEach((n) => {
    $("#quality-problems").insertAdjacentHTML("beforeend", note(n.level === "fail" ? "fail" : "warn", esc(n.message)));
  });
}

function renderState(j) {
  const s = j.state;
  const head = `<h2>기준일 ${esc(s.date)} 의 시장 상태</h2>` +
    `<div class="metrics">${metric("종가", (s.close || 0).toLocaleString())}` +
    s.groups.flatMap((g) => g.items.filter((i) =>
      ["ret_5", "dd_52w", "vol_realized", "dd_count"].includes(i.key))
      .map((i) => metric(i.label, i.formatted))).join("") + "</div>";
  const groups = s.groups.map((g) =>
    `<h3>${esc(g.group)}</h3><div class="metrics">` +
    g.items.map((i) => metric(i.label, i.formatted)).join("") + "</div>").join("");
  const dd = `<h3>분산일 상세</h3><p class="muted small">조건: ${esc(s.distribution.condition)}</p>` +
    tableHtml(s.distribution.recent, 3);
  $("#panel-state").innerHTML = head + groups + dd;
}

function renderMatches(j) {
  const dropped = Object.entries(j.dropped_features || {});
  $("#match-summary").innerHTML =
    `${j.matches.rows.length}개 match · 후보 ${j.candidates.toLocaleString()}일 · 사용 feature ${j.used_features.length}개` +
    (dropped.length ? ` · 제외 ${dropped.map(([k, v]) => `${esc(k)}(${esc(v)})`).join(", ")}` : "");
  plot($("#chart-price"), j.charts.price);
  $("#match-table").innerHTML = tableHtml(j.matches, 2);
}

function renderForward(j) {
  const f = j.forward;
  const ci = Math.round(f.ci_level * 100);
  const rows = [];
  f.rows.forEach((r) => {
    [["Matched", r.matched], ["Baseline", r.baseline]].forEach(([name, s]) => {
      rows.push(`<tr><td>+${r.horizon}일</td><td>${name}</td><td>${s.n}</td>
        <td>${num(s.mean)}</td><td>${num(s.median)}</td><td>${num(s.win_rate, 1)}</td>
        <td>${num(s.p25)}</td><td>${num(s.p75)}</td><td>${num(s.min)}</td><td>${num(s.max)}</td>
        <td>${num(s.std)}</td><td>${num(s.mdd_mean)}</td>
        <td>[${num(s.ci_mean[0])}, ${num(s.ci_mean[1])}]</td>
        <td>[${num(s.ci_median[0])}, ${num(s.ci_median[1])}]</td></tr>`);
    });
  });
  const statsTable = `<div class="table-wrap"><table class="data"><thead><tr>
    <th>Horizon</th><th>표본</th><th>N</th><th>평균(%)</th><th>중앙값(%)</th><th>승률(%)</th>
    <th>25%</th><th>75%</th><th>최소</th><th>최대</th><th>표준편차</th><th>평균 MDD</th>
    <th>평균 ${ci}% CI</th><th>중앙값 ${ci}% CI</th></tr></thead><tbody>${rows.join("")}</tbody></table></div>`;

  const diff = `<h3>Baseline 대비 초과/부족</h3><div class="table-wrap"><table class="data"><thead><tr>
    <th>Horizon</th><th>평균 차이(%p)</th><th>중앙값 차이(%p)</th><th>승률 차이(%p)</th>
    <th>Baseline 백분위</th><th>평균 CI 가 0 제외</th></tr></thead><tbody>` +
    f.rows.map((r) => `<tr><td>+${r.horizon}일</td><td>${signed(r.diff_mean, 2, "")}</td>
      <td>${signed(r.diff_median, 2, "")}</td><td>${signed(r.diff_win_rate, 1, "")}</td>
      <td>${num(r.baseline_pctile, 0)}</td><td>${r.ci_excludes_zero ? "예" : "아니오"}</td></tr>`).join("") +
    "</tbody></table></div>";

  const indep = `<h3>표본 독립성 진단</h3>
    <p class="muted small">n_eff = n² / Σ max(0, 1 − |tᵢ−tⱼ|/h) — forward 구간이 얼마나 겹치는지로 n 을 할인한 값.
    'i.i.d. 과소추정'이 양수면 단순 i.i.d. bootstrap 을 썼을 때 신뢰구간이 그만큼 좁게 나온다는 뜻입니다.
    현재 설정: 표본 ${esc(f.independence)} · CI ${esc(f.ci_method)}</p>
    <div class="table-wrap"><table class="data"><thead><tr>
    <th>Horizon</th><th>표본 n</th><th>독립 에피소드</th><th>n_eff</th><th>n_eff/n</th><th>제외</th>
    <th>평균 CI 폭(%p)</th><th>i.i.d. CI 폭(%p)</th><th>i.i.d. 과소추정(%)</th></tr></thead><tbody>` +
    f.rows.map((r) => {
      const ratio = r.matched.n ? r.ess / r.matched.n : null;
      const under = r.ci_width ? (1 - r.ci_width_iid / r.ci_width) * 100 : null;
      return `<tr><td>+${r.horizon}일</td><td>${r.matched.n}</td><td>${r.n_episodes}</td>
        <td>${num(r.ess, 1)}</td><td>${num(ratio, 2)}</td><td>${r.dropped}</td>
        <td>${num(r.ci_width)}</td><td>${num(r.ci_width_iid)}</td><td>${num(under, 1)}</td></tr>`;
    }).join("") + "</tbody></table></div>";

  $("#forward-tables").innerHTML = statsTable + diff + indep;
  plot($("#chart-forward"), j.charts.forward_bar);
  plot($("#chart-dist"), j.charts.distribution);

  const warnings = f.rows.flatMap((r) => r.warnings.map((w) => `+${r.horizon}일: ${w}`));
  $("#forward-warnings").innerHTML = warnings.map((w) => note("warn", esc(w))).join("") +
    note("ok", "Baseline CI 는 block bootstrap(블록 길이 = horizon), matched CI 는 기본적으로 " +
               "cluster bootstrap(겹치는 match 를 한 에피소드로 묶어 에피소드 단위 재표본)으로 계산합니다.");
}

function renderQualityTab(j) {
  const q = j.quality || {};
  $("#panel-quality").innerHTML = "<h2>Data Source Summary</h2>" + tableHtml(j.sources, 0) +
    "<h2>데이터 품질 요약</h2>" + tableHtml(q.table, 2) +
    ((q.notes || []).length ? "<h3>참고</h3><ul class='method small'>" +
      q.notes.map((n) => `<li><b>[${esc(n.series)}] ${esc(n.label)}</b> — ${esc(n.detail)}</li>`).join("") + "</ul>" : "");
}

function renderAll(j) {
  LAST = j;
  SESSION = j.session;
  $("#result-age").classList.add("hidden");
  $("#intro").classList.add("hidden");
  $("#tabs").classList.remove("hidden");
  // 한 섹션이 실패해도 나머지 결과는 보여 준다.
  [["#sources", renderSources], ["#panel-state", renderState], ["#panel-matches", renderMatches],
   ["#panel-forward", renderForward], ["#panel-quality", renderQualityTab]].forEach(([sel, fn]) => {
    try { fn(j); } catch (err) {
      const el = $(sel);
      if (el) el.innerHTML = note("fail", "이 영역을 그리지 못했습니다: " + esc(err.message || err));
    }
  });

  const dates = j.match_dates || [];
  $("#audit-date").innerHTML = dates.map((d) => `<option value="${d}">${d}</option>`).join("");
  $("#audit-body").innerHTML = '<p class="muted small">날짜를 고르고 <b>불러오기</b>를 누르면 그 날짜의 계산 과정을 전부 펼쳐 봅니다.</p>';
  if (!$("#anchor").value) $("#anchor").value = j.anchor;
  $("#anchor").min = j.anchor_range[0];
  $("#anchor").max = j.anchor_range[1];
  const hist = $("#hist-h");
  hist.innerHTML = j.forward.horizons.map((h) =>
    `<option value="${h}"${h === j.hist_horizon ? " selected" : ""}>+${h} 거래일</option>`).join("");
  showTab(document.querySelector(".tab.active")?.dataset.tab || "state");
  setStatus(`완료 · ${j.matches.rows.length}개 match (기준일 ${j.anchor})`);
}

function renderAudit(a) {
  const summary = Object.entries(a.summary || {}).map(([k, v]) => metric(k, num(v, 4))).join("");
  const dec = Object.entries(a.declustering || {}).map(([k, v]) =>
    `<tr><td>${esc(k)}</td><td style="text-align:left">${esc(v)}</td></tr>`).join("");
  $("#audit-body").innerHTML = `
    <div class="metrics">${metric("기준일", a.anchor)}${metric("감사 대상일", a.date)}${summary}</div>
    <h3>① 원본 OHLCV (전일·당일·익일)</h3>${tableHtml(a.ohlcv, 2)}
    <h3>② 이동평균과 이격률 (저장값 vs 재계산)</h3>${tableHtml(a.trend, 4)}
    <h3>③ 분산일 판정 근거</h3>${tableHtml(a.distribution, 4)}
    <h3>lookback 내 분산일</h3>${tableHtml(a.dd_days, 3)}
    <h3>④ feature 별 raw → 표준화 → 거리 기여도</h3>${tableHtml(a.features, 4)}
    <p class="muted small">z = (raw − center) / scale, 기여도 = weight × (z차이)², 거리 = √(기여도 합 / 가중치 합).</p>
    <h3>⑤ de-clustering 전후</h3><div class="table-wrap"><table class="data"><tbody>${dec}</tbody></table></div>
    <h3>⑥ forward return 계산에 쓰인 시작·종료 가격</h3>${tableHtml(a.forward, 4)}
    ${(a.notes || []).map((n) => `<p class="muted small">· ${esc(n)}</p>`).join("")}`;
}

function renderValidation(v) {
  $("#val-body").innerHTML =
    `<div class="metrics">
      ${metric("In-Sample 초과수익 (%p)", signed(v.in_sample, 2, ""))}
      ${metric("Out-of-Sample 초과수익 (%p)", signed(v.out_of_sample, 2, ""))}
      ${metric("IS − OOS 격차 (%p)", (v.in_sample !== null && v.out_of_sample !== null)
        ? signed(v.in_sample - v.out_of_sample, 2, "") : "–")}
    </div>` + tableHtml(v.table, 3) + '<div id="chart-val" class="chart"></div>';
  plot($("#chart-val"), v.chart);
}

/* ------------------------------------------------------------------ flow */

async function run() {
  const btn = $("#run-btn");
  btn.disabled = true;
  try {
    const pending = Object.values(PENDING).filter(Boolean);
    if (pending.length) {
      busy(true, "파일 업로드를 마치는 중…");
      await Promise.all(pending).catch(() => {});
    }
    busy(true, "분석 중… (데이터 로드 → feature → 유사 국면 → forward return)");
    setStatus("분석 중…");
    const json = await post("/api/regime/analyze", () => requestBody(false));
    renderAll(json);
    rememberResult(json);              // 새로고침해도 결과가 남도록
  } catch (err) {
    setStatus("분석 실패", "bad");
    $("#intro").classList.remove("hidden");
    $("#intro-note").innerHTML = note("fail", esc(err.message || err));
  } finally {
    busy(false);
    btn.disabled = false;
  }
}

async function runAudit() {
  const date = $("#audit-date").value;
  if (!date) return;
  busy(true, "계산 과정을 불러오는 중…");
  try {
    renderAudit(await post("/api/regime/audit", () => ({ ...requestBody(true), date })));
  } catch (err) {
    $("#audit-body").innerHTML = note("fail", esc(err.message || err));
  } finally {
    busy(false);
  }
}

async function runValidation() {
  const btn = $("#val-btn");
  btn.disabled = true;
  busy(true, "Walk-forward 검증 실행 중… 수십 초 걸립니다");
  try {
    renderValidation(await post("/api/regime/validation", () => requestBody(true)));
  } catch (err) {
    $("#val-body").innerHTML = note("fail", esc(err.message || err));
  } finally {
    busy(false);
    btn.disabled = false;
  }
}

function downloadMatches() {
  if (!LAST) { setStatus("먼저 분석을 실행하세요", "warn"); return; }
  const { columns, rows } = LAST.matches;
  const csv = [columns.join(",")].concat(
    rows.map((r) => r.map((v) => (typeof v === "string" && v.includes(",") ? `"${v}"` : v ?? "")).join(","))
  ).join("\n");
  download(`regime_matches_${LAST.ticker.replace(/[^A-Za-z0-9]/g, "")}.csv`, csv);
}

async function downloadFeatures() {
  busy(true, "feature 표를 만드는 중…");
  try {
    const json = await post("/api/regime/features.csv", () => requestBody(true));
    download("regime_features.csv", json.csv);
  } catch (err) {
    setStatus(String(err.message || err), "bad");
  } finally {
    busy(false);
  }
}

function showTab(name) {
  $$(".tab").forEach((t) => t.classList.toggle("active", t.dataset.tab === name));
  $$(".panel").forEach((p) => p.classList.toggle("hidden", p.id !== `panel-${name}`));
  // 탭이 숨어 있는 동안 그려진 차트는 크기를 모르므로 보일 때 한 번 맞춰 준다.
  if (!window.Plotly) return;
  $$(`#panel-${name} .chart`).forEach((el) => { if (el.data) Plotly.Plots.resize(el); });
}

/* ------------------------------------------------------------------ init */

async function init() {
  $("#run-btn").addEventListener("click", run);
  $("#csv-btn").addEventListener("click", downloadMatches);
  $("#audit-btn").addEventListener("click", runAudit);
  $("#val-btn").addEventListener("click", runValidation);
  $("#feat-csv-btn").addEventListener("click", downloadFeatures);
  $$(".tab").forEach((t) => t.addEventListener("click", () => showTab(t.dataset.tab)));
  $("#hist-h").addEventListener("change", run);
  $$('input[name="dmode"]').forEach((el) => el.addEventListener("change", () => {
    SESSION = null;
    $("#upload-box").classList.toggle("hidden", dataMode() !== "manual");
  }));
  $$(".file").forEach((el) => el.addEventListener("change", (e) => onFile(el.dataset.kind, e.target.files[0])));
  ["#p-ticker", "#p-years", "#p-offline"].forEach((sel) =>
    $(sel).addEventListener("change", () => { SESSION = null; }));
  $$('input[name="mmode"]').forEach((el) => el.addEventListener("change", () => {
    const strict = ($('input[name="mmode"]:checked') || {}).value === "strict";
    $("#strict-box").classList.toggle("hidden", !strict);
    $("#weights").classList.toggle("hidden", strict);
  }));
  $("#api-save").addEventListener("click", () => {
    const url = normaliseUrl($("#api-url").value);
    if (!url) return;
    storeApiBase(url);
    API_BASE = url;
    location.reload();
  });
  $("#api-clear").addEventListener("click", () => {
    storeApiBase("");
    API_BASE = builtinApiBase();
    location.reload();
  });
  $("#api-url").addEventListener("keydown", (e) => { if (e.key === "Enter") $("#api-save").click(); });
  $("#saved-clear").addEventListener("click", clearSaved);
  $("#p-remember").addEventListener("change", () => { if (!remembering()) clearSaved(); });
  $("#strict-add").addEventListener("click", () =>
    $("#strict-list").appendChild(strictRow(FEATURES[0] && FEATURES[0].key)));

  // 설명 · 설치 안내 — 백엔드와 무관하게 언제나 열린다(깨우는 중에도 읽을 수 있게).
  const sheet = (id, on) => {
    $(id).classList.toggle("hidden", !on);
    if (on) $(id + "-close").focus();
  };
  [["#help", "#help-btn"], ["#setup", "#setup-btn"]].forEach(([id, btn]) => {
    $(btn).addEventListener("click", () => sheet(id, true));
    $(id + "-close").addEventListener("click", () => sheet(id, false));
    $(id).addEventListener("click", (e) => { if (e.target.dataset.close) sheet(id, false); });
  });
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    ["#help", "#setup"].forEach((id) => {
      if (!$(id).classList.contains("hidden")) sheet(id, false);
    });
  });

  // 백엔드를 깨운다. 무료 인스턴스는 30~60초 걸리는데, 그동안 화면이 멈춘 것처럼
  // 보이지 않도록 남은 초를 계속 알려 준다(파일 고르기·파라미터 조정은 그동안도 된다).
  if (API_BASE) {
    $("#intro-note").innerHTML = note("info",
      "분석 백엔드를 깨우는 중입니다 — 무료 인스턴스는 처음 한 번 30~60초가 걸립니다. " +
      "기다리는 동안 왼쪽에서 파일과 파라미터를 미리 골라 두셔도 됩니다.");
    let wake = await ensureBackend((sec) => setStatus(`백엔드를 깨우는 중… ${sec}초`, "warn"));

    // 브라우저에 저장해 둔 주소가 틀렸을 수 있다(예전에 손으로 넣어 둔 주소 등).
    // 저장값은 무엇보다 우선하므로, 한 번 실패하면 이 빌드의 기본 주소로 되돌려 본다.
    const builtin = builtinApiBase();
    if (!wake.ok && storedApiBase() && builtin && builtin !== API_BASE) {
      storeApiBase("");
      API_BASE = builtin;
      $("#intro-note").innerHTML = note("info",
        "저장해 둔 백엔드 주소가 응답하지 않아 기본 주소로 되돌립니다 — " +
        `<code>${esc(builtin)}</code>`);
      wake = await ensureBackend((sec) => setStatus(`기본 백엔드를 깨우는 중… ${sec}초`, "warn"));
    }

    if (!wake.ok) {
      setStatus(wake.wrong ? "백엔드 주소를 확인하세요" : "백엔드가 응답하지 않습니다", "bad");
      $("#intro-note").innerHTML = note("warn",
        `<b>${esc(API_BASE)}</b> — ${esc(wake.why)}<br>` +
        "<span class='small'>대시보드 백엔드(FastAPI)의 주소가 필요합니다. Render 라면 " +
        "<code>suh-dh-api</code> 처럼 <code>uvicorn app.main:app</code> 을 띄우는 서비스이고, " +
        "<code>/api/health</code> 를 열었을 때 <code>{\"status\":\"ok\"}</code> 가 보이는 주소입니다. " +
        "아래에 주소를 넣으면 이 브라우저에 기억되고, <b>지우기</b> 를 누르면 기본 주소로 돌아갑니다.</span>");
      $("#backend-setup").classList.remove("hidden");
      $("#api-url").value = API_BASE;
      return;
    }
    $("#intro-note").innerHTML = "";
    if (wake.seconds >= 5) setStatus(`백엔드 준비 완료 (${wake.seconds}초)`);
  }

  setStatus("설정을 불러오는 중…");
  try {
    const res = await fetchTimeout(api("/api/regime/defaults"), REQUEST_TIMEOUT_MS);
    const json = await res.json();
    if (!res.ok || json.error) throw new Error(json.error || "기본 설정을 불러오지 못했습니다.");
    DEFAULTS = json.config;
    FEATURES = json.features;
  } catch (err) {
    setStatus("백엔드 주소가 필요합니다", "warn");
    $("#intro-note").innerHTML = note("warn",
      (API_BASE
        ? `<b>${esc(API_BASE)}</b> 에 연결하지 못했습니다. 주소가 맞는지, 서버가 깨어났는지 확인하세요 ` +
          "(무료 인스턴스는 첫 요청에 30~60초 걸릴 수 있습니다)."
        : "이 페이지는 정적 사이트라 계산을 직접 할 수 없습니다. 분석 백엔드 주소를 한 번만 연결해 주세요.") +
      "<br><span class='small'>" + esc(err.message || err) + "</span>");
    $("#backend-setup").classList.remove("hidden");
    $("#api-url").value = API_BASE || "";
    return;
  }

  const cfg = DEFAULTS;
  $("#p-ticker").value = cfg.market.ticker;
  $("#p-years").value = cfg.market.years;
  chips($("#p-sma"), "sma", SMA_CHOICES, cfg.features.sma_windows);
  chips($("#p-rets"), "ret", RET_CHOICES, cfg.features.return_windows);
  chips($("#p-horizons"), "horizon", HORIZON_CHOICES, cfg.forward.horizons);
  chips($("#p-showsma"), "showsma", SMA_CHOICES, [50, 200]);
  $("#p-slope").value = cfg.features.slope_window;
  $("#p-high").value = cfg.features.high_window;
  $("#p-vol").value = cfg.features.vol_window;
  $("#p-atr").value = cfg.features.atr_window;
  $("#p-dd-lb").value = cfg.distribution_day.lookback;
  $("#p-dd-drop").value = cfg.distribution_day.drop_pct;
  $("#p-dd-vol").value = cfg.distribution_day.volume_bump_pct;
  $("#p-dd-clv").value = cfg.distribution_day.clv_max;
  $("#p-topn").value = cfg.similarity.top_n;
  $("#p-gap").value = String(cfg.similarity.min_gap);
  $("#p-pick").value = cfg.similarity.episode_pick;
  $("#p-exclude").value = cfg.similarity.exclude_recent;
  $("#p-norm").value = cfg.similarity.normalization;
  $("#p-fullh").checked = !!cfg.similarity.require_full_horizon;
  $("#p-boot").value = String(cfg.forward.bootstrap_samples);
  $("#p-ci").value = Number(cfg.forward.ci_level).toFixed(2);
  $("#p-warn").value = cfg.forward.min_sample_warn;
  $("#p-indep").value = cfg.forward.independence || "all";
  $("#p-cimethod").value = cfg.forward.ci_method || "cluster";
  $("#p-val-mode").value = cfg.validation.mode;
  $("#p-val-train").value = cfg.validation.train_end;
  $("#p-val-valid").value = cfg.validation.validation_end;
  $("#p-val-step").value = cfg.validation.step;
  $("#p-val-h").value = String(cfg.validation.horizon);
  $("#p-shade").innerHTML = cfg.forward.horizons.map((h) =>
    `<option value="${h}">+${h}일</option>`).join("");
  buildWeights(cfg);
  $("#strict-list").appendChild(strictRow("dd_52w"));

  setStatus("준비됨 — 분석 실행을 누르세요");
  await renderSaved();
  if (await restoreSaved()) {         // 이전에 올린 파일이 있으면 그대로 되살리고
    await restoreResult();            // 그 파일로 낸 지난 분석 결과까지 되살린다
  }
}

init();
