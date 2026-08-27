/** Inventory lots + CK fulfillments — lifecycle tabs */
(function () {
  const STATUS_OPTIONS = [
    { value: "ordered", label: "Ordered" },
    { value: "inbound", label: "Inbound" },
    { value: "on_hand", label: "On hand" },
    { value: "problem", label: "Problem" },
    { value: "depleted", label: "Depleted" },
    { value: "cancelled", label: "Cancelled" },
  ];

  const TAB_NOTES = {
    all: "All inventory lots — free stock only counts as on hand; pack/ship/paid lines live in their own tabs.",
    orders: "Card Kingdom sell orders grouped by CK order #. Status is the furthest-behind pipeline stage. Changing status updates every line on that CK order.",
    inbound: "Waiting on TCG sellers — follow up if an order is late.",
    need_to_sell: "Free stock with a current CK buy price (or ordered/inbound 5+ days) — hidden once reserved for pack/ship or fulfilled today.",
    problem: "Wrong copies, disputes, or anything waiting on TCG/seller resolution — still inventory, but not sellable to CK.",
    to_pack: "Reserved for CK — no longer on-hand. Mark Packed when sleeved/boxed.",
    to_ship: "Packed and ready to mail — mark Sent when the package goes out.",
    awaiting_payment: "Sent to CK — move back to Packed/Need to pack if needed, or Mark paid when CK pays.",
    paid: "Completed CK payouts — edit CK paid $ on each row (blur to save). Profit uses that amount.",
  };

  const LOT_TABS = new Set(["all", "inbound", "need_to_sell", "problem"]);
  const LIFECYCLE_LOT_TABS = new Set(["inbound", "need_to_sell", "problem"]);
  const FULFILL_TABS = new Set(["to_pack", "to_ship", "awaiting_payment", "paid"]);
  const ORDER_TAB = "orders";
  const NEED_TO_SELL_DAYS = 5;
  const FULFILL_STATUS_OPTIONS = [
    { value: "planned", label: "Need to pack" },
    { value: "packed", label: "Need to ship" },
    { value: "sent", label: "Sent / awaiting pay" },
    { value: "paid", label: "Paid" },
  ];
  const ORDER_STATUS_OPTIONS = [
    { value: "planned", label: "Need to pack" },
    { value: "packed", label: "Need to ship" },
    { value: "sent", label: "Sent / awaiting pay" },
    { value: "paid", label: "Paid" },
  ];
  const ORDER_STATUS_LABELS = Object.fromEntries(
    ORDER_STATUS_OPTIONS.map((o) => [o.value, o.label])
  );
  const CK_GRADE_MULT = { nm: 1, ex: 0.75, vg: 0.5, g: 0.25 };
  let ordersById = new Map();
  let ordersList = [];
  /** null = API order; asc = oldest first; desc = newest first */
  let ordersPlacedSortDir = null;
  let payingOrderId = null;
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
    tabOrders: document.getElementById("tabOrders"),
    tabInbound: document.getElementById("tabInbound"),
    tabNeedSell: document.getElementById("tabNeedSell"),
    tabProblem: document.getElementById("tabProblem"),
    tabToPack: document.getElementById("tabToPack"),
    tabToShip: document.getElementById("tabToShip"),
    tabAwaiting: document.getElementById("tabAwaiting"),
    tabPaid: document.getElementById("tabPaid"),
    q: document.getElementById("q"),
    status: document.getElementById("status"),
    orderStatusFilter: document.getElementById("orderStatusFilter"),
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
    ordersResults: document.getElementById("ordersResults"),
    lotsTable: document.getElementById("lotsTable"),
    fulfillTable: document.getElementById("fulfillTable"),
    ordersTable: document.getElementById("ordersTable"),
    orderPaidModal: document.getElementById("orderPaidModal"),
    orderPaidForm: document.getElementById("orderPaidForm"),
    orderPaidClose: document.getElementById("orderPaidClose"),
    orderPaidCancel: document.getElementById("orderPaidCancel"),
    orderPaidSave: document.getElementById("orderPaidSave"),
    orderPaidTitle: document.getElementById("orderPaidTitle"),
    orderPaidSub: document.getElementById("orderPaidSub"),
    orderPaidBody: document.getElementById("orderPaidBody"),
    orderPaidSummary: document.getElementById("orderPaidSummary"),
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
    const canFulfill = (row.qty_on_hand ?? 0) > 0 && row.status !== "problem" && row.status !== "cancelled";
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

  /** Calendar days since placed (local). CK ship window is 7 days. */
  const CK_SHIP_DAYS = 7;

  function daysSincePlaced(iso) {
    if (!iso) return null;
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return null;
    const start = new Date(d.getFullYear(), d.getMonth(), d.getDate());
    const now = new Date();
    const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    return Math.floor((today - start) / 86400000);
  }

  function orderNeedsShip(status) {
    return status === "planned" || status === "packed";
  }

  const EMPTY_MESSAGES = {
    all: 'No inventory yet. Buy from <a href="/opportunities">Opportunities</a> or use <strong>Manual entry</strong>.',
    orders: "No CK orders yet — mass fulfill from Need to Sell with a CK order # / batch, then they show up here.",
    inbound: 'No inbound orders. Add buys from <a href="/opportunities">Opportunities</a> and set status to Ordered or Inbound.',
    to_pack: "No CK orders waiting to pack — Mass fulfill from Need to Sell as Need to pack.",
    to_ship: "Nothing packed awaiting shipment — mark rows Packed from Need to Pack.",
    need_to_sell: "Nothing in the sell queue — need On hand stock (any order date) or ordered/inbound 5+ days old, plus a current CK buy price and no CK fulfillment dated today.",
    problem: "No problem lots — set status to Problem when you get the wrong card or are waiting on a TCG/seller resolution.",
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

  function isOrdersTab() {
    return activeTab === ORDER_TAB;
  }

  function isLifecycleLotTab() {
    return LIFECYCLE_LOT_TABS.has(activeTab);
  }

  function tabButtons() {
    return [
      els.tabAll,
      els.tabOrders,
      els.tabInbound,
      els.tabNeedSell,
      els.tabProblem,
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
    const revHead = document.getElementById("fulfillRevenueHead");
    if (revHead) revHead.textContent = tab === "paid" ? "CK paid $" : "Revenue";
    const lotMode = isLotTab();
    const ordersMode = isOrdersTab();
    const fulfillMode = FULFILL_TABS.has(tab);
    els.lotsTable.hidden = !lotMode;
    els.fulfillTable.hidden = !fulfillMode;
    if (els.ordersTable) els.ordersTable.hidden = !ordersMode;
    els.linkBar.hidden = true;
    if (els.selectAll) els.selectAll.closest("th")?.classList.toggle("hidden-col", !lotMode);
    document.querySelectorAll(".inv-advanced-filter").forEach((el) => {
      el.hidden = activeTab !== "all";
    });
    document.querySelectorAll(".inv-orders-filter").forEach((el) => {
      el.hidden = !ordersMode;
    });
    // Orders tab: keep search, hide lot-only filters
    if (els.tcgOrderFilter) els.tcgOrderFilter.hidden = ordersMode;
    if (els.batchFilter) els.batchFilter.hidden = ordersMode;
    if (els.seller) els.seller.hidden = ordersMode;
    if (els.q) {
      els.q.placeholder = ordersMode ? "Search CK order # or card…" : "Search cards…";
    }
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
      problem: summary.problem,
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
    const canUndo = activeTab === "to_pack" || activeTab === "to_ship" || activeTab === "awaiting_payment";
    const undoBtns = canUndo
      ? `<button type="button" class="secondary opp-btn-ghost inv-fulfill-remove" data-action="remove-line" data-lot-id="${row.lot_id}" data-id="${row.fulfillment_id}" data-name="${escapeHtml(row.name)}" title="Remove this CK line — copies return to free inventory">Remove line</button>
          <button type="button" class="secondary pur-btn-danger inv-fulfill-cancel-buy" data-action="cancel-buy" data-lot-id="${row.lot_id}" data-id="${row.fulfillment_id}" data-name="${escapeHtml(row.name)}" title="TCG buy canceled — delete the lot and this CK line">Cancel buy</button>`
      : "";
    const paidDisplay =
      row.paid_amount != null ? row.paid_amount : row.fulfillment_revenue;
    const revenueCell =
      activeTab === "paid"
        ? `<td class="num">
            <input type="number" class="pur-link-input inv-paid-amount" step="0.01" min="0"
              data-lot-id="${row.lot_id}" data-id="${row.fulfillment_id}"
              value="${paidDisplay ?? ""}"
              title="CK paid amount for this line — edit anytime"
              aria-label="CK paid amount for ${escapeHtml(row.name)}" />
          </td>`
        : `<td class="num">${fmtUsd(row.fulfillment_revenue)}</td>`;
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
        ${revenueCell}
        <td class="num">${fmtUsd(row.fulfillment_cost)}</td>
        <td class="num ${profitClass}">${fmtUsd(row.fulfillment_profit)}</td>
        <td>${fmtDate(dateVal)}</td>
        <td>${fulfillStatusSelect(row)}</td>
        <td>${escapeHtml(row.tcg_order_id || "—")}</td>
        <td class="opp-actions inv-fulfill-actions">
          ${advanceBtn}
          ${undoBtns}
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

  async function deleteFulfillment(lotId, fulfillmentId) {
    const res = await fetch(`/api/inventory/${lotId}/fulfillments/${fulfillmentId}`, {
      method: "DELETE",
    });
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
    if (isOrdersTab()) {
      await loadOrders();
      return;
    }
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
            : activeTab === "problem"
              ? "problem / awaiting resolution"
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

  function orderStatusSelect(row) {
    const current = row.status || "planned";
    const options = ORDER_STATUS_OPTIONS.map(
      (o) =>
        `<option value="${o.value}" ${o.value === current ? "selected" : ""}>${escapeHtml(o.label)}</option>`
    ).join("");
    return `<select class="pur-status-select inv-order-status" data-order="${escapeHtml(row.ck_order_id)}" data-prev="${escapeHtml(current)}" aria-label="Status for CK order ${escapeHtml(row.ck_order_id)}">${options}</select>`;
  }

  function pipelineBits(row) {
    const bits = [];
    if (row.qty_planned) bits.push(`${row.qty_planned} pack`);
    if (row.qty_packed) bits.push(`${row.qty_packed} ship`);
    if (row.qty_sent) bits.push(`${row.qty_sent} sent`);
    if (row.qty_paid) bits.push(`${row.qty_paid} paid`);
    return bits.length ? bits.join(" · ") : "—";
  }

  function renderOrderRow(row) {
    const lines = row.lines || [];
    const statusLabel = ORDER_STATUS_LABELS[row.status] || row.status || "—";
    const cardsList = lines.length
      ? `<details class="inv-order-cards">
          <summary>${lines.length} line${lines.length === 1 ? "" : "s"} · ${row.qty_total} cards</summary>
          <ul class="inv-order-card-list">
            ${lines
              .map((l) => {
                const st = ORDER_STATUS_LABELS[l.status] || l.status || "";
                return `<li>
                  <span class="inv-order-card-name">${escapeHtml(l.name)}</span>
                  <span class="inv-order-card-meta">${l.qty}×${st ? ` · ${escapeHtml(st)}` : ""}</span>
                </li>`;
              })
              .join("")}
          </ul>
        </details>`
      : `<span class="inv-qty-sub">No lines</span>`;
    const canMarkPaid = row.status !== "paid" && lines.length > 0;
    const paidBtn = canMarkPaid
      ? `<button type="button" class="secondary inv-order-paid-btn" data-order="${escapeHtml(row.ck_order_id)}">Mark paid</button>`
      : "";
    const days = daysSincePlaced(row.created_at);
    const late = days != null && days >= CK_SHIP_DAYS && orderNeedsShip(row.status);
    const placedClass = late ? "inv-order-placed is-late" : "inv-order-placed";
    const daysLabel =
      days == null
        ? ""
        : `<div class="inv-qty-sub${late ? " is-late" : ""}">${days} day${days === 1 ? "" : "s"} ago${
            late ? " · ship overdue" : ""
          }</div>`;
    return `
      <tr class="inv-order-row" data-order="${escapeHtml(row.ck_order_id)}">
        <td>
          <div class="inv-order-id">${escapeHtml(row.ck_order_id)}</div>
          ${cardsList}
        </td>
        <td>${escapeHtml(row.ck_batch_id || "—")}</td>
        <td class="num">${row.line_count}</td>
        <td class="num">${row.qty_total}</td>
        <td>
          <div>${escapeHtml(statusLabel)}</div>
          <div class="inv-qty-sub">${escapeHtml(pipelineBits(row))}</div>
        </td>
        <td data-sort="${row.created_at ? new Date(row.created_at).getTime() : 0}">
          <div class="${placedClass}">${fmtDate(row.created_at)}</div>
          ${daysLabel}
        </td>
        <td>${orderStatusSelect(row)}</td>
        <td class="opp-actions">${paidBtn}</td>
      </tr>`;
  }

  function parseMoneyInput(el, fallback = 0) {
    const raw = parseFloat(el?.value);
    return Number.isFinite(raw) && raw >= 0 ? raw : fallback;
  }

  function linePaidFromUnits(nm, ex, vg, g, nmUnit, exUnit, vgUnit, gUnit) {
    return nm * nmUnit + ex * exUnit + vg * vgUnit + g * gUnit;
  }

  function readPaidGradeRow(tr) {
    const qty = parseInt(tr.dataset.qty, 10) || 0;
    const locked = parseFloat(tr.dataset.ckAdj);
    const base = Number.isFinite(locked) && locked >= 0 ? locked : 0;
    const nm = parseInt(tr.querySelector(".op-nm")?.value, 10) || 0;
    const ex = parseInt(tr.querySelector(".op-ex")?.value, 10) || 0;
    const vg = parseInt(tr.querySelector(".op-vg")?.value, 10) || 0;
    const g = parseInt(tr.querySelector(".op-g")?.value, 10) || 0;
    const nmUnit = parseMoneyInput(tr.querySelector(".op-nm-unit"), base * CK_GRADE_MULT.nm);
    const exUnit = parseMoneyInput(tr.querySelector(".op-ex-unit"), base * CK_GRADE_MULT.ex);
    const vgUnit = parseMoneyInput(tr.querySelector(".op-vg-unit"), base * CK_GRADE_MULT.vg);
    const gUnit = parseMoneyInput(tr.querySelector(".op-g-unit"), base * CK_GRADE_MULT.g);
    return {
      fulfillment_id: parseInt(tr.dataset.fulfillmentId, 10),
      qty,
      ckAdj: nmUnit,
      nm,
      ex,
      vg,
      g,
      nmUnit,
      exUnit,
      vgUnit,
      gUnit,
      sum: nm + ex + vg + g,
      paid: linePaidFromUnits(nm, ex, vg, g, nmUnit, exUnit, vgUnit, gUnit),
    };
  }

  function syncPaidGradesFromLower(tr, changedEl) {
    /** When EX/VG/G change, NM becomes the residual so the line still sums to qty. */
    const qty = parseInt(tr.dataset.qty, 10) || 0;
    const nmEl = tr.querySelector(".op-nm");
    const exEl = tr.querySelector(".op-ex");
    const vgEl = tr.querySelector(".op-vg");
    const gEl = tr.querySelector(".op-g");
    if (!nmEl || !exEl || !vgEl || !gEl) return;

    let ex = Math.max(0, parseInt(exEl.value, 10) || 0);
    let vg = Math.max(0, parseInt(vgEl.value, 10) || 0);
    let g = Math.max(0, parseInt(gEl.value, 10) || 0);

    const changed = changedEl?.classList;
    if (changed?.contains("op-ex")) {
      ex = Math.min(ex, Math.max(0, qty - vg - g));
      exEl.value = String(ex);
    } else if (changed?.contains("op-vg")) {
      vg = Math.min(vg, Math.max(0, qty - ex - g));
      vgEl.value = String(vg);
    } else if (changed?.contains("op-g")) {
      g = Math.min(g, Math.max(0, qty - ex - vg));
      gEl.value = String(g);
    } else {
      exEl.value = String(ex);
      vgEl.value = String(vg);
      gEl.value = String(g);
    }

    nmEl.value = String(Math.max(0, qty - ex - vg - g));
  }

  function updateOrderPaidSummary() {
    if (!els.orderPaidBody || !els.orderPaidSummary) return;
    const rows = [...els.orderPaidBody.querySelectorAll("tr[data-fulfillment-id]")];
    let expected = 0;
    let graded = 0;
    let ok = true;
    rows.forEach((tr) => {
      const r = readPaidGradeRow(tr);
      expected += r.qty * r.nmUnit;
      graded += r.paid;
      const paidCell = tr.querySelector(".op-paid");
      if (paidCell) paidCell.textContent = fmtUsd(r.paid);
      tr.classList.toggle("is-invalid", r.sum !== r.qty);
      if (r.sum !== r.qty) ok = false;
    });
    const delta = graded - expected;
    const deltaLabel =
      Math.abs(delta) < 0.005 ? "even" : `${delta > 0 ? "+" : ""}${fmtUsd(delta)} vs all-NM`;
    els.orderPaidSummary.textContent = `All-NM ${fmtUsd(expected)} · Graded paid ${fmtUsd(graded)} · ${deltaLabel}`;
    if (els.orderPaidSave) els.orderPaidSave.disabled = !ok || rows.length === 0;
  }

  function openOrderPaidModal(orderId) {
    const order = ordersById.get(orderId);
    if (!order || !els.orderPaidModal) return;
    payingOrderId = orderId;
    if (els.orderPaidTitle) els.orderPaidTitle.textContent = `Mark paid — CK ${orderId}`;
    const lines = order.lines || [];
    if (els.orderPaidBody) {
      els.orderPaidBody.innerHTML = lines
        .map((l) => {
          const ck = l.ck_adj != null ? Number(l.ck_adj) : 0;
          const qty = Number(l.qty) || 0;
          const nmU = (ck * CK_GRADE_MULT.nm).toFixed(2);
          const exU = (ck * CK_GRADE_MULT.ex).toFixed(2);
          const vgU = (ck * CK_GRADE_MULT.vg).toFixed(2);
          const gU = (ck * CK_GRADE_MULT.g).toFixed(2);
          return `<tr data-fulfillment-id="${l.fulfillment_id}" data-qty="${qty}" data-ck-adj="${ck}">
            <td>${escapeHtml(l.name)}</td>
            <td class="num">${qty}</td>
            <td class="num"><input type="number" class="op-nm" min="0" step="1" value="${qty}" aria-label="NM qty for ${escapeHtml(l.name)}" /></td>
            <td class="num"><input type="number" class="op-nm-unit" min="0" step="0.01" value="${nmU}" aria-label="NM unit $ for ${escapeHtml(l.name)}" /></td>
            <td class="num"><input type="number" class="op-ex" min="0" step="1" value="0" aria-label="EX qty for ${escapeHtml(l.name)}" /></td>
            <td class="num"><input type="number" class="op-ex-unit" min="0" step="0.01" value="${exU}" aria-label="EX unit $ for ${escapeHtml(l.name)}" /></td>
            <td class="num"><input type="number" class="op-vg" min="0" step="1" value="0" aria-label="VG qty for ${escapeHtml(l.name)}" /></td>
            <td class="num"><input type="number" class="op-vg-unit" min="0" step="0.01" value="${vgU}" aria-label="VG unit $ for ${escapeHtml(l.name)}" /></td>
            <td class="num"><input type="number" class="op-g" min="0" step="1" value="0" aria-label="G qty for ${escapeHtml(l.name)}" /></td>
            <td class="num"><input type="number" class="op-g-unit" min="0" step="0.01" value="${gU}" aria-label="G unit $ for ${escapeHtml(l.name)}" /></td>
            <td class="num op-paid">${fmtUsd(qty * ck)}</td>
          </tr>`;
        })
        .join("");
    }
    updateOrderPaidSummary();
    els.orderPaidModal.showModal();
  }

  function closeOrderPaidModal() {
    payingOrderId = null;
    els.orderPaidModal?.close();
  }

  async function submitOrderPaid() {
    if (!payingOrderId || !els.orderPaidBody) return;
    const rows = [...els.orderPaidBody.querySelectorAll("tr[data-fulfillment-id]")].map(readPaidGradeRow);
    for (const r of rows) {
      if (r.sum !== r.qty) {
        throw new Error(`Each card's NM+EX+VG+G must equal its qty (${r.qty}).`);
      }
    }
    const payload = {
      ck_order_id: payingOrderId,
      lines: rows.map((r) => ({
        fulfillment_id: r.fulfillment_id,
        nm: r.nm,
        ex: r.ex,
        vg: r.vg,
        g: r.g,
        nm_unit: Math.round(r.nmUnit * 100) / 100,
        ex_unit: Math.round(r.exUnit * 100) / 100,
        vg_unit: Math.round(r.vgUnit * 100) / 100,
        g_unit: Math.round(r.gUnit * 100) / 100,
        ck_adj: Math.round(r.nmUnit * 100) / 100,
      })),
    };
    const res = await fetch("/api/inventory/orders/mark-paid", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      let msg = await res.text();
      try {
        const parsed = JSON.parse(msg);
        if (parsed.detail) msg = typeof parsed.detail === "string" ? parsed.detail : JSON.stringify(parsed.detail);
      } catch {
        /* keep */
      }
      throw new Error(msg);
    }
    return res.json();
  }

  async function loadOrders() {
    setStatusLoading(els.statusMsg, true, "Loading CK orders…");
    try {
      const params = new URLSearchParams();
      if (els.q?.value.trim()) params.set("q", els.q.value.trim());
      const statusFilter = els.orderStatusFilter?.value || "";
      if (statusFilter) params.set("status", statusFilter);
      const res = await fetch(`/api/inventory/orders?${params}`);
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      ordersList = data.results || [];
      renderOrdersTable(ordersList);
      els.tableWrap.hidden = ordersList.length === 0;
      els.emptyState.hidden = ordersList.length !== 0;
      const statusLabel = statusFilter
        ? ORDER_STATUS_LABELS[statusFilter] || statusFilter
        : null;
      els.resultSummary.textContent = statusLabel
        ? `${(data.total || 0).toLocaleString()} CK order${data.total === 1 ? "" : "s"} · ${statusLabel}`
        : `${(data.total || 0).toLocaleString()} CK order${data.total === 1 ? "" : "s"}`;
      els.meta.textContent = ordersList.length
        ? `${ordersList.length} CK orders · change status to update every line on that order`
        : statusLabel
          ? `No CK orders in ${statusLabel}`
          : "Card Kingdom sell orders by order number";
      setStatusLoading(els.statusMsg, false);
    } catch (err) {
      els.statusMsg.textContent = err.message || String(err);
      els.statusMsg.className = "opp-status error";
    }
  }

  function sortOrdersByPlaced(rows) {
    if (!ordersPlacedSortDir) return rows;
    const dir = ordersPlacedSortDir === "asc" ? 1 : -1;
    return [...rows].sort((a, b) => {
      const ta = a.created_at ? new Date(a.created_at).getTime() : 0;
      const tb = b.created_at ? new Date(b.created_at).getTime() : 0;
      if (ta !== tb) return (ta - tb) * dir;
      return String(a.ck_order_id || "").localeCompare(String(b.ck_order_id || ""));
    });
  }

  function updateOrdersPlacedSortHeader() {
    const th = els.ordersTable?.querySelector("th[data-sort-col='placed']");
    if (!th) return;
    th.classList.remove("sort-asc", "sort-desc");
    if (ordersPlacedSortDir === "asc") {
      th.classList.add("sort-asc");
      th.dataset.sortDir = "asc";
      th.setAttribute("aria-sort", "ascending");
    } else if (ordersPlacedSortDir === "desc") {
      th.classList.add("sort-desc");
      th.dataset.sortDir = "desc";
      th.setAttribute("aria-sort", "descending");
    } else {
      th.dataset.sortDir = "asc";
      th.setAttribute("aria-sort", "none");
    }
  }

  function renderOrdersTable(rows) {
    const sorted = sortOrdersByPlaced(rows);
    ordersById = new Map(sorted.map((r) => [r.ck_order_id, r]));
    if (els.ordersResults) {
      els.ordersResults.innerHTML = sorted.map(renderOrderRow).join("");
      animateTableRows(els.ordersResults);
    }
    updateOrdersPlacedSortHeader();
  }

  function toggleOrdersPlacedSort() {
    // First click → oldest first (overdue ships up); then toggle.
    if (ordersPlacedSortDir == null) ordersPlacedSortDir = "asc";
    else if (ordersPlacedSortDir === "asc") ordersPlacedSortDir = "desc";
    else ordersPlacedSortDir = "asc";
    renderOrdersTable(ordersList);
  }

  async function setOrderStatus(ckOrderId, status) {
    const res = await fetch("/api/inventory/orders", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ck_order_id: ckOrderId, status }),
    });
    if (!res.ok) {
      let msg = await res.text();
      try {
        const parsed = JSON.parse(msg);
        if (parsed.detail) msg = typeof parsed.detail === "string" ? parsed.detail : JSON.stringify(parsed.detail);
      } catch {
        /* keep */
      }
      throw new Error(msg);
    }
    return res.json();
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

  async function patchFulfillmentPaidAmount(lotId, fulfillmentId, rawValue) {
    const trimmed = String(rawValue ?? "").trim();
    let paid_amount = null;
    if (trimmed !== "") {
      const amount = parseFloat(trimmed);
      if (Number.isNaN(amount) || amount < 0) {
        throw new Error("Paid amount must be a number ≥ 0");
      }
      paid_amount = amount;
    }
    const res = await fetch(`/api/inventory/${lotId}/fulfillments/${fulfillmentId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ paid_amount }),
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

  function conditionSelectValue(row) {
    const known = [
      "Near Mint",
      "Lightly Played",
      "Moderately Played",
      "Heavily Played",
      "Damaged",
    ];
    const raw = String(row.condition_raw || "").trim();
    if (known.includes(raw)) return raw;
    const display = String(row.condition_display || "").trim();
    for (const k of known) {
      if (display === k || display.startsWith(`${k} `) || display.startsWith(`${k}(`)) {
        return k;
      }
    }
    const hay = `${raw} ${display}`.toLowerCase();
    for (const k of known) {
      if (hay.includes(k.toLowerCase())) return k;
    }
    return "Near Mint";
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
    els.eCondition.value = conditionSelectValue(row);
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
      const lots = (data.results || []).filter(
        (row) =>
          (row.qty_on_hand ?? 0) > 0 &&
          row.status !== "problem" &&
          row.status !== "cancelled"
      );
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
  els.orderStatusFilter?.addEventListener("change", load);
  els.tcgOrderFilter?.addEventListener("change", load);
  els.batchFilter?.addEventListener("change", load);
  els.hasRemaining?.addEventListener("change", load);
  els.unlinkedOnly?.addEventListener("change", load);

  els.tabAll?.addEventListener("click", () => switchTab("all"));
  els.tabOrders?.addEventListener("click", () => switchTab("orders"));
  els.tabInbound?.addEventListener("click", () => switchTab("inbound"));
  els.tabNeedSell?.addEventListener("click", () => switchTab("need_to_sell"));
  els.tabProblem?.addEventListener("click", () => switchTab("problem"));
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
    const name = btn.dataset.name || "this card";
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
      } else if (action === "remove-line") {
        if (
          !confirm(
            `Remove "${name}" from this CK queue?\n\nCopies return to free inventory (Need to Sell / On hand). The inventory lot stays.`
          )
        ) {
          return;
        }
        await deleteFulfillment(lotId, fulfillmentId);
        showToast(`Removed CK line — ${name} back in inventory`);
      } else if (action === "cancel-buy") {
        if (
          !confirm(
            `Cancel buy for "${name}"?\n\nDeletes the inventory lot and this CK line. Use when the TCG seller canceled your order.`
          )
        ) {
          return;
        }
        // Lot delete cascades fulfillments; no need to delete the line first.
        await deleteLot(lotId);
        showToast(`Canceled buy — removed ${name}`);
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

  els.ordersResults?.addEventListener("change", async (e) => {
    const sel = e.target.closest(".inv-order-status");
    if (!sel) return;
    const orderId = sel.dataset.order;
    const status = sel.value;
    const prev = sel.dataset.prev || sel.value;
    if (status === "paid") {
      sel.value = prev;
      openOrderPaidModal(orderId);
      return;
    }
    sel.dataset.prev = status;
    try {
      const result = await setOrderStatus(orderId, status);
      const label = ORDER_STATUS_LABELS[status] || status;
      const n = result.updated_fulfillments || 0;
      showToast(n ? `CK order → ${label} (${n} line${n === 1 ? "" : "s"})` : `Order already ${label}`);
      await refreshSummaries();
      load();
    } catch (err) {
      sel.value = prev;
      alert(err.message || String(err));
    }
  });

  els.ordersTable?.querySelector("th[data-sort-col='placed']")?.addEventListener("click", (e) => {
    e.preventDefault();
    toggleOrdersPlacedSort();
  });
  els.ordersTable?.querySelector("th[data-sort-col='placed']")?.addEventListener("keydown", (e) => {
    if (e.key !== "Enter" && e.key !== " ") return;
    e.preventDefault();
    toggleOrdersPlacedSort();
  });

  els.ordersResults?.addEventListener("click", (e) => {
    const btn = e.target.closest(".inv-order-paid-btn");
    if (!btn) return;
    openOrderPaidModal(btn.dataset.order);
  });

  els.orderPaidBody?.addEventListener("input", (e) => {
    const input = e.target.closest("input");
    if (!input) return;
    const tr = input.closest("tr[data-fulfillment-id]");
    if (tr && (input.classList.contains("op-ex") || input.classList.contains("op-vg") || input.classList.contains("op-g"))) {
      syncPaidGradesFromLower(tr, input);
    }
    updateOrderPaidSummary();
  });

  els.orderPaidClose?.addEventListener("click", closeOrderPaidModal);
  els.orderPaidCancel?.addEventListener("click", closeOrderPaidModal);
  els.orderPaidForm?.addEventListener("submit", async (e) => {
    e.preventDefault();
    setButtonLoading(els.orderPaidSave, true);
    try {
      const result = await submitOrderPaid();
      showToast(`Marked paid · ${fmtUsd(result.order_paid)}`);
      closeOrderPaidModal();
      await refreshSummaries();
      load();
    } catch (err) {
      alert(err.message || String(err));
    } finally {
      setButtonLoading(els.orderPaidSave, false);
    }
  });

  els.fulfillResults?.addEventListener(
    "blur",
    async (e) => {
      const input = e.target.closest(".inv-paid-amount");
      if (!input) return;
      const lotId = parseInt(input.dataset.lotId, 10);
      const fulfillmentId = parseInt(input.dataset.id, 10);
      const prev = fulfillRowsById.get(fulfillmentId);
      const prevVal =
        prev?.paid_amount != null ? String(prev.paid_amount) : String(prev?.fulfillment_revenue ?? "");
      try {
        await patchFulfillmentPaidAmount(lotId, fulfillmentId, input.value);
        showToast("Updated CK paid amount");
        await refreshSummaries();
        load();
      } catch (err) {
        input.value = prevVal;
        alert(err.message || String(err));
      }
    },
    true
  );

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
