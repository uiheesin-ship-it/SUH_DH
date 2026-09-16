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
const API_BASE = (window.SUH_DH_API_BASE || "").replace(/\/+$/, "");
const api = (path) => (STATIC && API_BASE ? API_BASE + path : path);

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
function busy(on, text) {
  $("#overlay").classList.toggle("hidden", !on);
  $("#overlay-text").textContent = text || "";
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

async function post(path, body) {
  const res = await fetch(api(path), {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const json = await res.json().catch(() => ({ error: "응답을 읽지 못했습니다." }));
  if (!res.ok || json.error) throw new Error((json.error || "요청 실패") + (json.detail ? " — " + json.detail : ""));
  return json;
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
      if (!up) return;
      const mapping = {};
      $$(`.map[data-kind="${kind}"] select`).forEach((sel) => {
        mapping[sel.dataset.field] = sel.value || null;
      });
      data[kind] = { token: up.token, mapping };
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

/* ------------------------------------------------------------- file upload */

async function onFile(kind, file) {
  if (!file) return;
  busy(true, `${file.name} 읽는 중…`);
  try {
    const form = new FormData();
    form.append("file", file);
    form.append("kind", kind);
    const res = await fetch(api("/api/regime/inspect"), { method: "POST", body: form });
    const json = await res.json();
    if (!res.ok || json.error) throw new Error(json.error + (json.detail ? " — " + json.detail : ""));
    UPLOADS[kind] = json;
    SESSION = null;                       // 데이터가 바뀌면 세션을 새로 만든다
    renderMapping(kind, json);
    setStatus(`${json.name} · ${json.rows.toLocaleString()}행 읽음`);
  } catch (err) {
    UPLOADS[kind] = null;
    renderMapping(kind, null, String(err.message || err));
    setStatus("파일을 읽지 못했습니다", "bad");
  } finally {
    busy(false);
  }
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
  busy(true, "분석 중… (데이터 로드 → feature → 유사 국면 → forward return)");
  setStatus("분석 중…");
  try {
    const json = await post("/api/regime/analyze", requestBody(false));
    renderAll(json);
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
    renderAudit(await post("/api/regime/audit", { ...requestBody(true), date }));
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
    renderValidation(await post("/api/regime/validation", requestBody(true)));
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
    const json = await post("/api/regime/features.csv", requestBody(true));
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
  $("#strict-add").addEventListener("click", () =>
    $("#strict-list").appendChild(strictRow(FEATURES[0] && FEATURES[0].key)));

  setStatus("설정을 불러오는 중…");
  try {
    const res = await fetch(api("/api/regime/defaults"), { cache: "no-store" });
    const json = await res.json();
    if (!res.ok || json.error) throw new Error(json.error || "기본 설정을 불러오지 못했습니다.");
    DEFAULTS = json.config;
    FEATURES = json.features;
  } catch (err) {
    setStatus("백엔드에 연결하지 못했습니다", "bad");
    $("#intro-note").innerHTML = note("fail",
      "분석 백엔드에 연결하지 못했습니다. 정적 사이트에서 보고 있다면 " +
      "<code>SUH_DH_API_BASE</code> 가 설정된 빌드가 필요합니다. 로컬에서는 <code>./run.sh</code> 로 " +
      "대시보드를 띄우면 바로 동작합니다.<br><span class='small'>" + esc(err.message || err) + "</span>");
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
}

init();
