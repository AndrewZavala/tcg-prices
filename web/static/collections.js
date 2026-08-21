(function () {
  const root = document.getElementById("collectionsRoot");
  if (!root) return;

  const CARD_IMG_FALLBACK = "/static/empty-pokeball.png";

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
    return `<img class="sp-card-img" src="${esc(url)}" alt="${esc(alt || "")}" loading="lazy" onerror="this.onerror=null;this.src='${CARD_IMG_FALLBACK}';this.classList.add('is-fallback')" />`;
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
      throw new Error(err.detail || `Request failed (${resp.status})`);
    }
    return resp.json();
  }

  async function renderList() {
    const data = await api("/api/me/collections");
    if (!data) return;
    const rows = data.collections || [];
    root.innerHTML = `
      <div class="sp-collections-head">
        <h1 class="sp-collections-title">My Collections</h1>
        <form class="sp-new-collection" id="newCollectionForm">
          <input type="text" name="name" maxlength="80" placeholder="New collection name" required />
          <button type="submit">Create</button>
        </form>
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

  async function renderDetail(id) {
    const data = await api(`/api/me/collections/${encodeURIComponent(id)}`);
    if (!data) return;
    const coll = data.collection;
    const cards = data.cards || [];
    root.innerHTML = `
      <div class="sp-collections-head">
        <p class="sp-collections-back"><a href="/collections">← All collections</a></p>
        <h1 class="sp-collections-title">${esc(coll.name)}${
          coll.kind === "favorites" ? ' <span class="sp-collection-badge">♥</span>' : ""
        }</h1>
        <p class="sp-hint">${cards.length} saved art${cards.length === 1 ? "" : "s"}</p>
      </div>
      ${
        cards.length
          ? `<div class="sp-grid sp-collections-grid">
              ${cards
                .map(
                  (c) => `
                <article class="sp-card sp-collection-card" data-id="${esc(c.id)}" title="${esc(c.name)} — ${esc(c.set_name)} #${esc(c.local_id)}">
                  <a href="/?q=${encodeURIComponent(c.name)}" class="sp-collection-card-link">
                    ${cardImg(c.image_url, c.name)}
                  </a>
                  <button type="button" class="sp-collection-remove" data-card-id="${esc(c.id)}" title="Remove from collection">Remove</button>
                </article>`
                )
                .join("")}
            </div>`
          : `<p class="sp-empty">No cards yet. Open a card from Search and tap Favorite or Add to collection.</p>`
      }`;

    root.querySelectorAll(".sp-collection-remove").forEach((btn) => {
      btn.addEventListener("click", async () => {
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
    if (window.__spelltagAuthReady) {
      try {
        await window.__spelltagAuthReady;
      } catch (_) { /* ignore */ }
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
