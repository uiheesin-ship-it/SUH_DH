/* Saved screening presets (per screener, per device via localStorage).
 *
 * Captures the full filter state — every control inside `.filters` (sliders,
 * selects, checkboxes) PLUS the Excel-style per-column filters (colFilters,
 * supplied through a getter/setter hook) — under a name, and re-applies it with
 * one click. The search box is intentionally excluded (it's transient).
 *
 * Usage from a screener's app.js:
 *   SUHPresets.mount("flat", {
 *     container: document.getElementById("preset-bar"),
 *     getColFilters: () => structuredClone(colFilters),
 *     setColFilters: (c) => { colFilters = c || {}; },
 *     onApply: () => { syncScoreLabel(); render(); },
 *   });
 */
window.SUHPresets = (function () {
  const SKIP = new Set(["f-search"]);           // transient controls not saved

  function key(program) { return "suh_presets_" + program; }
  function load(program) {
    try { return JSON.parse(localStorage.getItem(key(program)) || "[]"); }
    catch (e) { return []; }
  }
  function save(program, list) {
    try { localStorage.setItem(key(program), JSON.stringify(list)); } catch (e) {}
  }

  function captureState(opts) {
    const controls = {};
    document.querySelectorAll(".filters [id]").forEach((el) => {
      if (SKIP.has(el.id)) return;
      if (el.type === "checkbox") controls[el.id] = el.checked;
      else if (el.tagName === "SELECT" || el.tagName === "INPUT") controls[el.id] = el.value;
    });
    let col = {};
    try { col = opts.getColFilters ? (opts.getColFilters() || {}) : {}; } catch (e) { col = {}; }
    return { controls, col };
  }

  function applyState(state, opts) {
    const controls = state.controls || {};
    Object.keys(controls).forEach((id) => {
      const el = document.getElementById(id);
      if (!el) return;
      if (el.type === "checkbox") el.checked = !!controls[id];
      else el.value = controls[id];
    });
    if (opts.setColFilters) {
      try { opts.setColFilters(JSON.parse(JSON.stringify(state.col || {}))); } catch (e) { opts.setColFilters({}); }
    }
    if (opts.onApply) opts.onApply();
  }

  function mount(program, opts) {
    const bar = opts.container;
    if (!bar) return;

    function render() {
      const list = load(program);
      bar.innerHTML = "";
      const label = document.createElement("span");
      label.className = "preset-label";
      label.textContent = "프리셋:";
      bar.appendChild(label);

      if (!list.length) {
        const empty = document.createElement("span");
        empty.className = "preset-empty";
        empty.textContent = "저장된 조건 없음";
        bar.appendChild(empty);
      }

      list.forEach((p, i) => {
        const chip = document.createElement("button");
        chip.className = "preset-chip";
        chip.title = "클릭: 이 조건으로 필터";
        const name = document.createElement("span");
        name.className = "preset-name";
        name.textContent = p.name;
        name.addEventListener("click", () => applyState(p.state, opts));
        // ✎ 이름 변경
        const rename = document.createElement("span");
        rename.className = "preset-edit";
        rename.textContent = "✎";
        rename.title = "이름 변경";
        rename.addEventListener("click", (e) => {
          e.stopPropagation();
          const l = load(program);
          const cur = (l[i] && l[i].name) || p.name;
          const nm = (prompt("새 이름:", cur) || "").trim();
          if (!nm || nm === cur) return;
          l[i].name = nm;
          // 같은 이름의 다른 프리셋이 있으면 이 항목만 남기고 제거(중복 방지)
          save(program, l.filter((q, j) => j === i || q.name !== nm));
          render();
        });
        // ⟳ 현재 화면의 필터로 이 프리셋의 조건을 갱신
        const upd = document.createElement("span");
        upd.className = "preset-upd";
        upd.textContent = "⟳";
        upd.title = "지금 걸린 필터(상단 + 열 필터)로 이 조건 갱신(덮어쓰기)";
        upd.addEventListener("click", (e) => {
          e.stopPropagation();
          if (!confirm(`'${p.name}' 조건을 지금 화면의 필터로 갱신(덮어쓰기)할까요?`)) return;
          const l = load(program);
          if (l[i]) { l[i].state = captureState(opts); save(program, l); render(); }
        });
        const del = document.createElement("span");
        del.className = "preset-del";
        del.textContent = "×";
        del.title = "삭제";
        del.addEventListener("click", (e) => {
          e.stopPropagation();
          const l = load(program);
          l.splice(i, 1);
          save(program, l);
          render();
        });
        chip.appendChild(name);
        chip.appendChild(upd);
        chip.appendChild(rename);
        chip.appendChild(del);
        bar.appendChild(chip);
      });

      const add = document.createElement("button");
      add.className = "preset-add";
      add.textContent = "＋ 현재 조건 저장";
      add.title = "지금 걸린 필터(상단 + 열 필터)를 이름 붙여 저장";
      add.addEventListener("click", () => {
        const nm = (prompt("저장할 조건 이름 (예: 베타>1·RS>80):") || "").trim();
        if (!nm) return;
        const l = load(program);
        const existing = l.findIndex((p) => p.name === nm);
        const entry = { name: nm, state: captureState(opts) };
        if (existing >= 0) l[existing] = entry; else l.push(entry);
        save(program, l);
        render();
      });
      bar.appendChild(add);
    }

    render();
  }

  return { mount };
})();
