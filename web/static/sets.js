(function () {
  const listEl = document.getElementById("setsList");
  const statusEl = document.getElementById("setsStatus");
  const titleEl = document.getElementById("setsTitle");
  const filterEl = document.getElementById("setsFilter");
  let allSets = [];

  function esc(s) {
    return String(s ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function formatDate(iso) {
    if (!iso) return "";
    const [y, m, d] = iso.split("-").map(Number);
    return new Date(y, m - 1, d).toLocaleDateString(undefined, {
      year: "numeric",
      month: "short",
      day: "numeric",
    });
  }

  function byNewest(a, b) {
    return (b.release_date || "").localeCompare(a.release_date || "") || a.name.localeCompare(b.name);
  }

  function groupBySeries(sets) {
    const groups = new Map();
    for (const s of sets) {
      const key = s.series_id || "_other";
      if (!groups.has(key)) groups.set(key, { name: s.series_name || "Other", sets: [] });
      groups.get(key).sets.push(s);
    }
    const out = [...groups.values()];
    for (const g of out) g.sets.sort(byNewest);
    out.sort((a, b) => byNewest(a.sets[0], b.sets[0]));
    return out;
  }

  function setRowHtml(s) {
    const href = `/?q=${encodeURIComponent(`set:${s.id}`)}&unique=art&sort=set`;
    const count = s.loaded_cards === 1 ? "1 card" : `${s.loaded_cards} cards`;
    return `
      <li>
        <a class="sp-set-row" href="${href}">
          <span class="sp-set-name">${esc(s.name)}</span>
          <span class="sp-set-code">${esc(s.tcg_online_code || "")}</span>
          <span class="sp-set-date">${esc(formatDate(s.release_date))}</span>
          <span class="sp-set-count">${count}</span>
        </a>
      </li>`;
  }

  function render() {
    const needle = filterEl.value.trim().toLowerCase();
    const sets = needle
      ? allSets.filter((s) =>
          [s.name, s.id, s.tcg_online_code, s.series_name].some((v) =>
            String(v || "").toLowerCase().includes(needle)
          )
        )
      : allSets;
    titleEl.textContent = `Sets (${sets.length})`;
    if (!sets.length) {
      listEl.innerHTML = "";
      statusEl.textContent = "No sets match that filter.";
      statusEl.hidden = false;
      return;
    }
    statusEl.hidden = true;
    listEl.innerHTML = groupBySeries(sets)
      .map(
        (g) => `
        <section class="sp-sets-series">
          <h3 class="sp-sets-series-title">
            ${esc(g.name)}
            <span class="sp-sets-series-count">${g.sets.length} ${g.sets.length === 1 ? "set" : "sets"}</span>
          </h3>
          <ul class="sp-sets-list">${g.sets.map(setRowHtml).join("")}</ul>
        </section>`
      )
      .join("");
  }

  async function load() {
    try {
      const resp = await fetch("/api/pokemon/meta?v=sets2");
      if (!resp.ok) throw new Error(String(resp.status));
      const meta = await resp.json();
      allSets = (meta.sets || []).filter((s) => s.loaded_cards > 0);
      render();
    } catch (_) {
      statusEl.textContent = "Couldn't load sets. Try refreshing the page.";
    }
  }

  filterEl.addEventListener("input", render);
  load();
})();
