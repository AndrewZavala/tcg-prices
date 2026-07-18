/** Opportunities — read-only view of /api/opportunities */
(function () {
  const limit = 50;
  let offset = 0;
  let lastTotal = 0;
  let searchTimer = null;
  let metaRowCount = 0;
  let activeTab = "cards";
  let sellerData = [];
  const selectedIds = new Set();

  const els = {
    meta: document.getElementById("meta"),
    kpis: document.getElementById("kpis"),
    kpiProfit: document.getElementById("kpiProfit"),
    kpiRoi: document.getElementById("kpiRoi"),
    kpiCount: document.getElementById("kpiCount"),
    tabCards: document.getElementById("tabCards"),
    tabSellers: document.getElementById("tabSellers"),
    panelCards: document.getElementById("panelCards"),
    panelSellers: document.getElementById("panelSellers"),
    q: document.getElementById("q"),
    seller: document.getElementById("seller"),
    minProfit: document.getElementById("min_profit"),
    minRoi: document.getElementById("min_roi"),
    sort: document.getElementById("sort"),
    filtersToggle: document.getElementById("filtersToggle"),
    advancedFilters: document.getElementById("advancedFilters"),
    chartToggle: document.getElementById("chartToggle"),
    chartPanel: document.getElementById("chartPanel"),
    profitChart: document.getElementById("profitChart"),
    activeChips: document.getElementById("activeChips"),
    resultSummary: document.getElementById("resultSummary"),
    addSelectedBtn: document.getElementById("addSelectedBtn"),
    selectAll: document.getElementById("selectAll"),
    purchaseToast: document.getElementById("purchaseToast"),
    pageInfo: document.getElementById("pageInfo"),
    prevBtn: document.getElementById("prevBtn"),
    nextBtn: document.getElementById("nextBtn"),
    resetBtn: document.getElementById("resetBtn"),
    emptyReset: document.getElementById("emptyReset"),
    status: document.getElementById("status"),
    results: document.getElementById("results"),
    tableWrap: document.getElementById("tableWrap"),
    emptyState: document.getElementById("emptyState"),
    sellerQ: document.getElementById("sellerQ"),
    sellerSummary: document.getElementById("sellerSummary"),
    sellerAddSelectedBtn: document.getElementById("sellerAddSelectedBtn"),
    sellerStatus: document.getElementById("sellerStatus"),
    sellerResults: document.getElementById("sellerResults"),
    sellerTableWrap: document.getElementById("sellerTableWrap"),
    sellerEmpty: document.getElementById("sellerEmpty"),
  };

  function escapeHtml(s) {
    return String(s ?? "").replace(/[&<>"']/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
    );
  }

  function fmtUsd(n) {
    return n == null || Number.isNaN(Number(n)) ? "—" : "$" + Number(n).toFixed(2);
  }

  function fmtPct(n) {
    if (n == null || Number.isNaN(Number(n))) return "—";
    const v = Number(n);
    return (v >= 0 ? "+" : "") + v.toFixed(2) + "%";
  }

  function fmtQty(n) {
    if (n == null || Number.isNaN(Number(n))) return "—";
    const v = Number(n);
    return Number.isInteger(v) ? String(v) : v.toFixed(1);
  }

  function shortCondition(c) {
    const s = String(c || "");
    if (s.includes("Near Mint")) return "NM";
    if (s.includes("Lightly Played")) return "LP";
    if (s.includes("Moderately Played")) return "MP";
    if (s.includes("Heavily Played")) return "HP";
    if (s.includes("Damaged")) return "DMG";
    return s.length > 14 ? s.slice(0, 12) + "…" : s || "—";
  }

  /** Per-copy buy cost (listing + fair share of shipping) — matches profit math. */
  function landedPrice(row) {
    if (row.lowest_price != null && row.lowest_price !== "") {
      return Number(row.lowest_price);
    }
    if (row.seller_price != null) {
      const qty = Math.max(Number(row.order_qty) || 1, 1);
      const unit = Number(row.seller_price);
      const ship = row.shipping_price != null ? Number(row.shipping_price) : 0;
      return unit + ship / qty;
    }
    return null;
  }

  function landedPriceTitle(row) {
    const landed = landedPrice(row);
    if (landed == null) return "";
    const parts = [`$${landed.toFixed(2)}/copy landed`];
    if (row.seller_price != null) parts.push(`$${Number(row.seller_price).toFixed(2)} listing`);
    if (row.shipping_price != null && Number(row.shipping_price) > 0) {
      const qty = Math.max(Number(row.order_qty) || 1, 1);
      parts.push(`$${Number(row.shipping_price).toFixed(2)} shipping ÷ ${qty}`);
    }
    return parts.join(" · ");
  }

  function cardMeta(row) {
    const parts = [row.set_name, row.variant, row.condition_display, row.finish]
      .map((p) => String(p || "").trim())
      .filter(Boolean);
    return parts.join(" · ") || "—";
  }

  function showToast(message, isError = false) {
    if (!els.purchaseToast) return;
    els.purchaseToast.textContent = message;
    els.purchaseToast.hidden = false;
    els.purchaseToast.classList.toggle("is-error", isError);
    clearTimeout(showToast._timer);
    showToast._timer = setTimeout(() => {
      els.purchaseToast.hidden = true;
    }, 4500);
  }

  function updateSelectionUi() {
    const n = selectedIds.size;
    const label = n ? `Add ${n} to inventory` : "Add to inventory";
    if (els.addSelectedBtn) {
      els.addSelectedBtn.disabled = n === 0;
      els.addSelectedBtn.textContent = label;
    }
    if (els.sellerAddSelectedBtn) {
      els.sellerAddSelectedBtn.disabled = n === 0;
      els.sellerAddSelectedBtn.textContent = label;
    }
    if (els.selectAll) {
      const boxes = els.results.querySelectorAll(".opp-row-check");
      const checked = [...boxes].filter((b) => b.checked).length;
      els.selectAll.checked = boxes.length > 0 && checked === boxes.length;
      els.selectAll.indeterminate = checked > 0 && checked < boxes.length;
    }
    syncBuyListCheckboxes();
  }

  function syncBuyListCheckboxes() {
    document.querySelectorAll(".opp-buylist-check").forEach((box) => {
      const id = Number(box.dataset.oppId);
      box.checked = selectedIds.has(id);
    });
    document.querySelectorAll(".opp-buylist-select-all").forEach((master) => {
      const sellerId = master.dataset.sellerId;
      const boxes = document.querySelectorAll(
        `.opp-buy-list-row[data-seller-id="${sellerId}"] .opp-buylist-check`
      );
      const checked = [...boxes].filter((b) => b.checked).length;
      master.checked = boxes.length > 0 && checked === boxes.length;
      master.indeterminate = checked > 0 && checked < boxes.length;
    });
  }

  async function addToInventoryBatch(items, loadingBtn = null) {
    if (!items.length) return;
    const btn = loadingBtn || els.addSelectedBtn || els.sellerAddSelectedBtn;
    setButtonLoading(btn, true);
    try {
      const res = await fetch("/api/inventory/batch", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ items }),
      });
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      const created = data.created?.length || 0;
      const skipped = data.skipped?.length || 0;
      const errors = data.errors?.length || 0;
      const parts = [];
      if (created) parts.push(`${created} added`);
      if (skipped) parts.push(`${skipped} skipped (already in inventory)`);
      if (errors) parts.push(`${errors} failed`);
      showToast(parts.join(" · ") || "Done", errors > 0);
      items.forEach((item) => {
        if (data.created?.some((r) => r.opportunity_id === item.opportunity_id)) {
          selectedIds.delete(item.opportunity_id);
        }
      });
      els.results.querySelectorAll(".opp-row-check").forEach((box) => {
        if (!selectedIds.has(Number(box.dataset.oppId))) box.checked = false;
      });
      updateSelectionUi();
    } catch (err) {
      showToast(err.message || String(err), true);
    } finally {
      setButtonLoading(btn, false);
    }
  }

  async function addSelectedToInventory() {
    const items = [...selectedIds].map((id) => ({ opportunity_id: id }));
    await addToInventoryBatch(items);
  }

  async function addSellerBuyList(sellerIdx, btn) {
    const seller = sellerData[Number(sellerIdx)];
    if (!seller?.buy_list?.length) return;
    const items = seller.buy_list
      .filter((item) => item.opportunity_id)
      .map((item) => ({ opportunity_id: item.opportunity_id }));
    if (!items.length) {
      showToast("No opportunity IDs in buy list — reload seller data", true);
      return;
    }
    await addToInventoryBatch(items, btn);
  }

  function sortValue(cell, type) {
    let val = cell.dataset.sort ?? cell.innerText.trim();
    if (type === "num") {
      return parseFloat(String(val).replace(/[^0-9.-]/g, "")) || 0;
    }
    return String(val).toLowerCase();
  }

  /** Client-side column sort (HTML report pattern). */
  function setupClientSortTable(tableEl, rowSelector) {
    const tableBody = tableEl.querySelector("tbody");
    const tableHeaders = tableEl.querySelectorAll("th.opp-sortable");
    tableHeaders.forEach((header) => {
      if (!header.dataset.sortDir) header.dataset.sortDir = "desc";
      header.addEventListener("click", function (e) {
        e.stopPropagation();
        const colIndex = parseInt(this.dataset.col, 10);
        const type = this.dataset.type || "num";
        const newDir = this.dataset.sortDir === "asc" ? "desc" : "asc";
        tableHeaders.forEach((h) => h.classList.remove("sort-asc", "sort-desc"));
        this.dataset.sortDir = newDir;
        this.classList.add(newDir === "asc" ? "sort-asc" : "sort-desc");
        const rows = Array.from(tableBody.querySelectorAll(rowSelector));
        rows.sort((a, b) => {
          const aVal = sortValue(a.cells[colIndex], type);
          const bVal = sortValue(b.cells[colIndex], type);
          if (aVal < bVal) return newDir === "asc" ? -1 : 1;
          if (aVal > bVal) return newDir === "asc" ? 1 : -1;
          return 0;
        });
        rows.forEach((row) => {
          tableBody.appendChild(row);
          const detail = tableBody.querySelector(
            `.opp-buy-list-row[data-seller-id="${row.dataset.sellerId}"]`
          );
          if (detail) tableBody.appendChild(detail);
        });
      });
    });
  }

  /** Cards table: profit/roi headers trigger server sort. */
  function setupCardsServerSort() {
    const table = document.querySelector("#panelCards .opp-table");
    if (!table) return;
    const headers = table.querySelectorAll("th.opp-sortable[data-sort-col]");
    headers.forEach((header) => {
      if (!header.dataset.sortDir) header.dataset.sortDir = "desc";
      header.addEventListener("click", function (e) {
        e.stopPropagation();
        const col = this.dataset.sortCol;
        const newDir = this.dataset.sortDir === "asc" ? "desc" : "asc";
        headers.forEach((h) => {
          h.classList.remove("sort-asc", "sort-desc");
          if (h !== this) h.dataset.sortDir = "desc";
        });
        this.dataset.sortDir = newDir;
        this.classList.add(newDir === "asc" ? "sort-asc" : "sort-desc");
        this.setAttribute("aria-sort", newDir === "asc" ? "ascending" : "descending");
        const sortVal = `${col}_${newDir}`;
        if (els.sort.querySelector(`option[value="${sortVal}"]`)) els.sort.value = sortVal;
        offset = 0;
        search();
      });
    });
  }

  function buildParams() {
    const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
    const q = els.q.value.trim();
    const seller = els.seller.value.trim();
    if (q) params.set("q", q);
    if (seller) params.set("seller", seller);
    if (els.minProfit.value) params.set("min_profit", els.minProfit.value);
    if (els.minRoi.value) params.set("min_roi", els.minRoi.value);
    if (els.sort.value) params.set("sort", els.sort.value);
    return params;
  }

  function hasActiveFilters() {
    return Boolean(
      els.q.value.trim() ||
        els.seller.value.trim() ||
        els.minProfit.value ||
        els.minRoi.value
    );
  }

  function renderChips() {
    const chips = [];
    const q = els.q.value.trim();
    const seller = els.seller.value.trim();
    if (q) chips.push({ key: "q", label: `“${q}”` });
    if (seller) chips.push({ key: "seller", label: `Seller: ${seller}` });
    if (els.minProfit.value) chips.push({ key: "min_profit", label: `Profit ≥ ${fmtUsd(els.minProfit.value)}` });
    if (els.minRoi.value) chips.push({ key: "min_roi", label: `ROI ≥ ${els.minRoi.value}%` });

    if (!chips.length) {
      els.activeChips.hidden = true;
      els.activeChips.innerHTML = "";
      return;
    }
    els.activeChips.hidden = false;
    els.activeChips.innerHTML = chips
      .map(
        (c) =>
          `<button type="button" class="opp-chip" data-chip="${escapeHtml(c.key)}" title="Remove filter">${escapeHtml(c.label)} <span aria-hidden="true">×</span></button>`
      )
      .join("");
  }

  function clearChip(key) {
    if (key === "q") els.q.value = "";
    if (key === "seller") els.seller.value = "";
    if (key === "min_profit") els.minProfit.value = "";
    if (key === "min_roi") els.minRoi.value = "";
    offset = 0;
    renderChips();
    search();
  }

  async function loadMeta() {
    const res = await fetch("/api/opportunities/meta");
    const data = await res.json();
    if (!data.snapshot_date) {
      els.meta.textContent = "No data yet — run the arbitrage pipeline.";
      return null;
    }
    metaRowCount = Number(data.row_count || 0);
    els.meta.textContent = `Snapshot ${data.snapshot_date}`;
    els.kpiCount.textContent = metaRowCount.toLocaleString();
    els.kpis.hidden = false;
    return data;
  }

  async function loadTopChart() {
    const res = await fetch("/api/opportunities?limit=8&offset=0&sort=profit_desc");
    if (!res.ok) return;
    const data = await res.json();
    const rows = data.results || [];
    if (!rows.length) return;

    els.kpiProfit.textContent = fmtUsd(rows[0].order_profit);
    const topRoi = rows.reduce(
      (best, r) => ((r.order_roi ?? -Infinity) > (best.order_roi ?? -Infinity) ? r : best),
      rows[0]
    );
    els.kpiRoi.textContent = fmtPct(topRoi.order_roi);

    const maxProfit = Math.max(...rows.map((r) => Number(r.order_profit) || 0), 1);
    els.profitChart.innerHTML = rows
      .map((row) => {
        const profit = Number(row.order_profit) || 0;
        const pct = Math.max(4, (profit / maxProfit) * 100);
        return `
          <button type="button" class="opp-chart-row" data-name="${escapeHtml(row.name)}" title="Filter to ${escapeHtml(row.name)}">
            <span class="opp-chart-label">${escapeHtml(row.name)}</span>
            <span class="opp-chart-track"><span class="opp-chart-fill" style="width:${pct.toFixed(0)}%"></span></span>
            <span class="opp-chart-val">${fmtUsd(profit)}</span>
          </button>`;
      })
      .join("");
  }

  function renderRow(row) {
    const landed = landedPrice(row);
    const profit = row.order_profit;
    const profitClass = (profit ?? 0) >= 0 ? "is-pos" : "is-neg";
    const roiClass = (row.order_roi ?? 0) >= 0 ? "is-pos" : "is-neg";
    const tcgUrl = row.tcg_url ? escapeHtml(row.tcg_url) : "";
    const ckUrl = row.ck_url ? escapeHtml(row.ck_url) : "";

    return `
      <tr class="opp-row" data-opp-id="${row.id}" data-tcg-url="${tcgUrl}" tabindex="0">
        <td class="opp-check-col">
          <input type="checkbox" class="opp-row-check" data-opp-id="${row.id}" aria-label="Select ${escapeHtml(row.name)}" />
        </td>
        <td class="opp-card-cell">
          <div class="opp-card-name">${escapeHtml(row.name)}</div>
          <div class="opp-card-meta">${escapeHtml(cardMeta(row))}</div>
          <div class="opp-card-seller">${escapeHtml(row.seller || "")}</div>
        </td>
        <td class="num price-cash">${fmtUsd(row.ck_cash)}</td>
        <td class="num price-tcg" title="${escapeHtml(landedPriceTitle(row))}">${fmtUsd(landed)}</td>
        <td class="num">${row.order_qty ?? "—"}</td>
        <td class="num opp-profit ${profitClass}" data-sort="${Number(profit ?? 0).toFixed(4)}">${fmtUsd(profit)}</td>
        <td class="num ${roiClass}" data-sort="${Number(row.order_roi ?? 0).toFixed(4)}">${fmtPct(row.order_roi)}</td>
        <td class="opp-actions">
          ${ckUrl ? `<a class="opp-link" href="${ckUrl}" target="_blank" rel="noopener" title="Card Kingdom">CK</a>` : ""}
          ${tcgUrl ? `<a class="opp-link opp-link-primary" href="${tcgUrl}" target="_blank" rel="noopener" title="TCGplayer listing">TCG</a>` : ""}
        </td>
      </tr>`;
  }

  function renderBuyListItem(item) {
    const ckUrl = item.ck_url ? escapeHtml(item.ck_url) : "";
    const tcgUrl = item.tcg_url ? escapeHtml(item.tcg_url) : "";
    const oppId = item.opportunity_id;
    const checked = oppId && selectedIds.has(oppId) ? " checked" : "";
    return `
      <tr>
        <td class="opp-check-col">
          ${oppId ? `<input type="checkbox" class="opp-buylist-check" data-opp-id="${oppId}"${checked} aria-label="Select ${escapeHtml(item.name)}" />` : ""}
        </td>
        <td>${escapeHtml(item.name)}</td>
        <td class="col-set" title="${escapeHtml(item.set_name)}">${escapeHtml(item.set_name || "—")}</td>
        <td class="col-variant" title="${escapeHtml(item.variant || "—")}">${escapeHtml(item.variant || "—")}</td>
        <td class="col-condition" title="${escapeHtml(item.condition_display)}">${escapeHtml(shortCondition(item.condition_display))}</td>
        <td>${escapeHtml(item.finish || "—")}</td>
        <td class="num">${fmtQty(item.order_qty)}</td>
        <td class="num" title="${escapeHtml(landedPriceTitle(item))}">${fmtUsd(landedPrice(item))}</td>
        <td class="num">${fmtUsd(item.ck_adj)}</td>
        <td class="num is-pos">${fmtUsd(item.order_profit)}</td>
        <td class="opp-actions">
          ${ckUrl ? `<a class="opp-link" href="${ckUrl}" target="_blank" rel="noopener">CK</a>` : ""}
          ${tcgUrl ? `<a class="opp-link opp-link-primary" href="${tcgUrl}" target="_blank" rel="noopener" title="Seller-filtered TCG listing">TCG</a>` : ""}
        </td>
      </tr>`;
  }

  function renderSellerRow(row, idx) {
    const profitClass = (row.order_profit ?? 0) >= 0 ? "is-pos" : "is-neg";
    const roiClass = (row.order_roi ?? 0) >= 0 ? "is-pos" : "is-neg";
    const buyList = (row.buy_list || []).map(renderBuyListItem).join("");
    return `
      <tr class="opp-seller-row" data-seller-id="${idx}">
        <td>${escapeHtml(row.seller)}</td>
        <td class="num" data-sort="${row.cards}">${row.cards}</td>
        <td class="num" data-sort="${Number(row.order_qty).toFixed(4)}">${fmtQty(row.order_qty)}</td>
        <td class="num" data-sort="${Number(row.shipping_price).toFixed(4)}">${fmtUsd(row.shipping_price)}</td>
        <td class="num" data-sort="${Number(row.order_cost).toFixed(4)}">${fmtUsd(row.order_cost)}</td>
        <td class="num ${profitClass}" data-sort="${Number(row.order_profit).toFixed(4)}">${fmtUsd(row.order_profit)}</td>
        <td class="num ${roiClass}" data-sort="${Number(row.order_roi ?? -1e9).toFixed(4)}">${fmtPct(row.order_roi)}</td>
        <td>
          <button type="button" class="opp-buy-list-toggle secondary opp-btn-ghost" data-seller-id="${idx}" data-count="${row.cards}">
            View buy list (${row.cards})
          </button>
          <button type="button" class="opp-add-buy-list secondary opp-btn-ghost" data-seller-id="${idx}">
            Add all to inventory
          </button>
        </td>
      </tr>
      <tr class="opp-buy-list-row" data-seller-id="${idx}">
        <td colspan="8">
          <div class="opp-buy-list-panel">
            <p class="opp-buy-list-hint">Select cards or use <strong>Add all to inventory</strong> for the full seller batch. Ctrl+click TCG links to open product listings.</p>
            <table class="opp-buy-list-table">
              <thead>
                <tr>
                  <th class="opp-check-col">
                    <input type="checkbox" class="opp-buylist-select-all" data-seller-id="${idx}" title="Select all cards from this seller" aria-label="Select all cards from this seller" />
                  </th>
                  <th>Name</th>
                  <th class="col-set">Set</th>
                  <th class="col-variant">Variant</th>
                  <th class="col-condition">Cond</th>
                  <th>Finish</th>
                  <th class="num">Buy qty</th>
                  <th class="num" title="Per-copy buy cost (listing + share of shipping)">Landed</th>
                  <th class="num">CK adj $</th>
                  <th class="num">Profit</th>
                  <th>Links</th>
                </tr>
              </thead>
              <tbody>${buyList}</tbody>
            </table>
          </div>
        </td>
      </tr>`;
  }

  function renderSellerTable(rows) {
    els.sellerResults.innerHTML = rows.map(renderSellerRow).join("");
    els.sellerTableWrap.hidden = rows.length === 0;
    els.sellerEmpty.hidden = rows.length !== 0;
    if (els.sellerSummary) {
      els.sellerSummary.textContent =
        rows.length === 0
          ? "No seller batches"
          : `${rows.length} seller batch${rows.length === 1 ? "" : "es"}`;
    }
    syncBuyListCheckboxes();
  }

  function filterSellerRows() {
    const filter = els.sellerQ.value.trim().toLowerCase();
    els.sellerResults.querySelectorAll(".opp-seller-row").forEach((row) => {
      const sellerId = row.dataset.sellerId;
      const detail = els.sellerResults.querySelector(
        `.opp-buy-list-row[data-seller-id="${sellerId}"]`
      );
      const haystack = detail
        ? `${row.innerText} ${detail.innerText}`.toLowerCase()
        : row.innerText.toLowerCase();
      const match = !filter || haystack.includes(filter);
      row.style.display = match ? "" : "none";
      if (detail) {
        detail.style.display = match && detail.classList.contains("open") ? "" : "none";
      }
    });
  }

  function updatePager() {
    const end = Math.min(offset + limit, lastTotal);
    els.pageInfo.textContent =
      lastTotal === 0 ? "0" : `${offset + 1}–${end} / ${lastTotal.toLocaleString()}`;
    els.prevBtn.disabled = offset <= 0;
    els.nextBtn.disabled = offset + limit >= lastTotal;
    els.resultSummary.textContent =
      lastTotal === 0
        ? "No matches"
        : `${lastTotal.toLocaleString()} opportunit${lastTotal === 1 ? "y" : "ies"}`;
  }

  async function search() {
    renderChips();
    els.filtersToggle.classList.toggle("is-active", hasActiveFilters());
    setStatusLoading(els.status, true, "Loading…");

    try {
      const res = await fetch(`/api/opportunities?${buildParams()}`);
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      lastTotal = data.total || 0;
      const rows = data.results || [];

      els.results.innerHTML = rows.map(renderRow).join("");
      animateTableRows(els.results);
      els.results.querySelectorAll(".opp-row-check").forEach((box) => {
        const id = Number(box.dataset.oppId);
        box.checked = selectedIds.has(id);
      });
      updateSelectionUi();
      els.tableWrap.hidden = rows.length === 0;
      els.emptyState.hidden = rows.length !== 0;
      updatePager();
      setStatusLoading(els.status, false);
    } catch (err) {
      els.status.textContent = err.message || String(err);
      els.status.className = "opp-status error";
    }
  }

  async function loadSellers() {
    setStatusLoading(els.sellerStatus, true, "Loading seller batches…");

    try {
      const res = await fetch("/api/opportunities/sellers?limit=50&offset=0&sort=profit_desc");
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      sellerData = data.results || [];
      renderSellerTable(sellerData);
      filterSellerRows();
      setStatusLoading(els.sellerStatus, false);
    } catch (err) {
      els.sellerStatus.textContent = err.message || String(err);
      els.sellerStatus.className = "opp-status error";
    }
  }

  function scheduleSearch(resetOffset = true) {
    if (resetOffset) offset = 0;
    clearTimeout(searchTimer);
    searchTimer = setTimeout(search, 280);
  }

  function resetFilters() {
    els.q.value = "";
    els.seller.value = "";
    els.minProfit.value = "";
    els.minRoi.value = "";
    els.sort.value = "profit_desc";
    offset = 0;
    renderChips();
    search();
  }

  function togglePanel(btn, panel) {
    const open = panel.hidden;
    panel.hidden = !open;
    btn.setAttribute("aria-expanded", String(open));
    btn.classList.toggle("is-active", open);
  }

  function switchTab(tab) {
    activeTab = tab;
    const isCards = tab === "cards";
    els.tabCards.classList.toggle("is-active", isCards);
    els.tabSellers.classList.toggle("is-active", !isCards);
    els.tabCards.setAttribute("aria-selected", String(isCards));
    els.tabSellers.setAttribute("aria-selected", String(!isCards));
    els.panelCards.hidden = !isCards;
    els.panelSellers.hidden = isCards;
    if (!isCards) {
      if (!sellerData.length) loadSellers();
      else filterSellerRows();
    }
    updateSelectionUi();
    if (isCards) els.q.focus();
    else els.sellerQ.focus();
  }

  els.q.addEventListener("input", () => scheduleSearch(true));
  els.seller.addEventListener("input", () => scheduleSearch(true));
  els.minProfit.addEventListener("change", () => scheduleSearch(true));
  els.minRoi.addEventListener("change", () => scheduleSearch(true));
  els.sort.addEventListener("change", () => {
    offset = 0;
    search();
  });
  els.resetBtn.addEventListener("click", resetFilters);
  els.emptyReset.addEventListener("click", resetFilters);
  els.addSelectedBtn?.addEventListener("click", addSelectedToInventory);
  els.sellerAddSelectedBtn?.addEventListener("click", addSelectedToInventory);
  els.selectAll?.addEventListener("change", () => {
    const checked = els.selectAll.checked;
    els.results.querySelectorAll(".opp-row-check").forEach((box) => {
      box.checked = checked;
      const id = Number(box.dataset.oppId);
      if (checked) selectedIds.add(id);
      else selectedIds.delete(id);
    });
    updateSelectionUi();
  });
  els.results.addEventListener("change", (e) => {
    const box = e.target.closest(".opp-row-check");
    if (!box) return;
    const id = Number(box.dataset.oppId);
    if (box.checked) selectedIds.add(id);
    else selectedIds.delete(id);
    updateSelectionUi();
  });
  els.sellerQ.addEventListener("input", filterSellerRows);

  els.tabCards.addEventListener("click", () => switchTab("cards"));
  els.tabSellers.addEventListener("click", () => switchTab("sellers"));

  els.filtersToggle.addEventListener("click", () => {
    togglePanel(els.filtersToggle, els.advancedFilters);
  });
  els.chartToggle.addEventListener("click", () => {
    togglePanel(els.chartToggle, els.chartPanel);
  });

  els.activeChips.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-chip]");
    if (btn) clearChip(btn.dataset.chip);
  });

  els.profitChart.addEventListener("click", (e) => {
    const row = e.target.closest("[data-name]");
    if (!row) return;
    els.q.value = row.dataset.name;
    offset = 0;
    if (els.chartPanel.hidden === false) togglePanel(els.chartToggle, els.chartPanel);
    scheduleSearch(true);
    els.q.focus();
  });

  els.results.addEventListener("click", (e) => {
    if (e.target.closest("a, input, label")) return;
    const tr = e.target.closest(".opp-row");
    if (!tr || !tr.dataset.tcgUrl) return;
    window.open(tr.dataset.tcgUrl, "_blank", "noopener");
  });

  els.results.addEventListener("keydown", (e) => {
    if (e.key !== "Enter" && e.key !== " ") return;
    const tr = e.target.closest(".opp-row");
    if (!tr || !tr.dataset.tcgUrl) return;
    e.preventDefault();
    window.open(tr.dataset.tcgUrl, "_blank", "noopener");
  });

  els.sellerResults.addEventListener("click", (e) => {
    const addBtn = e.target.closest(".opp-add-buy-list");
    if (addBtn) {
      e.stopPropagation();
      addSellerBuyList(addBtn.dataset.sellerId, addBtn);
      return;
    }
    const btn = e.target.closest(".opp-buy-list-toggle");
    if (!btn) return;
    e.stopPropagation();
    const sellerId = btn.dataset.sellerId;
    const detail = els.sellerResults.querySelector(
      `.opp-buy-list-row[data-seller-id="${sellerId}"]`
    );
    if (!detail) return;
    const open = detail.classList.toggle("open");
    const count = btn.dataset.count || "";
    btn.textContent = open ? `Hide buy list (${count})` : `View buy list (${count})`;
    detail.style.display = open ? "" : "none";
  });

  els.sellerResults.addEventListener("change", (e) => {
    const selectAll = e.target.closest(".opp-buylist-select-all");
    if (selectAll) {
      const sellerId = selectAll.dataset.sellerId;
      const boxes = els.sellerResults.querySelectorAll(
        `.opp-buy-list-row[data-seller-id="${sellerId}"] .opp-buylist-check`
      );
      boxes.forEach((box) => {
        const id = Number(box.dataset.oppId);
        box.checked = selectAll.checked;
        if (selectAll.checked) selectedIds.add(id);
        else selectedIds.delete(id);
      });
      updateSelectionUi();
      return;
    }
    const box = e.target.closest(".opp-buylist-check");
    if (!box) return;
    const id = Number(box.dataset.oppId);
    if (box.checked) selectedIds.add(id);
    else selectedIds.delete(id);
    updateSelectionUi();
  });

  els.prevBtn.addEventListener("click", () => {
    offset = Math.max(0, offset - limit);
    search();
    els.tableWrap.scrollIntoView({ behavior: "smooth", block: "start" });
  });
  els.nextBtn.addEventListener("click", () => {
    if (offset + limit < lastTotal) {
      offset += limit;
      search();
      els.tableWrap.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  });

  document.addEventListener("keydown", (e) => {
    if (e.key !== "/" || e.metaKey || e.ctrlKey || e.altKey) return;
    const tag = document.activeElement?.tagName;
    if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
    e.preventDefault();
    if (activeTab === "cards") {
      els.q.focus();
      els.q.select();
    } else {
      els.sellerQ.focus();
      els.sellerQ.select();
    }
  });

  setupCardsServerSort();
  const sellerTable = document.querySelector(".opp-seller-table");
  if (sellerTable) setupClientSortTable(sellerTable, "tr.opp-seller-row");

  (async function init() {
    await loadMeta();
    await loadTopChart();
    await search();
    els.q.focus();
  })();
})();
