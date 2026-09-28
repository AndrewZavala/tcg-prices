(function () {
  const statusEl = document.getElementById("loginStatus");
  const buttons = {
    google: document.getElementById("loginGoogle"),
    discord: document.getElementById("loginDiscord"),
  };

  (async () => {
    try {
      await window.__spelltagAuthReady;
    } catch (_) { /* ignore */ }
    if (window.__spelltagUser) {
      location.replace("/");
      return;
    }
    try {
      const resp = await fetch("/auth/status", { credentials: "same-origin" });
      if (!resp.ok) return;
      const status = await resp.json();
      buttons.google.hidden = !status.google_configured;
      buttons.discord.hidden = !status.discord_configured;
      if (!status.google_configured && !status.discord_configured) {
        statusEl.textContent = "Sign-in isn't available right now.";
        statusEl.hidden = false;
      }
    } catch (_) { /* leave both buttons visible */ }
  })();
})();
