(function () {
  const root = document.getElementById("collectionsRoot");
  if (!root) return;

  const CARD_IMG_FALLBACK = "/static/empty-pokeball.png";
  const importDialog = document.getElementById("importDialog");
  const importFile = document.getElementById("importFile");
  const importPreview = document.getElementById("importPreview");
  const importTarget = document.getElementById("importTarget");
  const importCollectionSelect = document.getElementById("importCollectionSelect");
  const importNewNameWrap = document.getElementById("importNewNameWrap");
  const importNewName = document.getElementById("importNewName");
  const importSubmit = document.getElementById("importSubmit");
  const importClose = document.getElementById("importClose");
  const importCancel = document.getElementById("importCancel");
  const cardModal = document.getElementById("cardModal");
  const modalBody = document.getElementById("modalBody");
  const modalClose = document.getElementById("modalClose");

  let importCubeData = null;
  let importPreviewData = null;
  let importPreselectId = null;
  let importUiBound = false;
  let detailCollectionId = null;
  let detailColl = null;
  let detailCards = [];
  let detailQuery = "";
  let detailSort = "saved";
  let listTagFilter = "";
  let listSort = "name";
  let allCollectionTags = [];

  function esc(s) {
    return String(s ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function collectionIdFromPath() {
    const m = location.pathname.match(/^\/collections\/([^/]+)\/?$/);
    return m ? decodeURIComponent(m[1]) : null;
  }

  function collectionSearchFromUrl() {
    return new URLSearchParams(location.search).get("q") || "";
  }

  function collectionSortFromUrl() {
    return new URLSearchParams(location.search).get("sort") || "";
  }

  function collectionTagFromUrl() {
    return new URLSearchParams(location.search).get("tag") || "";
  }

  function writeCollectionListToUrl() {
    const params = new URLSearchParams();
    if (listTagFilter) params.set("tag", listTagFilter);
    if (listSort && listSort !== "name") params.set("sort", listSort);
    const qs = params.toString();
    const next = qs ? `${location.pathname}?${qs}` : location.pathname;
    if (next !== `${location.pathname}${location.search}`) {
      history.replaceState(null, "", next);
    }
  }

  function writeCollectionDetailToUrl() {
    const params = new URLSearchParams();
    const q = String(detailQuery || "").trim();
    if (q) params.set("q", q);
    if (detailSort && detailSort !== "saved") params.set("sort", detailSort);
    const qs = params.toString();
    const next = qs ? `${location.pathname}?${qs}` : location.pathname;
    if (next !== `${location.pathname}${location.search}`) {
      history.replaceState(null, "", next);
    }
  }

  function renderTagPills(tags, { linkFilter = false } = {}) {
    if (!tags?.length) return "";
    return `<span class="sp-collection-tag-row">${tags
      .map((tag) =>
        linkFilter
          ? `<a class="sp-collection-tag" href="/collections?tag=${encodeURIComponent(tag)}">${esc(tag)}</a>`
          : `<span class="sp-collection-tag">${esc(tag)}</span>`
      )
      .join("")}</span>`;
  }

  function normalizeTagInput(raw) {
    return String(raw || "")
      .trim()
      .toLowerCase()
      .replace(/[^a-z0-9_-]+/g, "-")
      .replace(/-+/g, "-")
      .replace(/^-|-$/g, "");
  }

  async function saveCollectionTags(collectionId, tags) {
    const data = await api(`/api/me/collections/${encodeURIComponent(collectionId)}/tags`, {
      method: "PUT",
      body: JSON.stringify({ tags }),
    });
    return data.tags || [];
  }

  function bindTagEditor(collectionId, tags) {
    const listEl = document.getElementById("collectionTagList");
    const form = document.getElementById("collectionTagForm");
    const input = document.getElementById("collectionTagInput");
    if (!listEl || !form || !input) return;

    const renderTags = () => {
      const current = detailColl?.tags || tags || [];
      listEl.innerHTML = current.length
        ? current
            .map(
              (tag) =>
                `<button type="button" class="sp-collection-tag sp-collection-tag-removable" data-tag="${esc(
                  tag
                )}" title="Remove tag">${esc(tag)} ×</button>`
            )
            .join("")
        : `<span class="sp-hint">No tags yet — add labels like cube, draft, trade.</span>`;
      listEl.querySelectorAll("[data-tag]").forEach((btn) => {
        btn.addEventListener("click", async () => {
          const next = (detailColl.tags || []).filter((t) => t !== btn.dataset.tag);
          try {
            const saved = await saveCollectionTags(collectionId, next);
            detailColl.tags = saved;
            renderTags();
          } catch (err) {
            alert(err.message || "Could not update tags");
          }
        });
      });
    };

    renderTags();
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const slug = normalizeTagInput(input.value);
      if (!slug) return;
      const next = [...new Set([...(detailColl.tags || []), slug])].sort();
      try {
        const saved = await saveCollectionTags(collectionId, next);
        detailColl.tags = saved;
        input.value = "";
        renderTags();
      } catch (err) {
        alert(err.message || "Could not add tag");
      }
    });
  }

  function cardMatchesQuery(card, query) {
    const q = String(query || "").trim().toLowerCase();
    if (!q) return true;
    const hay = [
      card.name,
      card.set_name,
      card.set_id,
      card.local_id,
      card.id,
      card.rarity,
      card.illustrator,
    ]
      .filter(Boolean)
      .join(" ")
      .toLowerCase();
    return hay.includes(q);
  }

  function filteredDetailCards() {
    return detailCards.filter((c) => cardMatchesQuery(c, detailQuery));
  }

  function bindModalUi() {
    modalClose?.addEventListener("click", () => cardModal?.close());
    cardModal?.addEventListener("click", (e) => {
      if (e.target === cardModal) cardModal.close();
    });
  }

  function renderCardText(card) {
    const text = card.description || card.card_text;
    if (!text) return "";
    return `<div class="sp-block"><h3>Card text</h3><p class="sp-card-text">${esc(text)}</p></div>`;
  }

  function renderAbilities(card) {
    const abilities = card.abilities || [];
    if (!abilities.length) return "";
    return `<div class="sp-block"><h3>Abilities</h3>${abilities
      .map(
        (a) =>
          `<div class="sp-ability"><strong>${esc(a.name || "Ability")}</strong>${
            a.type ? ` <span class="sp-hint">(${esc(a.type)})</span>` : ""
          }${a.effect ? `<p>${esc(a.effect)}</p>` : ""}</div>`
      )
      .join("")}</div>`;
  }

  function renderAttacks(card) {
    const attacks = card.attacks || [];
    if (!attacks.length) return "";
    return `<div class="sp-block"><h3>Attacks</h3>${attacks
      .map((a) => {
        const cost = Array.isArray(a.cost) ? a.cost.join(" ") : "";
        const dmg = a.damage ? ` — ${esc(a.damage)}` : "";
        return `<div class="sp-attack"><strong>${esc(a.name || "Attack")}</strong>${
          cost ? ` <span class="sp-hint">[${esc(cost)}]</span>` : ""
        }${dmg}${a.effect ? `<p>${esc(a.effect)}</p>` : ""}</div>`;
      })
      .join("")}</div>`;
  }

  function cardImg(src, alt, extraClass) {
    const url = src || CARD_IMG_FALLBACK;
    const cls = ["sp-card-img", extraClass].filter(Boolean).join(" ");
    return `<img class="${cls}" src="${esc(url)}" alt="${esc(alt || "")}" loading="lazy" decoding="async" onerror="this.onerror=null;this.src='${CARD_IMG_FALLBACK}';this.classList.add('is-fallback')" />`;
  }

  async function openCardDetail(cardId, collectionId) {
    if (!cardModal || !modalBody) return;
    modalBody.innerHTML = `<p class="sp-empty">Loading…</p>`;
    cardModal.showModal();
    try {
      const card = await api(`/api/pokemon/cards/${encodeURIComponent(cardId)}`);
      const label = `${card.name} — ${card.set_name} #${card.local_id}`;
      modalBody.innerHTML = `
        <div class="sp-detail">
          <div class="sp-detail-art">
            ${cardImg(card.image_url_high || card.image_url, label, "sp-detail-img")}
          </div>
          <div class="sp-detail-body">
            <h2>${esc(card.name)}</h2>
            <p class="sp-detail-meta">
              ${esc(card.series_name || "—")} · ${esc(card.set_name)} · #${esc(card.local_id)} · ${esc(
                card.rarity || "—"
              )}
              · ${esc(card.illustrator || "Unknown artist")}
            </p>
            <div class="sp-detail-sticky-actions">
              <p class="sp-buy-row">
                <a class="sp-buy-btn" href="/?q=${encodeURIComponent(card.id)}">Open in Search</a>
                ${
                  collectionId
                    ? `<button type="button" class="sp-collection-remove sp-collection-remove-modal" data-card-id="${esc(
                        card.id
                      )}">Remove from collection</button>`
                    : ""
                }
              </p>
            </div>
            ${card.evolve_from ? `<p class="sp-hint">Evolves from ${esc(card.evolve_from)}</p>` : ""}
            ${renderCardText(card)}
            ${renderAbilities(card)}
            ${renderAttacks(card)}
          </div>
        </div>`;
      modalBody.querySelector(".sp-collection-remove-modal")?.addEventListener("click", async (e) => {
        const btn = e.currentTarget;
        btn.disabled = true;
        try {
          await api(
            `/api/me/collections/${encodeURIComponent(collectionId)}/items/${encodeURIComponent(cardId)}`,
            { method: "DELETE" }
          );
          cardModal.close();
          await renderDetail(collectionId);
        } catch (err) {
          alert(err.message || "Could not remove");
          btn.disabled = false;
        }
      });
    } catch (err) {
      modalBody.innerHTML = `<p class="sp-empty">${esc(err.message || "Could not load card")}</p>`;
    }
  }

  async function api(path, opts) {
    const resp = await fetch(path, {
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", ...(opts?.headers || {}) },
      ...opts,
    });
    if (resp.status === 401) {
      root.innerHTML = `
        <p class="sp-empty">Sign in to view your collections.</p>
        <p class="sp-empty"><a class="sp-topbar-login" href="/auth/google/login">Sign in with Google</a></p>`;
      return null;
    }
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      const detail = err.detail;
      const msg = typeof detail === "string" ? detail : `Request failed (${resp.status})`;
      throw new Error(msg);
    }
    return resp.json();
  }

  function resetImportModal() {
    importCubeData = null;
    importPreviewData = null;
    if (importFile) importFile.value = "";
    if (importPreview) {
      importPreview.hidden = true;
      importPreview.innerHTML = "";
    }
    if (importTarget) importTarget.hidden = true;
    if (importNewName) importNewName.value = "";
    if (importSubmit) importSubmit.disabled = true;
  }

  async function populateImportCollections(preselectId) {
    const data = await api("/api/me/collections");
    if (!data) return;
    const rows = (data.collections || []).filter((c) => c.kind !== "favorites");
    importCollectionSelect.innerHTML = [
      '<option value="__new__">Create new collection…</option>',
      ...rows.map(
        (c) =>
          `<option value="${esc(c.id)}"${c.id === preselectId ? " selected" : ""}>${esc(c.name)} (${c.item_count})</option>`
      ),
    ].join("");
    if (preselectId && rows.some((c) => c.id === preselectId)) {
      importCollectionSelect.value = preselectId;
      importNewNameWrap.hidden = true;
    } else if (preselectId) {
      importCollectionSelect.value = "__new__";
      importNewNameWrap.hidden = false;
    }
  }

  function renderImportPreview(data) {
    const unmatched = (data.items || []).filter((i) => i.status === "unmatched");
    importPreview.innerHTML = `
      <p class="sp-import-stats">
        ${data.unique_matched} unique matched · ${data.unmatched} unmatched · ${data.total} in file
        ${data.duplicate_slots ? ` · ${data.duplicate_slots} duplicate slots collapsed` : ""}
      </p>
      ${
        unmatched.length
          ? `<details><summary>${unmatched.length} unmatched</summary><ul class="sp-import-unmatched">${unmatched
              .slice(0, 40)
              .map(
                (u) =>
                  `<li>${esc(u.nickname || "Unknown")}${
                    u.hint ? ` <code>${esc(u.hint)}</code>` : ""
                  }</li>`
              )
              .join("")}${unmatched.length > 40 ? `<li>…and ${unmatched.length - 40} more</li>` : ""}</ul></details>`
          : "<p>All cards matched.</p>"
      }`;
    importPreview.hidden = false;
  }

  function importDropdownHtml(preselectId) {
    const attr = preselectId ? ` data-import-collection="${esc(preselectId)}"` : "";
    return `
      <div class="sp-import-menu"${attr}>
        <button type="button" class="sp-btn-primary sp-import-trigger" aria-haspopup="menu" aria-expanded="false">
          Import <span class="sp-import-caret" aria-hidden="true">▾</span>
        </button>
        <div class="sp-import-dropdown" role="menu" hidden>
          <button type="button" role="menuitem" data-import-format="cube-json"${attr}>
            CubeKoga / TTS JSON
          </button>
          <button type="button" role="menuitem" disabled title="Coming soon">CSV</button>
        </div>
      </div>`;
  }

  function closeAllImportDropdowns() {
    document.querySelectorAll(".sp-import-menu").forEach((menu) => {
      const panel = menu.querySelector(".sp-import-dropdown");
      const trigger = menu.querySelector(".sp-import-trigger");
      if (panel) panel.hidden = true;
      if (trigger) trigger.setAttribute("aria-expanded", "false");
    });
  }

  function toggleImportDropdown(menu) {
    const panel = menu.querySelector(".sp-import-dropdown");
    const trigger = menu.querySelector(".sp-import-trigger");
    if (!panel || !trigger) return;
    const open = panel.hidden;
    closeAllImportDropdowns();
    panel.hidden = !open;
    trigger.setAttribute("aria-expanded", open ? "true" : "false");
  }

  async function openImportModal(preselectId) {
    if (!importDialog) return;
    resetImportModal();
    importPreselectId = preselectId || null;
    await populateImportCollections(importPreselectId);
    importDialog.showModal();
  }

  async function handleImportFile(file) {
    if (!file) return;
    const text = await file.text();
    let cube;
    try {
      cube = JSON.parse(text);
    } catch (_) {
      alert("Could not parse JSON file");
      return;
    }
    importCubeData = cube;
    importSubmit.disabled = true;
    importPreview.hidden = false;
    importPreview.innerHTML = "<p class=\"sp-empty\">Matching cards…</p>";
    importTarget.hidden = true;
    try {
      const data = await api("/api/me/collections/import/preview", {
        method: "POST",
        body: JSON.stringify({ cube }),
      });
      importPreviewData = data;
      renderImportPreview(data);
      importTarget.hidden = false;
      importSubmit.disabled = !(data.unique_matched > 0);
    } catch (err) {
      importPreview.innerHTML = `<p class="sp-empty">${esc(err.message || "Preview failed")}</p>`;
    }
  }

  async function submitImport() {
    if (!importCubeData || !importPreviewData?.unique_matched) return;
    const mode = importCollectionSelect.value;
    const payload = { cube: importCubeData };
    if (mode === "__new__") {
      const name = String(importNewName.value || "").trim();
      if (!name) {
        alert("Enter a name for the new collection");
        return;
      }
      payload.new_collection_name = name;
    } else {
      payload.collection_id = mode;
    }
    importSubmit.disabled = true;
    importSubmit.textContent = "Importing…";
    try {
      const result = await api("/api/me/collections/import", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      importDialog.close();
      resetImportModal();
      const cid = result.collection_id;
      if (collectionIdFromPath() === cid) {
        await renderDetail(cid);
      } else {
        window.location.href = `/collections/${encodeURIComponent(cid)}`;
      }
    } catch (err) {
      alert(err.message || "Import failed");
      importSubmit.disabled = false;
      importSubmit.textContent = "Import matched cards";
    }
  }

  function bindImportUi() {
    if (!importDialog || importUiBound) return;
    importUiBound = true;
    document.addEventListener("click", (e) => {
      const trigger = e.target.closest(".sp-import-trigger");
      if (trigger) {
        e.stopPropagation();
        toggleImportDropdown(trigger.closest(".sp-import-menu"));
        return;
      }
      const formatBtn = e.target.closest("[data-import-format]");
      if (formatBtn && !formatBtn.disabled) {
        e.stopPropagation();
        closeAllImportDropdowns();
        const menu = formatBtn.closest(".sp-import-menu");
        const collectionId = formatBtn.dataset.importCollection || menu?.dataset.importCollection || "";
        const format = formatBtn.dataset.importFormat;
        if (format === "cube-json") {
          openImportModal(collectionId || null);
        }
        return;
      }
      if (!e.target.closest(".sp-import-menu")) {
        closeAllImportDropdowns();
      }
    });
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") closeAllImportDropdowns();
    });
    importFile?.addEventListener("change", () => {
      const file = importFile.files?.[0];
      if (file) handleImportFile(file);
    });
    importCollectionSelect?.addEventListener("change", () => {
      importNewNameWrap.hidden = importCollectionSelect.value !== "__new__";
    });
    importClose?.addEventListener("click", () => {
      importDialog.close();
      resetImportModal();
    });
    importCancel?.addEventListener("click", () => {
      importDialog.close();
      resetImportModal();
    });
    importDialog.addEventListener("close", resetImportModal);
    document.getElementById("importForm")?.addEventListener("submit", (e) => {
      e.preventDefault();
      submitImport();
    });
  }

  async function renderList() {
    listTagFilter = collectionTagFromUrl();
    listSort = collectionSortFromUrl() || "name";
    const params = new URLSearchParams();
    if (listTagFilter) params.set("tag", listTagFilter);
    if (listSort && listSort !== "name") params.set("sort", listSort);
    const qs = params.toString();
    const [data, tagData] = await Promise.all([
      api(`/api/me/collections${qs ? `?${qs}` : ""}`),
      api("/api/me/collection-tags").catch(() => ({ tags: [] })),
    ]);
    if (!data) return;
    allCollectionTags = tagData?.tags || [];
    if (listTagFilter && !allCollectionTags.includes(listTagFilter)) {
      allCollectionTags = [...allCollectionTags, listTagFilter].sort();
    }
    const rows = data.collections || [];
    const tagOptions = [
      '<option value="">All tags</option>',
      ...allCollectionTags.map(
        (tag) =>
          `<option value="${esc(tag)}"${tag === listTagFilter ? " selected" : ""}>${esc(tag)}</option>`
      ),
    ].join("");
    root.innerHTML = `
      <div class="sp-collections-head">
        <h1 class="sp-collections-title">My Collections</h1>
        <p class="sp-hint">Save favorite arts from Search, then browse them here.</p>
        <div class="sp-collection-list-controls">
          <label class="sp-collection-control">
            <span class="sp-label">Tag</span>
            <select id="listTagFilter">${tagOptions}</select>
          </label>
          <label class="sp-collection-control">
            <span class="sp-label">Sort</span>
            <select id="listSort">
              <option value="name"${listSort === "name" ? " selected" : ""}>Name</option>
              <option value="count"${listSort === "count" ? " selected" : ""}>Card count</option>
              <option value="updated"${listSort === "updated" ? " selected" : ""}>Recently updated</option>
            </select>
          </label>
        </div>
        <div class="sp-collections-toolbar">
          <form class="sp-new-collection" id="newCollectionForm">
            <input type="text" name="name" maxlength="80" placeholder="New collection name" required />
            <button type="submit" class="sp-btn-primary">Create</button>
          </form>
          ${importDropdownHtml()}
        </div>
      </div>
      <ul class="sp-collection-list">
        ${
          rows.length
            ? rows
                .map(
                  (c) => `
          <li>
            <a class="sp-collection-row" href="/collections/${esc(c.id)}">
              <span class="sp-collection-row-main">
                <span class="sp-collection-name">${esc(c.name)}${
                    c.kind === "favorites" ? ' <span class="sp-collection-badge">♥</span>' : ""
                  }</span>
                ${renderTagPills(c.tags, { linkFilter: true })}
              </span>
              <span class="sp-collection-count">${c.item_count} card${c.item_count === 1 ? "" : "s"}</span>
            </a>
          </li>`
                )
                .join("")
            : `<li class="sp-empty">No collections match${listTagFilter ? ` tag “${esc(listTagFilter)}”` : ""}.</li>`
        }
      </ul>`;

    document.getElementById("listTagFilter")?.addEventListener("change", (e) => {
      listTagFilter = e.target.value;
      writeCollectionListToUrl();
      renderList();
    });
    document.getElementById("listSort")?.addEventListener("change", (e) => {
      listSort = e.target.value;
      writeCollectionListToUrl();
      renderList();
    });

    document.getElementById("newCollectionForm").addEventListener("submit", async (e) => {
      e.preventDefault();
      const fd = new FormData(e.target);
      const name = String(fd.get("name") || "").trim();
      if (!name) return;
      try {
        await api("/api/me/collections", {
          method: "POST",
          body: JSON.stringify({ name }),
        });
        await renderList();
      } catch (err) {
        alert(err.message || "Could not create collection");
      }
    });
  }

  function renderCardTile(c) {
    const label = `${c.name} — ${c.set_name} #${c.local_id}`;
    return `
      <article class="sp-card sp-collection-card" data-id="${esc(c.id)}" tabindex="0" aria-label="${esc(label)}">
        ${cardImg(c.image_url, label)}
      </article>`;
  }

  function bindCollectionGrid(collectionId) {
    const grid = document.getElementById("collectionGrid");
    if (!grid) return;
    grid.querySelectorAll(".sp-collection-card[data-id]").forEach((el) => {
      const open = () => openCardDetail(el.dataset.id, collectionId);
      el.addEventListener("click", open);
      el.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          open();
        }
      });
    });
  }

  function renderDetailGrid(collectionId) {
    const grid = document.getElementById("collectionGrid");
    const countEl = document.getElementById("collectionSearchCount");
    const emptyEl = document.getElementById("collectionGridEmpty");
    if (!grid) return;
    const visible = filteredDetailCards();
    if (countEl) {
      const total = detailCards.length;
      countEl.textContent =
        detailQuery && visible.length !== total
          ? `${visible.length} of ${total}`
          : `${total} card${total === 1 ? "" : "s"}`;
    }
    if (visible.length) {
      grid.innerHTML = visible.map((c) => renderCardTile(c)).join("");
      grid.hidden = false;
      if (emptyEl) emptyEl.hidden = true;
      bindCollectionGrid(collectionId);
    } else {
      grid.innerHTML = "";
      grid.hidden = true;
      if (emptyEl) {
        emptyEl.hidden = false;
        emptyEl.textContent = detailQuery
          ? `No cards match “${detailQuery}”.`
          : "No cards in this collection.";
      }
    }
  }

  async function renderDetail(id) {
    detailSort = collectionSortFromUrl() || "saved";
    detailQuery = collectionSearchFromUrl();
    const sortParams = detailSort !== "saved" ? `?sort=${encodeURIComponent(detailSort)}` : "";
    const data = await api(`/api/me/collections/${encodeURIComponent(id)}${sortParams}`);
    if (!data) return;
    detailCollectionId = id;
    detailColl = data.collection;
    detailCards = data.cards || [];
    if (data.sort) detailSort = data.sort;
    const coll = detailColl;
    const cards = detailCards;
    const isFav = coll.kind === "favorites";
    root.innerHTML = `
      <div class="sp-collections-head">
        <p class="sp-collections-back"><a href="/collections">← All collections</a></p>
        <h1 class="sp-collections-title">${
          isFav ? '<span class="sp-collection-badge">♥</span> ' : ""
        }${esc(coll.name)}</h1>
        <p class="sp-hint">${
          isFav
            ? "Card arts you’ve hearted from Search."
            : "Cards you’ve saved to this list."
        }</p>
        <div class="sp-collection-tags-panel">
          <span class="sp-label">Collection tags</span>
          <div id="collectionTagList" class="sp-collection-tag-list"></div>
          <form id="collectionTagForm" class="sp-collection-tag-form">
            <input type="text" id="collectionTagInput" maxlength="32" placeholder="Add tag…" autocomplete="off" />
            <button type="submit" class="sp-btn-primary">Add</button>
          </form>
        </div>
        <div class="sp-collection-list-controls">
          <div class="sp-collection-search">
            <input
              type="search"
              id="collectionSearch"
              class="sp-collection-search-input"
              placeholder="Search cards…"
              value="${esc(detailQuery)}"
              autocomplete="off"
              spellcheck="false"
            />
            <span class="sp-collection-search-count" id="collectionSearchCount"></span>
          </div>
          <label class="sp-collection-control">
            <span class="sp-label">Sort cards</span>
            <select id="detailSort">
              <option value="saved"${detailSort === "saved" ? " selected" : ""}>Date saved</option>
              <option value="name"${detailSort === "name" ? " selected" : ""}>Name</option>
              <option value="set"${detailSort === "set" ? " selected" : ""}>Set</option>
              <option value="number"${detailSort === "number" ? " selected" : ""}>Number</option>
            </select>
          </label>
        </div>
        <p class="sp-collections-actions">
          <a class="sp-add-cards-btn" href="/collections/${esc(id)}/add">+ Add cards</a>
          ${isFav ? "" : importDropdownHtml(id)}
        </p>
      </div>
      ${
        cards.length
          ? `<div class="sp-grid sp-collections-grid" id="collectionGrid"></div>
             <p class="sp-empty" id="collectionGridEmpty" hidden></p>`
          : `<p class="sp-empty">${
              isFav
                ? "No favorites yet. Open a card on Search and tap ♡ Favorite, or use Add cards."
                : "No cards yet. Use Add cards to search and tap printings to save them here, or import a cube JSON."
            }</p>`
      }`;

    bindTagEditor(id, coll.tags || []);

    const searchInput = document.getElementById("collectionSearch");
    if (searchInput) {
      searchInput.addEventListener("input", () => {
        detailQuery = searchInput.value;
        writeCollectionDetailToUrl();
        renderDetailGrid(id);
      });
    }
    document.getElementById("detailSort")?.addEventListener("change", async (e) => {
      detailSort = e.target.value;
      writeCollectionDetailToUrl();
      await renderDetail(id);
    });
    if (cards.length) renderDetailGrid(id);
  }

  async function boot() {
    bindImportUi();
    bindModalUi();
    if (window.__spelltagAuthReady) {
      try {
        await window.__spelltagAuthReady;
      } catch (_) {
        /* ignore */
      }
    }
    const id = collectionIdFromPath();
    try {
      if (id) await renderDetail(id);
      else await renderList();
    } catch (err) {
      root.innerHTML = `<p class="sp-empty">${esc(err.message || "Something went wrong")}</p>`;
    }
  }

  boot();
})();
