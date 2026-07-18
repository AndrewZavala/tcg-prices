/** Read-only Postgres data explorer */

(function () {
  const PAGE_SIZE = 50;
  let catalog = [];
  let currentDataset = null;
  let offset = 0;
  let total = 0;
  let loadTimer = null;

  const els = {
    catalog: document.getElementById("catalog"),
    toolbar: document.getElementById("toolbar"),
    datasetDesc: document.getElementById("datasetDesc"),
    q: document.getElementById("q"),
    apiLink: document.getElementById("apiLink"),
    csvLink: document.getElementById("csvLink"),
    resultSummary: document.getElementById("resultSummary"),
    statusMsg: document.getElementById("statusMsg"),
    tableWrap: document.getElementById("tableWrap"),
    tableHead: document.getElementById("tableHead"),
    tableBody: document.getElementById("tableBody"),
    pager: document.getElementById("pager"),
    prevBtn: document.getElementById("prevBtn"),
    nextBtn: document.getElementById("nextBtn"),
    pageInfo: document.getElementById("pageInfo"),
    emptyPick: document.getElementById("emptyPick"),
    dataKpis: document.getElementById("dataKpis"),
    kpiDataset: document.getElementById("kpiDataset"),
    kpiRows: document.getElementById("kpiRows"),
    kpiStage: document.getElementById("kpiStage"),
  };

  function escapeHtml(s) {
    return String(s ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function fmtCell(value) {
    if (value == null || value === "") return '<span class="data-null">—</span>';
    if (typeof value === "number") {
      if (Number.isInteger(value)) return String(value);
      return value.toFixed(2);
    }
    const text = String(value);
    if (text.length > 80) {
      return `<span title="${escapeHtml(text)}">${escapeHtml(text.slice(0, 77))}…</span>`;
    }
    if (/^https?:\/\//i.test(text)) {
      return `<a href="${escapeHtml(text)}" target="_blank" rel="noopener">link</a>`;
    }
    return escapeHtml(text);
  }

  function datasetFromUrl() {
    return new URLSearchParams(window.location.search).get("dataset") || "";
  }

  function setUrlDataset(id) {
    const url = new URL(window.location.href);
    if (id) url.searchParams.set("dataset", id);
    else url.searchParams.delete("dataset");
    window.history.replaceState({}, "", url);
  }

  function renderCatalog() {
    if (!els.catalog) return;
    els.catalog.innerHTML = catalog
      .map(
        (d) => `
      <li>
        <button type="button" class="data-catalog-btn${currentDataset === d.id ? " is-active" : ""}" data-id="${escapeHtml(d.id)}">
          <span class="data-catalog-label">${escapeHtml(d.label)}</span>
          <span class="data-catalog-meta">${escapeHtml(d.stage)} · ${d.row_count.toLocaleString()} rows</span>
        </button>
      </li>`
      )
      .join("");
  }

  function updateLinks(dataset, q) {
    const params = new URLSearchParams({ limit: String(PAGE_SIZE), offset: String(offset) });
    if (q) params.set("q", q);
    const apiHref = `/api/data/${encodeURIComponent(dataset)}?${params}`;
    els.apiLink.href = apiHref;
    const csvParams = new URLSearchParams();
    if (q) csvParams.set("q", q);
    const csvQs = csvParams.toString();
    els.csvLink.href = `/api/data/${encodeURIComponent(dataset)}/export.csv${csvQs ? `?${csvQs}` : ""}`;
  }

  function renderTable(columns, rows) {
    els.tableHead.innerHTML = `<tr>${columns.map((c) => `<th>${escapeHtml(c)}</th>`).join("")}</tr>`;
    els.tableBody.innerHTML = rows
      .map(
        (row) =>
          `<tr>${columns.map((col) => `<td>${fmtCell(row[col])}</td>`).join("")}</tr>`
      )
      .join("");
  }

  function updatePager() {
    const page = Math.floor(offset / PAGE_SIZE) + 1;
    const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
    els.pageInfo.textContent = `Page ${page} of ${pages}`;
    els.prevBtn.disabled = offset <= 0;
    els.nextBtn.disabled = offset + PAGE_SIZE >= total;
    els.pager.hidden = total <= PAGE_SIZE;
  }

  async function loadRows() {
    if (!currentDataset) return;
    const q = els.q?.value.trim() || "";
    els.statusMsg.textContent = "Loading…";
    updateLinks(currentDataset, q);
    try {
      const params = new URLSearchParams({
        limit: String(PAGE_SIZE),
        offset: String(offset),
      });
      if (q) params.set("q", q);
      const res = await fetch(`/api/data/${encodeURIComponent(currentDataset)}?${params}`);
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      total = data.total || 0;
      const item = catalog.find((d) => d.id === currentDataset);

      els.toolbar.hidden = false;
      els.emptyPick.hidden = true;
      els.tableWrap.hidden = false;
      els.dataKpis.hidden = false;
      els.kpiDataset.textContent = data.label || currentDataset;
      els.kpiRows.textContent = total.toLocaleString();
      els.kpiStage.textContent = data.stage || item?.stage || "—";
      els.datasetDesc.textContent = data.description || "";

      const from = total === 0 ? 0 : offset + 1;
      const to = Math.min(offset + PAGE_SIZE, total);
      els.resultSummary.textContent = total
        ? `Showing ${from}–${to} of ${total.toLocaleString()} rows`
        : "No rows match";

      renderTable(data.columns || [], data.rows || []);
      updatePager();
      els.statusMsg.textContent = "";
    } catch (err) {
      els.statusMsg.textContent = err.message || String(err);
    }
  }

  function selectDataset(id) {
    if (!id || id === currentDataset) return;
    currentDataset = id;
    offset = 0;
    if (els.q) els.q.value = "";
    setUrlDataset(id);
    renderCatalog();
    loadRows();
  }

  async function loadCatalog() {
    els.statusMsg.textContent = "Loading catalog…";
    try {
      const res = await fetch("/api/data/catalog");
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      catalog = data.datasets || [];
      renderCatalog();
      const fromUrl = datasetFromUrl();
      const pick = fromUrl && catalog.some((d) => d.id === fromUrl) ? fromUrl : catalog[0]?.id;
      if (pick) selectDataset(pick);
      else els.statusMsg.textContent = "";
    } catch (err) {
      els.statusMsg.textContent = err.message || String(err);
    }
  }

  els.catalog?.addEventListener("click", (e) => {
    const btn = e.target.closest(".data-catalog-btn");
    if (btn?.dataset.id) selectDataset(btn.dataset.id);
  });

  els.q?.addEventListener("input", () => {
    clearTimeout(loadTimer);
    offset = 0;
    loadTimer = setTimeout(loadRows, 300);
  });

  els.prevBtn?.addEventListener("click", () => {
    offset = Math.max(0, offset - PAGE_SIZE);
    loadRows();
  });

  els.nextBtn?.addEventListener("click", () => {
    if (offset + PAGE_SIZE < total) {
      offset += PAGE_SIZE;
      loadRows();
    }
  });

  loadCatalog();
})();
