(function () {
  const GRID_ROWS = 6;
  let pageSize = 48;

  const qEl = document.getElementById("q");
  const seriesEl = document.getElementById("seriesId");
  const setEl = document.getElementById("setId");
  const dexEl = document.getElementById("dexId");
  const rarityEl = document.getElementById("rarity");
  const categoryEl = document.getElementById("category");
  const typeEl = document.getElementById("cardType");
  const stageEl = document.getElementById("stage");
  const subtypeEl = document.getElementById("subtype");
  const generationEl = document.getElementById("generation");
  const pokemonSpecialEl = document.getElementById("pokemonSpecial");
  const speciesGroupEl = document.getElementById("speciesGroup");
  const hasFilterEl = document.getElementById("hasFilter");
  const sortEl = document.getElementById("sort");
  const advToggle = document.getElementById("advToggle");
  const advPanel = document.getElementById("advPanel");
  const clearFiltersBtn = document.getElementById("clearFilters");
  const activeFiltersEl = document.getElementById("activeFilters");
  const gridEl = document.getElementById("cardGrid");
  const resultCount = document.getElementById("resultCount");
  const paginationEl = document.getElementById("pagination");
  const pagePrev = document.getElementById("pagePrev");
  const pageNext = document.getElementById("pageNext");
  const pageInfo = document.getElementById("pageInfo");
  const modal = document.getElementById("cardModal");
  const modalBody = document.getElementById("modalBody");
  const modalClose = document.getElementById("modalClose");
  const segmentBtns = document.querySelectorAll(".sp-segment-btn");
  const zoomOutBtn = document.getElementById("zoomOut");
  const zoomInBtn = document.getElementById("zoomIn");
  const CARD_ZOOM_KEY = "sp-card-zoom";
  const CARD_ZOOM_MIN = 90;
  const CARD_ZOOM_MAX = 260;
  const CARD_ZOOM_STEP = 20;
  const CARD_ZOOM_DEFAULT = 130;
  const CARD_ZOOM_MOBILE_DEFAULT = 100;
  let cardZoomPx = CARD_ZOOM_DEFAULT;

  function defaultCardZoom() {
    return window.matchMedia("(max-width: 720px)").matches
      ? CARD_ZOOM_MOBILE_DEFAULT
      : CARD_ZOOM_DEFAULT;
  }

  const filterEls = [
    seriesEl, setEl, dexEl, rarityEl, categoryEl, typeEl, stageEl, subtypeEl,
    generationEl, pokemonSpecialEl, speciesGroupEl, hasFilterEl,
  ];

  const SPECIES_GROUP_LABELS = {
    baby: "Baby",
    starter: "Starter",
    fossil: "Fossil",
    "pseudo-legendary": "Pseudo-Legendary",
    "ultra-beast": "Ultra Beast",
    paradox: "Paradox",
    eeveelution: "Eeveelution",
    regional: "Regional form",
  };

  let unique = "cards";
  let offset = 0;
  let debounceTimer = null;
  let catalogSets = [];
  let catalogFacets = {};

  function esc(s) {
    return String(s ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function tagLabel(tag) {
    return String(tag).replace(/-/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
  }

  const CARD_IMG_FALLBACK = "/static/empty-pokeball.png?v=rembg";

  function cardImg(src, alt, extraClass) {
    const cls = ["sp-card-img", extraClass].filter(Boolean).join(" ");
    if (!src) {
      return `<img class="${cls} is-fallback" src="${CARD_IMG_FALLBACK}" alt="${esc(alt || "Image unavailable")}" loading="lazy" />`;
    }
    return `<img class="${cls}" src="${esc(src)}" alt="${esc(alt || "")}" loading="lazy" onerror="this.onerror=null;this.src='${CARD_IMG_FALLBACK}';this.classList.add('is-fallback')" />`;
  }

  function renderCard(card) {
    const label = `${card.name} — ${card.set_name} #${card.local_id}`;
    return `
      <article class="sp-card" data-id="${esc(card.id)}" tabindex="0" aria-label="${esc(label)}" title="${esc(label)}">
        ${cardImg(card.image_url, label)}
      </article>`;
  }

  // Attack cost display (UI only). API still returns full type names.
  const ENERGY_COST_ABBREV = {
    grass: "G",
    fire: "R",
    water: "W",
    lightning: "L",
    psychic: "P",
    fighting: "F",
    darkness: "D",
    dark: "D",
    metal: "M",
    fairy: "Y",
    dragon: "N",
    colorless: "C",
  };

  function formatAttackCost(cost) {
    const parts = cost || [];
    if (!parts.length) return "—";
    return parts
      .map((t) => {
        const key = String(t || "").trim().toLowerCase();
        const abbr = ENERGY_COST_ABBREV[key];
        return abbr ? `{${abbr}}` : `{${t}}`;
      })
      .join("");
  }

  function attackBlock(atk) {
    const cost = formatAttackCost(atk.cost);
    const costTitle = (atk.cost || []).join(", ");
    const dmg = atk.damage != null ? ` · ${atk.damage} dmg` : "";
    const effect = atk.effect ? `<p>${esc(atk.effect)}</p>` : "";
    const costHtml = costTitle
      ? `<span title="${esc(costTitle)}">${esc(cost)}</span>`
      : esc(cost);
    return `<p><strong>${esc(atk.name)}</strong> ${costHtml}${dmg}</p>${effect}`;
  }

  function abilityBlock(ab) {
    return `<p><strong>${esc(ab.name)}</strong> (${esc(ab.type)}) — ${esc(ab.effect)}</p>`;
  }

  function cardTextBlock(card) {
    const text = card.description;
    if (!text) return "";
    const heading =
      card.category === "Pokemon" ? "Flavor text" : "Effect";
    const paragraphs = text
      .split(/\n\s*\n/)
      .map((p) => p.trim())
      .filter(Boolean)
      .map((p) => `<p>${esc(p)}</p>`)
      .join("");
    return `<div class="sp-block"><h3>${heading}</h3>${paragraphs}</div>`;
  }

  function subtypeBlock(card) {
    const subtypes = card.subtypes || [];
    if (!subtypes.length) return "";
    const tags = card.tags || [];
    const pills = subtypes
      .map((label, i) => {
        const tag = tags[i] || slugifyTag(label);
        return `<button type="button" class="sp-subtype" data-tag="${esc(tag)}" title="Filter by ${esc(label)}">${esc(label)}</button>`;
      })
      .join("");
    return `<div class="sp-subtypes" aria-label="Subtypes">${pills}</div>`;
  }

  function hasStatValue(value) {
    if (value == null || value === "") return false;
    if (Array.isArray(value)) return value.length > 0;
    return true;
  }

  function statCell(label, value) {
    if (!hasStatValue(value)) return "";
    const text = Array.isArray(value) ? value.join(", ") : value;
    return `<div class="sp-stat"><strong>${esc(label)}</strong>${esc(text)}</div>`;
  }

  function statGridBlock(card) {
    const cells = [
      statCell("Category", card.category),
      statCell("HP", card.hp),
      statCell("Stage", card.stage),
      statCell("Retreat", card.retreat),
      statCell("Types", card.types),
      statCell("Dex", card.dex_ids),
    ].filter(Boolean);
    if (!cells.length) return "";
    return `<div class="sp-stat-grid">${cells.join("")}</div>`;
  }

  function slugifyTag(label) {
    return String(label ?? "")
      .normalize("NFKD")
      .replace(/[\u0300-\u036f]/g, "")
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "");
  }

  function openAdvanced() {
    advPanel.hidden = false;
    advToggle.setAttribute("aria-expanded", "true");
    advToggle.classList.add("open");
  }

  function searchByTag(tag) {
    if (!tag) return;
    subtypeEl.value = tag;
    openAdvanced();
    modal.close();
    resetOffsetAndSearch();
  }

  function searchByOtag(slug) {
    if (!slug) return;
    qEl.value = `otag:${slug}`;
    clearAdvancedFilters();
    modal.close();
    resetOffsetAndSearch();
  }

  function oracleTagsBlock(card) {
    const applied = Array.isArray(card.oracle_tags) ? card.oracle_tags : [];
    const defs = (catalogFacets.oracle_tags || []).slice();
    const bySlug = new Map(defs.map((d) => [d.slug, d]));
    for (const t of applied) {
      if (t && t.slug && !bySlug.has(t.slug)) bySlug.set(t.slug, t);
    }
    const user = window.__spelltagUser;
    const canTag = !!(user && user.is_tagger);
    if (!applied.length && !canTag) return "";

    const chips = applied
      .map(
        (t) =>
          `<button type="button" class="sp-otag" data-otag="${esc(t.slug)}" title="Search otag:${esc(t.slug)}">${esc(
            t.label || t.slug
          )}</button>`
      )
      .join("");

    let editor = "";
    if (canTag) {
      const selectedSlugs = applied.map((t) => t.slug).filter(Boolean);
      editor = `
        <div class="sp-otag-editor" id="otagEditor">
          <p class="sp-hint">Select oracle tags for this card (all printings share them).</p>
          <div class="sp-otag-ms" id="otagMulti">
            <div class="sp-otag-ms-control" id="otagMsControl">
              <div class="sp-otag-ms-chips" id="otagMsChips"></div>
              <input type="search" class="sp-otag-ms-search" id="otagMsSearch"
                     placeholder="Search tags…" autocomplete="off" aria-label="Search oracle tags" />
              <span class="sp-otag-ms-caret" aria-hidden="true">▾</span>
            </div>
            <div class="sp-otag-ms-menu" id="otagMsMenu" hidden role="listbox"></div>
            <input type="hidden" id="otagMsValue" value="${esc(selectedSlugs.join(","))}" />
          </div>
          <div class="sp-otag-actions">
            <button type="button" class="sp-otag-save" id="otagSaveBtn">Save tags</button>
            <span class="sp-otag-status" id="otagStatus" aria-live="polite"></span>
          </div>
          <div class="sp-otag-admin" id="otagAdmin">
            <p class="sp-hint">Create a tag — use <em>Rain Dance</em> or <em>rain-dance</em>.</p>
            <div class="sp-otag-admin-row">
              <input type="text" id="otagNewName" placeholder="Rain Dance or rain-dance" maxlength="80" />
              <button type="button" class="sp-otag-save" id="otagCreateBtn">Create</button>
            </div>
            <span class="sp-otag-status" id="otagCreateStatus" aria-live="polite"></span>
          </div>
        </div>`;
    }

    return `
      <div class="sp-otag-block" id="otagBlock">
        <h3>Oracle tags</h3>
        <div class="sp-otag-list">${chips || '<span class="sp-hint">No oracle tags yet.</span>'}</div>
        ${editor}
      </div>`;
  }

  async function wireOracleTagControls(card) {
    const block = document.getElementById("otagBlock");
    if (!block) return;

    block.querySelectorAll(".sp-otag[data-otag]").forEach((el) => {
      el.addEventListener("click", () => searchByOtag(el.dataset.otag));
    });

    const editor = document.getElementById("otagEditor");
    const multi = document.getElementById("otagMulti");
    if (editor && multi) {
      const bySlug = new Map();
      for (const d of catalogFacets.oracle_tags || []) {
        if (d && d.slug) bySlug.set(d.slug, { slug: d.slug, label: d.label || d.slug });
      }
      for (const t of card.oracle_tags || []) {
        if (t && t.slug && !bySlug.has(t.slug)) {
          bySlug.set(t.slug, { slug: t.slug, label: t.label || t.slug });
        }
      }
      const defs = [...bySlug.values()].sort((a, b) =>
        String(a.label).localeCompare(String(b.label))
      );
      const valueEl = document.getElementById("otagMsValue");
      const chipsEl = document.getElementById("otagMsChips");
      const searchEl = document.getElementById("otagMsSearch");
      const menuEl = document.getElementById("otagMsMenu");
      const controlEl = document.getElementById("otagMsControl");

      const selected = new Set(
        String((valueEl && valueEl.value) || "")
          .split(",")
          .map((s) => s.trim())
          .filter(Boolean)
      );

      const labelFor = (slug) => {
        const hit = defs.find((d) => d.slug === slug);
        return (hit && hit.label) || slug;
      };

      const syncValue = () => {
        if (valueEl) valueEl.value = [...selected].join(",");
      };

      const renderChips = () => {
        if (!chipsEl) return;
        chipsEl.innerHTML = [...selected]
          .map(
            (slug) => `
            <button type="button" class="sp-otag-ms-chip" data-remove="${esc(slug)}" title="Remove ${esc(labelFor(slug))}">
              ${esc(labelFor(slug))}
              <span aria-hidden="true">×</span>
            </button>`
          )
          .join("");
        chipsEl.querySelectorAll("[data-remove]").forEach((btn) => {
          btn.addEventListener("click", (e) => {
            e.stopPropagation();
            selected.delete(btn.dataset.remove);
            syncValue();
            renderChips();
            renderMenu(searchEl ? searchEl.value : "");
          });
        });
      };

      const renderMenu = (query) => {
        if (!menuEl) return;
        const q = String(query || "").trim().toLowerCase();
        const rows = defs.filter((d) => {
          if (!q) return true;
          return (
            String(d.label || "").toLowerCase().includes(q) ||
            String(d.slug || "").toLowerCase().includes(q)
          );
        });
        if (!rows.length) {
          menuEl.innerHTML = '<div class="sp-otag-ms-empty">No matching tags</div>';
          return;
        }
        menuEl.innerHTML = rows
          .map((d) => {
            const on = selected.has(d.slug);
            return `
              <button type="button" class="sp-otag-ms-option${on ? " is-on" : ""}" role="option"
                      aria-selected="${on ? "true" : "false"}" data-slug="${esc(d.slug)}">
                <span class="sp-otag-ms-check" aria-hidden="true">${on ? "✓" : ""}</span>
                <span class="sp-otag-ms-label">${esc(d.label || d.slug)}</span>
              </button>`;
          })
          .join("");
        menuEl.querySelectorAll("[data-slug]").forEach((btn) => {
          btn.addEventListener("click", (e) => {
            e.stopPropagation();
            const slug = btn.dataset.slug;
            if (selected.has(slug)) selected.delete(slug);
            else selected.add(slug);
            syncValue();
            renderChips();
            renderMenu(searchEl ? searchEl.value : "");
          });
        });
      };

      const openMenu = () => {
        if (!menuEl) return;
        menuEl.hidden = false;
        multi.classList.add("is-open");
        renderMenu(searchEl ? searchEl.value : "");
      };

      const closeMenu = () => {
        if (!menuEl) return;
        menuEl.hidden = true;
        multi.classList.remove("is-open");
      };

      renderChips();
      syncValue();

      if (controlEl) {
        controlEl.addEventListener("click", () => {
          openMenu();
          if (searchEl) searchEl.focus();
        });
      }
      if (searchEl) {
        searchEl.addEventListener("focus", openMenu);
        searchEl.addEventListener("input", () => {
          openMenu();
          renderMenu(searchEl.value);
        });
        searchEl.addEventListener("keydown", (e) => {
          if (e.key === "Escape") {
            closeMenu();
            searchEl.blur();
          }
        });
      }
      document.addEventListener(
        "click",
        (e) => {
          if (!multi.contains(e.target)) closeMenu();
        },
        { capture: true }
      );
    }

    const saveBtn = document.getElementById("otagSaveBtn");
    if (saveBtn) {
      saveBtn.addEventListener("click", async () => {
        const status = document.getElementById("otagStatus");
        const valueEl = document.getElementById("otagMsValue");
        const selected = String((valueEl && valueEl.value) || "")
          .split(",")
          .map((s) => s.trim())
          .filter(Boolean);
        saveBtn.disabled = true;
        if (status) status.textContent = "Saving…";
        try {
          const resp = await fetch(
            `/api/pokemon/cards/${encodeURIComponent(card.id)}/oracle-tags`,
            {
              method: "PUT",
              credentials: "same-origin",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ tags: selected }),
            }
          );
          if (!resp.ok) {
            const err = await resp.json().catch(() => ({}));
            const detail = err.detail;
            const msg = Array.isArray(detail)
              ? detail.map((d) => d.msg || JSON.stringify(d)).join("; ")
              : detail || "Save failed";
            throw new Error(msg);
          }
          const data = await resp.json();
          card.oracle_tags = data.tags || [];
          if (status) status.textContent = "Saved.";
          openCard(card.id);
        } catch (err) {
          if (status) status.textContent = err.message || "Save failed";
        } finally {
          saveBtn.disabled = false;
        }
      });
    }

    const createBtn = document.getElementById("otagCreateBtn");
    if (createBtn) {
      createBtn.addEventListener("click", async () => {
        const status = document.getElementById("otagCreateStatus");
        const name = ((document.getElementById("otagNewName") || {}).value || "").trim();
        createBtn.disabled = true;
        if (status) status.textContent = "Creating…";
        try {
          const resp = await fetch("/api/oracle-tags", {
            method: "POST",
            credentials: "same-origin",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ name }),
          });
          if (!resp.ok) {
            const err = await resp.json().catch(() => ({}));
            const detail = err.detail;
            const msg = Array.isArray(detail)
              ? detail.map((d) => d.msg || JSON.stringify(d)).join("; ")
              : detail || "Create failed";
            throw new Error(msg);
          }
          const created = await resp.json();
          catalogFacets.oracle_tags = [...(catalogFacets.oracle_tags || []), created];
          if (status) status.textContent = `Created ${created.label} (${created.slug}).`;
          openCard(card.id);
        } catch (err) {
          if (status) status.textContent = err.message || "Create failed";
        } finally {
          createBtn.disabled = false;
        }
      });
    }
  }

  function searchByGeneration(genId) {
    if (!genId) return;
    generationEl.value = String(genId);
    openAdvanced();
    modal.close();
    resetOffsetAndSearch();
  }

  function searchByPokemonSpecial(special) {
    if (!special) return;
    pokemonSpecialEl.value = special;
    openAdvanced();
    modal.close();
    resetOffsetAndSearch();
  }

  function searchBySpeciesGroup(group) {
    if (!group) return;
    speciesGroupEl.value = group;
    openAdvanced();
    modal.close();
    resetOffsetAndSearch();
  }

  function searchByHas(hasVal) {
    if (!hasVal) return;
    hasFilterEl.value = hasVal;
    openAdvanced();
    modal.close();
    resetOffsetAndSearch();
  }

  function searchByName(name) {
    if (!name) return;
    qEl.value = name;
    modal.close();
    resetOffsetAndSearch();
  }

  function pokemonMetaBlock(card) {
    const p = card.pokemon;
    const pills = [];
    if (p?.generation_id) {
      pills.push(
        `<button type="button" class="sp-subtype sp-pokemon-meta" data-gen="${esc(p.generation_id)}" title="Filter ${esc(p.generation_name)}">${esc(p.generation_name)}</button>`
      );
    }
    if (p?.is_legendary) {
      pills.push(
        `<button type="button" class="sp-subtype sp-pokemon-meta" data-special="legendary" title="Filter Legendary Pokémon">Legendary</button>`
      );
    }
    if (p?.is_mythical) {
      pills.push(
        `<button type="button" class="sp-subtype sp-pokemon-meta" data-special="mythical" title="Filter Mythical Pokémon">Mythical</button>`
      );
    }
    if (p?.is_baby) {
      pills.push(
        `<button type="button" class="sp-subtype sp-pokemon-meta" data-group="baby" title="Filter Baby Pokémon">Baby</button>`
      );
    }
    for (const g of p?.species_groups || []) {
      const label = SPECIES_GROUP_LABELS[g] || g;
      pills.push(
        `<button type="button" class="sp-subtype sp-pokemon-meta" data-group="${esc(g)}" title="Filter ${esc(label)}">${esc(label)}</button>`
      );
    }
    if (card.is_regional) {
      pills.push(
        `<button type="button" class="sp-subtype sp-pokemon-meta" data-group="regional" title="Filter regional forms">Regional</button>`
      );
    }
    if (card.has_ability) {
      pills.push(
        `<button type="button" class="sp-subtype sp-pokemon-meta" data-has="ability" title="Filter cards with an Ability">Ability</button>`
      );
    }
    if (!pills.length) return "";
    return `<div class="sp-subtypes sp-pokemon-meta-row" aria-label="Pokémon metadata">${pills.join("")}</div>`;
  }

  function bindCardClicks() {
    gridEl.querySelectorAll(".sp-card").forEach((el) => {
      const open = () => openCard(el.dataset.id);
      el.addEventListener("click", open);
      el.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          open();
        }
      });
    });
  }

  async function openCard(id) {
    if (window.__spelltagAuthReady) {
      try {
        await window.__spelltagAuthReady;
      } catch (_) { /* ignore */ }
    }
    const resp = await fetch(`/api/pokemon/cards/${encodeURIComponent(id)}`);
    if (!resp.ok) {
      console.warn("Could not load card", id, resp.status);
      return;
    }
    const card = await resp.json();
    const showSpeciesPrints = unique === "pokemon" && (card.species_printings || []).length > 1;
    const related = showSpeciesPrints
      ? (card.species_printings || [])
      : (card.sibling_printings || []);
    const relatedTitle = showSpeciesPrints
      ? `All ${card.pokemon?.species_name || card.name} cards (${related.length})`
      : `Same oracle — all printings (${related.length})`;
    const relatedHint = showSpeciesPrints
      ? `Every printing in the catalog with Dex #${card.pokemon?.dex_id ?? "—"}.`
      : "Exact gameplay match across every field.";

    const relatedHtml = related
      .map((s) => {
        const cls = s.id === card.id ? "sp-sibling rep" : "sp-sibling";
        const img = cardImg(s.image_url, s.name || "");
        const nameLine = showSpeciesPrints && s.name && s.name !== card.name
          ? `<div class="sp-sibling-name">${esc(s.name)}</div>`
          : "";
        return `
          <div class="${cls}" data-id="${esc(s.id)}" title="${esc(s.name)} — ${esc(s.set_name)}">
            ${img}
            ${nameLine}
            <div>${esc(s.set_name)}</div>
            <div>#${esc(s.local_id)}</div>
          </div>`;
      })
      .join("");

    modalBody.innerHTML = `
      <div class="sp-detail">
        <div class="sp-detail-art">
          ${cardImg(card.image_url, card.name, "sp-detail-img")}
        </div>
        <div class="sp-detail-body">
          <h2>
            <button type="button" class="sp-name-link" data-name="${esc(card.name)}" title="Search for ${esc(card.name)}">
              ${esc(card.name)}
            </button>
          </h2>
          <div class="sp-detail-sticky-actions">
            ${(card.tcg_url || card.limitless_url) ? `
              <p class="sp-buy-row">
                ${card.tcg_url ? `
                  <a class="sp-buy-btn" href="${esc(card.tcg_url)}" target="_blank" rel="noopener noreferrer sponsored">
                    Buy on TCGplayer
                  </a>` : ""}
                ${card.limitless_url ? `
                  <a class="sp-limitless-btn" href="${esc(card.limitless_url)}" target="_blank" rel="noopener noreferrer"
                     title="Card stats &amp; decks on Limitless${card.limitless_set_code ? ` (${esc(card.limitless_set_code)} #${esc(card.local_id)})` : ""}">
                    Decks on Limitless
                  </a>` : ""}
              </p>` : ""}
            <div class="sp-collect-bar" id="collectBar" hidden>
              <button type="button" class="sp-fav-btn" id="favToggleBtn" aria-pressed="false">♡ Favorite</button>
              <label class="sp-collect-add">
                <span class="sp-visually-hidden">Add to collection</span>
                <select id="collectAddSelect">
                  <option value="">Add to collection…</option>
                </select>
              </label>
              <a class="sp-collect-link" href="/collections">My Collections</a>
            </div>
          </div>
          <p class="sp-detail-meta">
            ${esc(card.series_name || "—")} · ${esc(card.set_name)} · #${esc(card.local_id)} · ${esc(card.rarity || "—")}
            · ${esc(card.illustrator || "Unknown artist")}
          </p>
          ${pokemonMetaBlock(card)}
          ${subtypeBlock(card)}
          ${statGridBlock(card)}
          ${card.evolve_from ? `<p class="sp-hint">Evolves from ${esc(card.evolve_from)}</p>` : ""}
          ${cardTextBlock(card)}
          ${(card.abilities || []).length ? `<div class="sp-block"><h3>Abilities</h3>${card.abilities.map(abilityBlock).join("")}</div>` : ""}
          ${(card.attacks || []).length ? `<div class="sp-block"><h3>Attacks</h3>${card.attacks.map(attackBlock).join("")}</div>` : ""}
          ${oracleTagsBlock(card)}
          ${related.length > 1 ? `
            <div class="sp-siblings">
              <h3>${esc(relatedTitle)}</h3>
              <p class="sp-hint">${esc(relatedHint)}</p>
              <div class="sp-sibling-list">${relatedHtml}</div>
            </div>` : ""}
        </div>
      </div>`;

    modalBody.querySelectorAll(".sp-sibling").forEach((el) => {
      el.addEventListener("click", () => openCard(el.dataset.id));
    });
    modalBody.querySelectorAll(".sp-name-link").forEach((el) => {
      el.addEventListener("click", () => searchByName(el.dataset.name));
    });
    modalBody.querySelectorAll(".sp-subtype[data-tag]").forEach((el) => {
      el.addEventListener("click", () => searchByTag(el.dataset.tag));
    });
    modalBody.querySelectorAll(".sp-pokemon-meta[data-gen]").forEach((el) => {
      el.addEventListener("click", () => searchByGeneration(el.dataset.gen));
    });
    modalBody.querySelectorAll(".sp-pokemon-meta[data-special]").forEach((el) => {
      el.addEventListener("click", () => searchByPokemonSpecial(el.dataset.special));
    });
    modalBody.querySelectorAll(".sp-pokemon-meta[data-group]").forEach((el) => {
      el.addEventListener("click", () => searchBySpeciesGroup(el.dataset.group));
    });
    modalBody.querySelectorAll(".sp-pokemon-meta[data-has]").forEach((el) => {
      el.addEventListener("click", () => searchByHas(el.dataset.has));
    });
    // Dialog + target=_blank (and some Impact redirects) can open two tabs.
    // Open once via JS and stop the event from bubbling through <dialog>.
    modalBody.querySelectorAll("a.sp-buy-btn, a.sp-limitless-btn").forEach((el) => {
      el.addEventListener("click", (e) => {
        e.preventDefault();
        e.stopPropagation();
        const url = el.getAttribute("href");
        if (url) window.open(url, "_blank", "noopener,noreferrer");
      });
    });
    wireCollectionControls(card.id);
    wireOracleTagControls(card);
    modal.showModal();
  }

  async function wireCollectionControls(cardId) {
    const bar = document.getElementById("collectBar");
    const favBtn = document.getElementById("favToggleBtn");
    const addSel = document.getElementById("collectAddSelect");
    if (!bar || !favBtn || !addSel) return;

    if (window.__spelltagAuthReady) {
      try {
        await window.__spelltagAuthReady;
      } catch (_) { /* ignore */ }
    }

    const setFavUi = (on) => {
      favBtn.setAttribute("aria-pressed", on ? "true" : "false");
      favBtn.classList.toggle("is-on", on);
      favBtn.textContent = on ? "♥ Favorited" : "♡ Favorite";
    };

    try {
      const resp = await fetch(
        `/api/me/cards/${encodeURIComponent(cardId)}/memberships`,
        { credentials: "same-origin" }
      );
      if (resp.status === 401 || !resp.ok) {
        bar.hidden = true;
        return;
      }
      bar.hidden = false;
      const data = await resp.json();
      const cols = data.collections || [];
      const fav = cols.find((c) => c.kind === "favorites");
      setFavUi(!!(fav && fav.contains));

      addSel.innerHTML = '<option value="">Add to collection…</option>';
      for (const c of cols) {
        if (c.kind === "favorites") continue;
        const opt = document.createElement("option");
        opt.value = c.id;
        opt.textContent = c.contains ? `${c.name} ✓` : c.name;
        opt.disabled = !!c.contains;
        addSel.appendChild(opt);
      }

      favBtn.onclick = async () => {
        favBtn.disabled = true;
        try {
          const r = await fetch("/api/me/favorites/toggle", {
            method: "POST",
            credentials: "same-origin",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ card_id: cardId }),
          });
          if (r.ok) {
            const body = await r.json();
            setFavUi(!!body.favorited);
          }
        } finally {
          favBtn.disabled = false;
        }
      };

      addSel.onchange = async () => {
        const cid = addSel.value;
        if (!cid) return;
        addSel.disabled = true;
        try {
          const r = await fetch(`/api/me/collections/${encodeURIComponent(cid)}/items`, {
            method: "POST",
            credentials: "same-origin",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ card_id: cardId }),
          });
          if (r.ok) {
            const opt = addSel.selectedOptions[0];
            if (opt) {
              opt.textContent = `${opt.textContent.replace(/ ✓$/, "")} ✓`;
              opt.disabled = true;
            }
            addSel.value = "";
          }
        } finally {
          addSel.disabled = false;
        }
      };
    } catch (_) {
      bar.hidden = true;
    }
  }

  function fillSelect(el, values, { labelFn } = {}) {
    const current = el.value;
    const keepFirst = el.options[0];
    el.innerHTML = "";
    el.appendChild(keepFirst);
    for (const value of values) {
      const opt = document.createElement("option");
      opt.value = value;
      opt.textContent = labelFn ? labelFn(value) : value;
      el.appendChild(opt);
    }
    if ([...el.options].some((o) => o.value === current)) {
      el.value = current;
    }
  }

  function populateSetOptions() {
    const seriesFilter = seriesEl.value;
    const currentSet = setEl.value;
    setEl.innerHTML = '<option value="">All sets</option>';

    const bySeries = new Map();
    for (const s of catalogSets) {
      if (seriesFilter && s.series_id !== seriesFilter) continue;
      const key = s.series_name || "Other";
      if (!bySeries.has(key)) bySeries.set(key, []);
      bySeries.get(key).push(s);
    }

    for (const [seriesName, sets] of bySeries) {
      const group = document.createElement("optgroup");
      group.label = seriesName;
      for (const s of sets) {
        const opt = document.createElement("option");
        opt.value = s.id;
        opt.textContent = `${s.name} (${s.loaded_cards})`;
        opt.dataset.seriesId = s.series_id || "";
        group.appendChild(opt);
      }
      setEl.appendChild(group);
    }

    if ([...setEl.options].some((o) => o.value === currentSet)) {
      setEl.value = currentSet;
    } else {
      setEl.value = "";
    }
  }

  function activeFilterEntries() {
    const entries = [];
    if (seriesEl.value) {
      const series = (catalogFacets.series || []).find((s) => s.id === seriesEl.value);
      entries.push({ key: "series", label: series?.name || seriesEl.value, clear: () => { seriesEl.value = ""; populateSetOptions(); } });
    }
    if (setEl.value) {
      const set = catalogSets.find((s) => s.id === setEl.value);
      entries.push({ key: "set", label: set?.name || setEl.value, clear: () => { setEl.value = ""; } });
    }
    if (dexEl.value) entries.push({ key: "dex", label: `Dex #${dexEl.value}`, clear: () => { dexEl.value = ""; } });
    if (rarityEl.value) entries.push({ key: "rarity", label: rarityEl.value, clear: () => { rarityEl.value = ""; } });
    if (categoryEl.value) entries.push({ key: "category", label: categoryEl.value, clear: () => { categoryEl.value = ""; } });
    if (typeEl.value) entries.push({ key: "type", label: typeEl.value, clear: () => { typeEl.value = ""; } });
    if (stageEl.value) entries.push({ key: "stage", label: stageEl.value, clear: () => { stageEl.value = ""; } });
    if (subtypeEl.value) entries.push({ key: "subtype", label: tagLabel(subtypeEl.value), clear: () => { subtypeEl.value = ""; } });
    if (generationEl.value) {
      const gen = (catalogFacets.generations || []).find((g) => String(g.id) === generationEl.value);
      entries.push({
        key: "generation",
        label: gen?.name || `Gen ${generationEl.value}`,
        clear: () => { generationEl.value = ""; },
      });
    }
    if (pokemonSpecialEl.value) {
      const special = (catalogFacets.pokemon_special || []).find((s) => s.id === pokemonSpecialEl.value);
      entries.push({
        key: "pokemonSpecial",
        label: special?.name || pokemonSpecialEl.value,
        clear: () => { pokemonSpecialEl.value = ""; },
      });
    }
    if (speciesGroupEl.value) {
      const group = (catalogFacets.species_groups || []).find((s) => s.id === speciesGroupEl.value);
      entries.push({
        key: "speciesGroup",
        label: group?.name || SPECIES_GROUP_LABELS[speciesGroupEl.value] || speciesGroupEl.value,
        clear: () => { speciesGroupEl.value = ""; },
      });
    }
    if (hasFilterEl.value) {
      const hasOpt = (catalogFacets.has || []).find((s) => s.id === hasFilterEl.value);
      entries.push({
        key: "hasFilter",
        label: hasOpt?.name || `Has ${hasFilterEl.value}`,
        clear: () => { hasFilterEl.value = ""; },
      });
    }
    return entries;
  }

  function updateActiveFilters() {
    const entries = activeFilterEntries();
    const count = entries.length;
    advToggle.dataset.count = count ? String(count) : "";
    if (!entries.length) {
      activeFiltersEl.hidden = true;
      activeFiltersEl.innerHTML = "";
      return;
    }
    activeFiltersEl.hidden = false;
    activeFiltersEl.innerHTML = entries
      .map(
        (entry) =>
          `<button type="button" class="sp-filter-chip" data-key="${esc(entry.key)}">${esc(entry.label)} <span aria-hidden="true">×</span></button>`
      )
      .join("");
    activeFiltersEl.querySelectorAll(".sp-filter-chip").forEach((btn) => {
      btn.addEventListener("click", () => {
        const entry = entries.find((e) => e.key === btn.dataset.key);
        entry?.clear();
        resetOffsetAndSearch();
      });
    });
  }

  function clearAdvancedFilters() {
    for (const el of filterEls) {
      el.value = "";
    }
    populateSetOptions();
  }

  async function loadMeta() {
    const resp = await fetch("/api/pokemon/meta");
    if (!resp.ok) {
      return;
    }
    const meta = await resp.json();
    catalogSets = meta.sets || [];
    catalogFacets = meta.facets || {};

    seriesEl.innerHTML = '<option value="">All series</option>';
    for (const s of catalogFacets.series || []) {
      const opt = document.createElement("option");
      opt.value = s.id;
      opt.textContent = `${s.name} (${s.set_count} sets)`;
      seriesEl.appendChild(opt);
    }

    populateSetOptions();
    fillSelect(rarityEl, catalogFacets.rarities || []);
    fillSelect(categoryEl, catalogFacets.categories || []);
    fillSelect(typeEl, catalogFacets.types || []);
    fillSelect(stageEl, catalogFacets.stages || []);
    fillSelect(subtypeEl, catalogFacets.tags || [], { labelFn: tagLabel });
    generationEl.innerHTML = '<option value="">Any</option>';
    for (const g of catalogFacets.generations || []) {
      const opt = document.createElement("option");
      opt.value = String(g.id);
      opt.textContent = `${g.name} (${g.card_count})`;
      generationEl.appendChild(opt);
    }
    pokemonSpecialEl.innerHTML = '<option value="">Any</option>';
    for (const s of catalogFacets.pokemon_special || []) {
      const opt = document.createElement("option");
      opt.value = s.id;
      opt.textContent = s.name;
      pokemonSpecialEl.appendChild(opt);
    }
    speciesGroupEl.innerHTML = '<option value="">Any</option>';
    for (const s of catalogFacets.species_groups || []) {
      const opt = document.createElement("option");
      opt.value = s.id;
      opt.textContent = s.name;
      speciesGroupEl.appendChild(opt);
    }
    hasFilterEl.innerHTML = '<option value="">Any</option>';
    for (const s of catalogFacets.has || []) {
      const opt = document.createElement("option");
      opt.value = s.id;
      opt.textContent = s.name;
      hasFilterEl.appendChild(opt);
    }
  }

  function updatePagination(total, currentOffset, limit) {
    const pageCount = Math.max(1, Math.ceil(total / limit));
    const page = Math.floor(currentOffset / limit) + 1;
    const showingFrom = total === 0 ? 0 : currentOffset + 1;
    const showingTo = Math.min(currentOffset + limit, total);

    paginationEl.hidden = total <= limit;
    pageInfo.textContent =
      total === 0
        ? "No results"
        : `Page ${page} of ${pageCount} · ${showingFrom}–${showingTo} of ${total}`;
    pagePrev.disabled = page <= 1;
    pageNext.disabled = page >= pageCount;
  }

  async function search() {
    syncPageSize();
    const params = new URLSearchParams();
    params.set("unique", unique);
    params.set("sort", sortEl.value);
    params.set("limit", String(pageSize));
    params.set("offset", String(offset));
    if (qEl.value.trim()) params.set("q", qEl.value.trim());
    if (setEl.value) params.set("set_id", setEl.value);
    else if (seriesEl.value) params.set("series_id", seriesEl.value);
    if (dexEl.value) params.set("dex_id", dexEl.value);
    if (rarityEl.value) params.set("rarity", rarityEl.value);
    if (categoryEl.value) params.set("category", categoryEl.value);
    if (typeEl.value) params.set("type", typeEl.value);
    if (stageEl.value) params.set("stage", stageEl.value);
    if (subtypeEl.value) params.set("tag", subtypeEl.value);
    if (generationEl.value) params.set("generation", generationEl.value);
    if (pokemonSpecialEl.value) params.set("pokemon_special", pokemonSpecialEl.value);
    if (speciesGroupEl.value) params.set("species_group", speciesGroupEl.value);
    if (hasFilterEl.value) params.set("has", hasFilterEl.value);

    updateActiveFilters();

    gridEl.innerHTML = '<p class="sp-empty">Scanning the cosmos…</p>';
    paginationEl.hidden = true;

    const resp = await fetch(`/api/pokemon/cards?${params}`);
    if (!resp.ok) {
      gridEl.innerHTML = '<p class="sp-empty">Search failed.</p>';
      return;
    }
    const data = await resp.json();
    resultCount.textContent = `${data.total} result${data.total === 1 ? "" : "s"}`;
    updatePagination(data.total, data.offset, data.limit);

    if (!data.cards.length) {
      gridEl.innerHTML = '<p class="sp-empty">No cards in this constellation.</p>';
      return;
    }

    gridEl.innerHTML = data.cards.map(renderCard).join("");
    bindCardClicks();

    if (offset > 0) {
      gridEl.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }

  function resetOffsetAndSearch() {
    offset = 0;
    search();
  }

  function scheduleSearch() {
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(resetOffsetAndSearch, 220);
  }

  segmentBtns.forEach((btn) => {
    btn.addEventListener("click", () => {
      unique = btn.dataset.unique;
      segmentBtns.forEach((b) => {
        b.classList.toggle("active", b === btn);
        b.setAttribute("aria-selected", b === btn ? "true" : "false");
      });
      resetOffsetAndSearch();
    });
  });

  function gridGapPx() {
    const rem = parseFloat(getComputedStyle(document.documentElement).fontSize) || 16;
    return 0.85 * rem;
  }

  function columnCount() {
    const width = gridEl?.clientWidth || 0;
    if (width < 40) return 6;
    const gap = gridGapPx();
    return Math.max(1, Math.floor((width + gap) / (cardZoomPx + gap)));
  }

  /** Keep page length a multiple of visible columns so the last cell is never empty. */
  function syncPageSize() {
    const next = Math.max(columnCount() * GRID_ROWS, columnCount());
    const changed = next !== pageSize;
    pageSize = next;
    return changed;
  }

  function clampCardZoom(px) {
    const n = Math.round(Number(px) / CARD_ZOOM_STEP) * CARD_ZOOM_STEP;
    return Math.min(CARD_ZOOM_MAX, Math.max(CARD_ZOOM_MIN, n));
  }

  function applyCardZoom(px, persist, refetchOnPageChange = true) {
    cardZoomPx = clampCardZoom(px);
    document.documentElement.style.setProperty("--sp-card-min", `${cardZoomPx}px`);
    if (zoomOutBtn) zoomOutBtn.disabled = cardZoomPx <= CARD_ZOOM_MIN;
    if (zoomInBtn) zoomInBtn.disabled = cardZoomPx >= CARD_ZOOM_MAX;
    if (persist) {
      try {
        localStorage.setItem(CARD_ZOOM_KEY, String(cardZoomPx));
      } catch (_) { /* ignore */ }
    }
    if (syncPageSize() && refetchOnPageChange) {
      offset = 0;
      search();
    }
  }

  function loadCardZoom() {
    let saved = defaultCardZoom();
    try {
      const raw = localStorage.getItem(CARD_ZOOM_KEY);
      if (raw != null) saved = clampCardZoom(raw);
    } catch (_) { /* ignore */ }
    applyCardZoom(saved, false, false);
  }

  function bindZoomHold(btn, delta) {
    if (!btn) return;
    let holdTimer = null;
    let repeatTimer = null;

    const stop = () => {
      if (holdTimer) clearTimeout(holdTimer);
      if (repeatTimer) clearInterval(repeatTimer);
      holdTimer = null;
      repeatTimer = null;
    };

    const step = () => {
      applyCardZoom(cardZoomPx + delta, true);
      if (
        (delta < 0 && cardZoomPx <= CARD_ZOOM_MIN) ||
        (delta > 0 && cardZoomPx >= CARD_ZOOM_MAX)
      ) {
        stop();
      }
    };

    const start = (e) => {
      e.preventDefault();
      stop();
      step();
      holdTimer = setTimeout(() => {
        repeatTimer = setInterval(step, 55);
      }, 280);
    };

    btn.addEventListener("pointerdown", start);
    btn.addEventListener("pointerup", stop);
    btn.addEventListener("pointerleave", stop);
    btn.addEventListener("pointercancel", stop);
    btn.addEventListener("click", (e) => e.preventDefault());
  }

  loadCardZoom();
  bindZoomHold(zoomOutBtn, -CARD_ZOOM_STEP);
  bindZoomHold(zoomInBtn, CARD_ZOOM_STEP);

  qEl.addEventListener("input", scheduleSearch);
  sortEl.addEventListener("change", resetOffsetAndSearch);

  filterEls.forEach((el) => {
    el.addEventListener("change", () => {
      if (el === seriesEl) populateSetOptions();
      if (el === setEl && setEl.value) {
        const opt = setEl.selectedOptions[0];
        const sid = opt?.dataset?.seriesId;
        if (sid && seriesEl.value !== sid) seriesEl.value = sid;
      }
      resetOffsetAndSearch();
    });
  });
  dexEl.addEventListener("input", scheduleSearch);

  function syncSearchOrbitPath() {
    const orbit = document.querySelector(".sp-search-orbit");
    if (!orbit) return;
    const w = orbit.clientWidth;
    const h = orbit.clientHeight;
    if (w < 8 || h < 8) return;
    const r = Math.min(19, w / 2, h / 2);
    const d = [
      `M ${r},0`,
      `H ${w - r}`,
      `A ${r},${r} 0 0 1 ${w},${r}`,
      `V ${h - r}`,
      `A ${r},${r} 0 0 1 ${w - r},${h}`,
      `H ${r}`,
      `A ${r},${r} 0 0 1 0,${h - r}`,
      `V ${r}`,
      `A ${r},${r} 0 0 1 ${r},0`,
      "Z",
    ].join(" ");
    orbit.style.setProperty("--sp-orbit-path", `path("${d}")`);
  }

  function scheduleSearchOrbitSync() {
    requestAnimationFrame(() => {
      syncSearchOrbitPath();
      requestAnimationFrame(syncSearchOrbitPath);
    });
  }

  advToggle.addEventListener("click", () => {
    const open = advPanel.hidden;
    advPanel.hidden = !open;
    advToggle.setAttribute("aria-expanded", open ? "true" : "false");
    advToggle.classList.toggle("open", open);
    scheduleSearchOrbitSync();
  });

  const searchPanel = document.querySelector(".sp-search");
  if (searchPanel && typeof ResizeObserver !== "undefined") {
    new ResizeObserver(syncSearchOrbitPath).observe(searchPanel);
  }
  window.addEventListener("resize", syncSearchOrbitPath);
  syncSearchOrbitPath();

  clearFiltersBtn.addEventListener("click", () => {
    clearAdvancedFilters();
    resetOffsetAndSearch();
  });

  document.querySelectorAll(".sp-linkish").forEach((btn) => {
    btn.addEventListener("click", () => {
      qEl.value = btn.dataset.quick || "";
      openAdvanced();
      resetOffsetAndSearch();
    });
  });

  pagePrev.addEventListener("click", () => {
    offset = Math.max(0, offset - pageSize);
    search();
  });

  pageNext.addEventListener("click", () => {
    offset += pageSize;
    search();
  });

  let resizePageTimer = null;
  window.addEventListener("resize", () => {
    clearTimeout(resizePageTimer);
    resizePageTimer = setTimeout(() => {
      if (syncPageSize()) {
        offset = 0;
        search();
      }
    }, 200);
  });

  modalClose.addEventListener("click", () => modal.close());
  modal.addEventListener("click", (e) => {
    if (e.target === modal) modal.close();
  });

  // Swipe-down to close (mobile sheet)
  (function bindModalSwipeClose() {
    const inner = modal.querySelector(".sp-modal-inner");
    const chrome = modal.querySelector(".sp-modal-chrome");
    const scrollEl = modalBody;
    if (!inner || !chrome) return;

    let startY = 0;
    let startX = 0;
    let dragging = false;
    let dy = 0;

    const reset = () => {
      dragging = false;
      dy = 0;
      inner.style.transition = "";
      inner.style.transform = "";
    };

    const onStart = (y, x) => {
      if (!modal.open) return;
      if (scrollEl && scrollEl.scrollTop > 2) return;
      startY = y;
      startX = x;
      dragging = true;
      dy = 0;
      inner.style.transition = "none";
    };

    const onMove = (y, x, e) => {
      if (!dragging) return;
      dy = y - startY;
      const dx = Math.abs(x - startX);
      if (dy < 0) dy = 0;
      if (dy > 8 && dy > dx && e.cancelable) e.preventDefault();
      inner.style.transform = `translateY(${dy}px)`;
    };

    const onEnd = () => {
      if (!dragging) return;
      const shouldClose = dy > 110;
      inner.style.transition = "transform 0.2s ease";
      if (shouldClose) {
        inner.style.transform = "translateY(110%)";
        const finish = () => {
          modal.close();
          reset();
          inner.removeEventListener("transitionend", finish);
        };
        inner.addEventListener("transitionend", finish);
        setTimeout(finish, 250);
      } else {
        inner.style.transform = "translateY(0)";
        setTimeout(reset, 220);
      }
      dragging = false;
    };

    const target = chrome;
    const bind = (el) => {
      el.addEventListener(
        "touchstart",
        (e) => {
          if (e.touches.length !== 1) return;
          onStart(e.touches[0].clientY, e.touches[0].clientX);
        },
        { passive: true }
      );
      el.addEventListener(
        "touchmove",
        (e) => {
          if (e.touches.length !== 1) return;
          onMove(e.touches[0].clientY, e.touches[0].clientX, e);
        },
        { passive: false }
      );
      el.addEventListener("touchend", onEnd);
      el.addEventListener("touchcancel", reset);
    };
    bind(target);
    if (scrollEl) bind(scrollEl);

    modal.addEventListener("close", reset);
  })();

  loadMeta().then(resetOffsetAndSearch);
})();
