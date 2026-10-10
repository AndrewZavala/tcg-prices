/* Spell Tag collection binder: 3x3 pocket pages, a freeform table, swap/nudge, undo, layout history. */
(function () {
  const POCKETS = 9;
  const MAX_SLOT = 9999;
  const MAX_PAGES = Math.floor((MAX_SLOT + 1) / POCKETS);
  const HISTORY_LIMIT = 200;
  const SAVE_DELAY_MS = 400;
  const DRAG_THRESHOLD_PX = 5;
  const TOUCH_HOLD_MS = 260;
  const EDGE_FLIP_MS = 550;
  const EDGE_REPEAT_MS = 850;
  const CARD_RATIO = 88 / 63;
  const COVER_PAGE = -1;
  const COVER_MAX_W = 1000;
  const COVER_MAX_H = 1400;
  const FALLBACK_IMG = "/static/empty-pokeball.png";
  const ARRANGE_OPTIONS = [
    ["set", "Set"],
    ["number", "Number"],
    ["name", "Name"],
    ["type", "Type"],
    ["price", "Price"],
    ["saved", "Date saved"],
  ];
  const MODE_HINTS = {
    move: "Drag cards between pockets or onto the table. Dropping on a card swaps the two.",
    "nudge-left": "Click a card to push it and the cards before it back one pocket, opening a gap.",
    "nudge-right": "Click a card to push it and the cards after it forward one pocket, opening a gap.",
  };

  function esc(s) {
    return String(s ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function isTypingTarget(el) {
    if (!el || el === document.body) return false;
    const tag = (el.tagName || "").toLowerCase();
    return tag === "input" || tag === "textarea" || tag === "select" || el.isContentEditable;
  }

  function samePos(a, b) {
    if (!a || !b) return !a && !b;
    if (a.slot != null || b.slot != null) return a.slot === b.slot;
    return a.x === b.x && a.y === b.y && a.z === b.z;
  }

  function clamp01(n) {
    return Math.min(1, Math.max(0, n));
  }

  function bySavedAsc(a, b) {
    const sa = String(a.saved_at || "");
    const sb = String(b.saved_at || "");
    if (sa !== sb) return sa < sb ? -1 : 1;
    return String(a.id) < String(b.id) ? -1 : 1;
  }

  function formatWhen(iso) {
    const d = new Date(String(iso || "").replace(" ", "T"));
    if (Number.isNaN(d.getTime())) return "";
    return d.toLocaleString(undefined, {
      month: "short",
      day: "numeric",
      hour: "numeric",
      minute: "2-digit",
    });
  }

  function mount(el, opts) {
    const editable = !!opts.editable;
    const isMatch = opts.isMatch || (() => true);
    const cardsById = new Map();
    const pos = new Map();
    const slotMap = new Map();
    const undoStack = [];
    const redoStack = [];
    const pending = new Set();
    const narrowMq = window.matchMedia("(max-width: 700px)");

    let mode = "move";
    let page = COVER_PAGE;
    let cover = opts.cover || null;
    let preview = null;
    let saveTimer = null;
    let saveChain = Promise.resolve();
    let pendingUserEdit = false;
    let dailySnapshotDone = false;
    let nextSnapshot = null;
    let press = null;
    let drag = null;
    let destroyed = false;
    let statusTimer = null;
    const pagesKey = editable && opts.collectionId ? `spelltag-binder-pages:${opts.collectionId}` : null;
    let pageTotal = 1;
    try {
      if (pagesKey) pageTotal = Math.max(1, parseInt(localStorage.getItem(pagesKey), 10) || 1);
    } catch {
      /* storage unavailable */
    }

    // ---------- state ----------

    function setPageTotal(n) {
      pageTotal = Math.max(1, Math.min(MAX_PAGES, n));
      try {
        if (pagesKey) localStorage.setItem(pagesKey, String(pageTotal));
      } catch {
        /* storage unavailable */
      }
    }

    function setPos(id, p) {
      const old = pos.get(id);
      if (old && old.slot != null && slotMap.get(old.slot) === id) slotMap.delete(old.slot);
      if (p) {
        pos.set(id, p);
        if (p.slot != null) slotMap.set(p.slot, id);
      } else {
        pos.delete(id);
      }
      const card = cardsById.get(id);
      if (card) {
        card.binder_slot = p?.slot ?? null;
        card.table_x = p?.x ?? null;
        card.table_y = p?.y ?? null;
        card.table_z = p?.z ?? null;
      }
    }

    function loadCardPos(card) {
      const slot = card.binder_slot;
      if (slot != null && Number.isInteger(Number(slot)) && !slotMap.has(Number(slot))) {
        setPos(card.id, { slot: Number(slot) });
      } else if (card.table_x != null && card.table_y != null) {
        setPos(card.id, {
          x: clamp01(Number(card.table_x)),
          y: clamp01(Number(card.table_y)),
          z: Number(card.table_z) || 0,
        });
      }
    }

    function maxSlot(map) {
      let max = -1;
      for (const s of map.keys()) if (s > max) max = s;
      return max;
    }

    function maxZ() {
      let max = 0;
      for (const p of pos.values()) if (p.slot == null && p.z > max) max = p.z;
      return max;
    }

    function autoPlace(save) {
      const unplaced = [...cardsById.values()].filter((c) => !pos.has(c.id)).sort(bySavedAsc);
      if (!unplaced.length) return;
      let next = maxSlot(slotMap) + 1;
      for (const c of unplaced) {
        if (next > MAX_SLOT) break;
        setPos(c.id, { slot: next++ });
        if (save) pending.add(c.id);
      }
      if (save) flush();
    }

    function moveFor(id) {
      const p = pos.get(id);
      const onTable = p && p.slot == null;
      return {
        card_id: id,
        slot: p?.slot ?? null,
        x: onTable ? p.x : null,
        y: onTable ? p.y : null,
        z: onTable ? p.z || 0 : null,
      };
    }

    function applyChanges(changes, which, { queue = true } = {}) {
      for (const c of changes) {
        if (!cardsById.has(c.id)) continue;
        setPos(c.id, c[which] ? { ...c[which] } : null);
        if (queue) pending.add(c.id);
      }
      if (queue) scheduleSave();
    }

    function commit(changes, label, pagesAfter) {
      const real = changes.filter((c) => !samePos(c.before, c.after));
      const pagesBefore = pageTotal;
      const pagesChanged = pagesAfter != null && pagesAfter !== pagesBefore;
      if (!real.length && !pagesChanged) return false;
      applyChanges(real, "after");
      if (pagesChanged) setPageTotal(pagesAfter);
      undoStack.push({ label, changes: real, pagesBefore, pagesAfter: pageTotal });
      if (undoStack.length > HISTORY_LIMIT) undoStack.shift();
      redoStack.length = 0;
      if (real.length) pendingUserEdit = true;
      render();
      return true;
    }

    function undo() {
      if (!editable || preview || drag) return;
      const action = undoStack.pop();
      if (!action) return;
      applyChanges(action.changes, "before");
      if (action.pagesBefore != null) setPageTotal(action.pagesBefore);
      redoStack.push(action);
      pendingUserEdit = true;
      render();
      flashStatus(`Undid ${action.label.toLowerCase()}`);
    }

    function redo() {
      if (!editable || preview || drag) return;
      const action = redoStack.pop();
      if (!action) return;
      applyChanges(action.changes, "after");
      if (action.pagesAfter != null) setPageTotal(action.pagesAfter);
      undoStack.push(action);
      pendingUserEdit = true;
      render();
      flashStatus(`Redid ${action.label.toLowerCase()}`);
    }

    // ---------- saving ----------

    function scheduleSave() {
      clearTimeout(saveTimer);
      saveTimer = setTimeout(() => flush(), SAVE_DELAY_MS);
    }

    function flush(options) {
      saveChain = saveChain.then(() => doFlush(options || {}));
      return saveChain;
    }

    async function doFlush({ keepalive = false }) {
      clearTimeout(saveTimer);
      saveTimer = null;
      if (!pending.size || !editable) return true;
      const ids = [...pending].filter((id) => cardsById.has(id));
      pending.clear();
      if (!ids.length) return true;
      const body = {
        moves: ids.map(moveFor),
        tz_offset_minutes: new Date().getTimezoneOffset(),
      };
      if (nextSnapshot) {
        Object.assign(body, nextSnapshot);
        nextSnapshot = null;
        dailySnapshotDone = true;
      } else if (pendingUserEdit && !dailySnapshotDone) {
        body.snapshot = "auto-daily";
        dailySnapshotDone = true;
      }
      pendingUserEdit = false;
      setStatus("Saving…");
      try {
        await opts.save(body, { keepalive });
        flashStatus("Saved");
        return true;
      } catch (err) {
        setStatus("Couldn't save", true);
        if (!destroyed) opts.onSaveError?.(err);
        return false;
      }
    }

    // ---------- layout ----------

    function pagesPerView() {
      return narrowMq.matches ? 1 : 2;
    }

    function displaySlots() {
      return preview ? preview.slotMap : slotMap;
    }

    function usedPages(map) {
      return Math.floor(maxSlot(map) / POCKETS) + 1;
    }

    function pageCount() {
      const used = usedPages(displaySlots());
      return Math.max(1, used, preview ? 0 : pageTotal);
    }

    function clampPage() {
      if (page < 0) {
        page = COVER_PAGE;
        return;
      }
      page = Math.min(page, pageCount() - 1);
      if (pagesPerView() === 2) page -= page % 2;
    }

    function coverHtml() {
      const img = cover?.image_url
        ? `<img class="sb-cover-img" src="${esc(cover.image_url)}" alt="" decoding="async" draggable="false"
            onerror="this.remove()" />`
        : "";
      const btn = editable
        ? `<button type="button" class="sb-btn sb-btn-small sb-cover-btn" data-act="cover">${
            cover ? "Change cover" : "Choose a cover"
          }</button>`
        : "";
      return `<div class="sb-cover${cover ? "" : " is-blank"}" role="img" aria-label="Binder cover${
        cover?.name ? `: ${esc(cover.name)}` : ""
      }">${img}${btn}</div>`;
    }

    function cardHtml(card, style) {
      const label = `${card.name} — ${card.set_name} #${card.local_id}`;
      const cls = ["sb-card"];
      if (!isMatch(card)) cls.push("is-dimmed");
      if (drag && drag.id === card.id) cls.push("is-drag-source");
      return `<div class="${cls.join(" ")}" data-id="${esc(card.id)}" tabindex="0" role="button"
        aria-label="${esc(label)}" title="${esc(label)}"${style ? ` style="${style}"` : ""}>
        <img src="${esc(card.image_url || FALLBACK_IMG)}" alt="" loading="lazy" decoding="async" draggable="false"
          onerror="this.onerror=null;this.src='${FALLBACK_IMG}'" />
      </div>`;
    }

    function pageHtml(p) {
      if (p >= pageCount()) {
        return `<div class="sb-page is-blank">${
          editable && !preview
            ? `<button type="button" class="sb-btn sb-btn-small" data-act="add-page">+ Add page</button>`
            : ""
        }</div>`;
      }
      const slots = displaySlots();
      let pockets = "";
      for (let i = 0; i < POCKETS; i++) {
        const slot = p * POCKETS + i;
        const card = cardsById.get(slots.get(slot));
        pockets += `<div class="sb-pocket" data-slot="${slot}" aria-label="Page ${p + 1}, pocket ${i + 1}">${
          card ? cardHtml(card) : ""
        }</div>`;
      }
      return `<div class="sb-page" data-page="${p}">
        <div class="sb-pockets">${pockets}</div>
        <span class="sb-page-num">${p + 1}</span>
      </div>`;
    }

    function renderSpread(turn) {
      clampPage();
      const step = pagesPerView();
      const count = pageCount();
      const spread = el.querySelector(".sb-spread");
      const onCover = page === COVER_PAGE;
      let html = "";
      if (onCover) html = coverHtml();
      else for (let p = page; p < page + step; p++) html += pageHtml(p);
      spread.innerHTML = html;
      spread.classList.toggle("is-single", step === 1);
      spread.classList.toggle("is-cover", onCover);
      spread.classList.remove("is-turn-next", "is-turn-prev");
      if (turn) {
        void spread.offsetWidth;
        spread.classList.add(turn > 0 ? "is-turn-next" : "is-turn-prev");
      }
      el.querySelector(".sb-flip-prev").disabled = onCover;
      el.querySelector(".sb-flip-prev").setAttribute("aria-label", page === 0 ? "Close binder" : "Previous pages");
      el.querySelector(".sb-flip-next").disabled = !onCover && page + step >= count;
      el.querySelector(".sb-flip-next").setAttribute("aria-label", onCover ? "Open binder" : "Next pages");
      el.querySelector(".sb-pager").textContent = onCover
        ? `Cover · ${count} page${count === 1 ? "" : "s"}`
        : step === 1 || page + 1 >= count
          ? `Page ${page + 1} of ${count}`
          : `Pages ${page + 1}–${page + 2} of ${count}`;
    }

    function renderTable() {
      const table = el.querySelector(".sb-table");
      const onTable = [];
      for (const [id, p] of pos) {
        if (p.slot == null && cardsById.has(id)) onTable.push([id, p]);
      }
      onTable.sort((a, b) => a[1].z - b[1].z);
      table.innerHTML = onTable.length
        ? onTable
            .map(([id, p]) =>
              cardHtml(cardsById.get(id), `--x:${p.x};--y:${p.y};z-index:${Math.min(p.z, 900) + 1}`)
            )
            .join("")
        : `<p class="sb-table-empty">${
            editable
              ? "The table. Drag cards here to set them aside while you flip pages."
              : "Nothing on the table."
          }</p>`;
    }

    function renderChrome() {
      el.classList.toggle("is-previewing", !!preview);
      el.classList.toggle("is-nudge", mode !== "move" && !preview);
      if (!editable) return;
      el.querySelectorAll(".sb-modes button").forEach((b) => {
        const on = b.dataset.mode === mode;
        b.classList.toggle("is-active", on);
        b.setAttribute("aria-pressed", on ? "true" : "false");
        b.disabled = !!preview;
      });
      el.querySelector('[data-act="undo"]').disabled = !undoStack.length || !!preview;
      el.querySelector('[data-act="redo"]').disabled = !redoStack.length || !!preview;
      el.querySelector('.sb-toolbar [data-act="add-page"]').disabled = !!preview || pageCount() >= MAX_PAGES;
      el.querySelector('[data-act="remove-all"]').disabled = !!preview || !slotMap.size;
      el.querySelector(".sb-mode-hint").textContent = preview
        ? "Previewing only: moving cards is off until you go back to your arrangement."
        : MODE_HINTS[mode];
      const banner = el.querySelector(".sb-banner");
      banner.hidden = !preview;
      if (preview) {
        banner.querySelector(".sb-banner-text").innerHTML = `Previewing by <strong>${esc(
          preview.label
        )}</strong>. Your arrangement is unchanged.`;
      }
      const select = el.querySelector(".sb-arrange select");
      select.value = preview ? preview.key : "";
    }

    function render(turn) {
      if (destroyed) return;
      renderChrome();
      renderSpread(turn);
      renderTable();
      if (drag) markDropTarget();
    }

    function refreshDim() {
      el.querySelectorAll(".sb-card[data-id]").forEach((node) => {
        const card = cardsById.get(node.dataset.id);
        node.classList.toggle("is-dimmed", !!card && !isMatch(card));
      });
    }

    function flip(dir) {
      const before = page;
      if (page === COVER_PAGE) page = dir > 0 ? 0 : COVER_PAGE;
      else page = Math.max(COVER_PAGE, page + dir * pagesPerView());
      clampPage();
      if (page !== before) {
        renderSpread(dir);
        if (drag) markDropTarget();
      }
    }

    function setStatus(text, isError) {
      const node = el.querySelector(".sb-status");
      if (!node) return;
      clearTimeout(statusTimer);
      node.textContent = text;
      node.classList.toggle("is-error", !!isError);
    }

    function flashStatus(text) {
      setStatus(text);
      statusTimer = setTimeout(() => setStatus(""), 2200);
    }

    // ---------- nudge ----------

    function nudge(slot, dir) {
      if (!slotMap.has(slot)) {
        flashStatus("That pocket is already empty");
        return;
      }
      const changes = [];
      const countBefore = pageCount();
      let pagesAfter;
      if (dir > 0) {
        let end = slot;
        while (slotMap.has(end)) end++;
        if (end > MAX_SLOT) {
          flashStatus("The binder is full");
          return;
        }
        for (let s = end - 1; s >= slot; s--) {
          changes.push({ id: slotMap.get(s), before: { slot: s }, after: { slot: s + 1 } });
        }
        pagesAfter = Math.max(countBefore, Math.floor(end / POCKETS) + 1);
      } else {
        let end = slot;
        while (end >= 0 && slotMap.has(end)) end--;
        if (end < 0) {
          flashStatus("No empty pocket before this one to nudge into");
          return;
        }
        for (let s = end + 1; s <= slot; s++) {
          changes.push({ id: slotMap.get(s), before: { slot: s }, after: { slot: s - 1 } });
        }
        // Only the last page can be dropped, and only once the nudge leaves it with no cards.
        const lastBefore = maxSlot(slotMap);
        const after = new Set(slotMap.keys());
        after.delete(slot);
        after.add(end);
        let lastAfter = -1;
        for (const s of after) if (s > lastAfter) lastAfter = s;
        const lastPage = Math.floor(lastBefore / POCKETS);
        pagesAfter = countBefore;
        if (lastPage === countBefore - 1 && Math.floor(lastAfter / POCKETS) < lastPage) {
          pagesAfter = countBefore - 1;
        }
      }
      if (commit(changes, dir > 0 ? "Nudge right" : "Nudge left", pagesAfter)) {
        if (pagesAfter > countBefore) flashStatus(`Added page ${pagesAfter}`);
        else if (pagesAfter < countBefore) flashStatus(`Removed empty page ${countBefore}`);
      }
    }

    function addPage() {
      if (!editable || preview || drag) return;
      const count = pageCount();
      if (count >= MAX_PAGES) {
        flashStatus("The binder is full");
        return;
      }
      commit([], "Add page", count + 1);
      page = count;
      renderSpread(1);
      flashStatus(`Added page ${count + 1}`);
    }

    function pileOnTable(n) {
      const rect = el.querySelector(".sb-table").getBoundingClientRect();
      const cw = tableCardWidth();
      const ch = cw * CARD_RATIO;
      const w = Math.max(rect.width, cw);
      const h = Math.max(rect.height, ch);
      const cols = Math.max(1, Math.min(n, Math.round(Math.sqrt((n * w * ch) / (h * cw)))));
      const rows = Math.ceil(n / cols);
      const round = (v) => Math.round(v * 10000) / 10000;
      const spots = [];
      for (let i = 0; i < n; i++) {
        const c = i % cols;
        const r = Math.floor(i / cols);
        spots.push({
          x: round(cols > 1 ? c / (cols - 1) : 0.5),
          y: round(rows > 1 ? r / (rows - 1) : 0.5),
        });
      }
      return spots;
    }

    async function removeAll() {
      if (!editable || preview || drag) return;
      const inPockets = [...slotMap.entries()].sort((a, b) => a[0] - b[0]);
      if (!inPockets.length) {
        flashStatus("The binder is already empty");
        return;
      }
      const n = inPockets.length;
      const ok = window.confirm(
        `Take all ${n} card${n === 1 ? "" : "s"} out of the binder and put ${
          n === 1 ? "it" : "them"
        } on the table?\n\nYour current layout is saved to Layout history first, and you can undo this.`
      );
      if (!ok) return;
      await flush();
      const spots = pileOnTable(n);
      const top = maxZ() + n;
      // Earlier cards sit on top so each card's name strip stays visible in the pile.
      const changes = inPockets.map(([slot, id], i) => ({
        id,
        before: { slot },
        after: { x: spots[i].x, y: spots[i].y, z: top - i },
      }));
      nextSnapshot = { snapshot: "before-arrange", snapshot_label: "Before emptying the binder" };
      if (!commit(changes, "Remove all", pageCount())) {
        nextSnapshot = null;
        return;
      }
      await flush();
    }

    // ---------- drag and drop ----------

    function tableCardWidth() {
      const table = el.querySelector(".sb-table");
      const raw = getComputedStyle(table).getPropertyValue("--sb-table-card-w");
      return parseFloat(raw) || 96;
    }

    function markDropTarget() {
      el.querySelectorAll(".is-drop-target").forEach((n) => n.classList.remove("is-drop-target"));
      const t = drag?.target;
      if (!t) return;
      if (t.type === "pocket") {
        el.querySelector(`.sb-pocket[data-slot="${t.slot}"]`)?.classList.add("is-drop-target");
      } else if (t.type === "table") {
        el.querySelector(".sb-table")?.classList.add("is-drop-target");
      }
    }

    function setEdge(dir) {
      if (!drag || drag.edgeDir === dir) return;
      drag.edgeDir = dir;
      clearTimeout(drag.edgeTimer);
      el.querySelectorAll(".sb-flip.is-hot").forEach((n) => n.classList.remove("is-hot"));
      if (!dir) return;
      el.querySelector(dir > 0 ? ".sb-flip-next" : ".sb-flip-prev")?.classList.add("is-hot");
      const tick = () => {
        if (!drag || drag.edgeDir !== dir) return;
        flip(dir);
        drag.edgeTimer = setTimeout(tick, EDGE_REPEAT_MS);
      };
      drag.edgeTimer = setTimeout(tick, EDGE_FLIP_MS);
    }

    function sizeGhost(w, h) {
      if (drag.w === w && drag.h === h) return;
      drag.w = w;
      drag.h = h;
      drag.ghost.style.width = `${w}px`;
      drag.ghost.style.height = `${h}px`;
      drag.ghost.style.transformOrigin = `${drag.fx * w}px ${drag.fy * h}px`;
    }

    function startDrag() {
      const src = press.cardEl;
      const r = src.getBoundingClientRect();
      const ghost = document.createElement("div");
      ghost.className = "sb-ghost";
      ghost.setAttribute("aria-hidden", "true");
      const img = src.querySelector("img");
      if (img) ghost.appendChild(img.cloneNode(false));
      document.body.appendChild(ghost);
      drag = {
        id: press.id,
        from: { ...pos.get(press.id) },
        fx: clamp01((press.x0 - r.left) / Math.max(1, r.width)),
        fy: clamp01((press.y0 - r.top) / Math.max(1, r.height)),
        baseW: r.width,
        baseH: r.height,
        w: 0,
        h: 0,
        ghost,
        target: null,
        edgeDir: 0,
        edgeTimer: null,
      };
      sizeGhost(r.width, r.height);
      src.classList.add("is-drag-source");
      el.classList.add("is-dragging");
    }

    function moveDrag(e) {
      const hit = document.elementFromPoint(e.clientX, e.clientY);
      const flipBtn = hit?.closest?.(".sb-flip");
      const pocket = hit?.closest?.(".sb-pocket");
      const table = hit?.closest?.(".sb-table");
      if (flipBtn && el.contains(flipBtn)) {
        setEdge(flipBtn.classList.contains("sb-flip-next") ? 1 : -1);
      } else {
        setEdge(0);
      }
      let target = null;
      if (pocket && el.contains(pocket)) target = { type: "pocket", slot: Number(pocket.dataset.slot) };
      else if (table && el.contains(table)) target = { type: "table" };
      const changed =
        (target?.type || null) !== (drag.target?.type || null) || target?.slot !== drag.target?.slot;
      drag.target = target;
      drag.lastX = e.clientX;
      drag.lastY = e.clientY;
      if (target?.type === "table") {
        const cw = tableCardWidth();
        sizeGhost(cw, cw * CARD_RATIO);
      } else if (target?.type === "pocket") {
        const r = pocket.getBoundingClientRect();
        sizeGhost(r.width, r.height);
      } else {
        sizeGhost(drag.baseW, drag.baseH);
      }
      drag.ghost.style.left = `${e.clientX - drag.fx * drag.w}px`;
      drag.ghost.style.top = `${e.clientY - drag.fy * drag.h}px`;
      if (changed) markDropTarget();
    }

    function endDrag() {
      if (!drag) return;
      clearTimeout(drag.edgeTimer);
      drag.ghost.remove();
      el.classList.remove("is-dragging");
      el.querySelectorAll(".sb-flip.is-hot").forEach((n) => n.classList.remove("is-hot"));
      el.querySelectorAll(".is-drop-target").forEach((n) => n.classList.remove("is-drop-target"));
      el.querySelectorAll(".is-drag-source").forEach((n) => n.classList.remove("is-drag-source"));
      drag = null;
    }

    function dropDrag() {
      const { id, from, target } = drag;
      let changes = null;
      if (target?.type === "pocket") {
        const slot = target.slot;
        if (from.slot !== slot) {
          changes = [{ id, before: from, after: { slot } }];
          const other = slotMap.get(slot);
          if (other && other !== id) changes.push({ id: other, before: { slot }, after: { ...from } });
        }
      } else if (target?.type === "table") {
        const rect = el.querySelector(".sb-table").getBoundingClientRect();
        const cw = tableCardWidth();
        const ch = cw * CARD_RATIO;
        const left = drag.lastX - drag.fx * cw - rect.left;
        const top = drag.lastY - drag.fy * ch - rect.top;
        const x = clamp01(left / Math.max(1, rect.width - cw));
        const y = clamp01(top / Math.max(1, rect.height - ch));
        const round = (n) => Math.round(n * 10000) / 10000;
        changes = [{ id, before: from, after: { x: round(x), y: round(y), z: maxZ() + 1 } }];
      }
      endDrag();
      if (changes) commit(changes, "Move");
      else render();
    }

    function cancelPress() {
      if (!press) return;
      clearTimeout(press.holdTimer);
      press.cardEl?.classList.remove("is-held");
      press = null;
      window.removeEventListener("pointermove", onPointerMove);
      window.removeEventListener("pointerup", onPointerUp);
      window.removeEventListener("pointercancel", onPointerCancel);
    }

    function onPointerDown(e) {
      if (e.button !== 0 || press || drag) return;
      const cardEl = e.target.closest(".sb-card");
      const pocketEl = e.target.closest(".sb-pocket");
      if ((!cardEl && !pocketEl) || !el.contains(e.target)) return;
      const id = cardEl?.dataset.id || null;
      const canDrag = !!(editable && !preview && id);
      press = {
        id,
        cardEl,
        slot: pocketEl ? Number(pocketEl.dataset.slot) : null,
        x0: e.clientX,
        y0: e.clientY,
        pointerId: e.pointerId,
        touch: e.pointerType === "touch",
        canDrag,
        holdReady: e.pointerType !== "touch",
        moved: false,
        holdTimer: null,
      };
      if (canDrag && press.touch) {
        press.holdTimer = setTimeout(() => {
          if (!press) return;
          press.holdReady = true;
          cardEl.classList.add("is-held");
          navigator.vibrate?.(10);
        }, TOUCH_HOLD_MS);
      }
      if (e.pointerType === "mouse" && cardEl) e.preventDefault();
      window.addEventListener("pointermove", onPointerMove);
      window.addEventListener("pointerup", onPointerUp);
      window.addEventListener("pointercancel", onPointerCancel);
    }

    function onPointerMove(e) {
      if (!press || e.pointerId !== press.pointerId) return;
      if (drag) {
        moveDrag(e);
        return;
      }
      const dist = Math.hypot(e.clientX - press.x0, e.clientY - press.y0);
      if (dist < DRAG_THRESHOLD_PX) return;
      press.moved = true;
      if (!press.canDrag) return;
      if (!press.holdReady) {
        cancelPress();
        return;
      }
      press.cardEl.classList.remove("is-held");
      startDrag();
      moveDrag(e);
    }

    function onPointerUp(e) {
      if (!press || e.pointerId !== press.pointerId) return;
      const p = press;
      cancelPress();
      if (drag) {
        dropDrag();
        return;
      }
      if (p.moved) return;
      if (editable && !preview && mode !== "move" && p.slot != null) {
        nudge(p.slot, mode === "nudge-right" ? 1 : -1);
      } else if (p.id) {
        opts.onOpenCard?.(p.id);
      }
    }

    function onPointerCancel(e) {
      if (!press || e.pointerId !== press.pointerId) return;
      cancelPress();
      if (drag) {
        endDrag();
        render();
      }
    }

    function onTouchMove(e) {
      if (drag || (press && press.canDrag && press.holdReady && press.touch)) e.preventDefault();
    }

    // ---------- arrange preview ----------

    async function startPreview(key) {
      const label = (ARRANGE_OPTIONS.find(([k]) => k === key) || [key, key])[1];
      setStatus("Loading order…");
      let order;
      try {
        order = await opts.fetchOrder(key);
      } catch (err) {
        setStatus("Couldn't load that order", true);
        renderChrome();
        return;
      }
      if (destroyed) return;
      const inBinder = order.filter((id) => pos.get(id)?.slot != null);
      const seen = new Set(inBinder);
      for (const id of slotMap.values()) if (!seen.has(id)) inBinder.push(id);
      const previewSlots = new Map();
      inBinder.forEach((id, i) => previewSlots.set(i, id));
      preview = { key, label, slotMap: previewSlots };
      page = 0;
      setStatus("");
      render();
    }

    function exitPreview() {
      if (!preview) return;
      preview = null;
      page = 0;
      render();
    }

    async function applyPreview() {
      if (!preview) return;
      const count = preview.slotMap.size;
      const ok = window.confirm(
        `Replace your arrangement of ${count} card${count === 1 ? "" : "s"}? You can restore it from Layout history.`
      );
      if (!ok) return;
      const { slotMap: previewSlots, label } = preview;
      const changes = [];
      for (const [slot, id] of previewSlots) changes.push({ id, before: { ...pos.get(id) }, after: { slot } });
      preview = null;
      await flush();
      nextSnapshot = { snapshot: "before-arrange", snapshot_label: `Before arranging by ${label}` };
      if (!commit(changes, `Arrange by ${label}`)) {
        nextSnapshot = null;
        render();
        flashStatus("Already in that order");
        return;
      }
      await flush();
    }

    // ---------- layout history ----------

    function layoutsMenu() {
      return el.querySelector(".sb-layouts-menu");
    }

    function closeLayouts() {
      const menu = layoutsMenu();
      if (!menu || menu.hidden) return;
      menu.hidden = true;
      el.querySelector('[data-act="layouts"]')?.setAttribute("aria-expanded", "false");
    }

    async function openLayouts() {
      const menu = layoutsMenu();
      menu.hidden = false;
      el.querySelector('[data-act="layouts"]')?.setAttribute("aria-expanded", "true");
      menu.innerHTML = `<p class="sb-layouts-note">Loading…</p>`;
      let snapshots = [];
      try {
        snapshots = (await opts.listSnapshots())?.snapshots || [];
      } catch (err) {
        menu.innerHTML = `<p class="sb-layouts-note">${esc(err.message || "Couldn't load layouts")}</p>`;
        return;
      }
      const rows = snapshots
        .map(
          (s) => `<li class="sb-layout-row">
            <div class="sb-layout-main">
              <span class="sb-layout-label">${esc(s.label)}</span>
              <span class="sb-layout-meta">${esc(formatWhen(s.created_at))} · ${s.card_count} card${
                s.card_count === 1 ? "" : "s"
              }${s.is_auto ? " · automatic" : ""}</span>
            </div>
            <button type="button" class="sb-btn sb-btn-small" data-restore="${esc(s.id)}" data-label="${esc(
              s.label
            )}">Restore</button>
            <button type="button" class="sb-btn sb-btn-small sb-btn-quiet" data-delete="${esc(
              s.id
            )}" aria-label="Delete ${esc(s.label)}" title="Delete">×</button>
          </li>`
        )
        .join("");
      menu.innerHTML = `
        <div class="sb-layouts-head">
          <strong>Layout history</strong>
          <button type="button" class="sb-btn sb-btn-small" data-act="save-layout">Save current layout…</button>
        </div>
        ${rows ? `<ul class="sb-layout-list">${rows}</ul>` : `<p class="sb-layouts-note">No saved layouts yet.</p>`}
        <p class="sb-layouts-note">A copy is saved automatically before you apply an order or restore, and once on each day you edit. The last 15 automatic copies are kept.</p>`;
    }

    async function saveLayout() {
      const label = window.prompt("Name this layout:", "");
      if (!label || !label.trim()) return;
      await flush();
      try {
        await opts.saveSnapshot(label.trim().slice(0, 80));
        flashStatus("Layout saved");
      } catch (err) {
        alert(err.message || "Couldn't save layout");
      }
      openLayouts();
    }

    async function restoreLayout(id, label) {
      if (!window.confirm(`Restore “${label}”? Your current layout is saved to Layout history first.`)) return;
      closeLayouts();
      preview = null;
      await flush();
      let data;
      try {
        data = await opts.restoreSnapshot(id);
      } catch (err) {
        alert(err.message || "Couldn't restore layout");
        return;
      }
      if (!data || destroyed) return;
      const next = new Map();
      for (const row of data.layout || []) {
        next.set(
          row.card_id,
          row.slot != null ? { slot: row.slot } : { x: row.x, y: row.y, z: row.z || 0 }
        );
      }
      const changes = [];
      for (const cid of cardsById.keys()) {
        const before = pos.get(cid) ? { ...pos.get(cid) } : null;
        const after = next.get(cid) || null;
        if (!samePos(before, after)) changes.push({ id: cid, before, after });
      }
      applyChanges(changes, "after", { queue: false });
      if (changes.length) {
        undoStack.push({ label: `Restore “${label}”`, changes });
        redoStack.length = 0;
      }
      dailySnapshotDone = true;
      render();
      flashStatus("Layout restored");
    }

    // ---------- cover ----------

    function coverDialog() {
      return el.querySelector(".sb-cover-dialog");
    }

    function coverOptionsHtml(query) {
      const q = query.trim().toLowerCase();
      const ordered = [...cardsById.values()].sort((a, b) => {
        const pa = pos.get(a.id);
        const pb = pos.get(b.id);
        const sa = pa?.slot ?? MAX_SLOT + 1 + (pa?.z || 0);
        const sb = pb?.slot ?? MAX_SLOT + 1 + (pb?.z || 0);
        return sa - sb;
      });
      const shown = q
        ? ordered.filter((c) => `${c.name} ${c.set_name} ${c.local_id}`.toLowerCase().includes(q))
        : ordered;
      if (!shown.length) {
        return `<p class="sb-layouts-note">${q ? "No cards match." : "Add cards to this collection to use one as the cover."}</p>`;
      }
      return shown
        .map(
          (c) => `<button type="button" class="sb-cover-option${
            cover?.type === "card" && cover.card_id === c.id ? " is-current" : ""
          }" data-cover-card="${esc(c.id)}" title="${esc(`${c.name} — ${c.set_name} #${c.local_id}`)}">
            <img src="${esc(c.image_url || FALLBACK_IMG)}" alt="${esc(c.name)}" loading="lazy" decoding="async"
              onerror="this.onerror=null;this.src='${FALLBACK_IMG}'" />
          </button>`
        )
        .join("");
    }

    function openCoverPicker() {
      if (!editable) return;
      const dialog = coverDialog();
      const search = dialog.querySelector(".sb-cover-search");
      search.value = "";
      dialog.querySelector(".sb-cover-grid").innerHTML = coverOptionsHtml("");
      dialog.querySelector('[data-cover-act="clear"]').hidden = !cover;
      dialog.querySelector(".sb-cover-msg").textContent = "";
      dialog.showModal();
    }

    function applyCover(next, message) {
      cover = next || null;
      opts.onCoverChange?.(cover);
      if (coverDialog()?.open) coverDialog().close();
      page = COVER_PAGE;
      renderSpread();
      flashStatus(message);
    }

    async function pickCoverCard(cardId) {
      const msg = coverDialog().querySelector(".sb-cover-msg");
      msg.textContent = "Saving…";
      try {
        const data = await opts.setCoverCard(cardId);
        applyCover(data?.binder_cover, "Cover updated");
      } catch (err) {
        msg.textContent = err.message || "Couldn't set the cover";
      }
    }

    async function shrinkCoverImage(file) {
      const url = URL.createObjectURL(file);
      try {
        const img = new Image();
        img.src = url;
        await img.decode();
        const scale = Math.min(1, COVER_MAX_W / img.naturalWidth, COVER_MAX_H / img.naturalHeight);
        const w = Math.max(1, Math.round(img.naturalWidth * scale));
        const h = Math.max(1, Math.round(img.naturalHeight * scale));
        const canvas = document.createElement("canvas");
        canvas.width = w;
        canvas.height = h;
        const ctx = canvas.getContext("2d");
        ctx.fillStyle = "#17151c";
        ctx.fillRect(0, 0, w, h);
        ctx.drawImage(img, 0, 0, w, h);
        return await new Promise((resolve, reject) =>
          canvas.toBlob(
            (blob) => (blob ? resolve(blob) : reject(new Error("Couldn't read that image"))),
            "image/jpeg",
            0.86
          )
        );
      } catch (err) {
        throw new Error(err?.message?.startsWith("Couldn't") ? err.message : "Couldn't read that image");
      } finally {
        URL.revokeObjectURL(url);
      }
    }

    async function uploadCover(file) {
      if (!file) return;
      const msg = coverDialog().querySelector(".sb-cover-msg");
      if (!file.type.startsWith("image/")) {
        msg.textContent = "Choose an image file";
        return;
      }
      msg.textContent = "Uploading…";
      try {
        const blob = await shrinkCoverImage(file);
        const data = await opts.uploadCover(blob);
        applyCover(data?.binder_cover, "Cover updated");
      } catch (err) {
        msg.textContent = err.message || "Couldn't upload that image";
      }
    }

    async function clearCover() {
      const msg = coverDialog().querySelector(".sb-cover-msg");
      msg.textContent = "Removing…";
      try {
        await opts.clearCover();
        applyCover(null, "Cover removed");
      } catch (err) {
        msg.textContent = err.message || "Couldn't remove the cover";
      }
    }

    function onCoverDialogClick(e) {
      const dialog = coverDialog();
      if (e.target === dialog) {
        dialog.close();
        return;
      }
      const option = e.target.closest("[data-cover-card]");
      if (option) {
        pickCoverCard(option.dataset.coverCard);
        return;
      }
      const act = e.target.closest("[data-cover-act]")?.dataset.coverAct;
      if (act === "close") dialog.close();
      else if (act === "upload") dialog.querySelector(".sb-cover-file").click();
      else if (act === "clear") clearCover();
    }

    // ---------- events ----------

    function onToolbarClick(e) {
      const modeBtn = e.target.closest("[data-mode]");
      if (modeBtn && !preview) {
        mode = modeBtn.dataset.mode;
        renderChrome();
        return;
      }
      const act = e.target.closest("[data-act]")?.dataset.act;
      if (act === "undo") undo();
      else if (act === "redo") redo();
      else if (act === "add-page") addPage();
      else if (act === "remove-all") removeAll();
      else if (act === "exit-preview") exitPreview();
      else if (act === "apply-preview") applyPreview();
      else if (act === "layouts") {
        if (layoutsMenu().hidden) openLayouts();
        else closeLayouts();
      } else if (act === "save-layout") saveLayout();
      const restoreBtn = e.target.closest("[data-restore]");
      if (restoreBtn) restoreLayout(restoreBtn.dataset.restore, restoreBtn.dataset.label || "this layout");
      const deleteBtn = e.target.closest("[data-delete]");
      if (deleteBtn && window.confirm("Delete this saved layout?")) {
        opts
          .deleteSnapshot(deleteBtn.dataset.delete)
          .then(openLayouts)
          .catch((err) => alert(err.message || "Couldn't delete layout"));
      }
    }

    function onArrangeChange(e) {
      const key = e.target.value;
      if (key) startPreview(key);
      else exitPreview();
    }

    function onDocPointerDown(e) {
      const menu = layoutsMenu();
      if (menu && !menu.hidden && !e.target.closest(".sb-layouts")) closeLayouts();
    }

    function onKeyDown(e) {
      if (destroyed || !el.isConnected) return;
      if (e.key === "Escape") {
        if (drag) {
          cancelPress();
          endDrag();
          render();
          return;
        }
        closeLayouts();
      }
      if (document.querySelector("dialog[open]") || isTypingTarget(e.target)) return;
      const mod = e.ctrlKey || e.metaKey;
      const key = e.key.toLowerCase();
      if (mod && editable && key === "z") {
        e.preventDefault();
        if (e.shiftKey) redo();
        else undo();
      } else if (mod && editable && key === "y") {
        e.preventDefault();
        redo();
      } else if (!mod && !e.altKey && (e.key === "ArrowLeft" || e.key === "ArrowRight")) {
        e.preventDefault();
        flip(e.key === "ArrowRight" ? 1 : -1);
      }
    }

    function onCardKey(e) {
      if (e.key !== "Enter" && e.key !== " ") return;
      const cardEl = e.target.closest(".sb-card");
      if (!cardEl) return;
      e.preventDefault();
      opts.onOpenCard?.(cardEl.dataset.id);
    }

    function onPageHide() {
      flush({ keepalive: true });
    }

    function onVisibility() {
      if (document.visibilityState === "hidden") flush({ keepalive: true });
    }

    function onNarrowChange() {
      render();
    }

    // ---------- shell ----------

    const toolbar = editable
      ? `<div class="sb-toolbar">
          <div class="sb-modes" role="group" aria-label="Click mode">
            <button type="button" data-mode="move">Move</button>
            <button type="button" data-mode="nudge-left">Nudge left</button>
            <button type="button" data-mode="nudge-right">Nudge right</button>
          </div>
          <div class="sb-history-btns">
            <button type="button" class="sb-btn" data-act="undo" title="Undo (Ctrl+Z)">Undo</button>
            <button type="button" class="sb-btn" data-act="redo" title="Redo (Ctrl+Shift+Z)">Redo</button>
          </div>
          <div class="sb-history-btns">
            <button type="button" class="sb-btn" data-act="add-page" title="Add an empty page at the end of the binder">+ Add page</button>
            <button type="button" class="sb-btn sb-btn-danger" data-act="remove-all" title="Move every card out of the binder onto the table">Remove all…</button>
          </div>
          <label class="sb-arrange">
            <span class="sr-only">Arrange by</span>
            <select>
              <option value="">Arrange by…</option>
              ${ARRANGE_OPTIONS.map(([k, l]) => `<option value="${k}">${l}</option>`).join("")}
            </select>
          </label>
          <div class="sb-layouts">
            <button type="button" class="sb-btn" data-act="layouts" aria-expanded="false" aria-haspopup="true">Layout history ▾</button>
            <div class="sb-layouts-menu" hidden></div>
          </div>
          <span class="sb-status" aria-live="polite"></span>
        </div>
        <p class="sb-mode-hint"></p>
        <div class="sb-banner" hidden>
          <span class="sb-banner-text"></span>
          <span class="sb-banner-actions">
            <button type="button" class="sb-btn" data-act="exit-preview">Back to my arrangement</button>
            <button type="button" class="sb-btn sb-btn-primary" data-act="apply-preview">Use this order</button>
          </span>
        </div>`
      : "";

    el.classList.add("sb-root");
    el.classList.toggle("is-editable", editable);
    el.innerHTML = `
      ${toolbar}
      <div class="sb-stage">
        <div class="sb-binder">
          <div class="sb-spread-row">
            <button type="button" class="sb-flip sb-flip-prev" aria-label="Previous pages">‹</button>
            <div class="sb-spread"></div>
            <button type="button" class="sb-flip sb-flip-next" aria-label="Next pages">›</button>
          </div>
          <p class="sb-pager"></p>
        </div>
        <div class="sb-table-wrap">
          <div class="sb-table" aria-label="Table"></div>
        </div>
      </div>
      ${
        editable
          ? `<dialog class="sb-cover-dialog" aria-label="Binder cover">
              <div class="sb-cover-panel">
                <div class="sb-layouts-head">
                  <strong>Binder cover</strong>
                  <button type="button" class="sb-btn sb-btn-small sb-btn-quiet" data-cover-act="close" aria-label="Close">×</button>
                </div>
                <div class="sb-cover-actions">
                  <button type="button" class="sb-btn sb-btn-small" data-cover-act="upload">Upload image…</button>
                  <button type="button" class="sb-btn sb-btn-small sb-btn-danger" data-cover-act="clear">Remove cover</button>
                  <input type="file" class="sb-cover-file" accept="image/*" hidden />
                  <span class="sb-cover-msg" aria-live="polite"></span>
                </div>
                <input type="search" class="sb-cover-search" placeholder="Or pick a card from this collection…" autocomplete="off" spellcheck="false" />
                <div class="sb-cover-grid"></div>
              </div>
            </dialog>`
          : ""
      }`;

    for (const card of opts.cards || []) {
      cardsById.set(card.id, card);
      loadCardPos(card);
    }
    autoPlace(editable);
    if (editable) setPageTotal(Math.max(pageTotal, usedPages(slotMap)));

    el.querySelector(".sb-flip-prev").addEventListener("click", () => flip(-1));
    el.querySelector(".sb-spread").addEventListener("click", (e) => {
      if (e.target.closest('[data-act="add-page"]')) addPage();
      else if (e.target.closest('[data-act="cover"]')) openCoverPicker();
    });
    if (editable) {
      const dialog = coverDialog();
      dialog.addEventListener("click", onCoverDialogClick);
      dialog.querySelector(".sb-cover-search").addEventListener("input", (e) => {
        dialog.querySelector(".sb-cover-grid").innerHTML = coverOptionsHtml(e.target.value);
      });
      dialog.querySelector(".sb-cover-file").addEventListener("change", (e) => {
        uploadCover(e.target.files?.[0]);
        e.target.value = "";
      });
    }
    el.querySelector(".sb-flip-next").addEventListener("click", () => flip(1));
    el.addEventListener("pointerdown", onPointerDown);
    el.addEventListener("keydown", onCardKey);
    el.addEventListener("contextmenu", (e) => {
      if (e.target.closest(".sb-card") && editable) e.preventDefault();
    });
    el.addEventListener("dragstart", (e) => e.preventDefault());
    if (editable) {
      el.querySelector(".sb-toolbar").addEventListener("click", onToolbarClick);
      el.querySelector(".sb-banner").addEventListener("click", onToolbarClick);
      el.querySelector(".sb-arrange select").addEventListener("change", onArrangeChange);
    }
    document.addEventListener("keydown", onKeyDown);
    document.addEventListener("pointerdown", onDocPointerDown);
    document.addEventListener("touchmove", onTouchMove, { passive: false });
    window.addEventListener("pagehide", onPageHide);
    document.addEventListener("visibilitychange", onVisibility);
    narrowMq.addEventListener("change", onNarrowChange);

    render();

    return {
      el,
      collectionId: opts.collectionId,
      refreshDim,
      setCover(next) {
        cover = next || null;
        if (page === COVER_PAGE) renderSpread();
      },
      setCards(cards) {
        const next = new Map((cards || []).map((c) => [c.id, c]));
        let added = false;
        for (const id of [...cardsById.keys()]) {
          if (!next.has(id)) {
            setPos(id, null);
            cardsById.delete(id);
          }
        }
        for (const [id, card] of next) {
          if (cardsById.has(id)) {
            cardsById.set(id, card);
            setPos(id, pos.get(id) || null);
          } else {
            added = true;
            cardsById.set(id, card);
            loadCardPos(card);
          }
        }
        if (added) {
          undoStack.length = 0;
          redoStack.length = 0;
          autoPlace(editable);
        }
        if (preview) {
          for (const [slot, id] of [...preview.slotMap]) {
            if (!cardsById.has(id)) preview.slotMap.delete(slot);
          }
        }
        render();
      },
      orderedIds() {
        const slots = [...displaySlots().entries()].sort((a, b) => a[0] - b[0]).map(([, id]) => id);
        const table = [...pos.entries()]
          .filter(([, p]) => p.slot == null)
          .sort((a, b) => a[1].z - b[1].z)
          .map(([id]) => id);
        return [...slots, ...table];
      },
      destroy() {
        if (destroyed) return;
        flush({ keepalive: true });
        destroyed = true;
        cancelPress();
        endDrag();
        if (coverDialog()?.open) coverDialog().close();
        document.removeEventListener("keydown", onKeyDown);
        document.removeEventListener("pointerdown", onDocPointerDown);
        document.removeEventListener("touchmove", onTouchMove);
        window.removeEventListener("pagehide", onPageHide);
        document.removeEventListener("visibilitychange", onVisibility);
        narrowMq.removeEventListener("change", onNarrowChange);
      },
    };
  }

  window.SpellTagBinder = { mount };
})();
