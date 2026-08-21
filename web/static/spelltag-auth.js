(function () {
  const accountEl = document.querySelector(".sp-topbar-account");
  if (!accountEl) return;

  function esc(s) {
    return String(s ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function closeMenus() {
    accountEl.querySelectorAll(".sp-account-menu").forEach((m) => m.remove());
    accountEl.querySelectorAll(".sp-topbar-profile[aria-expanded='true']").forEach((el) => {
      el.setAttribute("aria-expanded", "false");
    });
  }

  function renderSignedOut() {
    accountEl.innerHTML =
      '<a class="sp-topbar-login" href="/auth/google/login">Sign in</a>';
    window.__spelltagUser = null;
  }

  function renderSignedIn(user) {
    window.__spelltagUser = user;
    const name = esc(user.name || user.email || "Account");
    const pic = user.picture_url
      ? `<img class="sp-topbar-avatar" src="${esc(user.picture_url)}" alt="" width="28" height="28" referrerpolicy="no-referrer" />`
      : `<span class="sp-topbar-avatar sp-topbar-avatar-fallback" aria-hidden="true">${esc(
          (user.name || user.email || "?").slice(0, 1).toUpperCase()
        )}</span>`;
    accountEl.innerHTML = `
      <div class="sp-account-wrap">
        <button type="button" class="sp-topbar-profile" id="spelltagAccountBtn" aria-expanded="false" aria-haspopup="true">
          ${pic}
          <span class="sp-topbar-profile-name">${name}</span>
          <span class="sp-account-caret" aria-hidden="true">▾</span>
        </button>
      </div>
    `;
    const btn = document.getElementById("spelltagAccountBtn");
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      const open = btn.getAttribute("aria-expanded") === "true";
      closeMenus();
      if (open) return;
      btn.setAttribute("aria-expanded", "true");
      const menu = document.createElement("div");
      menu.className = "sp-account-menu";
      menu.setAttribute("role", "menu");
      menu.innerHTML = `
        <a class="sp-account-menu-item" role="menuitem" href="/collections">My Collections</a>
        <button type="button" class="sp-account-menu-item is-placeholder" role="menuitem" disabled title="Coming soon">Decks</button>
        <button type="button" class="sp-account-menu-item" role="menuitem" id="spelltagLogout">Sign out</button>
      `;
      btn.parentElement.appendChild(menu);
      document.getElementById("spelltagLogout").addEventListener("click", async () => {
        try {
          await fetch("/auth/logout", { method: "POST", credentials: "same-origin" });
        } catch (_) { /* ignore */ }
        closeMenus();
        renderSignedOut();
      });
    });
  }

  document.addEventListener("click", () => closeMenus());

  async function refresh() {
    try {
      const resp = await fetch("/auth/me", { credentials: "same-origin" });
      if (!resp.ok) {
        renderSignedOut();
        return;
      }
      const data = await resp.json();
      if (data && data.authenticated) renderSignedIn(data);
      else renderSignedOut();
    } catch (_) {
      renderSignedOut();
    }
  }

  window.__spelltagAuthReady = refresh();
  refresh();
})();
