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
  let detailGroup = "none";
  let detailView = "spoiler";
  let detailKnownTags = [];
  let detailIsOwner = true;
  let listSort = "name";

  function esc(s) {
    return String(s ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function collectionIdFromPath() {
    const ref = collectionRefFromPath();
    return ref?.type === "id" ? ref.id : null;
  }

  function collectionRefFromPath() {
    const slugMatch = location.pathname.match(/^\/c\/([^/]+)\/?$/);
    if (slugMatch) return { type: "slug", id: decodeURIComponent(slugMatch[1]) };
    const idMatch = location.pathname.match(/^\/collections\/([^/]+)\/?$/);
    if (idMatch && idMatch[1] !== "add") {
      return { type: "id", id: decodeURIComponent(idMatch[1]) };
    }
    return null;
  }

  function collectionGroupFromUrl() {
    return new URLSearchParams(location.search).get("group") || "";
  }

  function collectionViewFromUrl() {
    return new URLSearchParams(location.search).get("view") || "";
  }

  function collectionSearchFromUrl() {
    return new URLSearchParams(location.search).get("q") || "";
  }

  function collectionSortFromUrl() {
    return new URLSearchParams(location.search).get("sort") || "";
  }

  function writeCollectionListToUrl() {
    const params = new URLSearchParams();
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
    if (detailGroup && detailGroup !== "none") params.set("group", detailGroup);
    if (detailView && detailView !== "spoiler") params.set("view", detailView);
    const qs = params.toString();
    const next = qs ? `${location.pathname}?${qs}` : location.pathname;
    if (next !== `${location.pathname}${location.search}`) {
      history.replaceState(null, "", next);
    }
  }

  function renderTagPills(tags) {
    if (!tags?.length) return "";
    return `<span class="sp-collection-tag-row">${tags
      .map((tag) => `<span class="sp-collection-tag">${esc(tag)}</span>`)
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

  async function saveCardTags(collectionId, cardId, tags) {
    const data = await api(
      `/api/me/collections/${encodeURIComponent(collectionId)}/items/${encodeURIComponent(cardId)}/tags`,
      {
        method: "PUT",
        body: JSON.stringify({ tags }),
      }
    );
    return data.tags || [];
  }

  function syncCardTagsInState(cardId, tags) {
    const row = detailCards.find((c) => c.id === cardId);
    if (row) row.tags = tags;
    const known = new Set(detailKnownTags);
    for (const t of tags) known.add(t);
    detailKnownTags = [...known].sort();
  }

  function bindCardTagEditor(collectionId, cardId, initialTags) {
    const listEl = document.getElementById("cardTagList");
    const form = document.getElementById("cardTagForm");
    const input = document.getElementById("cardTagInput");
    const datalist = document.getElementById("cardTagSuggestions");
    if (!listEl || !form || !input) return;

    let current = [...(initialTags || [])];
    if (datalist) {
      datalist.innerHTML = detailKnownTags
        .map((tag) => `<option value="${esc(tag)}"></option>`)
        .join("");
    }

    const renderTags = () => {
      listEl.innerHTML = current.length
        ? current
            .map(
              (tag) =>
                `<button type="button" class="sp-collection-tag sp-collection-tag-removable" data-tag="${esc(
                  tag
                )}" title="Remove tag">${esc(tag)} ×</button>`
            )
            .join("")
        : `<span class="sp-hint">No tags — add labels like draw, recycle, ramp.</span>`;
      listEl.querySelectorAll("[data-tag]").forEach((btn) => {
        btn.addEventListener("click", async () => {
          const next = current.filter((t) => t !== btn.dataset.tag);
          btn.disabled = true;
          try {
            current = await saveCardTags(collectionId, cardId, next);
            syncCardTagsInState(cardId, current);
            renderTags();
          } catch (err) {
            alert(err.message || "Could not update tags");
            btn.disabled = false;
          }
        });
      });
    };

    renderTags();
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const slug = normalizeTagInput(input.value);
      if (!slug) return;
      const next = [...new Set([...current, slug])].sort();
      try {
        current = await saveCardTags(collectionId, cardId, next);
        syncCardTagsInState(cardId, current);
        input.value = "";
        renderTags();
      } catch (err) {
        alert(err.message || "Could not add tag");
      }
    });
  }

  function cardById(cardId) {
    return detailCards.find((c) => c.id === cardId);
  }

  function updatePreviewPanel(card) {
    const empty = document.getElementById("collectionPreviewEmpty");
    const body = document.getElementById("collectionPreviewBody");
    const img = document.getElementById("previewImg");
    const nameEl = document.getElementById("previewName");
    const metaEl = document.getElementById("previewMeta");
    if (!empty || !body || !img) return;
    if (!card) {
      empty.hidden = false;
      body.hidden = true;
      return;
    }
    empty.hidden = true;
    body.hidden = false;
    img.src = card.image_url_high || card.image_url || CARD_IMG_FALLBACK;
    img.alt = card.name || "";
    if (nameEl) nameEl.textContent = card.name || "";
    if (metaEl) {
      metaEl.textContent = `${card.set_name || "—"} · #${card.local_id || "—"}${
        card.rarity ? ` · ${card.rarity}` : ""
      }`;
    }
  }

  function bindCardPreviewHover(scope) {
    const rootEl = scope || document;
    rootEl.querySelectorAll("[data-id].sp-collection-card, [data-id].sp-collection-stack-card").forEach((el) => {
      el.addEventListener("mouseenter", () => {
        updatePreviewPanel(cardById(el.dataset.id));
      });
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
      ...(card.tags || []),
    ]
      .filter(Boolean)
      .join(" ")
      .toLowerCase();
    return hay.includes(q);
  }

  function filteredDetailCards() {
    return detailCards.filter((c) => cardMatchesQuery(c, detailQuery));
  }

  function supportsConsidering() {
    return detailIsOwner && detailColl?.kind !== "favorites";
  }

  function cardBucket(card) {
    return card?.bucket === "considering" ? "considering" : "main";
  }

  function filteredMainCards() {
    return filteredDetailCards().filter((c) => cardBucket(c) === "main");
  }

  function filteredConsideringCards() {
    if (!supportsConsidering()) return [];
    return filteredDetailCards().filter((c) => cardBucket(c) === "considering");
  }

  function defaultPreviewCard() {
    const main = filteredMainCards();
    if (main.length) return main[0];
    const considering = filteredConsideringCards();
    return considering.length ? considering[0] : null;
  }

  async function setCardBucket(collectionId, cardId, bucket) {
    const data = await api(
      `/api/me/collections/${encodeURIComponent(collectionId)}/items/${encodeURIComponent(cardId)}`,
      {
        method: "PATCH",
        body: JSON.stringify({ bucket }),
      }
    );
    const row = detailCards.find((c) => c.id === cardId);
    if (row) row.bucket = data.bucket || bucket;
    return data;
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
    const savedRow = detailCards.find((c) => c.id === cardId);
    const initialTags = savedRow?.tags || [];
    const bucket = cardBucket(savedRow);
    const showConsidering = supportsConsidering() && collectionId && detailIsOwner;
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
                  showConsidering
                    ? bucket === "considering"
                      ? `<button type="button" class="sp-btn-secondary sp-collection-bucket-modal" data-bucket="main">Move to main collection</button>`
                      : `<button type="button" class="sp-btn-secondary sp-collection-bucket-modal" data-bucket="considering">Move to considering</button>`
                    : ""
                }
                ${
                  collectionId && detailIsOwner
                    ? `<button type="button" class="sp-collection-remove sp-collection-remove-modal" data-card-id="${esc(
                        card.id
                      )}">Remove from collection</button>`
                    : ""
                }
              </p>
            </div>
            ${
              collectionId && detailIsOwner
                ? `<div class="sp-collection-tags-panel sp-card-tags-panel">
                    <span class="sp-label">Your tags</span>
                    <p class="sp-hint">Private to this collection — e.g. draw, recycle, finisher.</p>
                    <div id="cardTagList" class="sp-collection-tag-list"></div>
                    <form id="cardTagForm" class="sp-collection-tag-form">
                      <input type="text" id="cardTagInput" list="cardTagSuggestions" maxlength="32" placeholder="Add tag…" autocomplete="off" />
                      <datalist id="cardTagSuggestions"></datalist>
                      <button type="submit" class="sp-btn-primary">Add</button>
                    </form>
                  </div>`
                : ""
            }
            ${card.evolve_from ? `<p class="sp-hint">Evolves from ${esc(card.evolve_from)}</p>` : ""}
            ${renderCardText(card)}
            ${renderAbilities(card)}
            ${renderAttacks(card)}
          </div>
        </div>`;
      if (collectionId && detailIsOwner) bindCardTagEditor(collectionId, cardId, initialTags);
      modalBody.querySelector(".sp-collection-bucket-modal")?.addEventListener("click", async (e) => {
        if (!detailIsOwner || !collectionId) return;
        const btn = e.currentTarget;
        const nextBucket = btn.dataset.bucket;
        if (!nextBucket) return;
        btn.disabled = true;
        try {
          await setCardBucket(collectionId, cardId, nextBucket);
          cardModal.close();
          renderDetailGrid(collectionId);
        } catch (err) {
          alert(err.message || "Could not move card");
          btn.disabled = false;
        }
      });
      modalBody.querySelector(".sp-collection-remove-modal")?.addEventListener("click", async (e) => {
        if (!detailIsOwner || !collectionId) return;
        const btn = e.currentTarget;
        btn.disabled = true;
        try {
          await api(
            `/api/me/collections/${encodeURIComponent(collectionId)}/items/${encodeURIComponent(cardId)}`,
            { method: "DELETE" }
          );
          cardModal.close();
          await renderDetail({ type: "id", id: collectionId });
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
      if (opts?.allow401) return null;
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

  async function apiPublic(path) {
    const resp = await fetch(path, { credentials: "same-origin" });
    if (resp.status === 404) {
      throw new Error("Collection not found or private");
    }
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      const detail = err.detail;
      throw new Error(typeof detail === "string" ? detail : `Request failed (${resp.status})`);
    }
    return resp.json();
  }

  async function fetchCollectionDetail(ref) {
    const params = new URLSearchParams();
    if (detailSort !== "saved") params.set("sort", detailSort);
    if (detailGroup && detailGroup !== "none") params.set("group", detailGroup);
    const qs = params.toString();
    const suffix = qs ? `?${qs}` : "";

    if (ref.type === "slug") {
      return apiPublic(`/api/collections/${encodeURIComponent(ref.id)}${suffix}`);
    }

    const meResp = await fetch(
      `/api/me/collections/${encodeURIComponent(ref.id)}${suffix}`,
      { credentials: "same-origin" }
    );
    if (meResp.ok) return meResp.json();
    if (meResp.status === 401) {
      return apiPublic(`/api/collections/${encodeURIComponent(ref.id)}${suffix}`);
    }
    if (meResp.status === 404) {
      try {
        return await apiPublic(`/api/collections/${encodeURIComponent(ref.id)}${suffix}`);
      } catch (_) {
        throw new Error("Collection not found");
      }
    }
    const err = await meResp.json().catch(() => ({}));
    throw new Error(typeof err.detail === "string" ? err.detail : "Request failed");
  }

  function visibilityBadge(visibility) {
    if (visibility === "public") {
      return '<span class="sp-collection-visibility-badge is-public">Public</span>';
    }
    if (visibility === "unlisted") {
      return '<span class="sp-collection-visibility-badge is-unlisted">Unlisted</span>';
    }
    return "";
  }

  const CATEGORY_LABELS = { Pokemon: "Pokémon", Trainer: "Trainer", Energy: "Energy" };
  const CATEGORY_ORDER = ["Pokemon", "Trainer", "Energy"];

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
        await renderDetail({ type: "id", id: cid });
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
    listSort = collectionSortFromUrl() || "name";
    const params = new URLSearchParams();
    if (listSort && listSort !== "name") params.set("sort", listSort);
    const qs = params.toString();
    const data = await api(`/api/me/collections${qs ? `?${qs}` : ""}`);
    if (!data) return;
    const rows = data.collections || [];
    root.innerHTML = `
      <div class="sp-collections-head">
        <h1 class="sp-collections-title">My Collections</h1>
        <p class="sp-hint">Save favorite arts from Search, then browse them here.</p>
        <div class="sp-collection-list-controls">
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
        ${rows
          .map(
            (c) => `
          <li>
            <a class="sp-collection-row" href="/collections/${esc(c.id)}">
              <span class="sp-collection-name">${esc(c.name)}${
                c.kind === "favorites" ? ' <span class="sp-collection-badge">♥</span>' : ""
              } ${visibilityBadge(c.visibility)}</span>
              <span class="sp-collection-count">${c.item_count} card${c.item_count === 1 ? "" : "s"}</span>
            </a>
          </li>`
          )
          .join("")}
      </ul>`;

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

  function stackCategoryClass(c) {
    const cat = String(c.category || "").toLowerCase();
    if (cat === "pokemon") return "is-pokemon";
    if (cat === "trainer") return "is-trainer";
    if (cat === "energy") return "is-energy";
    return "";
  }

  function renderCardStack(c) {
    const label = `${c.name} — ${c.set_name} #${c.local_id}`;
    const art = esc(c.image_url || CARD_IMG_FALLBACK);
    return `
      <article class="sp-collection-stack-card ${stackCategoryClass(c)}" data-id="${esc(c.id)}" tabindex="0" aria-label="${esc(label)}">
        <div class="sp-stack-bar">
          <span class="sp-stack-art" style="background-image:url('${art}')" aria-hidden="true"></span>
          <span class="sp-stack-name">${esc(c.name)}</span>
          <span class="sp-stack-meta">#${esc(c.local_id || "—")}</span>
        </div>
        <div class="sp-stack-body">
          ${cardImg(c.image_url, label, "sp-stack-img")}
        </div>
      </article>`;
  }

  function bucketCardsByCategory(cards) {
    const buckets = new Map();
    for (const c of cards) {
      const key = c.category || "Unknown";
      if (!buckets.has(key)) buckets.set(key, []);
      buckets.get(key).push(c);
    }
    const keys = CATEGORY_ORDER.filter((k) => buckets.has(k) && buckets.get(k).length);
    for (const k of buckets.keys()) {
      if (!keys.includes(k) && buckets.get(k).length) keys.push(k);
    }
    return { buckets, keys };
  }

  function bindCollectionGrid(collectionId, scope) {
    const rootEl = scope || document;
    rootEl.querySelectorAll(".sp-collection-card[data-id], .sp-collection-stack-card[data-id]").forEach((el) => {
      const open = () => openCardDetail(el.dataset.id, detailIsOwner ? collectionId : null);
      el.addEventListener("click", open);
      el.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          open();
        }
      });
    });
    bindCardPreviewHover(rootEl);
  }

  function renderGroupedGridHtml(cards) {
    const { buckets, keys } = bucketCardsByCategory(cards);
    return keys
      .map((key) => {
        const groupCards = buckets.get(key) || [];
        const label = CATEGORY_LABELS[key] || key;
        return `<section class="sp-collection-group">
          <h2 class="sp-collection-group-title">${esc(label)} <span class="sp-collection-group-count">${groupCards.length}</span></h2>
          <div class="sp-grid sp-collections-grid">${groupCards.map((c) => renderCardTile(c)).join("")}</div>
        </section>`;
      })
      .join("");
  }

  function renderGroupedStacksHtml(cards) {
    const { buckets, keys } = bucketCardsByCategory(cards);
    return `<div class="sp-collection-stack-columns">${keys
      .map((key) => {
        const groupCards = buckets.get(key) || [];
        const label = CATEGORY_LABELS[key] || key;
        return `<section class="sp-collection-stack-column">
          <h2 class="sp-collection-group-title">${esc(label)} <span class="sp-collection-group-count">${groupCards.length}</span></h2>
          <div class="sp-collection-stack">${groupCards.map((c) => renderCardStack(c)).join("")}</div>
        </section>`;
      })
      .join("")}</div>`;
  }

  function renderStacksHtml(cards) {
    return `<div class="sp-collection-stack sp-collection-stack-solo">${cards
      .map((c) => renderCardStack(c))
      .join("")}</div>`;
  }

  function renderCardsHtml(cards) {
    if (detailView === "stacks") {
      return detailGroup === "category" ? renderGroupedStacksHtml(cards) : renderStacksHtml(cards);
    }
    if (detailGroup === "category") {
      return renderGroupedGridHtml(cards);
    }
    return `<div class="sp-grid sp-collections-grid">${cards.map((c) => renderCardTile(c)).join("")}</div>`;
  }

  function renderCardsIntoMount(mount, cards, collectionId) {
    if (!mount) return;
    if (!cards.length) {
      mount.innerHTML = "";
      mount.hidden = true;
      return;
    }
    mount.hidden = false;
    mount.classList.toggle("is-stacks", detailView === "stacks");
    mount.classList.toggle("is-spoiler", detailView !== "stacks");
    mount.innerHTML = renderCardsHtml(cards);
    bindCollectionGrid(collectionId, mount);
  }

  function renderDetailGrid(collectionId) {
    const mainMount = document.getElementById("collectionGridMount");
    const consideringMount = document.getElementById("consideringGridMount");
    const consideringSection = document.getElementById("consideringSection");
    const mainEmptyEl = document.getElementById("collectionMainEmpty");
    const countEl = document.getElementById("collectionSearchCount");
    const emptyEl = document.getElementById("collectionGridEmpty");
    if (!mainMount) return;

    const mainCards = filteredMainCards();
    const consideringCards = filteredConsideringCards();
    const visibleTotal = mainCards.length + consideringCards.length;
    const total = detailCards.length;

    if (countEl) {
      if (detailQuery && visibleTotal !== total) {
        countEl.textContent = `${visibleTotal} of ${total}`;
      } else if (supportsConsidering()) {
        const mainCount = detailCards.filter((c) => cardBucket(c) === "main").length;
        const consideringCount = detailCards.filter((c) => cardBucket(c) === "considering").length;
        countEl.textContent =
          consideringCount > 0
            ? `${mainCount} main · ${consideringCount} considering`
            : `${total} card${total === 1 ? "" : "s"}`;
      } else {
        countEl.textContent = `${total} card${total === 1 ? "" : "s"}`;
      }
    }

    if (visibleTotal) {
      renderCardsIntoMount(mainMount, mainCards, collectionId);
      if (mainEmptyEl) {
        mainEmptyEl.hidden = mainCards.length > 0 || !supportsConsidering();
        mainEmptyEl.textContent = detailQuery
          ? "No main cards match your search."
          : "No cards in the main collection yet.";
      }
      if (consideringSection && consideringMount) {
        if (consideringCards.length) {
          consideringSection.hidden = false;
          const consideringCountEl = document.getElementById("consideringCount");
          if (consideringCountEl) {
            consideringCountEl.textContent = String(consideringCards.length);
          }
          renderCardsIntoMount(consideringMount, consideringCards, collectionId);
        } else {
          consideringSection.hidden = true;
          consideringMount.innerHTML = "";
          consideringMount.hidden = true;
        }
      }
      if (emptyEl) emptyEl.hidden = true;
      updatePreviewPanel(defaultPreviewCard());
    } else {
      mainMount.innerHTML = "";
      mainMount.hidden = true;
      if (consideringMount) {
        consideringMount.innerHTML = "";
        consideringMount.hidden = true;
      }
      if (consideringSection) consideringSection.hidden = true;
      if (mainEmptyEl) mainEmptyEl.hidden = true;
      updatePreviewPanel(null);
      if (emptyEl) {
        emptyEl.hidden = false;
        emptyEl.textContent = detailQuery
          ? `No cards match “${detailQuery}”.`
          : "No cards in this collection.";
      }
    }
  }

  async function patchCollection(id, body) {
    return api(`/api/me/collections/${encodeURIComponent(id)}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    });
  }

  function bindSharePanel(collectionId, coll) {
    const visEl = document.getElementById("visibilitySelect");
    const slugEl = document.getElementById("shareSlug");
    const copyBtn = document.getElementById("copyShareLink");
    const statusEl = document.getElementById("shareStatus");
    if (!visEl) return;

    const syncSlugVisibility = () => {
      const shareable = visEl.value === "unlisted" || visEl.value === "public";
      document.getElementById("shareSlugWrap")?.toggleAttribute("hidden", !shareable);
      copyBtn?.toggleAttribute("hidden", !shareable);
    };

    syncSlugVisibility();

    visEl.addEventListener("change", async () => {
      visEl.disabled = true;
      try {
        const data = await patchCollection(collectionId, { visibility: visEl.value });
        detailColl = data.collection;
        syncSlugVisibility();
        if (statusEl) statusEl.textContent = "Saved";
      } catch (err) {
        alert(err.message || "Could not update visibility");
        visEl.value = coll.visibility || "private";
      } finally {
        visEl.disabled = false;
      }
    });

    slugEl?.addEventListener("change", async () => {
      const slug = String(slugEl.value || "").trim();
      slugEl.disabled = true;
      try {
        const data = await patchCollection(collectionId, { share_slug: slug });
        detailColl = data.collection;
        slugEl.value = detailColl.share_slug || "";
        if (statusEl) statusEl.textContent = "Link updated";
      } catch (err) {
        alert(err.message || "Could not update link slug");
        slugEl.value = coll.share_slug || "";
      } finally {
        slugEl.disabled = false;
      }
    });

    copyBtn?.addEventListener("click", async () => {
      const url = detailColl?.public_url || coll.public_url;
      if (!url) return;
      try {
        await navigator.clipboard.writeText(url);
        if (statusEl) statusEl.textContent = "Copied!";
      } catch (_) {
        prompt("Copy this link:", url);
      }
    });
  }

  async function renderDetail(ref) {
    detailSort = collectionSortFromUrl() || "saved";
    detailGroup = collectionGroupFromUrl() || "none";
    detailView = collectionViewFromUrl() || "spoiler";
    if (detailView !== "stacks") detailView = "spoiler";
    detailQuery = collectionSearchFromUrl();

    const data = await fetchCollectionDetail(ref);
    detailCollectionId = data.collection.id;
    detailColl = data.collection;
    detailCards = data.cards || [];
    detailKnownTags = data.card_tags || [];
    detailIsOwner = data.is_owner !== false;
    if (data.sort) detailSort = data.sort;
    if (data.group) detailGroup = data.group;

    const coll = detailColl;
    const isFav = coll.kind === "favorites";
    const ownerName = coll.owner?.name;

    const sharePanel =
      detailIsOwner && !isFav
        ? `<div class="sp-collection-share-panel" id="sharePanel">
            <label class="sp-collection-control">
              <span class="sp-label">Visibility</span>
              <select id="visibilitySelect">
                <option value="private"${(coll.visibility || "private") === "private" ? " selected" : ""}>Private</option>
                <option value="unlisted"${coll.visibility === "unlisted" ? " selected" : ""}>Unlisted</option>
                <option value="public"${coll.visibility === "public" ? " selected" : ""}>Public</option>
              </select>
            </label>
            <label class="sp-collection-control" id="shareSlugWrap"${
              coll.visibility === "unlisted" || coll.visibility === "public" ? "" : " hidden"
            }>
              <span class="sp-label">Link slug</span>
              <input type="text" id="shareSlug" maxlength="48" placeholder="my-cube" value="${esc(
                coll.share_slug || ""
              )}" autocomplete="off" />
            </label>
            <button type="button" class="sp-btn-secondary" id="copyShareLink"${
              coll.visibility === "unlisted" || coll.visibility === "public" ? "" : " hidden"
            }>Copy link</button>
            <span class="sp-share-status" id="shareStatus" aria-live="polite"></span>
          </div>`
        : "";

    root.innerHTML = `
      <div class="sp-collections-head">
        <p class="sp-collections-back">${
          detailIsOwner
            ? '<a href="/collections">← All collections</a>'
            : '<a href="/">← Search</a>'
        }</p>
        <h1 class="sp-collections-title">${
          isFav ? '<span class="sp-collection-badge">♥</span> ' : ""
        }${esc(coll.name)} ${detailIsOwner ? visibilityBadge(coll.visibility) : ""}</h1>
        <p class="sp-hint">${
          !detailIsOwner && ownerName
            ? `Shared by ${esc(ownerName)} — view only.`
            : isFav
              ? "Card arts you’ve hearted from Search."
              : "Cards you’ve saved to this list. Click a card to add tags or move cards to Considering while building a cube."
        }</p>
        ${sharePanel}
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
            <span class="sp-label">View</span>
            <select id="detailView">
              <option value="spoiler"${detailView === "spoiler" ? " selected" : ""}>Visual Spoiler</option>
              <option value="stacks"${detailView === "stacks" ? " selected" : ""}>Visual Stacks</option>
            </select>
          </label>
          <label class="sp-collection-control">
            <span class="sp-label">Group</span>
            <select id="detailGroup">
              <option value="none"${detailGroup === "none" ? " selected" : ""}>None</option>
              <option value="category"${detailGroup === "category" ? " selected" : ""}>Category</option>
            </select>
          </label>
          <label class="sp-collection-control">
            <span class="sp-label">Sort</span>
            <select id="detailSort">
              <option value="saved"${detailSort === "saved" ? " selected" : ""}>Date saved</option>
              <option value="name"${detailSort === "name" ? " selected" : ""}>Name</option>
              <option value="set"${detailSort === "set" ? " selected" : ""}>Set</option>
              <option value="number"${detailSort === "number" ? " selected" : ""}>Number</option>
              <option value="type"${detailSort === "type" ? " selected" : ""}>Type</option>
              ${
                detailIsOwner
                  ? `<option value="tag"${detailSort === "tag" ? " selected" : ""}>Tag</option>`
                  : ""
              }
            </select>
          </label>
        </div>
        ${
          detailIsOwner
            ? `<p class="sp-collections-actions">
                <a class="sp-add-cards-btn" href="/collections/${esc(detailCollectionId)}/add">+ Add cards</a>
                ${isFav ? "" : importDropdownHtml(detailCollectionId)}
              </p>`
            : ""
        }
      </div>
      ${
        detailCards.length
          ? `<div class="sp-collection-body">
               <aside class="sp-collection-preview" id="collectionPreview" aria-label="Card preview">
                 <p class="sp-collection-preview-empty" id="collectionPreviewEmpty">Hover a card to preview</p>
                 <div class="sp-collection-preview-body" id="collectionPreviewBody" hidden>
                   <img id="previewImg" class="sp-preview-img sp-card-img" src="" alt="" decoding="async" />
                   <h2 class="sp-preview-name" id="previewName"></h2>
                   <p class="sp-preview-meta" id="previewMeta"></p>
                 </div>
               </aside>
               <div class="sp-collection-main">
                 <section class="sp-collection-section" aria-label="Main collection">
                   <div id="collectionGridMount"></div>
                   <p class="sp-empty sp-collection-section-empty" id="collectionMainEmpty" hidden></p>
                 </section>
                 ${
                   detailIsOwner && !isFav
                     ? `<section class="sp-collection-section sp-collection-considering" id="consideringSection" hidden aria-label="Considering">
                          <h2 class="sp-collection-group-title">Considering <span class="sp-collection-group-count" id="consideringCount"></span></h2>
                          <p class="sp-hint sp-collection-considering-hint">Cards you’re still deciding on — not shown on shared links.</p>
                          <div id="consideringGridMount"></div>
                        </section>`
                     : ""
                 }
                 <p class="sp-empty" id="collectionGridEmpty" hidden></p>
               </div>
             </div>`
          : `<p class="sp-empty">${
              isFav
                ? "No favorites yet. Open a card on Search and tap ♡ Favorite, or use Add cards."
                : detailIsOwner
                  ? "No cards yet. Use Add cards to search and tap printings to save them here, or import a cube JSON."
                  : "This collection is empty."
            }</p>`
      }`;

    if (detailIsOwner && !isFav) bindSharePanel(detailCollectionId, coll);

    const searchInput = document.getElementById("collectionSearch");
    if (searchInput) {
      searchInput.addEventListener("input", () => {
        detailQuery = searchInput.value;
        writeCollectionDetailToUrl();
        renderDetailGrid(detailCollectionId);
      });
    }
    document.getElementById("detailGroup")?.addEventListener("change", async (e) => {
      detailGroup = e.target.value;
      writeCollectionDetailToUrl();
      await renderDetail(ref);
    });
    document.getElementById("detailView")?.addEventListener("change", (e) => {
      detailView = e.target.value === "stacks" ? "stacks" : "spoiler";
      writeCollectionDetailToUrl();
      renderDetailGrid(detailCollectionId);
    });
    document.getElementById("detailSort")?.addEventListener("change", async (e) => {
      detailSort = e.target.value;
      writeCollectionDetailToUrl();
      await renderDetail(ref);
    });
    if (detailCards.length) {
      document.getElementById("collectionGridMount")?.addEventListener("mouseleave", () => {
        updatePreviewPanel(defaultPreviewCard());
      });
      renderDetailGrid(detailCollectionId);
    }
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
    const ref = collectionRefFromPath();
    try {
      if (ref) await renderDetail(ref);
      else await renderList();
    } catch (err) {
      root.innerHTML = `<p class="sp-empty">${esc(err.message || "Something went wrong")}</p>`;
    }
  }

  boot();
})();
