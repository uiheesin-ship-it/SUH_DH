"use strict";

const $ = (sel) => document.querySelector(sel);
const STATIC = !!window.SUH_DH_STATIC;
const BUILT = window.SUH_DH_BUILT || null;
const API_BASE = (window.SUH_DH_API_BASE || "").replace(/\/+$/, "");

function bust(url) { return url + (url.includes("?") ? "&" : "?") + "_=" + Date.now(); }

let ALL = [];            // all company rows
let SORT = { key: "latest_backlog_krw", dir: -1 };

// ---------- formatting ----------
function fmtWon(v) {                 // won -> 조 / 억
  if (v == null) return "-";
  const neg = v < 0; v = Math.abs(v);
  let s;
  if (v >= 1e12) s = (v / 1e12).toFixed(v >= 1e13 ? 1 : 2) + "조";
  else if (v >= 1e8) s = Math.round(v / 1e8).toLocaleString() + "억";
  else s = Math.round(v).toLocaleString();
  return (neg ? "-" : "") + s;
}
function fmtPct(v) {
  if (v == null) return "-";
  return (v > 0 ? "+" : "") + v.toFixed(1) + "%";
}
function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

// ---------- load ----------
async function loadData() {
  $("#status").textContent = "불러오는 중…";
  try {
    const url = STATIC ? bust("../data/kr_backlog.json") : "/api/backlog";
    const res = await fetch(url, { cache: "no-store" });
    const data = await res.json();
    if (!res.ok || data.error) {
      renderError(data.error || "데이터를 불러오지 못했습니다.", data.detail);
      return;
    }
    ALL = data.companies || [];
    $("#demo-badge").classList.toggle("hidden", !data.demo);
    fillSectors(ALL);
    render();
    const when = STATIC ? (BUILT ? new Date(BUILT).toLocaleString("ko-KR") : "최근")
                        : new Date().toLocaleTimeString("ko-KR");
    $("#status").textContent =
      `${data.count}개사 · ${STATIC ? "갱신 " + when + " · 매일 자동" : "업데이트 " + when}`;
  } catch (e) {
    renderError("데이터를 불러오지 못했습니다", e.message);
  }
}

function renderError(msg, detail) {
  $("#content").innerHTML =
    `<div class="error"><b>${esc(msg)}</b>${detail ? "<br><small>" + esc(detail) + "</small>" : ""}</div>`;
  $("#status").textContent = "오류";
}

function fillSectors(rows) {
  const sel = $("#sector");
  const cur = sel.value;
  const secs = [...new Set(rows.map((r) => r.sector).filter(Boolean))].sort();
  sel.innerHTML = '<option value="">전체 섹터</option>' +
    secs.map((s) => `<option value="${esc(s)}">${esc(s)}</option>`).join("");
  sel.value = cur;
}

// ---------- filter + sort ----------
function currentRows() {
  const q = $("#search").value.trim().toLowerCase();
  const sec = $("#sector").value;
  let rows = ALL.filter((r) => {
    if (sec && r.sector !== sec) return false;
    if (q && !(`${r.name} ${r.stock_code}`.toLowerCase().includes(q))) return false;
    return true;
  });
  const { key, dir } = SORT;
  rows = rows.slice().sort((a, b) => {
    let x = a[key], y = b[key];
    if (typeof x === "string" || typeof y === "string") {
      x = x || ""; y = y || "";
      return dir * String(x).localeCompare(String(y), "ko");
    }
    // nulls last regardless of direction
    if (x == null && y == null) return 0;
    if (x == null) return 1;
    if (y == null) return -1;
    return dir * (x - y);
  });
  return rows;
}

// ---------- render ----------
const COLS = [
  { key: "name", label: "회사", align: "left" },
  { key: "sector", label: "섹터", align: "left" },
  { key: "latest_quarter", label: "최신 분기", align: "left" },
  { key: "latest_backlog_krw", label: "수주잔고", align: "right" },
  { key: "qoq_pct", label: "전분기比", align: "right" },
  { key: "yoy_pct", label: "전년비", align: "right" },
];

function render() {
  const rows = currentRows();
  if (!rows.length) {
    // Distinguish "no data collected yet" from "filter matched nothing".
    if (!ALL.length) {
      $("#content").innerHTML = `<div class="empty setup">
        <p><b>아직 수주잔고 데이터가 없습니다.</b></p>
        <p>DART에서 수집하려면 저장소에 무료 인증키를 등록하고 최초 백필을 한 번 실행하세요:</p>
        <ol>
          <li><a class="ext" href="https://opendart.fss.or.kr" target="_blank" rel="noopener">opendart.fss.or.kr ↗</a> 에서 인증키 발급</li>
          <li>저장소 <b>Settings → Secrets and variables → Actions</b> 에 <code>DART_API_KEY</code> 등록</li>
          <li><b>Actions → "Refresh KR order backlog (DART)" → Run workflow → mode=backfill</b> 실행</li>
        </ol>
        <p class="muted">이후에는 매일 자동으로 그날 제출된 정기보고서만 반영됩니다.</p>
      </div>`;
    } else {
      $("#content").innerHTML = `<div class="empty">검색·필터 결과가 없습니다.</div>`;
    }
    return;
  }
  const head = COLS.map((c) => {
    const arrow = SORT.key === c.key ? (SORT.dir < 0 ? " ▾" : " ▴") : "";
    return `<th class="th-${c.align}" data-key="${c.key}">${c.label}${arrow}</th>`;
  }).join("");

  const body = rows.map(rowHtml).join("");
  $("#content").innerHTML =
    `<table class="tbl"><thead><tr>${head}<th></th></tr></thead><tbody>${body}</tbody></table>`;

  $("#content").querySelectorAll("th[data-key]").forEach((th) => {
    th.onclick = () => {
      const k = th.dataset.key;
      if (SORT.key === k) SORT.dir *= -1;
      else SORT = { key: k, dir: k === "name" || k === "sector" ? 1 : -1 };
      render();
    };
  });
  $("#content").querySelectorAll("tr.main").forEach((tr) => {
    tr.onclick = (e) => {
      if (e.target.closest("a")) return;
      const sub = tr.nextElementSibling;
      if (sub && sub.classList.contains("detail")) sub.classList.toggle("hidden");
    };
  });
}

function backlogCell(r) {
  if (r.currency) {                 // FX-denominated: show raw + currency
    return `${esc(r.latest_backlog_raw || "-")} <span class="cur">${esc(r.currency)}</span>`;
  }
  return `₩${fmtWon(r.latest_backlog_krw)}`;
}

function chgCell(v) {
  if (v == null) return `<td class="num">-</td>`;
  const cls = v > 0 ? "chg-up" : v < 0 ? "chg-down" : "";
  return `<td class="num ${cls}">${fmtPct(v)}</td>`;
}

function rowHtml(r) {
  const src = r.source
    ? `<a class="ext" href="${esc(r.source)}" target="_blank" rel="noopener">DART ↗</a>` : "";
  return `<tr class="main">
    <td><b>${esc(r.name)}</b><div class="sub">${esc(r.stock_code)} · ${esc(r.market || "")}</div></td>
    <td>${esc(r.sector || "-")}</td>
    <td>${esc(r.latest_quarter || "-")}<div class="sub">${esc(r.latest_rcept_dt || "")}</div></td>
    <td class="num strong">${backlogCell(r)}</td>
    ${chgCell(r.qoq_pct)}
    ${chgCell(r.yoy_pct)}
    <td class="num">${src}</td>
  </tr>
  <tr class="detail hidden"><td colspan="7">${detailHtml(r)}</td></tr>`;
}

function detailHtml(r) {
  const qs = (r.quarters || []).slice().reverse();   // oldest -> newest for the trend
  const krw = qs.map((q) => q.backlog_krw).filter((v) => v != null);
  const max = krw.length ? Math.max(...krw) : 0;
  const bars = qs.map((q) => {
    const w = max && q.backlog_krw != null ? Math.max(3, (q.backlog_krw / max) * 100) : 0;
    const val = q.currency ? `${esc(q.backlog_raw)} ${esc(q.currency)}` : `₩${fmtWon(q.backlog_krw)}`;
    const link = q.source
      ? `<a class="ext" href="${esc(q.source)}" target="_blank" rel="noopener">↗</a>` : "";
    return `<div class="qrow">
      <div class="qlabel">${esc(q.quarter || q.period)}</div>
      <div class="qbar"><div class="qbar-fill" style="width:${w}%"></div></div>
      <div class="qval">${val} ${link}</div>
    </div>`;
  }).join("");
  return `<div class="detail-inner">
    <div class="detail-title">분기별 수주잔고 추이</div>${bars}</div>`;
}

// ---------- events ----------
$("#refresh-btn").onclick = loadData;
$("#search").oninput = render;
$("#sector").onchange = render;
loadData();
