"use strict";
// Cross-device watchlist sync for the SUH_DH screeners.
//
// The dashboard is a static site (no backend/DB), so a starred list normally
// lives only in this browser's localStorage. This module layers an optional
// cloud copy on top, using jsonblob.com — a free, anonymous, CORS-enabled JSON
// store. The user creates or enters a personal "sync code" (a jsonblob id) once
// per device; ONE blob holds both programs' lists as {base:[...], flat:[...]},
// so base/ and flat/ share a single code but keep separate lists.
//
// localStorage stays the source of truth locally: every cloud call is
// best-effort and swallows errors, so the page keeps working if the service is
// unreachable. Convergence: on load a connected device adopts the cloud list
// (last-write-wins); linking a brand-new code merges local ∪ cloud so neither
// side is lost. A push reads the blob first so it never clobbers the sibling
// program's list.
(function () {
  const API = "https://jsonblob.com/api/jsonBlob";
  const CODE_KEY = "suh_sync_code";

  const getCode = () => localStorage.getItem(CODE_KEY) || "";
  const setCode = (c) => c ? localStorage.setItem(CODE_KEY, c) : localStorage.removeItem(CODE_KEY);
  const EMPTY = () => ({ base: [], flat: [] });

  async function createBlob(initial) {
    const res = await fetch(API, {
      method: "POST",
      headers: { "Content-Type": "application/json", "Accept": "application/json" },
      body: JSON.stringify(initial || EMPTY()),
    });
    if (!res.ok) throw new Error("코드 생성 실패 (" + res.status + ")");
    // jsonblob returns the new id in the X-jsonblob header (CORS-exposed); fall
    // back to the Location header's last path segment.
    let id = res.headers.get("x-jsonblob");
    if (!id) { const loc = res.headers.get("Location"); if (loc) id = loc.split("/").pop(); }
    if (!id) throw new Error("코드 생성 실패 (응답에서 코드를 못 읽음)");
    return id.trim();
  }

  async function getBlob() {
    const code = getCode();
    if (!code) return null;
    const res = await fetch(`${API}/${encodeURIComponent(code)}`,
                           { cache: "no-store", headers: { "Accept": "application/json" } });
    if (res.status === 404) return EMPTY();
    if (!res.ok) throw new Error("읽기 실패 (" + res.status + ")");
    try { const o = await res.json(); return (o && typeof o === "object") ? o : EMPTY(); }
    catch { return EMPTY(); }
  }

  async function putBlob(obj) {
    const code = getCode();
    if (!code) return;
    await fetch(`${API}/${encodeURIComponent(code)}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json", "Accept": "application/json" },
      body: JSON.stringify(obj || EMPTY()),
    });
  }

  function injectStyles() {
    if (document.getElementById("suh-sync-style")) return;
    const s = document.createElement("style");
    s.id = "suh-sync-style";
    s.textContent = `
      #suh-sync-btn.on { background:#134e2a; color:#86efac; }
      .suh-sync-ov { position:fixed; inset:0; background:rgba(0,0,0,.55);
        display:flex; align-items:center; justify-content:center; z-index:9999; }
      .suh-sync-card { background:#0f172a; color:#e2e8f0; border:1px solid #334155;
        border-radius:10px; padding:18px; width:min(440px,92vw); font-size:13px; }
      .suh-sync-card h3 { margin:0 0 10px; font-size:15px; }
      .suh-sync-card p { color:#94a3b8; margin:6px 0; line-height:1.55; }
      .suh-sync-card input { width:100%; box-sizing:border-box; background:#1e293b;
        color:#e2e8f0; border:1px solid #334155; border-radius:6px; padding:7px 8px;
        font-size:13px; margin:6px 0; }
      .suh-sync-card button { background:#1e293b; color:#e2e8f0; border:1px solid #334155;
        border-radius:6px; padding:7px 10px; font-size:12px; cursor:pointer; margin:2px 4px 2px 0; }
      .suh-sync-card button.primary { background:#1d4ed8; border-color:#1d4ed8; color:#fff; }
      .suh-sync-card .code { font-family:monospace; background:#1e293b; padding:6px 8px;
        border-radius:6px; word-break:break-all; display:inline-block; margin:2px 0; }
      .suh-sync-card .row { display:flex; gap:6px; align-items:center; flex-wrap:wrap; margin-top:8px; }
      .suh-sync-msg { min-height:16px; margin-top:8px; color:#fca5a5; }
      .suh-sync-msg.ok { color:#86efac; }
    `;
    document.head.appendChild(s);
  }

  window.SUHSync = {
    getCode, setCode,
    hasCode: () => !!getCode(),

    async pull(program) {
      try { const o = await getBlob(); if (!o) return null; return Array.isArray(o[program]) ? o[program] : []; }
      catch { return null; }
    },
    async push(program, arr) {
      try {
        const o = (await getBlob()) || EMPTY();
        o[program] = arr || [];
        await putBlob(o);
      } catch { /* best-effort */ }
    },
    async createCode(program, seedList) {
      const init = EMPTY();
      init[program] = seedList || [];
      const id = await createBlob(init);
      setCode(id);
      return id;
    },

    // Add a "☁ 동기화" button to `container` and wire the setup dialog.
    //   getList() -> current array of tickers
    //   setList(arr) -> replace the local list + re-render
    mount(program, { container, getList, setList }) {
      if (!container) return;
      injectStyles();

      const btn = document.createElement("button");
      btn.id = "suh-sync-btn";
      btn.title = "관심종목 기기 간 동기화";
      const refresh = () => {
        const on = !!getCode();
        btn.textContent = on ? "☁ 동기화됨" : "☁ 동기화";
        btn.classList.toggle("on", on);
      };
      refresh();
      btn.addEventListener("click", openDialog);
      container.insertBefore(btn, container.firstChild);

      // Loss-proof adopt: a NON-EMPTY cloud list wins (so adds/removes made on
      // another device show up). An EMPTY or failed cloud read NEVER wipes local
      // — instead, if we have local stars, we push them up to HEAL the cloud.
      // This is the fix for "stars all disappeared": a transient empty read used
      // to overwrite the local list with [].
      const adopt = async (cloud) => {
        if (Array.isArray(cloud) && cloud.length) { setList(cloud); return "adopted"; }
        if (Array.isArray(cloud) && cloud.length === 0 && getList().length) {
          await window.SUHSync.push(program, getList());   // heal empty cloud from local
          return "healed";
        }
        return "kept";
      };

      // Runs on load and again whenever the tab regains focus/visibility, so a
      // change made on another device shows up when you return — no manual
      // refresh. Throttled so rapid tab-switching doesn't hammer the service.
      let lastPull = 0;
      const autoPull = async (force) => {
        if (!getCode() || document.hidden) return;
        const now = Date.now();
        if (!force && now - lastPull < 3000) return;
        lastPull = now;
        await adopt(await window.SUHSync.pull(program));
      };
      autoPull(true);
      document.addEventListener("visibilitychange", () => { if (!document.hidden) autoPull(); });
      window.addEventListener("focus", () => autoPull());

      function openDialog() {
        const ov = document.createElement("div");
        ov.className = "suh-sync-ov";
        const connected = !!getCode();
        ov.innerHTML = `
          <div class="suh-sync-card" role="dialog" aria-modal="true">
            <h3>☁ 관심종목 동기화</h3>
            <p>같은 <b>동기화 코드</b>를 여러 기기에 입력하면, 폰·PC 어디서 별표를 바꿔도
               같은 목록이 보입니다. 베이스·평평 스크리너가 같은 코드를 공유합니다.</p>
            ${connected ? `
              <p>현재 코드 (다른 기기에 이 코드를 입력하세요):</p>
              <div class="code" id="suh-sync-code"></div>
              <div class="row">
                <button class="primary" id="suh-sync-copy">코드 복사</button>
                <button id="suh-sync-sync">지금 동기화</button>
                <button id="suh-sync-disc">연결 해제</button>
              </div>` : `
              <div class="row"><button class="primary" id="suh-sync-new">새 코드 생성</button></div>
              <p>또는 다른 기기에서 만든 코드 입력:</p>
              <input id="suh-sync-input" placeholder="동기화 코드 붙여넣기" autocomplete="off" />
              <div class="row"><button id="suh-sync-connect">연결</button></div>`}
            <div class="suh-sync-msg" id="suh-sync-msg"></div>
            <div class="row" style="justify-content:flex-end">
              <button id="suh-sync-close">닫기</button>
            </div>
          </div>`;
        document.body.appendChild(ov);
        const qs = (sel) => ov.querySelector(sel);
        const msg = (t, ok) => { const m = qs("#suh-sync-msg"); m.textContent = t; m.classList.toggle("ok", !!ok); };
        const close = () => ov.remove();
        ov.addEventListener("click", (e) => { if (e.target === ov) close(); });
        qs("#suh-sync-close").addEventListener("click", close);

        if (connected) {
          qs("#suh-sync-code").textContent = getCode();
          qs("#suh-sync-copy").addEventListener("click", async () => {
            try { await navigator.clipboard.writeText(getCode()); msg("복사됐습니다. 다른 기기에 붙여넣으세요.", true); }
            catch { msg("복사 실패 — 코드를 길게 눌러 직접 복사하세요."); }
          });
          qs("#suh-sync-sync").addEventListener("click", async () => {
            msg("동기화 중…");
            const r = await adopt(await window.SUHSync.pull(program));
            if (r === "adopted") msg("최신 목록을 받아왔습니다.", true);
            else if (r === "healed") msg("클라우드가 비어 있어 이 기기 목록으로 복구했습니다.", true);
            else msg("변경 없음 (또는 읽기 실패) — 로컬 목록 유지.", true);
          });
          qs("#suh-sync-disc").addEventListener("click", () => { setCode(""); refresh(); close(); });
        } else {
          qs("#suh-sync-new").addEventListener("click", async () => {
            msg("코드 생성 중…");
            try {
              await window.SUHSync.createCode(program, getList());   // seed cloud with current stars
              refresh(); close(); openDialog();                      // reopen in connected state
            } catch (e) { msg(e.message || "생성 실패"); }
          });
          qs("#suh-sync-connect").addEventListener("click", async () => {
            const code = qs("#suh-sync-input").value.trim();
            if (!code) { msg("코드를 입력하세요."); return; }
            msg("연결 중…");
            setCode(code);
            const cloud = await window.SUHSync.pull(program);
            if (cloud == null) { setCode(""); msg("연결 실패 — 코드를 확인하세요."); return; }
            // First link: merge local ∪ cloud so neither list is lost.
            const union = Array.from(new Set([...(getList() || []), ...cloud]));
            setList(union);
            await window.SUHSync.push(program, union);
            refresh(); close();
          });
        }
      }
    },
  };
})();
