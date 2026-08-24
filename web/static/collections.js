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

  async function renderList() {
    const data = await api("/api/me/collections");
    if (!data) return;
    const rows = data.collections || [];
    root.innerHTML = `
      <div class="sp-collections-head">
        <h1 class="sp-collections-title">My Collections</h1>
        <p class="sp-hint">Save favorite arts from Search, then browse them here.</p>
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

  function renderCardTile(c, collectionId) {
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
        </p>
      </div>
      ${
        cards.length
          ? `<div class="sp-grid sp-collections-grid">
              ${cards.map((c) => renderCardTile(c, id)).join("")}
            </div>`
          : `<p class="sp-empty">${
              isFav
                ? "No favorites yet. Open a card on Search and tap ♡ Favorite, or use Add cards."
                : "No cards yet. Use Add cards to search and tap printings to save them here."
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
