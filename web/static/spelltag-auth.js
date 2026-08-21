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

  function renderSignedOut() {
    accountEl.innerHTML =
      '<a class="sp-topbar-login" href="/auth/google/login">Sign in</a>';
  }

  function renderSignedIn(user) {
    const name = esc(user.name || user.email || "Account");
    const pic = user.picture_url
      ? `<img class="sp-topbar-avatar" src="${esc(user.picture_url)}" alt="" width="28" height="28" referrerpolicy="no-referrer" />`
      : `<span class="sp-topbar-avatar sp-topbar-avatar-fallback" aria-hidden="true">${esc(
          (user.name || user.email || "?").slice(0, 1).toUpperCase()
        )}</span>`;
    accountEl.innerHTML = `
      <div class="sp-topbar-profile" title="${name}">
        ${pic}
        <span class="sp-topbar-profile-name">${name}</span>
      </div>
      <button type="button" class="sp-topbar-logout" id="spelltagLogout">Sign out</button>
    `;
    const btn = document.getElementById("spelltagLogout");
    if (btn) {
      btn.addEventListener("click", async () => {
        btn.disabled = true;
        try {
          await fetch("/auth/logout", { method: "POST", credentials: "same-origin" });
        } catch (_) { /* ignore */ }
        renderSignedOut();
      });
    }
  }

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

  refresh();
})();
