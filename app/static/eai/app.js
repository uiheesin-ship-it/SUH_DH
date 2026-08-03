"use strict";

// Two run modes (see config.js):
//   STATIC=false -> live FastAPI backend (/api/eai/*), used when running locally
//   STATIC=true  -> pre-built daily JSON in ../data/eai/*.json (GitHub Pages),
//                   produced by app/eai/export.py in GitHub Actions.
const STATIC = !!window.SUH_DH_STATIC;
const API_BASE = window.SUH_DH_API_BASE || "";

const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

// kind -> [staticPath, livePath]. Export mirrors the API response shapes.
const SRC = {
  index: ["../data/eai/index.json", "/api/eai/health"],
  themes: ["../data/eai/themes.json", "/api/eai/themes"],
  ideas: ["../data/eai/investment_themes.json", "/api/eai/investment-themes"],
  companies: ["../data/eai/companies.json", "/api/eai/companies"],
  coverage: ["../data/eai/coverage.json", "/api/eai/coverage"],
  usage: ["../data/eai/usage.json", "/api/eai/usage"],
};

async function load(kind, ticker) {
  let url;
  if (kind === "company") {
    url = STATIC ? `../data/eai/company/${ticker}.json`
                 : `${API_BASE}/api/eai/companies/${ticker}`;
  } else {
    const [s, l] = SRC[kind];
    url = STATIC ? s : `${API_BASE}${l}`;
  }
  const res = await fetch(url, { cache: "no-store" });
  if (!res.ok) throw new Error(`${url} → ${res.status}`);
  return res.json();
}

const fmt = (x) => (x == null ? "—" : (typeof x === "number" ? x.toFixed(2) : x));
const scoreBadge = (label, sb) => {
  const ins = !sb || sb.score == null || sb.status === "data_insufficient";
  const cls = ins ? "ins" : "ok";
  const val = ins ? "Data Insufficient" : sb.score;
  return `<span class="badge ${cls}">${label}: ${val}</span>`;
};
const STATUS_KO = {
  "Confirmed Acceleration": "가속 확인", "Narrative Ahead of Numbers": "내러티브>숫자",
  "Conservative or Underpromising": "보수적", "Mixed Signals": "혼재",
  "Confirmed Deterioration": "악화 확인",
};

function evidenceHtml(list) {
  if (!list || !list.length) return "";
  return list.map((e) =>
    `<div class="quote"><span class="pid">${esc(e.paragraph_id || "")}</span>“${esc(e.exact_quote_en || "")}”</div>`
  ).join("");
}

// ---------------- views ----------------
const views = {
  async themes() {
    const d = await load("themes");
    if (!d.themes.length) return `<p class="muted">아직 테마가 없습니다.</p>`;
    return `<div class="grid">${d.themes.map((t) => {
      const p = t.payload || {}, c = p.components || {};
      return `<div class="card">
        <h3>${esc(t.theme_name_ko)}</h3>
        <p class="en">${esc(t.theme_name_en)}</p>
        <p class="desc">${esc(p.theme_description_ko || "")}</p>
        <div class="badges">
          <span class="badge exp">Experimental</span>
          ${scoreBadge("Theme Score", { score: t.theme_score, status: t.score_status })}
          <span class="badge">지지 기업 ${p.company_count || 0}개</span>
          <span class="badge">Breadth ${fmt(c.breadth)}</span>
          <span class="badge">Numeric ${fmt(c.numeric_confirmation)}</span>
          <span class="badge">ValueChain ${fmt(c.value_chain_confirmation)}</span>
        </div>
        <div class="muted" style="margin-top:8px">지지: ${(p.companies_mentioning || []).join(", ") || "—"}</div>
        ${t.maturity_label ? `<div class="badge warn" style="margin-top:8px">${esc(t.maturity_label)}</div>` : ""}
        ${evidenceHtml(p.supporting_evidence)}
      </div>`;
    }).join("")}</div>`;
  },

  async ideas() {
    const d = await load("ideas");
    if (!d.investment_themes.length) return `<p class="muted">아직 투자 테마가 없습니다.</p>`;
    return d.investment_themes.map((it) => {
      const p = it.payload || {};
      const L = (title, arr) => (arr && arr.length)
        ? `<div class="section-title">${title}</div><ul class="tight">${arr.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>` : "";
      return `<div class="card" style="margin-bottom:14px">
        <h3>${esc(it.investment_theme)}</h3>
        <div class="badges">
          <span class="badge exp">Experimental</span>
          <span class="badge ${it.conviction === "high" ? "ok" : "ins"}">Conviction: ${esc(it.conviction)}</span>
          ${it.narrative_confirmation_status ? `<span class="badge">${STATUS_KO[it.narrative_confirmation_status] || it.narrative_confirmation_status}</span>` : ""}
          ${it.maturity_label ? `<span class="badge warn">${esc(it.maturity_label)}</span>` : ""}
        </div>
        <p class="desc" style="margin-top:8px">${esc(p.why_it_is_emerging || "")}</p>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:8px">
          ${L("지지 기업", p.companies_supporting)}${L("직접 수혜 후보", p.direct_beneficiaries)}
          ${L("2차 수혜 후보", p.secondary_beneficiaries)}${L("피해 가능", p.potential_losers)}
          ${L("미확인 가정", p.unconfirmed_assumptions)}${L("반대 근거/리스크", p.risks)}
          ${L("다음 분기 확인 지표", p.next_quarter_checkpoints)}
        </div>
        ${evidenceHtml(p.numeric_evidence)}${evidenceHtml(p.management_evidence)}
      </div>`;
    }).join("");
  },

  async companies() {
    const d = await load("companies");
    return `<table><thead><tr><th>티커</th><th>이름</th><th>섹터</th><th>구분</th><th>Signal Role</th></tr></thead>
      <tbody>${d.companies.map((c) =>
      `<tr><td><a href="#company/${c.ticker}">${c.ticker}</a></td><td>${esc(c.name)}</td>
        <td class="muted">${esc(c.sector || "")}</td><td>${esc(c.universe_type || "")}</td>
        <td>${(c.signal_roles || []).map((r) => `<span class="badge">${r.replace(/_sensor$/, "")}</span>`).join(" ")}</td></tr>`
    ).join("")}</tbody></table>`;
  },

  async company(ticker) {
    const d = await load("company", ticker);
    if (!d) return `<p class="muted">${ticker} 데이터가 없습니다.</p>`;
    const calls = (d.calls || []).map((call) => {
      const s = call.scores, sm = call.summary || {};
      const L = (title, arr) => (arr && arr.filter(Boolean).length)
        ? `<div class="section-title">${title}</div><ul class="tight">${arr.filter(Boolean).map((x) => `<li>${esc(x)}</li>`).join("")}</ul>` : "";
      return `<div class="card" style="margin-bottom:12px">
        <h3>FY${call.fiscal_year} Q${call.fiscal_quarter}</h3>
        <p class="desc">${esc(sm.executive_summary_ko || "")}</p>
        ${s ? `<div class="badges">
          <span class="badge exp">Experimental</span>
          ${scoreBadge("Narrative Momentum", s.narrative_momentum)}
          ${scoreBadge("Fundamental Confirmation", s.fundamental_confirmation)}
          <span class="badge">${STATUS_KO[s.narrative_confirmation_status] || s.narrative_confirmation_status || ""}</span>
          <span class="badge">검증 KPI ${s.verified_kpi_count || 0}개</span>
        </div>` : ""}
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:8px">
          ${L("Prepared vs Q&A", [sm.prepared_vs_qa_gap])}${L("내러티브 vs 숫자", [sm.narrative_vs_numbers_gap])}
          ${L("수요 신호", sm.demand_signals)}${L("가이던스 신호", sm.guidance_signals)}
          ${L("리스크", sm.risks)}${L("애널리스트 우려", sm.analyst_concerns)}
        </div>
      </div>`;
    }).join("");
    const qoq = (d.quarterly_comparisons || []).map((q) => {
      const p = q.payload || {};
      const L = (t, a) => (a && a.length) ? `<div class="section-title">${t}</div><ul class="tight">${a.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>` : "";
      return `<div class="card"><div class="muted">${esc(q.from_period)} → ${esc(q.to_period)}</div>
        ${L("신규 부상", p.newly_emerging_topics)}${L("가속", p.accelerating_topics)}
        ${L("약화", p.weakening_topics)}${L("소멸", p.disappeared_topics)}</div>`;
    }).join("");
    return `<p><a href="#companies">← 기업 목록</a></p>
      <h2 style="font-size:18px">${esc(d.name)} <span class="badge">${d.ticker}</span> <span class="badge">${esc(d.universe_type || "")}</span></h2>
      <p class="muted">${esc(d.sector || "")} · Signal Roles: ${(d.signal_roles || []).join(", ")}</p>
      ${calls}${qoq ? `<div class="section-title">분기 비교 (QoQ)</div>${qoq}` : ""}`;
  },

  async coverage() {
    const d = await load("coverage");
    const counts = (title, map) => `<div class="stat"><div class="l">${title}</div>
      ${Object.entries(map || {}).map(([k, v]) => `<div style="display:flex;justify-content:space-between"><span class="muted">${esc(k)}</span><span>${v}</span></div>`).join("")}</div>`;
    return `<div class="grid">
      <div class="stat"><div class="n">${d.total_companies}</div><div class="l">총 기업 수</div></div>
      ${counts("섹터별", d.by_sector)}${counts("Signal Role별", d.by_signal_role)}
      ${counts("밸류체인별", d.by_value_chain)}${counts("구분별", d.by_universe_type)}</div>
      <div class="card" style="margin-top:14px"><div class="section-title">확인 기업이 1개뿐인 Topic (커버리지 부족)</div>
      <div class="badges">${(d.single_company_topics || []).map((t) => `<span class="badge">${esc(t)}</span>`).join("") || '<span class="muted">없음</span>'}</div>
      <div class="badge warn" style="margin-top:8px">${esc(d.maturity || "")}</div></div>`;
  },

  async usage() {
    const d = await load("usage");
    const S = (n, l) => `<div class="stat"><div class="n">${n}</div><div class="l">${l}</div></div>`;
    return `<div class="grid">
      ${S(d.total_calls, "총 LLM 호출")}${S(d.input_tokens, "Input 토큰")}${S(d.output_tokens, "Output 토큰")}
      ${S("$" + Number(d.estimated_cost).toFixed(4), "예상 비용")}${S(d.cache_hit_rate, "Cache Hit Rate")}</div>
      <div class="card" style="margin-top:14px"><table><thead><tr><th>모델</th><th>호출</th><th>Input</th><th>Output</th><th>비용</th></tr></thead>
      <tbody>${Object.entries(d.by_model || {}).map(([m, v]) =>
      `<tr><td class="pid">${esc(m)}</td><td>${v.calls}</td><td>${v.input_tokens}</td><td>${v.output_tokens}</td><td>$${Number(v.estimated_cost).toFixed(6)}</td></tr>`).join("")}</tbody></table>
      <div class="muted" style="margin-top:8px">평균 처리시간 ${d.avg_processing_time}s · 모든 호출은 model_usage에 기록됩니다.</div></div>`;
  },
};

const TABS = [
  ["themes", "마켓 테마"], ["ideas", "투자 아이디어"], ["companies", "기업"],
  ["coverage", "유니버스 커버리지"], ["usage", "비용"],
];

function renderTabs(active) {
  $("#tabs").innerHTML = TABS.map(([k, l]) =>
    `<button class="tab ${k === active ? "active" : ""}" data-k="${k}">${l}</button>`).join("");
  $("#tabs").querySelectorAll(".tab").forEach((b) =>
    b.addEventListener("click", () => { location.hash = b.dataset.k; }));
}

async function route() {
  const hash = (location.hash || "#themes").slice(1);
  const [kind, arg] = hash.split("/");
  const tab = ["themes", "ideas", "companies", "coverage", "usage"].includes(kind) ? kind
            : (kind === "company" ? "companies" : "themes");
  renderTabs(tab);
  $("#view").innerHTML = `<p class="muted">불러오는 중…</p>`;
  try {
    const fn = views[kind] || views.themes;
    $("#view").innerHTML = await fn(arg);
  } catch (e) {
    $("#view").innerHTML = `<p class="muted">불러오지 못했습니다: ${esc(e.message)}<br/>
      ${STATIC ? "정적 데이터가 아직 생성되지 않았을 수 있습니다." : "백엔드(/api/eai)가 실행 중인지 확인하세요."}</p>`;
  }
}

async function boot() {
  try {
    const meta = await load("index");
    $("#maturity").textContent = "⚠️ " + (meta.maturity || "");
    $("#meta").textContent = [
      meta.built ? `업데이트 ${meta.built}` : "",
      meta.llm_provider ? `LLM=${meta.llm_provider}` : "",
      meta.transcript_provider ? `Transcript=${meta.transcript_provider}` : "",
    ].filter(Boolean).join(" · ");
  } catch (_) { /* index optional */ }
  window.addEventListener("hashchange", route);
  route();
}
boot();
