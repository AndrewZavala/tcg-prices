(function () {
  const root = document.getElementById("messagesRoot");
  const title = document.getElementById("messagesTitle");
  if (!root) return;

  const TOPIC_LABELS = { bug: "Bug report", tagger: "Tagger request", other: "Other" };
  let status = "open";

  function esc(s) {
    return String(s ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function formatDate(iso) {
    const d = new Date(iso);
    return d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
  }

  function renderMessage(m) {
    const email = m.email
      ? `<a href="mailto:${esc(m.email)}">${esc(m.email)}</a>`
      : `<span class="sp-hint">no email</span>`;
    const account = m.user_name || m.user_email
      ? ` · signed in as ${esc(m.user_name || m.user_email)}`
      : "";
    const handled = Boolean(m.handled_at);
    return `
      <article class="sp-message${handled ? " is-handled" : ""}" data-id="${m.id}">
        <div class="sp-message-meta">
          <span class="sp-message-topic sp-message-topic-${esc(m.topic)}">${esc(TOPIC_LABELS[m.topic] || m.topic)}</span>
          <span>${esc(formatDate(m.created_at))}</span>
          <span>${email}${account}</span>
        </div>
        <p class="sp-message-body">${esc(m.message)}</p>
        <div class="sp-message-actions">
          ${handled ? `<span class="sp-hint">Handled ${esc(formatDate(m.handled_at))}</span>` : ""}
          <button type="button" class="sp-message-toggle" data-handled="${handled ? "false" : "true"}">
            ${handled ? "Reopen" : "Mark handled"}
          </button>
        </div>
      </article>`;
  }

  async function load() {
    root.innerHTML = `<p class="sp-empty">Loading…</p>`;
    let resp;
    try {
      resp = await fetch(`/api/admin/contact-messages?status=${status}`, { credentials: "same-origin" });
    } catch (_) {
      root.innerHTML = `<p class="sp-empty">Could not reach the server.</p>`;
      return;
    }
    if (resp.status === 401) {
      root.innerHTML = `<p class="sp-empty"><a href="/auth/google/login">Sign in</a> with the admin account to read messages.</p>`;
      return;
    }
    if (resp.status === 403) {
      root.innerHTML = `<p class="sp-empty">This page is only available to the site admin.</p>`;
      return;
    }
    if (!resp.ok) {
      root.innerHTML = `<p class="sp-empty">Could not load messages (error ${resp.status}).</p>`;
      return;
    }
    const data = await resp.json();
    title.textContent = `Contact messages (${data.open_count} open)`;
    root.innerHTML = data.messages.length
      ? data.messages.map(renderMessage).join("")
      : `<p class="sp-empty">${status === "open" ? "No open messages." : "No messages yet."}</p>`;
  }

  document.querySelectorAll(".sp-messages-filter-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      status = btn.dataset.status;
      document.querySelectorAll(".sp-messages-filter-btn").forEach((b) => {
        b.classList.toggle("is-active", b === btn);
      });
      load();
    });
  });

  root.addEventListener("click", async (e) => {
    const btn = e.target.closest(".sp-message-toggle");
    if (!btn) return;
    const id = btn.closest(".sp-message")?.dataset.id;
    if (!id) return;
    btn.disabled = true;
    try {
      const resp = await fetch(`/api/admin/contact-messages/${id}/handled`, {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ handled: btn.dataset.handled === "true" }),
      });
      if (!resp.ok) throw new Error(String(resp.status));
      await load();
    } catch (_) {
      btn.disabled = false;
      alert("Could not update the message. Please try again.");
    }
  });

  load();
})();
