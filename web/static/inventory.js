/** Inventory lots + CK fulfillments — lifecycle tabs */
(function () {
  const STATUS_OPTIONS = [
    { value: "ordered", label: "Ordered" },
    { value: "inbound", label: "Inbound" },
    { value: "on_hand", label: "On hand" },
    { value: "depleted", label: "Depleted" },
    { value: "cancelled", label: "Cancelled" },
  ];

  const TAB_NOTES = {
    all: "All inventory lots — free stock only counts as on hand; pack/ship/paid lines live in their own tabs.",
    inbound: "Waiting on TCG sellers — follow up if an order is late.",
    need_to_sell: "Free stock with a current CK buy price (or ordered/inbound 5+ days) — hidden once reserved for pack/ship or fulfilled today.",
    to_pack: "Reserved for CK — no longer on-hand. Mark Packed when sleeved/boxed.",
    to_ship: "Packed and ready to mail — mark Sent when the package goes out.",
    awaiting_payment: "Sent to CK — move back to Packed/Need to pack if needed, or Mark paid when CK pays.",
    paid: "Completed CK payouts — profit uses paid amount when recorded.",
  };

  const LOT_TABS = new Set(["all", "inbound", "need_to_sell"]);
  const LIFECYCLE_LOT_TABS = new Set(["inbound", "need_to_sell"]);
  const FULFILL_TABS = new Set(["to_pack", "to_ship", "awaiting_payment", "paid"]);
  const NEED_TO_SELL_DAYS = 5;
  const FULFILL_STATUS_OPTIONS = [
    { value: "planned", label: "Need to pack" },
    { value: "packed", label: "Need to ship" },
    { value: "sent", label: "Sent / awaiting pay" },
    { value: "paid", label: "Paid" },
  ];

  let searchTimer = null;
  let activeTab = "all";
  const selected = new Set();
  const rowsById = new Map();
  const fulfillRowsById = new Map();
  let editingId = null;
  let fulfillingId = null;
  let lastFulfillTotals = null;

  const els = {
    meta: document.getElementById("meta"),
    linkKpis: document.getElementById("linkKpis"),
    kpi1: document.getElementById("kpi1"),
    kpi2: document.getElementById("kpi2"),
    kpi3: document.getElementById("kpi3"),
    kpi4: document.getElementById("kpi4"),
    tabNote: document.getElementById("tabNote"),
    tabAll: document.getElementById("tabAll"),
    tabInbound: document.getElementById("tabInbound"),
    tabNeedSell: document.getElementById("tabNeedSell"),
    tabToPack: document.getElementById("tabToPack"),
    tabToShip: document.getElementById("tabToShip"),
    tabAwaiting: document.getElementById("tabAwaiting"),
    tabPaid: document.getElementById("tabPaid"),
    q: document.getElementById("q"),
    status: document.getElementById("status"),
    seller: document.getElementById("seller"),
    tcgOrderFilter: document.getElementById("tcgOrderFilter"),
    batchFilter: document.getElementById("batchFilter"),
    hasRemaining: document.getElementById("hasRemaining"),
    unlinkedOnly: document.getElementById("unlinkedOnly"),
    linkBar: document.getElementById("linkBar"),
    selectedCount: document.getElementById("selectedCount"),
    bulkTcgOrder: document.getElementById("bulkTcgOrder"),
    applyLinkBtn: document.getElementById("applyLinkBtn"),
    removeSelectedBtn: document.getElementById("removeSelectedBtn"),
    clearSelectBtn: document.getElementById("clearSelectBtn"),
    selectAll: document.getElementById("selectAll"),
    resultSummary: document.getElementById("resultSummary"),
    statusMsg: document.getElementById("statusMsg"),
    linkToast: document.getElementById("linkToast"),
    results: document.getElementById("results"),
    fulfillResults: document.getElementById("fulfillResults"),
    lotsTable: document.getElementById("lotsTable"),
    fulfillTable: document.getElementById("fulfillTable"),
    tableWrap: document.getElementById("tableWrap"),
    emptyState: document.getElementById("emptyState"),
    emptyMessage: document.getElementById("emptyMessage"),
    manualToggle: document.getElementById("manualToggle"),
    manualPanel: document.getElementById("manualPanel"),
    manualForm: document.getElementById("manualForm"),
    manualSubmit: document.getElementById("manualSubmit"),
    manualClear: document.getElementById("manualClear"),
    mName: document.getElementById("mName"),
    mSet: document.getElementById("mSet"),
    mSeller: document.getElementById("mSeller"),
    mSellerPrice: document.getElementById("mSellerPrice"),
    mQty: document.getElementById("mQty"),
    mCkMax: document.getElementById("mCkMax"),
    mCondition: document.getElementById("mCondition"),
    mFinish: document.getElementById("mFinish"),
    mShipping: document.getElementById("mShipping"),
    mCkCash: document.getElementById("mCkCash"),
    mTcgUrl: document.getElementById("mTcgUrl"),
    mTcgOrder: document.getElementById("mTcgOrder"),
    mOrderedAt: document.getElementById("mOrderedAt"),
    mNotes: document.getElementById("mNotes"),
    editModal: document.getElementById("editModal"),
    editForm: document.getElementById("editForm"),
    editClose: document.getElementById("editClose"),
    editCancel: document.getElementById("editCancel"),
    editSave: document.getElementById("editSave"),
    eName: document.getElementById("eName"),
    eSet: document.getElementById("eSet"),
    eSeller: document.getElementById("eSeller"),
    eSellerPrice: document.getElementById("eSellerPrice"),
    eQtyOriginal: document.getElementById("eQtyOriginal"),
    eQtyOnHand: document.getElementById("eQtyOnHand"),
    eExpectedCkQty: document.getElementById("eExpectedCkQty"),
    eCkMax: document.getElementById("eCkMax"),
    eCondition: document.getElementById("eCondition"),
    eFinish: document.getElementById("eFinish"),
    eShipping: document.getElementById("eShipping"),
    eCkCash: document.getElementById("eCkCash"),
    eCkCashExpected: document.getElementById("eCkCashExpected"),
    eStatus: document.getElementById("eStatus"),
    eTcgOrder: document.getElementById("eTcgOrder"),
    eOrderedAt: document.getElementById("eOrderedAt"),
    eTcgUrl: document.getElementById("eTcgUrl"),
    eCkUrl: document.getElementById("eCkUrl"),
    eNotes: document.getElementById("eNotes"),
    fulfillModal: document.getElementById("fulfillModal"),
    fulfillForm: document.getElementById("fulfillForm"),
    fulfillClose: document.getElementById("fulfillClose"),
    fulfillCancel: document.getElementById("fulfillCancel"),
    fulfillSave: document.getElementById("fulfillSave"),
    fulfillTitle: document.getElementById("fulfillTitle"),
    fulfillSubtitle: document.getElementById("fulfillSubtitle"),
    fulfillList: document.getElementById("fulfillList"),
    fQty: document.getElementById("fQty"),
    fCkBatch: document.getElementById("fCkBatch"),
    fCkRef: document.getElementById("fCkRef"),
    fCkAdj: document.getElementById("fCkAdj"),
    fStatus: document.getElementById("fStatus"),
    fPaidAmount: document.getElementById("fPaidAmount"),
    fNotes: document.getElementById("fNotes"),
    massFulfillToggle: document.getElementById("massFulfillToggle"),
    massFulfillSelectedBtn: document.getElementById("massFulfillSelectedBtn"),
    massFulfillModal: document.getElementById("massFulfillModal"),
    massFulfillForm: document.getElementById("massFulfillForm"),
    massFulfillClose: document.getElementById("massFulfillClose"),
    massFulfillCancel: document.getElementById("massFulfillCancel"),
    massFulfillSave: document.getElementById("massFulfillSave"),
    mfCkRef: document.getElementById("mfCkRef"),
    mfCkBatch: document.getElementById("mfCkBatch"),
    mfStatus: document.getElementById("mfStatus"),
    mfNotes: document.getElementById("mfNotes"),
    mfFilter: document.getElementById("mfFilter"),
    mfSelectAll: document.getElementById("mfSelectAll"),
    mfResults: document.getElementById("mfResults"),
    mfSummary: document.getElementById("mfSummary"),
  };

  let massFulfillLots = [];

  function escapeHtml(s) {
    return String(s ?? "").replace(/[&<>"']/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
    );
  }

  function fmtUsd(n) {
    return n == null || Number.isNaN(Number(n)) ? "—" : "$" + Number(n).toFixed(2);
  }

  function fmtCkDelta(n) {
    if (n == null || Number.isNaN(Number(n))) return "—";
    const v = Number(n);
    if (Math.abs(v) < 0.005) return "—";
    return (v > 0 ? "+" : "") + "$" + v.toFixed(2);
  }

  function ckDeltaClass(n) {
    if (n == null || Number.isNaN(Number(n)) || Math.abs(Number(n)) < 0.005) return "";
    return Number(n) > 0 ? "is-pos" : "is-neg";
  }

  function cardMeta(row) {
    const parts = [row.set_name, row.variant, row.condition_display, row.finish]
      .map((p) => String(p || "").trim())
      .filter(Boolean);
    const ckMax = row.ck_max_qty ? `CK max ${row.ck_max_qty}` : "";
    if (ckMax) parts.push(ckMax);
    return parts.join(" · ") || "—";
  }

  function showToast(msg) {
    els.linkToast.textContent = msg;
    els.linkToast.hidden = false;
    clearTimeout(showToast._t);
    showToast._t = setTimeout(() => {
      els.linkToast.hidden = true;
    }, 4000);
  }

  function defaultFulfillQty(row) {
    const onHand = Number(row.qty_on_hand) || 0;
    const ckMax = Number(row.ck_max_qty);
    if (onHand <= 0) return 1;
    if (ckMax > 0) return Math.min(onHand, ckMax);
    return onHand;
  }

  function updateSelectionUi() {
    const n = selected.size;
    els.linkBar.hidden = n === 0;
    els.selectedCount.textContent = `${n} selected`;
    const boxes = els.results.querySelectorAll(".inv-row-check");
    const checked = [...boxes].filter((b) => b.checked).length;
    if (els.selectAll) {
      els.selectAll.checked = boxes.length > 0 && checked === boxes.length;
      els.selectAll.indeterminate = checked > 0 && checked < boxes.length;
    }
  }

  function linkInput(cls, id, value, label, placeholder) {
    return `<input type="text" class="${cls}" data-id="${id}" value="${escapeHtml(value || "")}" placeholder="${placeholder}" aria-label="${label} for ${id}" />`;
  }

  function statusSelect(row) {
    const options = STATUS_OPTIONS.map(
      (opt) =>
        `<option value="${opt.value}"${row.status === opt.value ? " selected" : ""}>${opt.label}</option>`
    ).join("");
    return `<select class="pur-status-select" data-id="${row.id}" aria-label="Status for ${escapeHtml(row.name)}">${options}</select>`;
  }

  function showCkBuyCols() {
    return activeTab === "all" || activeTab === "need_to_sell";
  }

  function updateCkBuyColVisibility() {
    const show = showCkBuyCols();
    document.querySelectorAll(".inv-ck-buy-col").forEach((el) => {
      el.classList.toggle("is-hidden", !show);
    });
  }

  function renderRow(row) {
    const expClass = (row.expected_profit ?? 0) >= 0 ? "is-pos" : "is-neg";
    const realClass = (row.realized_profit_paid ?? 0) >= 0 ? "is-pos" : "is-neg";
    const ckUrl = row.ck_url ? escapeHtml(row.ck_url) : "";
    const tcgUrl = row.tcg_url ? escapeHtml(row.tcg_url) : "";
    const checked = selected.has(row.id) ? " checked" : "";
    const manualBadge = row.opportunity_id == null ? '<span class="pur-manual-badge">Manual</span> ' : "";
    const fulfilled = Number(row.qty_fulfilled) || 0;
    const packing = Number(row.qty_packing) || 0;
    const onHandBits = [];
    if (fulfilled > 0) onHandBits.push(`${fulfilled} sent to CK`);
    if (packing > 0) onHandBits.push(`${packing} packing`);
    const onHandSub = onHandBits.length
      ? `<div class="inv-qty-sub">${onHandBits.join(" · ")}</div>`
      : "";
    const canFulfill = (row.qty_on_hand ?? 0) > 0;
    const showBuyCk = showCkBuyCols();
    const ckTitle = [
      row.ck_cash == null && row.tcg_product_id
        ? "CK not buying this finish on latest buylist"
        : null,
      row.ck_adj != null ? `${fmtUsd(row.ck_adj)}/copy adj` : null,
      row.ck_price_snapshot ? `snapshot ${row.ck_price_snapshot}` : null,
      row.ck_cash_expected != null ? `at buy ${fmtUsd(row.ck_cash_expected)}` : null,
      !row.tcg_product_id && row.ck_cash == null ? "Add TCG URL to sync CK prices" : null,
      row.tcg_product_id ? `TCG #${row.tcg_product_id}` : null,
    ]
      .filter(Boolean)
      .join(" · ");
    const deltaTitle =
      row.ck_cash == null
        ? "No current CK cash — not on latest buylist for this finish"
        : row.ck_cash_expected != null
          ? `${fmtUsd(row.ck_cash_expected)} at buy → ${fmtUsd(row.ck_cash)} now`
          : "No CK @ buy baseline — set when adding from Opportunities or edit the lot";
    const orderDate = row.ordered_at || row.acquired_at || "";
    const ageDays = orderDate
      ? Math.floor((Date.now() - new Date(`${orderDate}T00:00:00`).getTime()) / 86400000)
      : null;
    const ageLabel =
      ageDays == null || Number.isNaN(ageDays)
        ? "—"
        : ageDays <= 0
          ? "today"
          : `${ageDays}d`;
    const buyCkCell = showBuyCk
      ? `<td class="num inv-ck-buy-col" title="CK cash when purchased">${fmtUsd(row.ck_cash_expected)}</td>`
      : `<td class="num inv-ck-buy-col is-hidden" aria-hidden="true"></td>`;
    return `
      <tr class="inv-row" data-id="${row.id}">
        <td class="opp-check-col">
          <input type="checkbox" class="inv-row-check" data-id="${row.id}"${checked} aria-label="Select ${escapeHtml(row.name)}" />
        </td>
        <td class="opp-card-cell">
          <div class="opp-card-name">${manualBadge}${escapeHtml(row.name)}</div>
          <div class="opp-card-meta">${escapeHtml(cardMeta(row))}</div>
          <div class="opp-card-seller">${escapeHtml(row.seller || "")}</div>
        </td>
        <td class="num inv-qty-cell">
          <span class="inv-qty-main">${row.qty_on_hand}/${row.qty_original}</span>
          ${onHandSub}
        </td>
        <td class="inv-ordered-cell" title="${escapeHtml(orderDate || "No order date")}">
          <div>${escapeHtml(orderDate || "—")}</div>
          <div class="inv-qty-sub">${ageLabel}</div>
        </td>
        <td class="num">${fmtUsd(row.seller_price)}</td>
        ${buyCkCell}
        <td class="num price-cash" title="${escapeHtml(ckTitle)}">${fmtUsd(row.ck_cash)}</td>
        <td class="num ${ckDeltaClass(row.ck_cash_delta)}" title="${escapeHtml(deltaTitle)}">${fmtCkDelta(row.ck_cash_delta)}</td>
        <td class="num ${expClass}">${fmtUsd(row.expected_profit)}</td>
        <td class="num ${realClass}">${fmtUsd(row.realized_profit_paid)}</td>
        <td>${statusSelect(row)}</td>
        <td>${linkInput("pur-link-input pur-tcg-input", row.id, row.tcg_order_id, "TCG order id", "order #")}</td>
        <td class="inv-actions-col">
          <div class="inv-row-actions">
            ${ckUrl ? `<a class="opp-link" href="${ckUrl}" target="_blank" rel="noopener">CK</a>` : ""}
            ${tcgUrl ? `<a class="opp-link opp-link-primary" href="${tcgUrl}" target="_blank" rel="noopener">TCG</a>` : ""}
            ${canFulfill ? `<button type="button" class="pur-edit-btn inv-fulfill-btn" data-id="${row.id}" title="CK fulfillment" aria-label="Fulfill ${escapeHtml(row.name)}">→</button>` : ""}
            <button type="button" class="pur-edit-btn" data-id="${row.id}" title="Edit lot" aria-label="Edit ${escapeHtml(row.name)}">✎</button>
            <button type="button" class="pur-remove-btn" data-id="${row.id}" data-name="${escapeHtml(row.name)}" title="Remove lot" aria-label="Remove ${escapeHtml(row.name)}">×</button>
          </div>
        </td>
      </tr>`;
  }

  function fmtDate(iso) {
    if (!iso) return "—";
    const d = new Date(iso);
    return Number.isNaN(d.getTime()) ? "—" : d.toLocaleDateString();
  }

  const EMPTY_MESSAGES = {
    all: 'No inventory yet. Buy from <a href="/opportunities">Opportunities</a> or use <strong>Manual entry</strong>.',
    inbound: 'No inbound orders. Add buys from <a href="/opportunities">Opportunities</a> and set status to Ordered or Inbound.',
    to_pack: "No CK orders waiting to pack — Mass fulfill from Need to Sell as Need to pack.",
    to_ship: "Nothing packed awaiting shipment — mark rows Packed from Need to Pack.",
    need_to_sell: "Nothing in the sell queue — need On hand stock (any order date) or ordered/inbound 5+ days old, plus a current CK buy price and no CK fulfillment dated today.",
    awaiting_payment: "No CK shipments awaiting payment — mark Sent from Need to Ship.",
    paid: "No paid fulfillments yet — mark rows paid from Awaiting payment.",
  };

  function updateEmptyMessage() {
    if (els.emptyMessage) {
      els.emptyMessage.innerHTML = EMPTY_MESSAGES[activeTab] || EMPTY_MESSAGES.all;
    }
  }

  function isLotTab() {
    return LOT_TABS.has(activeTab);
  }

  function isLifecycleLotTab() {
    return LIFECYCLE_LOT_TABS.has(activeTab);
  }

  function tabButtons() {
    return [
      els.tabAll,
      els.tabInbound,
      els.tabNeedSell,
      els.tabToPack,
      els.tabToShip,
      els.tabAwaiting,
      els.tabPaid,
    ].filter(Boolean);
  }

  function switchTab(tab) {
    activeTab = tab;
    selected.clear();
    tabButtons().forEach((btn) => {
      const on = btn.dataset.tab === tab;
      btn.classList.toggle("is-active", on);
      btn.setAttribute("aria-selected", String(on));
    });
    if (els.tabNote) {
      const note = TAB_NOTES[tab] || "";
      els.tabNote.textContent = note;
      els.tabNote.hidden = !note || tab === "all";
    }
    updateEmptyMessage();
    updateCkBuyColVisibility();
    const lotMode = isLotTab();
    els.lotsTable.hidden = !lotMode;
    els.fulfillTable.hidden = lotMode;
    els.linkBar.hidden = true;
    if (els.selectAll) els.selectAll.closest("th")?.classList.toggle("hidden-col", !lotMode);
    document.querySelectorAll(".inv-advanced-filter").forEach((el) => {
      el.hidden = activeTab !== "all";
    });
    load();
  }

  function updateTabCounts(summary) {
    if (!summary || !els.linkKpis) return;
    els.linkKpis.hidden = false;
    if (els.kpi1) els.kpi1.textContent = String(summary.inbound ?? 0);
    if (els.kpi2) els.kpi2.textContent = String(summary.need_to_sell ?? 0);
    if (els.kpi3) els.kpi3.textContent = String(summary.awaiting_payment ?? 0);
    if (els.kpi4) {
      els.kpi4.textContent = fmtUsd(summary.paid_profit ?? 0);
      els.kpi4.classList.toggle("is-pos", (summary.paid_profit ?? 0) > 0);
    }
    const countMap = {
      all: summary.total_lots,
      inbound: summary.inbound,
      need_to_sell: summary.need_to_sell,
      to_pack: summary.to_pack,
      to_ship: summary.to_ship,
      awaiting_payment: summary.awaiting_payment,
      paid: summary.paid,
    };
    tabButtons().forEach((btn) => {
      const base = btn.dataset.label || btn.textContent.replace(/\s*\(\d+\)$/, "");
      const n = countMap[btn.dataset.tab];
      btn.textContent = n != null ? `${base} (${n})` : base;
    });
  }

  function fulfillStatusSelect(row) {
    const current = row.fulfillment_status || "planned";
    const editable = activeTab === "to_pack" || activeTab === "to_ship" || activeTab === "awaiting_payment";
    if (!editable) {
      const label = FULFILL_STATUS_OPTIONS.find((o) => o.value === current)?.label || current;
      return escapeHtml(label);
    }
    const options = FULFILL_STATUS_OPTIONS.filter((o) => o.value !== "paid" || current === "paid")
      .map(
        (opt) =>
          `<option value="${opt.value}"${current === opt.value ? " selected" : ""}>${opt.label}</option>`
      )
      .join("");
    return `<select class="pur-status-select inv-fulfill-status" data-lot-id="${row.lot_id}" data-id="${row.fulfillment_id}" aria-label="Fulfillment status for ${escapeHtml(row.name)}">${options}</select>`;
  }

  function renderFulfillmentRow(row) {
    const profitClass = (row.fulfillment_profit ?? 0) >= 0 ? "is-pos" : "is-neg";
    const dateVal =
      activeTab === "paid"
        ? row.paid_at
        : activeTab === "to_ship"
          ? row.packed_at || row.created_at
          : activeTab === "to_pack"
            ? row.created_at
            : row.sent_at;
    const ckUrl = row.ck_url ? escapeHtml(row.ck_url) : "";
    const tcgUrl = row.tcg_url ? escapeHtml(row.tcg_url) : "";
    const advanceBtn =
      activeTab === "to_pack"
        ? `<button type="button" class="secondary inv-advance-btn" data-action="mark-packed" data-lot-id="${row.lot_id}" data-id="${row.fulfillment_id}">Packed</button>`
        : activeTab === "to_ship"
          ? `<button type="button" class="secondary inv-advance-btn" data-action="mark-shipped" data-lot-id="${row.lot_id}" data-id="${row.fulfillment_id}">Shipped</button>`
          : activeTab === "awaiting_payment"
            ? `<button type="button" class="secondary inv-advance-btn" data-action="mark-paid" data-lot-id="${row.lot_id}" data-id="${row.fulfillment_id}">Mark paid</button>`
            : "";
    return `
      <tr class="inv-fulfill-row" data-id="${row.fulfillment_id}">
        <td class="opp-card-cell">
          <div class="opp-card-name">${escapeHtml(row.name)}</div>
          <div class="opp-card-meta">${escapeHtml(cardMeta(row))}</div>
          <div class="opp-card-seller">${escapeHtml(row.seller || "")}</div>
        </td>
        <td class="num">${row.fulfillment_qty}</td>
        <td>${escapeHtml(row.ck_batch_id || "—")}</td>
        <td>${escapeHtml(row.ck_ref || "—")}</td>
        <td class="num">${fmtUsd(row.fulfillment_revenue)}</td>
        <td class="num">${fmtUsd(row.fulfillment_cost)}</td>
        <td class="num ${profitClass}">${fmtUsd(row.fulfillment_profit)}</td>
        <td>${fmtDate(dateVal)}</td>
        <td>${fulfillStatusSelect(row)}</td>
        <td>${escapeHtml(row.tcg_order_id || "—")}</td>
        <td class="opp-actions inv-fulfill-actions">
          ${advanceBtn}
          ${ckUrl ? `<a class="opp-link" href="${ckUrl}" target="_blank" rel="noopener">CK</a>` : ""}
          ${tcgUrl ? `<a class="opp-link opp-link-primary" href="${tcgUrl}" target="_blank" rel="noopener">TCG</a>` : ""}
        </td>
      </tr>`;
  }

  function buildParams() {
    const params = new URLSearchParams({
      limit: "200",
      sort: activeTab === "need_to_sell" ? "ordered_asc" : "created_desc",
    });
    const q = els.q.value.trim();
    const seller = els.seller.value.trim();
    if (q) params.set("q", q);
    if (seller) params.set("seller", seller);
    if (isLifecycleLotTab()) {
      params.set("lifecycle", activeTab);
    }
    if (activeTab === "all") {
      if (els.status?.value) params.set("status", els.status.value);
      if (els.hasRemaining?.checked) params.set("has_remaining", "true");
      if (els.unlinkedOnly?.checked) params.set("unlinked", "true");
    }
    if (els.tcgOrderFilter?.value) params.set("tcg_order_id", els.tcgOrderFilter.value);
    if (els.batchFilter?.value) params.set("ck_batch_id", els.batchFilter.value);
    return params;
  }

  function buildFulfillParams() {
    const params = new URLSearchParams({ limit: "200", lifecycle: activeTab });
    const q = els.q.value.trim();
    const seller = els.seller.value.trim();
    if (q) params.set("q", q);
    if (seller) params.set("seller", seller);
    if (els.batchFilter?.value) params.set("ck_batch_id", els.batchFilter.value);
    params.set(
      "sort",
      activeTab === "paid"
        ? "paid_desc"
        : activeTab === "to_pack" || activeTab === "to_ship"
          ? "name"
          : "sent_desc"
    );
    return params;
  }

  async function patchLot(id, body) {
    const res = await fetch(`/api/inventory/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error(await res.text());
    return res.json();
  }

  async function deleteLot(id) {
    const res = await fetch(`/api/inventory/${id}`, { method: "DELETE" });
    if (!res.ok) throw new Error(await res.text());
    return res.json();
  }

  async function batchLink(lotIds, body) {
    const res = await fetch("/api/inventory/batch-link", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ lot_ids: lotIds, ...body }),
    });
    if (!res.ok) throw new Error(await res.text());
    return res.json();
  }

  async function batchDelete(lotIds) {
    const res = await fetch("/api/inventory/batch-delete", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ lot_ids: lotIds }),
    });
    if (!res.ok) throw new Error(await res.text());
    return res.json();
  }

  function fillSelect(select, items, valueKey, labelFn, emptyLabel, current) {
    const prev = current || select.value;
    select.innerHTML = `<option value="">${emptyLabel}</option>`;
    for (const item of items) {
      const val = item[valueKey];
      const opt = document.createElement("option");
      opt.value = val;
      opt.textContent = labelFn(item);
      select.appendChild(opt);
    }
    if (prev && [...select.options].some((o) => o.value === prev)) {
      select.value = prev;
    }
  }

  async function loadLifecycleSummary() {
    try {
      const res = await fetch("/api/inventory/lifecycle-summary");
      if (!res.ok) return;
      updateTabCounts(await res.json());
    } catch {
      /* optional */
    }
  }

  async function refreshSummaries() {
    await Promise.all([loadLifecycleSummary(), loadLinkingSummary()]);
  }

  async function loadLinkingSummary() {
    try {
      const res = await fetch("/api/inventory/linking-summary");
      if (!res.ok) return;
      const data = await res.json();
      if (els.tcgOrderFilter) {
        fillSelect(
          els.tcgOrderFilter,
          data.tcg_orders || [],
          "tcg_order_id",
          (r) => `${r.tcg_order_id} (${r.count})`,
          "All TCG orders",
          els.tcgOrderFilter.value
        );
      }
      if (els.batchFilter) {
        fillSelect(
          els.batchFilter,
          data.ck_batches || [],
          "ck_batch_id",
          (r) => `${r.ck_batch_id} (${r.total_qty} cards)`,
          "All CK batches",
          els.batchFilter.value
        );
      }
    } catch {
      /* optional */
    }
  }

  async function loadFulfillments() {
    setStatusLoading(els.statusMsg, true, "Loading…");
    try {
      const res = await fetch(`/api/inventory/fulfillments?${buildFulfillParams()}`);
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      const rows = data.results || [];
      fulfillRowsById.clear();
      rows.forEach((row) => fulfillRowsById.set(row.fulfillment_id, row));
      els.fulfillResults.innerHTML = rows.map(renderFulfillmentRow).join("");
      animateTableRows(els.fulfillResults);
      els.tableWrap.hidden = rows.length === 0;
      els.emptyState.hidden = rows.length !== 0;
      lastFulfillTotals = data.totals || null;
      const totals = data.totals || {};
      const label =
        activeTab === "paid"
          ? "paid rows"
          : activeTab === "to_pack"
            ? "need to pack"
            : activeTab === "to_ship"
              ? "need to ship"
              : "awaiting payment";
      els.resultSummary.textContent = `${(data.total || 0).toLocaleString()} ${label} · profit ${fmtUsd(totals.total_profit)} · revenue ${fmtUsd(totals.total_revenue)}`;
      els.meta.textContent =
        activeTab === "paid"
          ? `Realized earnings from CK payouts (${fmtUsd(totals.total_profit)} profit on ${fmtUsd(totals.total_cost)} cost)`
          : activeTab === "to_pack"
            ? `${rows.length} CK line${rows.length === 1 ? "" : "s"} waiting to pack`
            : activeTab === "to_ship"
              ? `${rows.length} packed line${rows.length === 1 ? "" : "s"} — mark Sent when you ship`
              : `${rows.length} shown · expected ${fmtUsd(totals.total_profit)} when paid`;
      setStatusLoading(els.statusMsg, false);
    } catch (err) {
      els.statusMsg.textContent = err.message || String(err);
      els.statusMsg.className = "opp-status error";
    }
  }

  async function load() {
    if (!isLotTab()) {
      await loadFulfillments();
      return;
    }
    setStatusLoading(els.statusMsg, true, "Loading…");
    try {
      const res = await fetch(`/api/inventory?${buildParams()}`);
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      const rows = data.results || [];
      rowsById.clear();
      rows.forEach((row) => rowsById.set(row.id, row));
      els.results.innerHTML = rows.map(renderRow).join("");
      animateTableRows(els.results);
      els.tableWrap.hidden = rows.length === 0;
      els.emptyState.hidden = rows.length !== 0;
      els.resultSummary.textContent = `${(data.total || 0).toLocaleString()} lot${data.total === 1 ? "" : "s"}`;
      const tabLabel =
        activeTab === "all"
          ? "all lots"
          : activeTab === "inbound"
            ? "inbound from TCG"
            : `need to sell (on hand, or ${NEED_TO_SELL_DAYS}+ days ordered/inbound)`;
      els.meta.textContent = rows.length
        ? `${rows.length} shown · ${tabLabel}`
        : activeTab === "all"
          ? "On-hand stock from TCG buys"
          : `No lots in ${tabLabel}`;
      setStatusLoading(els.statusMsg, false);
      updateSelectionUi();
    } catch (err) {
      els.statusMsg.textContent = err.message || String(err);
      els.statusMsg.className = "opp-status error";
    }
  }

  async function markFulfillmentPaid(lotId, fulfillmentId) {
    const paid = prompt("CK paid amount for this line ($)? Leave blank to use CK adj × qty.");
    const payload = { status: "paid" };
    if (paid != null && paid.trim()) {
      const amount = parseFloat(paid);
      if (!Number.isNaN(amount) && amount >= 0) payload.paid_amount = amount;
    }
    const res = await fetch(`/api/inventory/${lotId}/fulfillments/${fulfillmentId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok) throw new Error(await res.text());
  }

  async function setFulfillmentStatus(lotId, fulfillmentId, status) {
    const res = await fetch(`/api/inventory/${lotId}/fulfillments/${fulfillmentId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status }),
    });
    if (!res.ok) throw new Error(await res.text());
  }

  function scheduleLoad() {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(load, 280);
  }

  function populateStatusSelect(selectEl, current) {
    selectEl.innerHTML = STATUS_OPTIONS.map(
      (opt) =>
        `<option value="${opt.value}"${current === opt.value ? " selected" : ""}>${opt.label}</option>`
    ).join("");
  }

  function openEditModal(id) {
    const row = rowsById.get(id);
    if (!row || !els.editModal) return;
    editingId = id;
    els.eName.value = row.name || "";
    els.eSet.value = row.set_name || "";
    els.eSeller.value = row.seller || "";
    els.eSellerPrice.value = row.seller_price ?? "";
    els.eQtyOriginal.value = row.qty_original ?? "";
    els.eQtyOriginal.dataset.prev = String(row.qty_original ?? "");
    els.eQtyOnHand.value = row.qty_on_hand ?? "";
    els.eExpectedCkQty.value = row.expected_ck_qty ?? row.qty_original ?? "";
    els.eCkMax.value = row.ck_max_qty ?? "";
    els.eCondition.value = row.condition_display || row.condition_raw || "Near Mint";
    els.eFinish.value = row.finish || "normal";
    els.eShipping.value = row.shipping_price ?? "";
    els.eCkCash.value = row.ck_cash ?? "";
    if (els.eCkCashExpected) els.eCkCashExpected.value = row.ck_cash_expected ?? "";
    populateStatusSelect(els.eStatus, row.status || "on_hand");
    els.eTcgOrder.value = row.tcg_order_id || "";
    els.eOrderedAt.value = row.ordered_at || row.acquired_at || "";
    els.eTcgUrl.value = row.tcg_url || "";
    els.eCkUrl.value = row.ck_url || "";
    els.eNotes.value = row.notes || "";
    els.editModal.showModal();
    els.eName.focus();
  }

  function closeEditModal() {
    editingId = null;
    els.editModal?.close();
  }

  async function saveEditForm() {
    if (!editingId) return;
    const payload = {
      name: els.eName.value.trim(),
      seller: els.eSeller.value.trim(),
      seller_price: parseFloat(els.eSellerPrice.value),
      qty_original: parseInt(els.eQtyOriginal.value, 10),
      qty_on_hand: parseInt(els.eQtyOnHand.value, 10),
      expected_ck_qty: parseInt(els.eExpectedCkQty.value, 10) || undefined,
      ck_max_qty: els.eCkMax.value ? parseInt(els.eCkMax.value, 10) : null,
      set_name: els.eSet.value.trim() || null,
      condition: els.eCondition.value,
      finish: els.eFinish.value,
      shipping_price: els.eShipping.value ? parseFloat(els.eShipping.value) : null,
      ck_cash: els.eCkCash.value ? parseFloat(els.eCkCash.value) : null,
      ck_cash_expected: els.eCkCashExpected?.value ? parseFloat(els.eCkCashExpected.value) : null,
      status: els.eStatus.value,
      tcg_order_id: els.eTcgOrder.value.trim() || null,
      ordered_at: els.eOrderedAt.value || null,
      tcg_url: els.eTcgUrl.value.trim() || null,
      ck_url: els.eCkUrl.value.trim() || null,
      notes: els.eNotes.value.trim(),
    };
    setButtonLoading(els.editSave, true);
    try {
      await patchLot(editingId, payload);
      showToast(`Updated ${payload.name}`);
      closeEditModal();
      await refreshSummaries();
      load();
    } catch (err) {
      alert(err.message || String(err));
    } finally {
      setButtonLoading(els.editSave, false);
    }
  }

  function renderFulfillmentList(items) {
    if (!items.length) {
      els.fulfillList.hidden = true;
      els.fulfillList.innerHTML = "";
      return;
    }
    els.fulfillList.hidden = false;
    els.fulfillList.innerHTML = `
      <p class="inv-fulfill-list-title">Previous CK submissions</p>
      <ul class="inv-fulfill-items">
        ${items
          .map(
            (f) =>
              `<li><strong>${f.qty}×</strong> ${escapeHtml(f.ck_batch_id || "no batch")} · ${escapeHtml(f.status)}${f.ck_adj != null ? ` · ${fmtUsd(f.ck_adj)}/copy` : ""}</li>`
          )
          .join("")}
      </ul>`;
  }

  async function openFulfillModal(id) {
    const row = rowsById.get(id);
    if (!row || !els.fulfillModal) return;
    fulfillingId = id;
    els.fulfillTitle.textContent = `CK fulfillment — ${row.name}`;
    els.fulfillSubtitle.textContent = `${row.qty_on_hand} on hand of ${row.qty_original} bought · ${row.ck_max_qty ? `CK max ${row.ck_max_qty}` : "no CK max set"}`;
    els.fQty.value = String(defaultFulfillQty(row));
    els.fQty.max = String(row.qty_on_hand);
    els.fCkBatch.value = "";
    els.fCkRef.value = "";
    els.fCkAdj.value = row.ck_adj ?? row.ck_cash ?? "";
    els.fStatus.value =
      activeTab === "to_pack" || activeTab === "need_to_sell"
        ? "planned"
        : activeTab === "to_ship"
          ? "packed"
          : "sent";
    els.fPaidAmount.value = "";
    els.fNotes.value = "";
    try {
      const res = await fetch(`/api/inventory/${id}/fulfillments`);
      if (res.ok) {
        const data = await res.json();
        renderFulfillmentList(data.fulfillments || []);
      }
    } catch {
      renderFulfillmentList([]);
    }
    els.fulfillModal.showModal();
    els.fQty.focus();
  }

  function closeFulfillModal() {
    fulfillingId = null;
    els.fulfillModal?.close();
  }

  async function saveFulfillForm() {
    if (!fulfillingId) return;
    const qty = parseInt(els.fQty.value, 10);
    if (!qty || qty < 1) return;
    const payload = {
      qty,
      ck_batch_id: els.fCkBatch.value.trim() || null,
      ck_ref: els.fCkRef.value.trim() || null,
      ck_adj: els.fCkAdj.value ? parseFloat(els.fCkAdj.value) : null,
      status: els.fStatus.value,
      paid_amount: els.fPaidAmount.value ? parseFloat(els.fPaidAmount.value) : null,
      notes: els.fNotes.value.trim() || null,
    };
    setButtonLoading(els.fulfillSave, true);
    try {
      const res = await fetch(`/api/inventory/${fulfillingId}/fulfillments`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!res.ok) throw new Error(await res.text());
      const row = rowsById.get(fulfillingId);
      showToast(`Sent ${qty}× ${row?.name || "card"} to CK`);
      closeFulfillModal();
      await refreshSummaries();
      load();
    } catch (err) {
      alert(err.message || String(err));
    } finally {
      setButtonLoading(els.fulfillSave, false);
    }
  }

  function massLineTotal(tr) {
    const qty = parseFloat(tr.querySelector(".inv-mass-qty")?.value || "0");
    const ck = parseFloat(tr.querySelector(".inv-mass-ck")?.value || "0");
    if (!qty || Number.isNaN(qty) || Number.isNaN(ck)) return null;
    return qty * ck;
  }

  function updateMassFulfillSummary() {
    if (!els.mfSummary) return;
    const rows = [...(els.mfResults?.querySelectorAll("tr[data-id]") || [])];
    let selected = 0;
    let copies = 0;
    let total = 0;
    rows.forEach((tr) => {
      const checked = tr.querySelector(".inv-mass-check")?.checked;
      if (!checked) return;
      selected += 1;
      const qty = parseInt(tr.querySelector(".inv-mass-qty")?.value || "0", 10);
      const line = massLineTotal(tr);
      if (qty > 0) copies += qty;
      if (line != null) total += line;
      const lineEl = tr.querySelector(".inv-mass-line");
      if (lineEl) lineEl.textContent = line != null ? fmtUsd(line) : "—";
    });
    const parts = [`${selected} card${selected === 1 ? "" : "s"} selected`];
    if (copies) parts.push(`${copies} copies`);
    if (total) parts.push(`${fmtUsd(total)} CK`);
    els.mfSummary.textContent = parts.join(" · ");
  }

  function renderMassFulfillRows(lots, precheckedIds) {
    const checkedSet = new Set(precheckedIds || []);
    els.mfResults.innerHTML = lots
      .map((row) => {
        const checked = checkedSet.has(row.id) ? " checked" : "";
        const qty = defaultFulfillQty(row);
        const ck = row.ck_adj ?? row.ck_cash ?? "";
        return `
          <tr class="inv-mass-row" data-id="${row.id}" data-name="${escapeHtml((row.name || "").toLowerCase())}">
            <td class="opp-check-col">
              <input type="checkbox" class="inv-mass-check" data-id="${row.id}"${checked} aria-label="Include ${escapeHtml(row.name)}" />
            </td>
            <td class="opp-card-cell">
              <div class="opp-card-name">${escapeHtml(row.name)}</div>
              <div class="opp-card-meta">${escapeHtml(cardMeta(row))}</div>
            </td>
            <td class="num">${row.qty_on_hand}</td>
            <td class="num">
              <input type="number" class="inv-mass-qty" data-id="${row.id}" min="1" max="${row.qty_on_hand}" step="1" value="${qty}" />
            </td>
            <td class="num">
              <input type="number" class="inv-mass-ck" data-id="${row.id}" min="0" step="0.01" value="${ck}" />
            </td>
            <td class="num inv-mass-line">—</td>
          </tr>`;
      })
      .join("");
    els.mfResults.querySelectorAll("tr[data-id]").forEach((tr) => {
      const on = tr.querySelector(".inv-mass-check")?.checked;
      tr.classList.toggle("is-disabled", !on);
    });
    updateMassFulfillSummary();
  }

  function filterMassFulfillRows() {
    const q = (els.mfFilter?.value || "").trim().toLowerCase();
    els.mfResults?.querySelectorAll("tr[data-id]").forEach((tr) => {
      const name = tr.dataset.name || "";
      tr.hidden = Boolean(q) && !name.includes(q);
    });
  }

  async function openMassFulfillModal(preferredIds = null) {
    if (!els.massFulfillModal) return;
    const prechecked = preferredIds?.length
      ? preferredIds
      : selected.size
        ? [...selected]
        : [];

    setButtonLoading(els.massFulfillToggle, true);
    setButtonLoading(els.massFulfillSelectedBtn, true);
    try {
      // Always offer full on-hand inventory (not just the active lifecycle tab).
      const params = new URLSearchParams({
        limit: "500",
        sort: "name",
        has_remaining: "true",
      });
      const res = await fetch(`/api/inventory?${params}`);
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      const lots = (data.results || []).filter((row) => (row.qty_on_hand ?? 0) > 0);
      lots.sort((a, b) => String(a.name || "").localeCompare(String(b.name || "")));
      if (!lots.length) {
        alert("No lots with stock on hand to fulfill.");
        return;
      }
      massFulfillLots = lots;
      lots.forEach((row) => rowsById.set(row.id, row));

      els.mfCkRef.value = "";
      els.mfCkBatch.value = "";
      els.mfStatus.value =
        activeTab === "to_ship"
          ? "packed"
          : activeTab === "awaiting_payment"
            ? "sent"
            : "planned";
      els.mfNotes.value = "";
      if (els.mfFilter) els.mfFilter.value = "";

      // Precheck only what the user already selected on the page (if any).
      const checkIds = prechecked.filter((id) => lots.some((r) => r.id === id));
      renderMassFulfillRows(lots, checkIds);
      if (els.mfSelectAll) {
        const visibleBoxes = lots.length;
        els.mfSelectAll.checked = checkIds.length > 0 && checkIds.length === visibleBoxes;
        els.mfSelectAll.indeterminate = checkIds.length > 0 && checkIds.length < visibleBoxes;
      }
      els.massFulfillModal.showModal();
      els.mfCkRef.focus();
    } catch (err) {
      alert(err.message || String(err));
    } finally {
      setButtonLoading(els.massFulfillToggle, false);
      setButtonLoading(els.massFulfillSelectedBtn, false);
    }
  }

  function closeMassFulfillModal() {
    massFulfillLots = [];
    els.massFulfillModal?.close();
  }

  async function saveMassFulfillForm() {
    const ckRef = els.mfCkRef.value.trim();
    const ckBatch = els.mfCkBatch.value.trim();
    if (!ckRef && !ckBatch) {
      alert("Enter a CK order # (or batch label).");
      els.mfCkRef.focus();
      return;
    }
    const items = [];
    els.mfResults.querySelectorAll("tr[data-id]").forEach((tr) => {
      if (!tr.querySelector(".inv-mass-check")?.checked) return;
      const id = parseInt(tr.dataset.id, 10);
      const qty = parseInt(tr.querySelector(".inv-mass-qty")?.value || "0", 10);
      const ckRaw = tr.querySelector(".inv-mass-ck")?.value;
      if (!qty || qty < 1) return;
      items.push({
        inventory_lot_id: id,
        qty,
        ck_adj: ckRaw !== "" && ckRaw != null ? parseFloat(ckRaw) : null,
      });
    });
    if (!items.length) {
      alert("Select at least one card with qty ≥ 1.");
      return;
    }
    const payload = {
      items,
      ck_ref: ckRef || null,
      ck_batch_id: ckBatch || null,
      status: els.mfStatus.value,
      notes: els.mfNotes.value.trim() || null,
    };
    setButtonLoading(els.massFulfillSave, true);
    try {
      const res = await fetch("/api/inventory/fulfillments/batch", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      const n = data.count || data.created?.length || items.length;
      showToast(`Created ${n} CK fulfillment${n === 1 ? "" : "s"}`);
      selected.clear();
      updateSelectionUi();
      closeMassFulfillModal();
      await refreshSummaries();
      load();
    } catch (err) {
      alert(err.message || String(err));
    } finally {
      setButtonLoading(els.massFulfillSave, false);
    }
  }

  els.q.addEventListener("input", scheduleLoad);
  els.seller.addEventListener("input", scheduleLoad);
  els.status?.addEventListener("change", load);
  els.tcgOrderFilter?.addEventListener("change", load);
  els.batchFilter?.addEventListener("change", load);
  els.hasRemaining?.addEventListener("change", load);
  els.unlinkedOnly?.addEventListener("change", load);

  els.tabAll?.addEventListener("click", () => switchTab("all"));
  els.tabInbound?.addEventListener("click", () => switchTab("inbound"));
  els.tabNeedSell?.addEventListener("click", () => switchTab("need_to_sell"));
  els.tabToPack?.addEventListener("click", () => switchTab("to_pack"));
  els.tabToShip?.addEventListener("click", () => switchTab("to_ship"));
  els.tabAwaiting?.addEventListener("click", () => switchTab("awaiting_payment"));
  els.tabPaid?.addEventListener("click", () => switchTab("paid"));

  els.fulfillResults?.addEventListener("click", async (e) => {
    const btn = e.target.closest("[data-action]");
    if (!btn) return;
    const action = btn.dataset.action;
    const lotId = parseInt(btn.dataset.lotId, 10);
    const fulfillmentId = parseInt(btn.dataset.id, 10);
    try {
      if (action === "mark-packed") {
        await setFulfillmentStatus(lotId, fulfillmentId, "packed");
        showToast("Moved to Need to Ship");
      } else if (action === "mark-shipped") {
        await setFulfillmentStatus(lotId, fulfillmentId, "sent");
        showToast("Moved to Awaiting payment");
      } else if (action === "mark-paid") {
        await markFulfillmentPaid(lotId, fulfillmentId);
        showToast("Marked paid");
      } else {
        return;
      }
      await refreshSummaries();
      load();
    } catch (err) {
      alert(err.message || String(err));
    }
  });

  els.fulfillResults?.addEventListener("change", async (e) => {
    const sel = e.target.closest(".inv-fulfill-status");
    if (!sel) return;
    const lotId = parseInt(sel.dataset.lotId, 10);
    const fulfillmentId = parseInt(sel.dataset.id, 10);
    const status = sel.value;
    const prev = fulfillRowsById.get(fulfillmentId)?.fulfillment_status;
    try {
      await setFulfillmentStatus(lotId, fulfillmentId, status);
      const label = FULFILL_STATUS_OPTIONS.find((o) => o.value === status)?.label || status;
      showToast(`Moved to ${label}`);
      await refreshSummaries();
      load();
    } catch (err) {
      if (prev) sel.value = prev;
      alert(err.message || String(err));
    }
  });

  els.selectAll?.addEventListener("change", () => {
    const boxes = els.results.querySelectorAll(".inv-row-check");
    boxes.forEach((b) => {
      b.checked = els.selectAll.checked;
      const id = parseInt(b.dataset.id, 10);
      if (els.selectAll.checked) selected.add(id);
      else selected.delete(id);
    });
    updateSelectionUi();
  });

  els.clearSelectBtn.addEventListener("click", () => {
    selected.clear();
    load();
  });

  els.applyLinkBtn.addEventListener("click", async () => {
    const ids = [...selected];
    if (!ids.length) return;
    const tcgOrder = els.bulkTcgOrder.value.trim();
    if (!tcgOrder) {
      alert("Enter a TCG order #.");
      return;
    }
    try {
      const data = await batchLink(ids, { tcg_order_id: tcgOrder, status: "ordered" });
      showToast(`Updated ${data.count} lot${data.count === 1 ? "" : "s"}`);
      selected.clear();
      await refreshSummaries();
      load();
    } catch (err) {
      alert(err.message || String(err));
    }
  });

  els.removeSelectedBtn?.addEventListener("click", async () => {
    const ids = [...selected];
    if (!ids.length) return;
    if (!confirm(`Remove ${ids.length} lot${ids.length === 1 ? "" : "s"} from inventory?`)) return;
    try {
      const data = await batchDelete(ids);
      showToast(`Removed ${data.count} lot${data.count === 1 ? "" : "s"}`);
      ids.forEach((id) => selected.delete(id));
      await refreshSummaries();
      load();
    } catch (err) {
      alert(err.message || String(err));
    }
  });

  els.results.addEventListener("click", async (e) => {
    const fulfillBtn = e.target.closest(".inv-fulfill-btn");
    if (fulfillBtn) {
      openFulfillModal(parseInt(fulfillBtn.dataset.id, 10));
      return;
    }
    const editBtn = e.target.closest(".pur-edit-btn:not(.inv-fulfill-btn)");
    if (editBtn) {
      openEditModal(parseInt(editBtn.dataset.id, 10));
      return;
    }
    const btn = e.target.closest(".pur-remove-btn");
    if (!btn) return;
    const id = parseInt(btn.dataset.id, 10);
    const name = btn.dataset.name || "this lot";
    if (!confirm(`Remove "${name}" from inventory?`)) return;
    try {
      await deleteLot(id);
      selected.delete(id);
      showToast(`Removed ${name}`);
      await refreshSummaries();
      load();
    } catch (err) {
      alert(err.message || String(err));
    }
  });

  els.results.addEventListener("change", async (e) => {
    const rowCheck = e.target.closest(".inv-row-check");
    if (rowCheck) {
      const id = parseInt(rowCheck.dataset.id, 10);
      if (rowCheck.checked) selected.add(id);
      else selected.delete(id);
      updateSelectionUi();
      return;
    }
    const statusSel = e.target.closest(".pur-status-select");
    if (statusSel) {
      try {
        await patchLot(statusSel.dataset.id, { status: statusSel.value });
      } catch (err) {
        alert(err.message || String(err));
        load();
      }
    }
  });

  els.results.addEventListener("blur", async (e) => {
    const linkInputEl = e.target.closest(".pur-tcg-input");
    if (!linkInputEl) return;
    try {
      await patchLot(linkInputEl.dataset.id, { tcg_order_id: linkInputEl.value.trim() || null });
      refreshSummaries();
    } catch (err) {
      alert(err.message || String(err));
      load();
    }
  }, true);

  function clearManualForm() {
    els.manualForm.reset();
    els.mQty.value = "1";
    if (els.mOrderedAt) els.mOrderedAt.value = new Date().toISOString().slice(0, 10);
  }

  function toggleManualPanel() {
    const open = els.manualPanel.hidden;
    els.manualPanel.hidden = !open;
    els.manualToggle.setAttribute("aria-expanded", String(open));
    els.manualToggle.classList.toggle("is-active", open);
    if (open) els.mName.focus();
  }

  els.manualToggle?.addEventListener("click", toggleManualPanel);
  els.manualClear?.addEventListener("click", clearManualForm);

  els.editClose?.addEventListener("click", closeEditModal);
  els.editCancel?.addEventListener("click", closeEditModal);
  els.editModal?.addEventListener("cancel", (e) => {
    e.preventDefault();
    closeEditModal();
  });
  els.eQtyOriginal?.addEventListener("input", () => {
    const bought = parseInt(els.eQtyOriginal.value, 10);
    if (!bought || bought < 1) return;
    const prevBought = parseInt(els.eQtyOriginal.dataset.prev || "", 10);
    const onHand = parseInt(els.eQtyOnHand.value, 10);
    // Keep on-hand aligned when correcting a full buy (opportunity qty was wrong).
    if (!Number.isNaN(onHand) && (onHand === prevBought || onHand > bought)) {
      els.eQtyOnHand.value = String(bought);
    }
    const expected = parseInt(els.eExpectedCkQty.value, 10);
    if (!Number.isNaN(expected) && (expected === prevBought || expected > bought)) {
      els.eExpectedCkQty.value = String(bought);
    }
    els.eQtyOriginal.dataset.prev = String(bought);
  });
  els.editForm?.addEventListener("submit", async (e) => {
    e.preventDefault();
    await saveEditForm();
  });

  els.fulfillClose?.addEventListener("click", closeFulfillModal);
  els.fulfillCancel?.addEventListener("click", closeFulfillModal);
  els.fulfillModal?.addEventListener("cancel", (e) => {
    e.preventDefault();
    closeFulfillModal();
  });
  els.fulfillForm?.addEventListener("submit", async (e) => {
    e.preventDefault();
    await saveFulfillForm();
  });

  els.massFulfillToggle?.addEventListener("click", () => openMassFulfillModal());
  els.massFulfillSelectedBtn?.addEventListener("click", () => openMassFulfillModal([...selected]));
  els.massFulfillClose?.addEventListener("click", closeMassFulfillModal);
  els.massFulfillCancel?.addEventListener("click", closeMassFulfillModal);
  els.massFulfillModal?.addEventListener("cancel", (e) => {
    e.preventDefault();
    closeMassFulfillModal();
  });
  els.massFulfillForm?.addEventListener("submit", async (e) => {
    e.preventDefault();
    await saveMassFulfillForm();
  });
  els.mfFilter?.addEventListener("input", filterMassFulfillRows);
  els.mfSelectAll?.addEventListener("change", () => {
    const on = els.mfSelectAll.checked;
    els.mfResults?.querySelectorAll("tr[data-id]").forEach((tr) => {
      if (tr.hidden) return;
      const box = tr.querySelector(".inv-mass-check");
      if (box) box.checked = on;
      tr.classList.toggle("is-disabled", !on);
    });
    updateMassFulfillSummary();
  });
  els.mfResults?.addEventListener("change", (e) => {
    const check = e.target.closest(".inv-mass-check");
    if (check) {
      const tr = check.closest("tr");
      tr?.classList.toggle("is-disabled", !check.checked);
    }
    if (e.target.closest(".inv-mass-check, .inv-mass-qty, .inv-mass-ck")) {
      const boxes = [...(els.mfResults?.querySelectorAll("tr[data-id]:not([hidden]) .inv-mass-check") || [])];
      const checked = boxes.filter((b) => b.checked).length;
      if (els.mfSelectAll) {
        els.mfSelectAll.checked = boxes.length > 0 && checked === boxes.length;
        els.mfSelectAll.indeterminate = checked > 0 && checked < boxes.length;
      }
      updateMassFulfillSummary();
    }
  });
  els.mfResults?.addEventListener("input", (e) => {
    if (e.target.closest(".inv-mass-qty, .inv-mass-ck")) updateMassFulfillSummary();
  });

  els.manualForm?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const payload = {
      name: els.mName.value.trim(),
      seller: els.mSeller.value.trim(),
      seller_price: parseFloat(els.mSellerPrice.value),
      qty: parseInt(els.mQty.value, 10) || 1,
      set_name: els.mSet.value.trim() || null,
      condition: els.mCondition.value,
      finish: els.mFinish.value,
      shipping_price: els.mShipping.value ? parseFloat(els.mShipping.value) : null,
      ck_cash: els.mCkCash.value ? parseFloat(els.mCkCash.value) : null,
      ck_max_qty: els.mCkMax.value ? parseInt(els.mCkMax.value, 10) : null,
      tcg_url: els.mTcgUrl.value.trim() || null,
      tcg_order_id: els.mTcgOrder.value.trim() || null,
      ordered_at: els.mOrderedAt?.value || null,
      notes: els.mNotes.value.trim() || null,
      status: els.mTcgOrder.value.trim() ? "ordered" : "on_hand",
    };
    setButtonLoading(els.manualSubmit, true);
    try {
      const res = await fetch("/api/inventory/manual", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!res.ok) throw new Error(await res.text());
      showToast(`Added ${payload.name}`);
      clearManualForm();
      els.manualPanel.hidden = true;
      els.manualToggle.classList.remove("is-active");
      els.manualToggle.setAttribute("aria-expanded", "false");
      await refreshSummaries();
      load();
    } catch (err) {
      let msg = err.message || String(err);
      try {
        const parsed = JSON.parse(msg);
        if (parsed.detail) msg = typeof parsed.detail === "string" ? parsed.detail : JSON.stringify(parsed.detail);
      } catch {
        /* keep raw */
      }
      alert(msg);
    } finally {
      setButtonLoading(els.manualSubmit, false);
    }
  });

  refreshSummaries();
  switchTab("all");
})();
