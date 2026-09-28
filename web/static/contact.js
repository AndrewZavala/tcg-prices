(function () {
  const form = document.getElementById("contactForm");
  if (!form) return;
  const topicEl = document.getElementById("contactTopic");
  const emailEl = document.getElementById("contactEmail");
  const messageEl = document.getElementById("contactMessage");
  const statusEl = document.getElementById("contactStatus");
  const submitBtn = document.getElementById("contactSubmit");
  const accountHint = document.getElementById("contactAccountHint");
  const doneEl = document.getElementById("contactDone");

  const params = new URLSearchParams(location.search);
  const wantedTopic = params.get("topic");
  if (wantedTopic && [...topicEl.options].some((o) => o.value === wantedTopic)) {
    topicEl.value = wantedTopic;
  }

  function setStatus(msg) {
    statusEl.textContent = msg || "";
    statusEl.hidden = !msg;
  }

  function syncPlaceholder() {
    emailEl.placeholder = topicEl.value === "tagger"
      ? "The email on the account you sign in with"
      : "So we can reply (optional for bug reports)";
  }
  topicEl.addEventListener("change", syncPlaceholder);
  syncPlaceholder();

  (async () => {
    try {
      await window.__spelltagAuthReady;
    } catch (_) { /* ignore */ }
    const user = window.__spelltagUser;
    if (!user) return;
    if (user.email && !emailEl.value) emailEl.value = user.email;
    accountHint.textContent = "You're signed in, so your account will be attached to this message.";
    accountHint.hidden = false;
  })();

  function errorText(data, status) {
    const detail = data && data.detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail) && detail.length) {
      const field = detail[0].loc ? detail[0].loc[detail[0].loc.length - 1] : "";
      if (field === "message") return "Please write a message (up to 4,000 characters).";
      if (field === "email") return "That email address is too long.";
    }
    return `Could not send your message (error ${status}). Please try again.`;
  }

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    setStatus("");
    const message = messageEl.value.trim();
    if (!message) {
      setStatus("Please write a message.");
      messageEl.focus();
      return;
    }
    submitBtn.disabled = true;
    submitBtn.textContent = "Sending…";
    try {
      const resp = await fetch("/api/contact", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          topic: topicEl.value,
          email: emailEl.value.trim() || null,
          message,
          website: form.elements.website.value || null,
        }),
      });
      const data = await resp.json().catch(() => null);
      if (!resp.ok) {
        setStatus(errorText(data, resp.status));
        return;
      }
      form.hidden = true;
      doneEl.hidden = false;
    } catch (_) {
      setStatus("Could not reach the server. Check your connection and try again.");
    } finally {
      submitBtn.disabled = false;
      submitBtn.textContent = "Send message";
    }
  });
})();
