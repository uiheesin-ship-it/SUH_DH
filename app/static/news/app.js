"use strict";

const $ = (sel) => document.querySelector(sel);

// Two run modes (see config.js):
//   STATIC=false -> live FastAPI backend (/api/news), used when running locally
//   STATIC=true  -> pre-built daily JSON in ../data/news.json (GitHub Pages)
const STATIC = !!window.SUH_DH_STATIC;
const BUILT = window.SUH_DH_BUILT || null;

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

// Prefer the publisher's own timestamp localized to the reader; fall back to
// whatever string the feed gave us.
function fmtTime(item) {
  if (item.published_ts) {
    try {
      return new Date(item.published_ts * 1000).toLocaleString("ko-KR", {
        month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit",
      });
    } catch (_) { /* fall through */ }
  }
  return item.published || "";
}

async function loadNews() {
  $("#status").textContent = "불러오는 중…";
  try {
    const res = STATIC ? await SUHData.fetch("news.json", true)
                       : await fetch("/api/news", { cache: "no-store" });
    const data = await res.json();
    if (!res.ok || data.error) {
      renderError(data.error || "뉴스를 불러오지 못했습니다.", data.detail);
      return;
    }
    render(data);
    $("#demo-badge").classList.toggle("hidden", !data.demo);
    if (STATIC) {
      const when = BUILT ? new Date(BUILT).toLocaleString("ko-KR") : "최근";
      $("#status").textContent = `${data.count}건 · 마지막 갱신 ${when} · 매일 자동 갱신`;
    } else {
      $("#status").textContent =
        `${data.count}건 · 업데이트 ${new Date().toLocaleTimeString("ko-KR")}`;
    }
  } catch (e) {
    renderError("뉴스를 불러오지 못했습니다", e.message);
  }
}

function renderError(msg, detail) {
  $("#content").innerHTML =
    `<div class="error"><b>${esc(msg)}</b>${detail ? "<br><small>" + esc(detail) + "</small>" : ""}</div>`;
  $("#status").textContent = "오류";
}

function newsCard(item) {
  const cats = (item.categories || [])
    .map((c) => `<span class="cat">${esc(c)}</span>`).join("");
  const title = item.title_ko || item.title || "";
  const showOrig = item.title && item.title_ko && item.title !== item.title_ko;
  const paywall = item.paywall
    ? `<span class="paywall" title="원문이 유료 구독 매체입니다">🔒 유료</span>` : "";
  return `<article class="news-item${item.paywall ? " is-paywall" : ""}">
    <div class="news-meta">
      <span class="source" data-src="${esc(item.source)}">${esc(item.source)}</span>
      ${paywall}
      <span class="time">${esc(fmtTime(item))}</span>
      <span class="cats">${cats}</span>
    </div>
    <h2 class="news-title"><a href="${esc(item.link)}" target="_blank" rel="noopener">${esc(title)}</a></h2>
    ${item.summary_ko ? `<p class="news-summary">${esc(item.summary_ko)}</p>` : ""}
    <div class="news-foot">
      <a class="ext-link" href="${esc(item.link)}" target="_blank" rel="noopener">원문 보기 ↗</a>
      ${showOrig ? `<span class="orig-title">${esc(item.title)}</span>` : ""}
    </div>
  </article>`;
}

function render(data) {
  if (!data.items || !data.items.length) {
    $("#content").innerHTML =
      `<div class="loading">표시할 뉴스가 없습니다. 잠시 후 다시 시도해 주세요.</div>`;
    return;
  }
  $("#content").innerHTML = data.items.map(newsCard).join("");
}

// ---------- events ----------
$("#refresh-btn").addEventListener("click", loadNews);

let timer = null;
function scheduleAuto() {
  if (timer) clearInterval(timer);
  if (!$("#auto-toggle").checked) return;
  timer = setInterval(loadNews, parseInt($("#auto-interval").value, 10) * 1000);
}
$("#auto-toggle").addEventListener("change", scheduleAuto);
$("#auto-interval").addEventListener("change", scheduleAuto);

// In static mode the data is rebuilt daily server-side; live auto-refresh is moot.
if (STATIC) {
  const auto = document.querySelector(".auto");
  if (auto) auto.classList.add("hidden");
}

loadNews();
scheduleAuto();
