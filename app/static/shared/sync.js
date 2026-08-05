"use strict";
// Cross-device watchlist sync — timestamp-merge, loss-proof.
//
// Model: per program (base/flat) we keep a map  { TICKER: {on:bool, t:ms} }.
// The starred list is the tickers whose latest entry has on=true. Merge across
// devices is per-ticker last-write-wins by timestamp, so a star OR un-star made
// on any device propagates, and — crucially — a transient empty/failed cloud
// read can never wipe local stars (an unknown ticker just keeps its local
// entry). One jsonblob holds every program's map: { base:{...}, flat:{...} }.
//
// localStorage is always safe on its own; every cloud call is best-effort and
// swallows errors, so stars keep working offline / if the service is down.
(function () {
  const API = "https://jsonblob.com/api/jsonBlob";
  const CODE_KEY = "suh_sync_code";
  const mapKey = (program) => `suh_wl_${program}`;

  // Monotonic-ish timestamp. Date.now() is fine in the browser.
  const now = () => Date.now();
  const getCode = () => localStorage.getItem(CODE_KEY) || "";
  const setCode = (c) => c ? localStorage.setItem(CODE_KEY, c) : localStorage.removeItem(CODE_KEY);

  function loadMap(program) {
    try { const o = JSON.parse(localStorage.getItem(mapKey(program)) || "{}"); return (o && typeof o === "object") ? o : {}; }
    catch { return {}; }
  }
  function saveMap(program, map) {
    try { localStorage.setItem(mapKey(program), JSON.stringify(map)); } catch (_) {}
  }
  function deriveList(map) {
    return Object.keys(map).filter((t) => map[t] && map[t].on);
  }
  function mergeMaps(a, b) {
    const out = {};
    for (const k of new Set([...Object.keys(a || {}), ...Object.keys(b || {})])) {
      const x = a && a[k], y = b && b[k];
      if (!x) out[k] = y;
      else if (!y) out[k] = x;
      else out[k] = ((y.t || 0) > (x.t || 0)) ? y : x;   // later timestamp wins
    }
    return out;
  }

  // ---- cloud: one blob holds every program's map ----
  async function getBlob() {
    const code = getCode(); if (!code) return null;
    const res = await fetch(`${API}/${encodeURIComponent(code)}?_=${now()}`,
                           { cache: "no-store", headers: { Accept: "application/json" } });
    if (res.status === 404) return {};
    if (!res.ok) throw new Error("read " + res.status);
    try { const o = await res.json(); return (o && typeof o === "object") ? o : {}; }
    catch { return {}; }
  }
  async function putBlob(obj) {
    const code = getCode(); if (!code) return;
    await fetch(`${API}/${encodeURIComponent(code)}`, {
      method: "PUT", headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(obj || {}) });
  }
  async function createBlob(initial) {
    const res = await fetch(API, {
      method: "POST", headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(initial || {}) });
    if (!res.ok) throw new Error("코드 생성 실패 (" + res.status + ")");
    let id = res.headers.get("x-jsonblob");
    if (!id) { const loc = res.headers.get("Location"); if (loc) id = loc.split("/").pop(); }
    if (!id) throw new Error("코드 생성 실패 (응답에서 코드를 못 읽음)");
    return id.trim();
  }

  // Merge local program map INTO the cloud blob (preserving sibling programs),
  // fold any cloud-newer entries back into local, and write back. Best-effort.
  async function pushProgram(program) {
    if (!getCode()) return;
    try {
      const blob = (await getBlob()) || {};
      const merged = mergeMaps(blob[program] || {}, loadMap(program));
      saveMap(program, merged);
      blob[program] = merged;
      await putBlob(blob);
    } catch (_) { /* will retry on next change/focus */ }
  }

  // Merge cloud into local (loss-proof); returns the merged map or null on failure.
  async function pullProgram(program) {
    if (!getCode()) return null;
    try {
      const blob = await getBlob();
      if (!blob) return null;
      const merged = mergeMaps(loadMap(program), blob[program] || {});
      saveMap(program, merged);
      return merged;
    } catch (_) { return null; }
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

    // Record a single star toggle with a timestamp, then sync up (best-effort).
    record(program, ticker, on) {
      const map = loadMap(program);
      map[ticker] = { on: !!on, t: now() };
      saveMap(program, map);
      pushProgram(program);
    },

    mount(program, { container, getList, setList }) {
      if (!container) return;
      injectStyles();

      // Upgrade/seed: fold any pre-existing local stars into the timestamp map
      // so nothing is lost when moving to this model.
      const map0 = loadMap(program);
      let changed = false;
      for (const t of (getList() || [])) if (!map0[t]) { map0[t] = { on: true, t: now() }; changed = true; }
      if (changed) saveMap(program, map0);
      setList(deriveList(loadMap(program)));   // display reflects the map

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

      const applyMerged = (map) => { if (map) setList(deriveList(map)); };
      let lastPull = 0;
      const autoPull = async (force) => {
        if (!getCode() || document.hidden) return;
        const t = now(); if (!force && t - lastPull < 3000) return; lastPull = t;
        applyMerged(await pullProgram(program));
        pushProgram(program);   // heal cloud with any local-newer entries
      };
      if (getCode()) autoPull(true);
      document.addEventListener("visibilitychange", () => { if (!document.hidden) autoPull(); });
      window.addEventListener("focus", () => autoPull());

      function openDialog() {
        const ov = document.createElement("div");
        ov.className = "suh-sync-ov";
        const connected = !!getCode();
        ov.innerHTML = `
          <div class="suh-sync-card" role="dialog" aria-modal="true">
            <h3>☁ 관심종목 동기화</h3>
            <p>같은 <b>동기화 코드</b>를 여러 기기에 입력하면, 폰·PC 어디서 별표를 켜고 꺼도
               같은 목록이 됩니다(종목별 최신 변경이 반영). 베이스·평평이 한 코드를 공유합니다.</p>
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
            const merged = await pullProgram(program);
            if (merged) { applyMerged(merged); await pushProgram(program); msg("동기화 완료 (양방향 병합).", true); }
            else msg("읽기 실패 — 로컬 목록은 그대로 유지됩니다.");
          });
          qs("#suh-sync-disc").addEventListener("click", () => { setCode(""); refresh(); close(); });
        } else {
          qs("#suh-sync-new").addEventListener("click", async () => {
            msg("코드 생성 중…");
            try {
              const id = await createBlob({});
              setCode(id);
              await pushProgram(program);      // seed cloud with current local map
              refresh(); close(); openDialog();
            } catch (e) { msg(e.message || "생성 실패"); }
          });
          qs("#suh-sync-connect").addEventListener("click", async () => {
            const code = qs("#suh-sync-input").value.trim();
            if (!code) { msg("코드를 입력하세요."); return; }
            msg("연결 중…");
            setCode(code);
            const merged = await pullProgram(program);
            if (merged == null) { setCode(""); msg("연결 실패 — 코드를 확인하세요."); return; }
            applyMerged(merged);
            await pushProgram(program);
            refresh(); close();
          });
        }
      }
    },
  };
})();
