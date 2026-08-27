/** Stacks sell list — CK match by batch, export, mark sold / restore */
(function () {
  let activeTab = "sell";
  let sellRowsById = new Map();
  let cardsById = new Map();
  let editingCardId = null;
  let sellBatches = [];
  let pendingExportRows = [];
  let confirmBatchKeys = [];
  let confirmActiveBatch = "";
  let searchTimer = null;

  const els = {
    meta: document.getElementById("meta"),
    kpiLines: document.getElementById("kpiLines"),
    kpiCash: document.getElementById("kpiCash"),
    kpiCredit: document.getElementById("kpiCredit"),
    kpiSelected: document.getElementById("kpiSelected"),
    tabNote: document.getElementById("tabNote"),
    tabSell: document.getElementById("tabSell"),
    tabKeep: document.getElementById("tabKeep"),
    tabSold: document.getElementById("tabSold"),
    tabAll: document.getElementById("tabAll"),
    q: document.getElementById("q"),
    exportBtn: document.getElementById("exportBtn"),
    batchSelectBtn: document.getElementById("batchSelectBtn"),
    keepBtn: document.getElementById("keepBtn"),
    markSoldBtn: document.getElementById("markSoldBtn"),
    restoreBtn: document.getElementById("restoreBtn"),
    addBatchLabel: document.getElementById("addBatchLabel"),
    addBatchFiles: document.getElementById("addBatchFiles"),
    importInventoryLabel: document.getElementById("importInventoryLabel"),
    importFiles: document.getElementById("importFiles"),
    importResultModal: document.getElementById("importResultModal"),
    importResultForm: document.getElementById("importResultForm"),
    importResultClose: document.getElementById("importResultClose"),
    importResultTitle: document.getElementById("importResultTitle"),
    importResultIntro: document.getElementById("importResultIntro"),
    importResultList: document.getElementById("importResultList"),
    importResultSummary: document.getElementById("importResultSummary"),
    cardEditModal: document.getElementById("cardEditModal"),
    cardEditForm: document.getElementById("cardEditForm"),
    cardEditClose: document.getElementById("cardEditClose"),
    cardEditCancel: document.getElementById("cardEditCancel"),
    cardEditSave: document.getElementById("cardEditSave"),
    ceName: document.getElementById("ceName"),
    ceSet: document.getElementById("ceSet"),
    ceCollector: document.getElementById("ceCollector"),
    ceFinish: document.getElementById("ceFinish"),
    ceQty: document.getElementById("ceQty"),
    ceStatus: document.getElementById("ceStatus"),
    ceScryfall: document.getElementById("ceScryfall"),
    ceNotes: document.getElementById("ceNotes"),
    ceMeta: document.getElementById("ceMeta"),
    statusMsg: document.getElementById("statusMsg"),
    resultSummary: document.getElementById("resultSummary"),
    sellPanel: document.getElementById("sellPanel"),
    batchHost: document.getElementById("batchHost"),
    emptySell: document.getElementById("emptySell"),
    tablePanel: document.getElementById("tablePanel"),
    cardsBody: document.getElementById("cardsBody"),
    emptyCards: document.getElementById("emptyCards"),
    selectAll: document.getElementById("selectAll"),
    batchSelectModal: document.getElementById("batchSelectModal"),
    batchSelectForm: document.getElementById("batchSelectForm"),
    batchSelectList: document.getElementById("batchSelectList"),
    batchSelectClose: document.getElementById("batchSelectClose"),
    batchSelectCancel: document.getElementById("batchSelectCancel"),
    batchSelectAll: document.getElementById("batchSelectAll"),
    batchSelectNone: document.getElementById("batchSelectNone"),
    confirmModal: document.getElementById("confirmSoldModal"),
    confirmTabs: document.getElementById("confirmSoldTabs"),
    confirmPanels: document.getElementById("confirmSoldPanels"),
    confirmBatchMeta: document.getElementById("confirmBatchMeta"),
    confirmSummary: document.getElementById("confirmSoldSummary"),
    confirmBatchPrev: document.getElementById("confirmBatchPrev"),
    confirmBatchNext: document.getElementById("confirmBatchNext"),
    confirmCheckAll: document.getElementById("confirmCheckAll"),
    confirmKeepAll: document.getElementById("confirmKeepAll"),
    confirmUncheckAll: document.getElementById("confirmUncheckAll"),
    confirmForm: document.getElementById("confirmSoldForm"),
    confirmClose: document.getElementById("confirmSoldClose"),
    confirmCancel: document.getElementById("confirmSoldCancel"),
    linkToast: document.getElementById("linkToast"),
  };

  function escapeHtml(s) {
    return String(s ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function fmtUsd(n) {
    if (n == null || Number.isNaN(Number(n))) return "—";
    return (
      "$" +
      Number(n).toLocaleString(undefined, {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
      })
    );
  }

  /** Row tint from Stacks Colors (W/U/B/R/G) — matches classic sell_list.html */
  function manaRowClass(colors) {
    const raw = String(colors ?? "")
      .trim()
      .toUpperCase()
      .replace(/\s+/g, "");
    if (!raw || raw === "NA" || raw === "C" || raw === "COLORLESS") {
      return "mana-c";
    }
    const letters = [...new Set(raw.replace(/[^WUBRG]/g, "").split(""))].filter(Boolean);
    if (letters.length === 0) return "mana-c";
    if (letters.length >= 2) return "mana-m";
    return `mana-${letters[0].toLowerCase()}`;
  }

  function showToast(msg) {
    if (!els.linkToast) return;
    els.linkToast.textContent = msg;
    els.linkToast.hidden = false;
    clearTimeout(showToast._t);
    showToast._t = setTimeout(() => {
      els.linkToast.hidden = true;
    }, 3200);
  }

  function csvEscape(v) {
    const s = String(v ?? "");
    return `"${s.replace(/"/g, '""')}"`;
  }

  function downloadCkCsv(rows) {
    const lines = rows.map((r) =>
      [
        r.ck_export_name || r.ck_name || r.name,
        r.ck_edition || "",
        r.foil || "FALSE",
        r.quantity ?? 1,
      ]
        .map(csvEscape)
        .join(",")
    );
    const blob = new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8;" });
    const a = document.createElement("a");
    const day = new Date().toISOString().slice(0, 10);
    a.href = URL.createObjectURL(blob);
    a.download = `ck_upload_${day}.csv`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(a.href);
  }

  function setBatchChecks(batchFile, on) {
    document
      .querySelectorAll(`.sell-batch[data-batch="${CSS.escape(batchFile)}"] .sell-check`)
      .forEach((box) => {
        box.checked = on;
      });
  }

  function batchCheckState(batchFile) {
    const boxes = [
      ...document.querySelectorAll(
        `.sell-batch[data-batch="${CSS.escape(batchFile)}"] .sell-check`
      ),
    ];
    if (!boxes.length) return { checked: false, indeterminate: false };
    const n = boxes.filter((b) => b.checked).length;
    return {
      checked: n === boxes.length,
      indeterminate: n > 0 && n < boxes.length,
    };
  }

  function checkedSellRows() {
    return [...document.querySelectorAll(".sell-check:checked")]
      .map((box) => sellRowsById.get(parseInt(box.dataset.id, 10)))
      .filter(Boolean);
  }

  function updateSelectedKpi() {
    const rows = checkedSellRows();
    const cash = rows.reduce((s, r) => s + (r.line_cash || 0), 0);
    if (els.kpiSelected) els.kpiSelected.textContent = fmtUsd(cash);
  }

  function renderBatch(batch) {
    const rowsHtml = batch.rows
      .map((row) => {
        sellRowsById.set(row.id, row);
        return `
        <tr data-id="${row.id}" class="${manaRowClass(row.colors)}">
          <td class="opp-check-col">
            <input type="checkbox" class="sell-check" data-id="${row.id}"
              aria-label="Select ${escapeHtml(row.name)}" />
          </td>
          <td class="opp-card-cell">
            <div class="opp-card-name">${escapeHtml(row.name)}</div>
            <div class="opp-card-meta">${escapeHtml(row.ck_export_name || row.ck_name || "")}${row.ck_edition ? ` · ${escapeHtml(row.ck_edition)}` : ""}</div>
          </td>
          <td>${escapeHtml(row.finish)}</td>
          <td>${escapeHtml(row.scan_order)}</td>
          <td class="num">${row.quantity}</td>
          <td class="num">${fmtUsd(row.cash_price)}</td>
          <td class="num">${fmtUsd(row.credit_price)}</td>
          <td class="num">${fmtUsd(row.tcg_price)}</td>
          <td class="num">${row.pct_of_tcg != null ? `${row.pct_of_tcg}%` : "—"}</td>
          <td class="opp-actions">
            <button type="button" class="pur-edit-btn sell-card-edit" data-id="${row.id}"
              title="Edit card" aria-label="Edit ${escapeHtml(row.name)}">✎</button>
          </td>
        </tr>`;
      })
      .join("");

    return `
      <section class="sell-batch" data-batch="${escapeHtml(batch.batch_file)}">
        <div class="sell-batch-header">
          <h2>${escapeHtml(batch.batch_file)}</h2>
          <div class="sell-batch-actions">
            <button type="button" class="secondary opp-btn-ghost sell-batch-check" data-batch="${escapeHtml(batch.batch_file)}" data-on="1">Check all</button>
            <button type="button" class="secondary opp-btn-ghost sell-batch-check" data-batch="${escapeHtml(batch.batch_file)}" data-on="0">Uncheck all</button>
          </div>
        </div>
        <p class="sell-batch-totals">
          ${batch.totals.lines} lines · Cash ${fmtUsd(batch.totals.cash)} · Credit ${fmtUsd(batch.totals.credit)} · TCG ${fmtUsd(batch.totals.tcg)}
        </p>
        <div class="opp-table-wrap">
          <table class="opp-table inv-table">
            <thead>
              <tr>
                <th class="opp-check-col"></th>
                <th>Name / CK</th>
                <th>Finish</th>
                <th>Scan</th>
                <th class="num">Qty</th>
                <th class="num">CK cash</th>
                <th class="num">CK credit</th>
                <th class="num">TCG</th>
                <th class="num">% TCG</th>
                <th><span class="sr-only">Edit</span></th>
              </tr>
            </thead>
            <tbody>${rowsHtml}</tbody>
          </table>
        </div>
      </section>`;
  }

  async function loadSellList() {
    setStatusLoading(els.statusMsg, true, "Loading sell list…");
    sellRowsById.clear();
    try {
      const params = new URLSearchParams();
      if (els.q?.value.trim()) params.set("q", els.q.value.trim());
      const res = await fetch(`/api/collection/sell-list?${params}`);
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      const batches = data.batches || [];
      sellBatches = batches;
      const summary = data.summary || {};
      if (els.kpiLines) els.kpiLines.textContent = String(summary.lines ?? 0);
      if (els.kpiCash) els.kpiCash.textContent = fmtUsd(summary.total_cash);
      if (els.kpiCredit) els.kpiCredit.textContent = fmtUsd(summary.total_credit);
      els.batchHost.innerHTML = batches.map(renderBatch).join("");
      els.emptySell.hidden = batches.length > 0;
      els.resultSummary.textContent = batches.length
        ? `${summary.lines} sellable · ${batches.length} batch${batches.length === 1 ? "" : "es"}`
        : "";
      els.meta.textContent = batches.length
        ? `${summary.lines} cards CK is buying from your Stacks collection`
        : "Import Stacks CSVs on the All cards tab, or wait for a matching buylist";
      updateSelectedKpi();
      setStatusLoading(els.statusMsg, false);
    } catch (err) {
      els.statusMsg.textContent = err.message || String(err);
      els.statusMsg.className = "opp-status error";
    }
  }

  async function loadCards(status) {
    setStatusLoading(els.statusMsg, true, "Loading…");
    try {
      const params = new URLSearchParams({ limit: "500" });
      if (status) params.set("status", status);
      if (els.q?.value.trim()) params.set("q", els.q.value.trim());
      const res = await fetch(`/api/collection/cards?${params}`);
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      const rows = data.results || [];
      cardsById = new Map(rows.map((r) => [r.id, r]));
      els.cardsBody.innerHTML = rows
        .map(
          (row) => `
        <tr data-id="${row.id}" class="${manaRowClass(row.colors)}">
          <td class="opp-check-col">
            <input type="checkbox" class="card-check" data-id="${row.id}"
              aria-label="Select ${escapeHtml(row.name)}" />
          </td>
          <td class="opp-card-cell">
            <div class="opp-card-name">${escapeHtml(row.name)}</div>
            <div class="opp-card-meta">${escapeHtml(row.set_code || "")} · ${escapeHtml(row.scryfall_id || "")}</div>
          </td>
          <td>${escapeHtml(row.batch_file)}</td>
          <td>${escapeHtml(row.scan_order)}</td>
          <td>${escapeHtml(row.finish)}</td>
          <td class="num">${row.quantity}</td>
          <td>${escapeHtml(row.status)}</td>
          <td>${row.sold_at ? escapeHtml(String(row.sold_at).slice(0, 10)) : "—"}</td>
          <td class="opp-actions">
            <button type="button" class="pur-edit-btn sell-card-edit" data-id="${row.id}"
              title="Edit card" aria-label="Edit ${escapeHtml(row.name)}">✎</button>
          </td>
        </tr>`
        )
        .join("");
      els.emptyCards.hidden = rows.length > 0;
      els.resultSummary.textContent = `${(data.total || 0).toLocaleString()} card${data.total === 1 ? "" : "s"}`;
      if (els.selectAll) els.selectAll.checked = false;
      setStatusLoading(els.statusMsg, false);
      refreshSummaryKpis();
    } catch (err) {
      els.statusMsg.textContent = err.message || String(err);
      els.statusMsg.className = "opp-status error";
    }
  }

  async function refreshSummaryKpis() {
    try {
      const res = await fetch("/api/collection/summary");
      if (!res.ok) return;
      const s = await res.json();
      if (activeTab !== "sell") {
        if (els.kpiLines) els.kpiLines.textContent = String(s.sellable ?? 0);
        if (els.kpiCash) els.kpiCash.textContent = String(s.active ?? 0);
        if (els.kpiCredit) els.kpiCredit.textContent = String(s.keep ?? 0);
        if (els.kpiSelected) els.kpiSelected.textContent = String(s.sold ?? 0);
        const labels = document.querySelectorAll("#kpis dt");
        if (labels[0]) labels[0].textContent = "Sellable";
        if (labels[1]) labels[1].textContent = "Active";
        if (labels[2]) labels[2].textContent = "Keep";
        if (labels[3]) labels[3].textContent = "Sold";
      } else {
        const labels = document.querySelectorAll("#kpis dt");
        if (labels[0]) labels[0].textContent = "Sellable";
        if (labels[1]) labels[1].textContent = "CK cash";
        if (labels[2]) labels[2].textContent = "CK credit";
        if (labels[3]) labels[3].textContent = "Selected cash";
      }
    } catch (_) {
      /* ignore */
    }
  }

  function switchTab(tab) {
    activeTab = tab;
    [els.tabSell, els.tabKeep, els.tabSold, els.tabAll].forEach((btn) => {
      if (!btn) return;
      const on = btn.dataset.tab === tab;
      btn.classList.toggle("is-active", on);
      btn.setAttribute("aria-selected", String(on));
    });
    const isSell = tab === "sell";
    els.sellPanel.hidden = !isSell;
    els.tablePanel.hidden = isSell;
    els.exportBtn.hidden = !isSell;
    if (els.batchSelectBtn) els.batchSelectBtn.hidden = !isSell;
    if (els.keepBtn) els.keepBtn.hidden = !(tab === "sell" || tab === "all");
    if (els.markSoldBtn) els.markSoldBtn.hidden = tab !== "all";
    els.restoreBtn.hidden = !(tab === "sold" || tab === "keep");
    if (els.addBatchLabel) els.addBatchLabel.hidden = !(tab === "sell" || tab === "all");
    if (els.importInventoryLabel) els.importInventoryLabel.hidden = tab !== "all";
    const labels = document.querySelectorAll("#kpis dt");
    if (isSell) {
      if (labels[0]) labels[0].textContent = "Sellable";
      if (labels[1]) labels[1].textContent = "CK cash";
      if (labels[2]) labels[2].textContent = "CK credit";
      if (labels[3]) labels[3].textContent = "Selected cash";
    }
    if (els.tabNote) {
      els.tabNote.textContent = isSell
        ? "Active Stacks cards CK is buying for at least $0.03 cash, grouped by batch. Use Add batch… for new Stacks exports (CK match is live). Export for CK, then confirm Sell / Keep / Skip."
        : tab === "keep"
          ? "Cards tagged Keep — still in your digital collection / share HTML, but hidden from the CK sell list. Restore to make them sellable again."
          : tab === "sold"
            ? "Recently sold collection cards — restore any CK rejected after import."
            : "Full Stacks inventory. Add batch… for new exports, or Replace inventory.csv for a full reload. Keep for decks; Mark sold for non-CK sales.";
    }
    load();
  }

  function load() {
    if (activeTab === "sell") return loadSellList();
    if (activeTab === "sold") return loadCards("sold");
    if (activeTab === "keep") return loadCards("keep");
    return loadCards("");
  }

  function selectedCardIds() {
    return [...document.querySelectorAll(".card-check:checked")].map((b) =>
      parseInt(b.dataset.id, 10)
    );
  }

  function selectedSellIds() {
    return [...document.querySelectorAll(".sell-check:checked")].map((b) =>
      parseInt(b.dataset.id, 10)
    );
  }

  async function postCollectionIds(path, ids) {
    const res = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ids }),
    });
    if (!res.ok) throw new Error(await res.text());
    return res.json();
  }

  function resolveCardForEdit(id) {
    return cardsById.get(id) || sellRowsById.get(id) || null;
  }

  function openCardEditModal(id) {
    const row = resolveCardForEdit(id);
    if (!row) {
      alert("Card not loaded — refresh and try again.");
      return;
    }
    editingCardId = id;
    if (els.ceName) els.ceName.value = row.name || "";
    if (els.ceSet) els.ceSet.value = row.set_code || "";
    if (els.ceCollector) els.ceCollector.value = row.collector_number || "";
    const finish = String(row.finish || "normal").toLowerCase();
    if (els.ceFinish) {
      els.ceFinish.value = ["normal", "foil", "etched"].includes(finish) ? finish : "normal";
    }
    if (els.ceQty) els.ceQty.value = String(row.quantity ?? 1);
    if (els.ceStatus) els.ceStatus.value = row.status || "active";
    if (els.ceScryfall) els.ceScryfall.value = row.scryfall_id || "";
    if (els.ceNotes) els.ceNotes.value = row.notes || "";
    if (els.ceMeta) {
      els.ceMeta.textContent = `${row.batch_file || "—"} · scan ${row.scan_order || "—"}`;
    }
    els.cardEditModal?.showModal();
  }

  function closeCardEditModal() {
    editingCardId = null;
    els.cardEditModal?.close();
  }

  async function saveCardEdit() {
    if (!editingCardId) return;
    const payload = {
      name: els.ceName?.value.trim() || "",
      set_code: els.ceSet?.value.trim() || null,
      collector_number: els.ceCollector?.value.trim() || null,
      finish: els.ceFinish?.value || "normal",
      quantity: parseInt(els.ceQty?.value, 10) || 1,
      status: els.ceStatus?.value || "active",
      scryfall_id: els.ceScryfall?.value.trim() || "",
      notes: els.ceNotes?.value.trim() || null,
    };
    setButtonLoading(els.cardEditSave, true);
    try {
      const res = await fetch(`/api/collection/cards/${editingCardId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!res.ok) throw new Error(await res.text());
      closeCardEditModal();
      showToast("Card updated");
      load();
    } catch (err) {
      alert(err.message || String(err));
    } finally {
      setButtonLoading(els.cardEditSave, false);
    }
  }

  function openBatchSelectModal() {
    if (!sellBatches.length) {
      alert("No batches loaded yet.");
      return;
    }
    els.batchSelectList.innerHTML = sellBatches
      .map((batch) => {
        const state = batchCheckState(batch.batch_file);
        const lines = batch.totals?.lines ?? batch.rows?.length ?? 0;
        const cash = batch.totals?.cash;
        return `
        <label class="sell-batch-picker-item">
          <input type="checkbox" class="batch-pick-check" data-batch="${escapeHtml(batch.batch_file)}"
            ${state.checked ? "checked" : ""} />
          <span>${escapeHtml(batch.batch_file)}</span>
          <span class="sell-batch-picker-meta">${lines} · ${fmtUsd(cash)}</span>
        </label>`;
      })
      .join("");
    // Restore indeterminate after insert (property, not attribute).
    els.batchSelectList.querySelectorAll(".batch-pick-check").forEach((box) => {
      const state = batchCheckState(box.dataset.batch);
      box.indeterminate = state.indeterminate;
    });
    els.batchSelectModal?.showModal();
  }

  function closeBatchSelectModal() {
    els.batchSelectModal?.close();
  }

  function applyBatchSelection() {
    els.batchSelectList.querySelectorAll(".batch-pick-check").forEach((box) => {
      setBatchChecks(box.dataset.batch, box.checked);
    });
    updateSelectedKpi();
    closeBatchSelectModal();
  }

  function setPickerChecks(on) {
    els.batchSelectList.querySelectorAll(".batch-pick-check").forEach((box) => {
      box.checked = on;
      box.indeterminate = false;
    });
  }

  function batchShortLabel(batchFile) {
    const raw = String(batchFile || "").trim();
    if (!raw) return "No batch";
    const m = raw.match(/^(Batch\d+)/i);
    if (m) return m[1];
    return raw.replace(/\.csv$/i, "") || "No batch";
  }

  function groupExportByBatch(rows) {
    const map = new Map();
    for (const r of rows) {
      const key = r.batch_file || "No batch";
      if (!map.has(key)) map.set(key, []);
      map.get(key).push(r);
    }
    return map;
  }

  function confirmRowsForBatch(batchKey) {
    return [
      ...document.querySelectorAll(
        `.sell-confirm-panel[data-batch="${CSS.escape(batchKey)}"] tr[data-id]`
      ),
    ];
  }

  function confirmDispositionCounts(scope) {
    const rows = scope
      ? [...scope.querySelectorAll("tr[data-id]")]
      : [...document.querySelectorAll("#confirmSoldPanels tr[data-id]")];
    let sell = 0;
    let keep = 0;
    let skip = 0;
    for (const tr of rows) {
      const d = tr.dataset.disposition || "sell";
      if (d === "keep") keep += 1;
      else if (d === "skip") skip += 1;
      else sell += 1;
    }
    return { sell, keep, skip, total: rows.length };
  }

  function setConfirmRowDisposition(tr, disposition) {
    if (!tr) return;
    const d = disposition === "keep" || disposition === "skip" ? disposition : "sell";
    tr.dataset.disposition = d;
    tr.classList.toggle("is-keep", d === "keep");
    tr.classList.toggle("is-skip", d === "skip");
    tr.querySelectorAll(".sell-confirm-disp-btn").forEach((btn) => {
      btn.classList.toggle("is-active", btn.dataset.disp === d);
    });
  }

  function setConfirmBatchDisposition(disposition) {
    confirmRowsForBatch(confirmActiveBatch).forEach((tr) => {
      setConfirmRowDisposition(tr, disposition);
    });
    updateConfirmSummary();
  }

  function updateConfirmSummary() {
    const all = confirmDispositionCounts();
    const batch = confirmActiveBatch
      ? confirmDispositionCounts(
          document.querySelector(
            `.sell-confirm-panel[data-batch="${CSS.escape(confirmActiveBatch)}"]`
          )
        )
      : { sell: 0, keep: 0, skip: 0, total: 0 };
    const idx = confirmBatchKeys.indexOf(confirmActiveBatch);
    const label = batchShortLabel(confirmActiveBatch);
    if (els.confirmBatchMeta) {
      els.confirmBatchMeta.textContent =
        confirmBatchKeys.length > 1
          ? `${label} · ${idx + 1} of ${confirmBatchKeys.length} · ${batch.sell} sell · ${batch.keep} keep`
          : `${label} · ${batch.sell} sell · ${batch.keep} keep · ${batch.skip} skip`;
    }
    if (els.confirmSummary) {
      els.confirmSummary.textContent = `${all.sell} sell · ${all.keep} keep · ${all.skip} skip across ${confirmBatchKeys.length} batch${
        confirmBatchKeys.length === 1 ? "" : "es"
      }`;
    }
    if (els.confirmBatchPrev) els.confirmBatchPrev.disabled = confirmBatchKeys.length <= 1 || idx <= 0;
    if (els.confirmBatchNext) {
      els.confirmBatchNext.disabled =
        confirmBatchKeys.length <= 1 || idx < 0 || idx >= confirmBatchKeys.length - 1;
    }
    els.confirmTabs?.querySelectorAll(".sell-confirm-tab").forEach((btn) => {
      const key = btn.dataset.batch;
      const counts = confirmDispositionCounts(
        document.querySelector(`.sell-confirm-panel[data-batch="${CSS.escape(key)}"]`)
      );
      const badge = btn.querySelector(".sell-confirm-tab-count");
      if (badge) badge.textContent = `${counts.sell}/${counts.total}`;
      btn.classList.toggle("is-partial", counts.sell > 0 && counts.sell < counts.total);
      btn.classList.toggle("is-empty", counts.sell === 0);
    });
  }

  function showConfirmBatch(batchKey) {
    if (!confirmBatchKeys.includes(batchKey)) return;
    confirmActiveBatch = batchKey;
    els.confirmTabs?.querySelectorAll(".sell-confirm-tab").forEach((btn) => {
      const on = btn.dataset.batch === batchKey;
      btn.classList.toggle("is-active", on);
      btn.setAttribute("aria-selected", on ? "true" : "false");
      btn.tabIndex = on ? 0 : -1;
    });
    els.confirmPanels?.querySelectorAll(".sell-confirm-panel").forEach((panel) => {
      const on = panel.dataset.batch === batchKey;
      panel.hidden = !on;
      panel.classList.toggle("is-active", on);
    });
    updateConfirmSummary();
    const activeTabBtn = els.confirmTabs?.querySelector(
      `.sell-confirm-tab[data-batch="${CSS.escape(batchKey)}"]`
    );
    activeTabBtn?.scrollIntoView({ block: "nearest", inline: "nearest" });
  }

  function stepConfirmBatch(delta) {
    const idx = confirmBatchKeys.indexOf(confirmActiveBatch);
    if (idx < 0) return;
    const next = confirmBatchKeys[idx + delta];
    if (next) showConfirmBatch(next);
  }

  function openConfirmModal(rows) {
    pendingExportRows = rows;
    const byBatch = groupExportByBatch(rows);
    confirmBatchKeys = [...byBatch.keys()];
    confirmActiveBatch = confirmBatchKeys[0] || "";

    if (els.confirmTabs) {
      els.confirmTabs.innerHTML = confirmBatchKeys
        .map((key) => {
          const count = byBatch.get(key)?.length || 0;
          return `
          <button type="button" class="sell-confirm-tab" role="tab"
            data-batch="${escapeHtml(key)}"
            aria-selected="false" tabindex="-1">
            <span class="sell-confirm-tab-label">${escapeHtml(batchShortLabel(key))}</span>
            <span class="sell-confirm-tab-count">${count}/${count}</span>
          </button>`;
        })
        .join("");
    }

    if (els.confirmPanels) {
      els.confirmPanels.innerHTML = confirmBatchKeys
        .map((key) => {
          const batchRows = byBatch.get(key) || [];
          const cash = batchRows.reduce((s, r) => s + (r.line_cash || 0), 0);
          const rowsHtml = batchRows
            .map(
              (r) => `
            <tr class="${manaRowClass(r.colors)}" data-id="${r.id}" data-disposition="sell">
              <td class="sell-confirm-disp">
                <div class="sell-confirm-disp-group" role="group" aria-label="Disposition for ${escapeHtml(r.ck_name || r.name)}">
                  <button type="button" class="sell-confirm-disp-btn is-active" data-disp="sell">Sell</button>
                  <button type="button" class="sell-confirm-disp-btn" data-disp="keep">Keep</button>
                  <button type="button" class="sell-confirm-disp-btn" data-disp="skip">Skip</button>
                </div>
              </td>
              <td class="opp-card-cell">
                <div class="opp-card-name">${escapeHtml(r.ck_name || r.name)}</div>
                <div class="opp-card-meta">${escapeHtml(r.ck_export_name || "")}${
                r.ck_edition ? ` · ${escapeHtml(r.ck_edition)}` : ""
              }</div>
              </td>
              <td>${escapeHtml(r.scan_order)}</td>
              <td class="num">${r.quantity}</td>
              <td class="num">${fmtUsd(r.line_cash)}</td>
            </tr>`
            )
            .join("");
          return `
          <div class="sell-confirm-panel" data-batch="${escapeHtml(key)}" role="tabpanel" hidden>
            <p class="sell-confirm-panel-totals">
              ${batchRows.length} card${batchRows.length === 1 ? "" : "s"} · Cash ${fmtUsd(cash)}
            </p>
            <div class="sell-confirm-table-wrap">
              <table class="opp-table inv-table">
                <thead>
                  <tr>
                    <th>Action</th>
                    <th>Name</th>
                    <th>Scan</th>
                    <th class="num">Qty</th>
                    <th class="num">Cash</th>
                  </tr>
                </thead>
                <tbody>${rowsHtml}</tbody>
              </table>
            </div>
          </div>`;
        })
        .join("");
    }

    els.confirmModal?.showModal();
    if (confirmActiveBatch) showConfirmBatch(confirmActiveBatch);
    else updateConfirmSummary();
  }

  function closeConfirmModal() {
    pendingExportRows = [];
    confirmBatchKeys = [];
    confirmActiveBatch = "";
    els.confirmModal?.close();
  }

  function confirmIdsByDisposition(disposition) {
    return [...document.querySelectorAll(`#confirmSoldPanels tr[data-disposition="${disposition}"]`)]
      .map((tr) => parseInt(tr.dataset.id, 10))
      .filter((id) => Number.isFinite(id) && id > 0);
  }

  els.exportBtn?.addEventListener("click", () => {
    const rows = checkedSellRows();
    if (!rows.length) {
      alert("Check at least one card to export.");
      return;
    }
    downloadCkCsv(rows);
    openConfirmModal(rows);
  });

  els.confirmForm?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const sellIds = confirmIdsByDisposition("sell");
    const keepIds = confirmIdsByDisposition("keep");
    if (!sellIds.length && !keepIds.length) {
      alert("Everything is Skip — nothing to update. Cancel if you only needed the CSV.");
      return;
    }
    try {
      let sold = 0;
      let kept = 0;
      if (sellIds.length) {
        const data = await postCollectionIds("/api/collection/mark-sold", sellIds);
        sold = data.updated || 0;
      }
      if (keepIds.length) {
        const data = await postCollectionIds("/api/collection/mark-keep", keepIds);
        kept = data.updated || 0;
      }
      closeConfirmModal();
      const parts = [];
      if (sold) parts.push(`${sold} sold`);
      if (kept) parts.push(`${kept} keep`);
      showToast(parts.join(" · ") || "Updated");
      loadSellList();
    } catch (err) {
      alert(err.message || String(err));
    }
  });

  els.confirmClose?.addEventListener("click", closeConfirmModal);
  els.confirmCancel?.addEventListener("click", closeConfirmModal);
  els.confirmModal?.addEventListener("cancel", (e) => {
    e.preventDefault();
    closeConfirmModal();
  });
  els.confirmTabs?.addEventListener("click", (e) => {
    const tab = e.target.closest(".sell-confirm-tab");
    if (!tab) return;
    showConfirmBatch(tab.dataset.batch);
  });
  els.confirmBatchPrev?.addEventListener("click", () => stepConfirmBatch(-1));
  els.confirmBatchNext?.addEventListener("click", () => stepConfirmBatch(1));
  els.confirmCheckAll?.addEventListener("click", () => setConfirmBatchDisposition("sell"));
  els.confirmKeepAll?.addEventListener("click", () => setConfirmBatchDisposition("keep"));
  els.confirmUncheckAll?.addEventListener("click", () => setConfirmBatchDisposition("skip"));
  els.confirmPanels?.addEventListener("click", (e) => {
    const btn = e.target.closest(".sell-confirm-disp-btn");
    if (!btn) return;
    const tr = btn.closest("tr[data-id]");
    setConfirmRowDisposition(tr, btn.dataset.disp);
    updateConfirmSummary();
  });
  els.confirmModal?.addEventListener("keydown", (e) => {
    if (!els.confirmModal.open) return;
    if (e.key === "ArrowLeft") {
      e.preventDefault();
      stepConfirmBatch(-1);
    } else if (e.key === "ArrowRight") {
      e.preventDefault();
      stepConfirmBatch(1);
    }
  });

  els.restoreBtn?.addEventListener("click", async () => {
    const ids = selectedCardIds();
    if (!ids.length) {
      alert(activeTab === "keep" ? "Select keep cards to restore." : "Select sold cards to restore.");
      return;
    }
    const label = activeTab === "keep" ? "sellable (active)" : "active";
    if (!confirm(`Restore ${ids.length} card${ids.length === 1 ? "" : "s"} to ${label}?`)) return;
    try {
      const data = await postCollectionIds("/api/collection/restore", ids);
      showToast(`Restored ${data.updated}`);
      load();
    } catch (err) {
      alert(err.message || String(err));
    }
  });

  els.keepBtn?.addEventListener("click", async () => {
    const ids = activeTab === "sell" ? selectedSellIds() : selectedCardIds();
    if (!ids.length) {
      alert("Select cards to keep for decks.");
      return;
    }
    if (
      !confirm(
        `Keep ${ids.length} card${ids.length === 1 ? "" : "s"}? They stay in your collection / share, but leave the CK sell list.`
      )
    ) {
      return;
    }
    try {
      const data = await postCollectionIds("/api/collection/mark-keep", ids);
      showToast(`Kept ${data.updated}`);
      load();
    } catch (err) {
      alert(err.message || String(err));
    }
  });

  els.markSoldBtn?.addEventListener("click", async () => {
    const ids = selectedCardIds();
    if (!ids.length) {
      alert("Select cards to mark sold.");
      return;
    }
    if (!confirm(`Mark ${ids.length} card${ids.length === 1 ? "" : "s"} as sold?`)) return;
    try {
      const data = await postCollectionIds("/api/collection/mark-sold", ids);
      showToast(`Marked ${data.updated} sold`);
      load();
    } catch (err) {
      alert(err.message || String(err));
    }
  });

  function showImportResult(data) {
    const imported = data.imported || [];
    const skipped = data.skipped || [];
    const errors = data.errors || [];
    const parts = [];
    for (const item of imported) {
      const sellable = item.sellable ?? 0;
      parts.push(`
        <li class="sell-import-result-item is-ok">
          <strong>${escapeHtml(batchShortLabel(item.file_name))}</strong>
          <span>${item.inserted} new · ${sellable} on CK sell list</span>
          <span class="sell-import-result-file">${escapeHtml(item.file_name)}</span>
        </li>`);
    }
    for (const item of skipped) {
      parts.push(`
        <li class="sell-import-result-item is-skip">
          <strong>${escapeHtml(batchShortLabel(item.file_name))}</strong>
          <span>Skipped — already imported</span>
          <span class="sell-import-result-file">${escapeHtml(item.file_name)}</span>
        </li>`);
    }
    for (const err of errors) {
      parts.push(`
        <li class="sell-import-result-item is-err">
          <strong>Error</strong>
          <span>${escapeHtml(err)}</span>
        </li>`);
    }
    if (els.importResultList) {
      els.importResultList.innerHTML = parts.length
        ? parts.join("")
        : "<li class=\"sell-import-result-item\">Nothing to import.</li>";
    }
    if (els.importResultTitle) {
      els.importResultTitle.textContent = data.replaced
        ? "Inventory replaced"
        : imported.length
          ? "Batches added"
          : skipped.length
            ? "Nothing new"
            : "Import finished";
    }
    if (els.importResultIntro) {
      els.importResultIntro.textContent = data.replaced
        ? "Collection cleared and reloaded from inventory.csv. CK matching is live against the current buylist."
        : "New Stacks cards are in your collection. CK matching is live against the current buylist — no pipeline run needed.";
    }
    if (els.importResultSummary) {
      const bits = [];
      if (data.inserted_total) bits.push(`${data.inserted_total} cards added`);
      if (data.sellable_new != null) bits.push(`${data.sellable_new} now on CK sell list`);
      if (data.skipped_files) bits.push(`${data.skipped_files} skipped`);
      if (errors.length) bits.push(`${errors.length} error${errors.length === 1 ? "" : "s"}`);
      if (data.sellable_total != null) bits.push(`${data.sellable_total} sellable total`);
      els.importResultSummary.textContent = bits.join(" · ") || "No changes";
    }
    els.importResultModal?.showModal();
  }

  function closeImportResult() {
    els.importResultModal?.close();
  }

  async function uploadCollectionFiles(fileList, { replace = false } = {}) {
    const files = [...(fileList || [])];
    if (!files.length) return;
    const fd = new FormData();
    for (const f of files) fd.append("files", f);
    const qs = replace ? "?replace=true" : "";
    setStatusLoading(els.statusMsg, true, replace ? "Replacing inventory…" : "Adding batch…");
    try {
      const res = await fetch(`/api/collection/import${qs}`, { method: "POST", body: fd });
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      setStatusLoading(els.statusMsg, false);
      showImportResult(data);
      const toastBits = [];
      if (data.inserted_total) toastBits.push(`${data.inserted_total} added`);
      if (data.sellable_new) toastBits.push(`${data.sellable_new} on sell list`);
      if (data.skipped_files) toastBits.push(`${data.skipped_files} skipped`);
      if ((data.errors || []).length) toastBits.push(`${data.errors.length} errors`);
      showToast(toastBits.join(" · ") || "Import finished");
      if (activeTab === "sell" || activeTab === "all") load();
      else switchTab("sell");
    } catch (err) {
      els.statusMsg.textContent = err.message || String(err);
      els.statusMsg.className = "opp-status error";
    }
  }

  els.addBatchFiles?.addEventListener("change", async () => {
    const files = els.addBatchFiles.files;
    if (!files?.length) return;
    const list = [...files];
    if (list.some((f) => (f.name || "").toLowerCase() === "inventory.csv")) {
      if (
        !confirm(
          "One selected file is inventory.csv — that replaces your whole collection (not an incremental batch add). Continue?"
        )
      ) {
        els.addBatchFiles.value = "";
        return;
      }
    }
    await uploadCollectionFiles(list, { replace: false });
    els.addBatchFiles.value = "";
  });

  els.importFiles?.addEventListener("change", async () => {
    const files = els.importFiles.files;
    if (!files?.length) return;
    const name = files[0]?.name || "";
    if (name.toLowerCase() !== "inventory.csv") {
      if (
        !confirm(
          `Replace the whole collection with "${name}"? This clears existing cards first. Prefer inventory.csv for a full replace, or use Add batch for new Stacks exports.`
        )
      ) {
        els.importFiles.value = "";
        return;
      }
    } else if (
      !confirm("Replace the whole collection from inventory.csv? Existing cards will be cleared first.")
    ) {
      els.importFiles.value = "";
      return;
    }
    await uploadCollectionFiles(files, { replace: true });
    els.importFiles.value = "";
  });

  els.importResultClose?.addEventListener("click", closeImportResult);
  els.importResultForm?.addEventListener("submit", (e) => {
    e.preventDefault();
    closeImportResult();
  });
  els.importResultModal?.addEventListener("cancel", (e) => {
    e.preventDefault();
    closeImportResult();
  });

  els.batchSelectBtn?.addEventListener("click", openBatchSelectModal);
  els.batchSelectForm?.addEventListener("submit", (e) => {
    e.preventDefault();
    applyBatchSelection();
  });
  els.batchSelectClose?.addEventListener("click", closeBatchSelectModal);
  els.batchSelectCancel?.addEventListener("click", closeBatchSelectModal);
  els.batchSelectAll?.addEventListener("click", () => setPickerChecks(true));
  els.batchSelectNone?.addEventListener("click", () => setPickerChecks(false));
  els.batchSelectModal?.addEventListener("cancel", (e) => {
    e.preventDefault();
    closeBatchSelectModal();
  });

  els.batchHost?.addEventListener("click", (e) => {
    const editBtn = e.target.closest(".sell-card-edit");
    if (editBtn) {
      openCardEditModal(parseInt(editBtn.dataset.id, 10));
      return;
    }
    const btn = e.target.closest(".sell-batch-check");
    if (!btn) return;
    setBatchChecks(btn.dataset.batch, btn.dataset.on === "1");
    updateSelectedKpi();
  });

  els.cardsBody?.addEventListener("click", (e) => {
    const editBtn = e.target.closest(".sell-card-edit");
    if (!editBtn) return;
    openCardEditModal(parseInt(editBtn.dataset.id, 10));
  });

  els.cardEditClose?.addEventListener("click", closeCardEditModal);
  els.cardEditCancel?.addEventListener("click", closeCardEditModal);
  els.cardEditForm?.addEventListener("submit", async (e) => {
    e.preventDefault();
    await saveCardEdit();
  });
  els.cardEditModal?.addEventListener("cancel", (e) => {
    e.preventDefault();
    closeCardEditModal();
  });

  els.batchHost?.addEventListener("change", (e) => {
    if (e.target.classList.contains("sell-check")) updateSelectedKpi();
  });

  els.selectAll?.addEventListener("change", () => {
    const on = els.selectAll.checked;
    document.querySelectorAll(".card-check").forEach((b) => {
      b.checked = on;
    });
  });

  els.tabSell?.addEventListener("click", () => switchTab("sell"));
  els.tabKeep?.addEventListener("click", () => switchTab("keep"));
  els.tabSold?.addEventListener("click", () => switchTab("sold"));
  els.tabAll?.addEventListener("click", () => switchTab("all"));

  els.q?.addEventListener("input", () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(load, 250);
  });

  switchTab("sell");
})();
