"use strict";

// 분기 실적표 프런트엔드.
//
// 두 가지 실행 모드 (config.js 참고):
//   STATIC=false -> 라이브 FastAPI 백엔드 (/api/qtable/{ticker}) — 로컬 실행
//   STATIC=true  -> 빌드된 JSON (../data/qtable/{TICKER}.json) — GitHub Pages.
//                   미리 만들어지지 않은 티커는 SUH_DH_API_BASE 백엔드로 폴백.
const STATIC = !!window.SUH_DH_STATIC;
const BUILT = window.SUH_DH_BUILT || null;
const API_BASE = (window.SUH_DH_API_BASE || "").replace(/\/$/, "");

let TABLE = null;   // 마지막으로 그린 표(복사·CSV용)

const $ = (sel) => document.querySelector(sel);

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

// ---------- 렌더 ----------
const SOURCE_KO = {
  curated: "큐레이션(보도자료·발표자료)",
  yfinance: "Yahoo Finance 자동 수집",
  derived: "역산",
};

function cellTitle(cell, colLabel, rowLabel) {
  const bits = [`${colLabel} · ${rowLabel}`];
  if (cell.low != null && cell.high != null) bits.push(`밴드 ${cell.low}~${cell.high}`);
  if (cell.source) bits.push(SOURCE_KO[cell.source] || cell.source);
  if (cell.note) bits.push(cell.note);
  if (cell.sources && cell.sources.length) bits.push(cell.sources.join("\n"));
  return bits.join("\n");
}

// 실적 행은 컨센서스와 비교해 상회(빨강)/하회(파랑)로 물들인다.
function beatClass(table, metricIdx, colIdx) {
  const sec = (key) => table.sections.find((s) => s.key === key);
  const act = sec("actual"), cons = sec("consensus");
  if (!act || !cons) return "";
  const a = act.rows[metricIdx].cells[colIdx];
  const c = cons.rows[metricIdx].cells[colIdx];
  if (a?.value == null || c?.value == null || c.value === 0) return "";
  const diff = (a.value - c.value) / Math.abs(c.value);
  if (Math.abs(diff) < 0.005) return "";
  return diff > 0 ? "beat" : "miss";
}

function renderTable(table) {
  const cols = table.columns;
  const head = `
    <thead>
      <tr class="yr">
        <th class="rowhead" rowspan="2">${esc(table.ticker)}<br><span class="unit">${esc(table.unit_ko)} 단위</span></th>
        ${cols.map((c) => `<th class="${c.status}${c.anchor ? " anchor" : ""}">${esc(c.year)}</th>`).join("")}
      </tr>
      <tr class="qr">
        ${cols.map((c) => {
          const tip = [`${c.label} (${c.status === "reported" ? "발표" : "미발표"})`,
                       `분기 마감 ${c.period_end}`,
                       c.report_date ? `발표일 ${c.report_date}` : ""].filter(Boolean).join("\n");
          return `<th class="${c.status}${c.anchor ? " anchor" : ""}" title="${esc(tip)}">${esc(c.quarter)}</th>`;
        }).join("")}
      </tr>
    </thead>`;

  const body = table.sections.map((section) => {
    const secRow = `<tr class="section"><td class="rowhead">${esc(section.label)}</td>` +
      cols.map((c) => `<td class="${c.status}"></td>`).join("") + "</tr>";
    const rows = section.rows.map((row, mi) => {
      const cells = row.cells.map((cell, ci) => {
        const col = cols[ci];
        const txt = cell.text || "";
        const cls = ["val", col.status];
        if (!txt) cls.push("empty");
        else if (cell.value == null) cls.push("text");        // 미제공 / 연간 제공
        if (cell.source === "curated") cls.push("curated");
        if (section.key === "actual" && txt) {
          const b = beatClass(table, mi, ci);
          if (b) cls.push(b);
        }
        const title = txt ? ` title="${esc(cellTitle(cell, col.label, `${section.label} ${row.label}`))}"` : "";
        return `<td class="${cls.join(" ")}"${title}>${esc(txt || "–")}</td>`;
      }).join("");
      return `<tr data-section="${esc(section.key)}"><td class="rowhead"><span class="m">${esc(row.label)}</span></td>${cells}</tr>`;
    }).join("");
    return secRow + rows;
  }).join("");

  return `<div class="table-wrap"><table class="qt">${head}<tbody>${body}</tbody></table></div>`;
}

function renderMeta(table) {
  const a = table.anchor;
  const chips = [
    `기준 분기 <b>${esc(a.label)}</b>${a.report_date ? ` (발표 ${esc(a.report_date)})` : ""}`,
    `${esc(table.fy_end_month)}월 결산`,
    `단위 ${esc(table.unit_label)}`,
    `과거 ${table.past}개 + 향후 ${table.ahead}개 분기`,
  ];
  if (table.basis) chips.push(esc(table.basis));
  const warn = table.fetch_error
    ? `<span class="chip warn" title="${esc(table.fetch_error)}">Yahoo 수집 실패 — 큐레이션 값만</span>` : "";
  const curated = table.curated
    ? "" : `<span class="chip warn">가이던스 큐레이션 없음 — tools/qtable.py add 로 입력</span>`;
  return `<div class="meta">
      <span class="name">${esc(table.name || table.ticker)}</span>
      <span class="tick">${esc(table.ticker)}</span>
      ${chips.map((c) => `<span class="chip">${c}</span>`).join("")}
      ${warn}${curated}
    </div>`;
}

function renderLegend(table) {
  const notes = (table.notes || []).map((n) => `<li>${esc(n)}</li>`).join("");
  return `<div class="legend">
      <span><span class="k g">가이던스</span> 큐레이션</span>
      <span><span class="k c">컨센서스</span> 야후 + 큐레이션</span>
      <span><span class="k a">실적</span> 야후 자동 수집 (큐레이션 우선)</span>
      <span>실적 색: <span class="k beat">컨센서스 상회</span> / <span class="k miss">하회</span></span>
      <span>· 표시 = 큐레이션 값 (마우스 올리면 출처)</span>
    </div>${notes ? `<ul class="notes">${notes}</ul>` : ""}`;
}

function render(table) {
  TABLE = table;
  $("#content").innerHTML = renderMeta(table) + renderTable(table) + renderLegend(table);
}

function renderError(msg, detail) {
  TABLE = null;
  $("#content").innerHTML =
    `<div class="error"><b>${esc(msg)}</b>${detail ? "<br><small>" + esc(detail) + "</small>" : ""}</div>`;
  $("#status").textContent = "오류";
}

// ---------- 격자(엑셀 붙여넣기 / CSV) ----------
function toGrid(table) {
  const cols = table.columns;
  const grid = [[""].concat(cols.map((c) => c.year)), [""].concat(cols.map((c) => c.quarter))];
  table.sections.forEach((s) => {
    grid.push([s.label].concat(cols.map(() => "")));
    s.rows.forEach((r) => grid.push(["    " + r.label].concat(r.cells.map((c) => c.text || ""))));
  });
  return grid;
}

function toDelimited(table, sep) {
  return toGrid(table).map((row) => row.map((cell) => {
    if (sep !== ",") return cell;
    const v = String(cell).replace(/"/g, '""');
    return /[",]/.test(v) ? `"${v}"` : v;
  }).join(sep)).join("\n") + "\n";
}

async function copyTable() {
  if (!TABLE) return;
  const text = toDelimited(TABLE, "\t");
  try {
    await navigator.clipboard.writeText(text);
    $("#status").textContent = "표를 복사했어요 — 엑셀에 붙여넣기(Ctrl+V)";
  } catch (_) {
    // 클립보드 권한이 없으면 선택해서 복사할 수 있게 보여준다.
    window.prompt("복사할 표 (Ctrl+C)", text);
  }
}

function downloadCsv() {
  if (!TABLE) return;
  // 엑셀이 UTF-8 로 열도록 BOM 을 붙인다.
  const blob = new Blob(["﻿" + toDelimited(TABLE, ",")], { type: "text/csv;charset=utf-8" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `${TABLE.ticker}_분기실적표.csv`;
  a.click();
  URL.revokeObjectURL(a.href);
}

// ---------- 로드 ----------
async function loadTable(ticker) {
  ticker = (ticker || "").trim().toUpperCase();
  if (!ticker) return;
  $("#status").textContent = "불러오는 중…";
  $("#content").innerHTML = `<div class="loading">${esc(ticker)} 분기 실적표를 만드는 중…</div>`;
  try {
    const url = STATIC ? `../data/qtable/${ticker}.json` : `/api/qtable/${ticker}`;
    let res = await fetch(url, { cache: "no-store" });
    if (!res.ok && STATIC) {
      if (API_BASE) {
        $("#content").innerHTML = `<div class="loading">${esc(ticker)} 라이브 조회 중 (백엔드)…</div>`;
        res = await fetch(`${API_BASE}/api/qtable/${ticker}`, { cache: "no-store" });
      } else {
        renderError(`${ticker}는 미리 만들어진 목록에 없습니다.`,
          "정적 사이트에선 빌드된 티커만 조회됩니다. 백엔드(SUH_DH_API_BASE)를 연결하거나 로컬에서 ./run.sh 로 실행하면 아무 티커나 조회할 수 있어요.");
        return;
      }
    }
    const data = await res.json();
    if (!res.ok || data.error) {
      renderError(data.error || "데이터를 불러오지 못했습니다.", data.detail);
      return;
    }
    document.title = `${ticker} 분기 실적표 · SUH_DH`;
    render(data);
    $("#demo-badge").classList.toggle("hidden", !data.demo);
    $("#status").textContent = `${esc(ticker)} · 채워진 칸 ${data.filled_cells}개`
      + (STATIC && BUILT ? ` · 갱신 ${new Date(BUILT).toLocaleDateString("ko-KR")}` : "");
    if (location.hash.slice(1) !== ticker) location.hash = ticker;
    renderRegistered(ticker);
  } catch (e) {
    renderError("데이터를 불러오지 못했습니다", e.message);
  }
}

// ---------- 등록 종목 패널 ----------
let REGISTERED = [];

function renderRegistered(active) {
  const wrap = $("#registered-list");
  if (!wrap) return;
  if (!REGISTERED.length) {
    wrap.innerHTML = `<div class="reg-empty">등록된 종목이 없습니다.</div>`;
    return;
  }
  wrap.innerHTML = `<div class="reg-group">` + REGISTERED.map((t) =>
    `<button class="reg-item${t === active ? " active" : ""}" data-t="${esc(t)}">${esc(t)}</button>`
  ).join("") + `</div>`;
}

async function loadRegistered() {
  try {
    const url = STATIC ? "../data/qtable/_index.json" : "/api/qtable/tickers";
    const res = await fetch(url, { cache: "no-store" });
    if (!res.ok) return;
    const data = await res.json();
    REGISTERED = data.curated || data.tickers || [];
    const options = data.tickers || REGISTERED;
    $("#ticker-list").innerHTML = options.map((t) => `<option value="${esc(t)}">`).join("");
  } catch (_) { /* 목록은 없어도 동작한다 */ }
  renderRegistered(location.hash.slice(1));
}

function setPanel(open) {
  $("#registered-panel").classList.toggle("open", open);
  $("#registered-panel").setAttribute("aria-hidden", open ? "false" : "true");
}

// ---------- 이벤트 ----------
$("#load-btn").addEventListener("click", () => loadTable($("#ticker-input").value));
$("#ticker-input").addEventListener("keydown", (e) => {
  if (e.key === "Enter") loadTable($("#ticker-input").value);
});
$("#copy-btn").addEventListener("click", copyTable);
$("#csv-btn").addEventListener("click", downloadCsv);
$("#reg-toggle").addEventListener("click", () =>
  setPanel(!$("#registered-panel").classList.contains("open")));
$("#reg-close").addEventListener("click", () => setPanel(false));
$("#registered-list").addEventListener("click", (e) => {
  const btn = e.target.closest(".reg-item");
  if (!btn) return;
  $("#ticker-input").value = btn.dataset.t;
  loadTable(btn.dataset.t);
  setPanel(false);
});
window.addEventListener("hashchange", () => {
  const t = location.hash.slice(1);
  if (t && t !== (TABLE && TABLE.ticker)) {
    $("#ticker-input").value = t;
    loadTable(t);
  }
});

(async function init() {
  await loadRegistered();
  const initial = location.hash.slice(1) || REGISTERED[0] || (STATIC ? "" : "APPS");
  if (initial) {
    $("#ticker-input").value = initial;
    loadTable(initial);
  }
})();
