/** Shared UI: nav highlight, table row animation, button loading state, theme picker */
(function () {
  const THEMES = [
    { id: "bakery", label: "Bakery" },
    { id: "ocean", label: "Ocean" },
    { id: "forest", label: "Forest" },
    { id: "slate", label: "Slate" },
    { id: "plum", label: "Plum" },
    { id: "sunset", label: "Sunset" },
  ];
  const STORAGE_KEY = "manifestBreadTheme";

  function currentThemeId() {
    return document.documentElement.dataset.theme || "bakery";
  }

  function themeIndex(id) {
    const idx = THEMES.findIndex((t) => t.id === id);
    return idx >= 0 ? idx : 0;
  }

  function applyTheme(id) {
    const theme = THEMES.find((t) => t.id === id) || THEMES[0];
    if (theme.id === "bakery") {
      delete document.documentElement.dataset.theme;
    } else {
      document.documentElement.dataset.theme = theme.id;
    }
    try {
      localStorage.setItem(STORAGE_KEY, theme.id);
    } catch (_) {
      /* ignore */
    }
    const nameEl = document.getElementById("themeName");
    if (nameEl) nameEl.textContent = theme.label;
    document.querySelectorAll(".theme-picker-dot").forEach((dot) => {
      dot.classList.toggle("is-active", dot.dataset.theme === theme.id);
      dot.setAttribute("aria-current", dot.dataset.theme === theme.id ? "true" : "false");
    });
  }

  function stepTheme(delta) {
    const next = (themeIndex(currentThemeId()) + delta + THEMES.length) % THEMES.length;
    applyTheme(THEMES[next].id);
  }

  function mountThemePicker() {
    const nav = document.querySelector("nav");
    if (!nav || document.getElementById("themePicker")) return;

    const wrap = document.createElement("div");
    wrap.id = "themePicker";
    wrap.className = "theme-picker";
    wrap.setAttribute("role", "group");
    wrap.setAttribute("aria-label", "Color palette");

    const label = document.createElement("span");
    label.className = "theme-picker-label";
    label.textContent = "Theme";

    const prev = document.createElement("button");
    prev.type = "button";
    prev.className = "theme-picker-btn";
    prev.id = "themePrev";
    prev.setAttribute("aria-label", "Previous palette");
    prev.textContent = "‹";

    const name = document.createElement("span");
    name.className = "theme-picker-name";
    name.id = "themeName";

    const next = document.createElement("button");
    next.type = "button";
    next.className = "theme-picker-btn";
    next.id = "themeNext";
    next.setAttribute("aria-label", "Next palette");
    next.textContent = "›";

    const dots = document.createElement("div");
    dots.className = "theme-picker-dots";
    dots.setAttribute("aria-hidden", "true");
    for (const theme of THEMES) {
      const dot = document.createElement("button");
      dot.type = "button";
      dot.className = "theme-picker-dot";
      dot.dataset.theme = theme.id;
      dot.title = theme.label;
      dot.setAttribute("aria-label", theme.label);
      dot.addEventListener("click", () => applyTheme(theme.id));
      dots.appendChild(dot);
    }

    wrap.append(label, prev, name, next, dots);
    nav.appendChild(wrap);

    prev.addEventListener("click", () => stepTheme(-1));
    next.addEventListener("click", () => stepTheme(1));
    applyTheme(currentThemeId());
  }

  const path = window.location.pathname.replace(/\/$/, "") || "/";
  document.querySelectorAll("nav a").forEach((a) => {
    const href = a.getAttribute("href");
    const norm = href === "/" ? "/" : href.replace(/\/$/, "");
    if (norm === path || (path === "/" && href === "/")) {
      a.classList.add("active");
    }
  });

  mountThemePicker();
})();

function setButtonLoading(btn, loading) {
  if (!btn) return;
  btn.classList.toggle("is-loading", loading);
  if (loading) {
    if (!btn.dataset.prevText) btn.dataset.prevText = btn.textContent;
    btn.textContent = "Baking…";
  } else {
    btn.textContent = btn.dataset.prevText || btn.textContent;
  }
}

function animateTableRows(tbody) {
  if (!tbody) return;
  tbody.querySelectorAll("tr").forEach((tr, i) => {
    tr.classList.remove("row-in");
    tr.style.animationDelay = `${Math.min(i * 0.02, 0.4)}s`;
    void tr.offsetWidth;
    tr.classList.add("row-in");
  });
}

function setStatusLoading(el, loading, message) {
  if (!el) return;
  if (loading) {
    el.textContent = message || "Loading…";
    el.className = "status-loading";
  } else {
    el.className = "";
    el.textContent = "";
  }
}

/** Card Kingdom buylist advanced search by card name (matches CK's mtg_singles filter URL). */
function ckBuylistUrl(cardName) {
  const name = String(cardName ?? "").trim().toLowerCase();
  if (!name) return null;
  const params = new URLSearchParams({
    "filter[sort]": "price_desc",
    "filter[search]": "mtg_advanced",
    "filter[name]": name,
    "filter[edition]": "",
    "filter[format]": "",
    "filter[foils]": "1",
    "filter[singles]": "1",
    "filter[price_op]": "",
    "filter[price]": "",
  });
  return `https://www.cardkingdom.com/purchasing/mtg_singles?${params.toString()}`;
}
