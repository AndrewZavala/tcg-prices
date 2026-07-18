/** Apply saved palette before first paint to avoid flash. */
(function () {
  try {
    const theme = localStorage.getItem("manifestBreadTheme");
    if (theme && theme !== "bakery") document.documentElement.dataset.theme = theme;
  } catch (_) {
    /* ignore private browsing */
  }
})();
