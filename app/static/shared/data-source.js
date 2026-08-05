"use strict";
// Read a committed data snapshot from raw.githubusercontent (always the freshest
// committed copy) with a fallback to the deployed ../data/ file.
//
// Why: the dashboard's snapshot pages (base/flat/KR) ship their JSON inside the
// GitHub Pages deploy artifact. During a long scan build, a shorter build that
// started earlier can reuse an OLDER committed snapshot and deploy it LAST —
// making the live data appear to go backwards ("last deploy wins"). Reading the
// data straight from the repo's raw URL decouples what the page SHOWS from which
// build deployed last: the data is always the newest committed file, regardless
// of deploy timing. Charts still come from the deploy (they change slowly).
//
// The repo is public, so raw.githubusercontent serves these with permissive
// CORS. If raw is ever unreachable (offline/CORS), we fall back to the deployed
// copy, so there is never a regression versus the old behaviour.
(function () {
  const RAW_BASE =
    "https://raw.githubusercontent.com/uiheesin-ship-it/SUH_DH/refs/heads/claude/funny-carson-ent3s7/data";

  function bust(url) {
    return url + (url.includes("?") ? "&" : "?") + "_=" + Date.now();
  }

  window.SUHData = {
    RAW_BASE,
    // Fetch `file` (e.g. "base.json"). In static mode try raw first, then the
    // deployed copy; in live mode (local FastAPI) skip raw and use ../data.
    async fetch(file, isStatic = true) {
      if (isStatic) {
        try {
          const r = await fetch(bust(`${RAW_BASE}/${file}`), { cache: "no-store" });
          if (r.ok) return r;
        } catch (_) { /* fall through to the deployed snapshot */ }
      }
      return fetch(bust(`../data/${file}`), { cache: "no-store" });
    },
  };
})();
