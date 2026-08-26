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

  let importCubeData = null;
  let importPreviewData = null;
  let importPreselectId = null;
  let importUiBound = false;

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

  function cardImg(src, alt) {
    const url = src || CARD_IMG_FALLBACK;
    return `<img src="${esc(url)}" alt="${esc(alt || "")}" loading="lazy" decoding="async" onerror="this.onerror=null;this.src='${CARD_IMG_FALLBACK}';this.classList.add('is-fallback')" />`;
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
      const btn = e.target.closest("[data-import-cube]");
      if (!btn) return;
      openImportModal(btn.dataset.importCube || null);
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
    const data = await api("/api/me/collections");
    if (!data) return;
    const rows = data.collections || [];
    root.innerHTML = `
      <div class="sp-collections-head">
        <h1 class="sp-collections-title">My Collections</h1>
        <p class="sp-hint">Save favorite arts from Search, then browse them here.</p>
        <div class="sp-collections-toolbar">
          <form class="sp-new-collection" id="newCollectionForm">
            <input type="text" name="name" maxlength="80" placeholder="New collection name" required />
            <button type="submit">Create</button>
          </form>
          <button type="button" class="sp-import-btn" data-import-cube>Import cube JSON</button>
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
              }</span>
              <span class="sp-collection-count">${c.item_count} card${c.item_count === 1 ? "" : "s"}</span>
            </a>
          </li>`
          )
          .join("")}
      </ul>`;

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
      <div class="sp-collection-item">
        <article class="sp-card" data-id="${esc(c.id)}" title="${esc(label)}" tabindex="0" aria-label="${esc(label)}">
          ${cardImg(c.image_url, label)}
        </article>
        <div class="sp-collection-caption">
          <div class="sp-collection-card-name">${esc(c.name)}</div>
          <div class="sp-collection-card-set">${esc(c.set_name)} · #${esc(c.local_id)}</div>
        </div>
        <button type="button" class="sp-collection-remove" data-card-id="${esc(c.id)}" title="Remove from collection">Remove</button>
      </div>`;
  }

  async function renderDetail(id) {
    const data = await api(`/api/me/collections/${encodeURIComponent(id)}`);
    if (!data) return;
    const coll = data.collection;
    const cards = data.cards || [];
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
        } · ${cards.length} saved</p>
        <p class="sp-collections-actions">
          <a class="sp-add-cards-btn" href="/collections/${esc(id)}/add">+ Add cards</a>
          ${
            isFav
              ? ""
              : `<button type="button" class="sp-import-btn" data-import-cube="${esc(id)}">Import cube JSON</button>`
          }
        </p>
      </div>
      ${
        cards.length
          ? `<div class="sp-grid sp-collections-grid">
              ${cards.map((c) => renderCardTile(c)).join("")}
            </div>`
          : `<p class="sp-empty">${
              isFav
                ? "No favorites yet. Open a card on Search and tap ♡ Favorite, or use Add cards."
                : "No cards yet. Use Add cards to search and tap printings to save them here, or import a cube JSON."
            }</p>`
      }`;

    root.querySelectorAll(".sp-card[data-id]").forEach((el) => {
      const openSearch = () => {
        const name = el.getAttribute("aria-label")?.split(" — ")[0] || "";
        window.location.href = `/?q=${encodeURIComponent(name)}`;
      };
      el.addEventListener("click", openSearch);
      el.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          openSearch();
        }
      });
    });

    root.querySelectorAll(".sp-collection-remove").forEach((btn) => {
      btn.addEventListener("click", async (e) => {
        e.stopPropagation();
        const cardId = btn.dataset.cardId;
        try {
          await api(
            `/api/me/collections/${encodeURIComponent(id)}/items/${encodeURIComponent(cardId)}`,
            { method: "DELETE" }
          );
          await renderDetail(id);
        } catch (err) {
          alert(err.message || "Could not remove");
        }
      });
    });
  }

  async function boot() {
    bindImportUi();
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
