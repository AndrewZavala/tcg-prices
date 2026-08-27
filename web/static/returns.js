/** CK returns — committed fulfillments + open unpaid inventory */
(function () {
  const els = {
    meta: document.getElementById("meta"),
    monthFilter: document.getElementById("monthFilter"),
    openMonthFilter: document.getElementById("openMonthFilter"),
    stPlanned: document.getElementById("stPlanned"),
    stPacked: document.getElementById("stPacked"),
    stSent: document.getElementById("stSent"),
    stPaid: document.getElementById("stPaid"),
    resultSummary: document.getElementById("resultSummary"),
    openResultSummary: document.getElementById("openResultSummary"),
    statusMsg: document.getElementById("statusMsg"),
    openStatusMsg: document.getElementById("openStatusMsg"),
    kpiCost: document.getElementById("kpiCost"),
    kpiRevenue: document.getElementById("kpiRevenue"),
    kpiProfit: document.getElementById("kpiProfit"),
    kpiRoi: document.getElementById("kpiRoi"),
    topCards: document.getElementById("topCards"),
    openTopCards: document.getElementById("openTopCards"),
    emptyState: document.getElementById("emptyState"),
    openEmptyState: document.getElementById("openEmptyState"),
    panelCommitted: document.getElementById("panelCommitted"),
    panelOpen: document.getElementById("panelOpen"),
    tabCommitted: document.getElementById("tabCommitted"),
    tabOpen: document.getElementById("tabOpen"),
  };

  let activeTab = "committed";
  let moneyChart = null;
  let statusChart = null;
  let openMoneyChart = null;
  let openStageChart = null;

  const COLORS = {
    cost: "#6b4a3a",
    revenue: "#c9852c",
    profit: "#2f6b4f",
    free: "#5c6b7a",
    problem: "#a65d4a",
    planned: "#a89070",
    packed: "#8b7355",
    sent: "#c9852c",
    paid: "#2f6b4f",
  };

  function fmtUsd(n) {
    if (n == null || Number.isNaN(Number(n))) return "—";
    return "$" + Number(n).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }

  function fmtPct(n) {
    if (n == null || Number.isNaN(Number(n))) return "—";
    const v = Number(n);
    return (v > 0 ? "+" : "") + v.toFixed(1) + "%";
  }

  function monthLabel(ym) {
    if (!ym) return "All time";
    const [y, m] = ym.split("-").map(Number);
    return new Date(y, m - 1, 1).toLocaleDateString(undefined, { month: "long", year: "numeric" });
  }

  function selectedStatuses() {
    const out = [];
    if (els.stPlanned?.checked) out.push("planned");
    if (els.stPacked?.checked) out.push("packed");
    if (els.stSent?.checked) out.push("sent");
    if (els.stPaid?.checked) out.push("paid");
    return out.length ? out : ["planned", "packed", "sent", "paid"];
  }

  function setLoading(el, on, msg) {
    if (!el) return;
    if (typeof setStatusLoading === "function") {
      setStatusLoading(el, on, on ? msg : "");
    } else {
      el.textContent = on ? msg : "";
      el.className = "opp-status";
    }
  }

  function fillMonthOptions(selectEl, months, selected) {
    if (!selectEl) return;
    const cur = selected || selectEl.value || "";
    selectEl.innerHTML =
      `<option value="">All months</option>` +
      (months || [])
        .map((m) => `<option value="${m}"${m === cur ? " selected" : ""}>${monthLabel(m)}</option>`)
        .join("");
    if (cur && ![...selectEl.options].some((o) => o.value === cur)) {
      selectEl.value = "";
    } else {
      selectEl.value = cur;
    }
  }

  function renderKpis(summary) {
    const cost = summary.cost || 0;
    const revenue = summary.revenue || 0;
    const profit = summary.profit || 0;
    els.kpiCost.textContent = fmtUsd(cost);
    els.kpiRevenue.textContent = fmtUsd(revenue);
    els.kpiProfit.textContent = fmtUsd(profit);
    els.kpiProfit.classList.toggle("is-pos", profit > 0);
    els.kpiProfit.classList.toggle("is-neg", profit < 0);
    els.kpiRoi.textContent = fmtPct(summary.roi_pct);
    els.kpiRoi.classList.toggle("is-pos", (summary.roi_pct || 0) > 0);
    els.kpiRoi.classList.toggle("is-neg", (summary.roi_pct || 0) < 0);
  }

  function renderTopCards(tbody, emptyEl, rows) {
    if (!tbody) return;
    if (!rows.length) {
      tbody.innerHTML = "";
      if (emptyEl) emptyEl.hidden = false;
      return;
    }
    if (emptyEl) emptyEl.hidden = true;
    tbody.innerHTML = rows
      .map((row) => {
        const profitClass = (row.profit ?? 0) >= 0 ? "is-pos" : "is-neg";
        const finish = row.finish && row.finish !== "normal" ? ` · ${row.finish}` : "";
        return `<tr>
          <td>${escapeHtml(row.name || "—")}${escapeHtml(finish)}</td>
          <td class="num">${row.qty ?? 0}</td>
          <td class="num">${fmtUsd(row.cost)}</td>
          <td class="num">${fmtUsd(row.revenue)}</td>
          <td class="num ${profitClass}">${fmtUsd(row.profit)}</td>
        </tr>`;
      })
      .join("");
  }

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function upsertBarChart(chartRef, canvasId, byMonth, moneyLabel) {
    const labels = byMonth.map((r) => monthLabel(r.month));
    const datasets = [
      {
        label: "Cost (spent)",
        data: byMonth.map((r) => r.cost || 0),
        backgroundColor: COLORS.cost,
        borderRadius: 4,
      },
      {
        label: moneyLabel || "Expected CK pay",
        data: byMonth.map((r) => r.revenue || 0),
        backgroundColor: COLORS.revenue,
        borderRadius: 4,
      },
      {
        label: "Expected profit",
        data: byMonth.map((r) => r.profit || 0),
        backgroundColor: COLORS.profit,
        borderRadius: 4,
      },
    ];
    const ctx = document.getElementById(canvasId);
    if (chartRef.chart) {
      chartRef.chart.data.labels = labels;
      chartRef.chart.data.datasets = datasets;
      chartRef.chart.update();
      return;
    }
    chartRef.chart = new Chart(ctx, {
      type: "bar",
      data: { labels, datasets },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { position: "bottom" },
          tooltip: {
            callbacks: {
              label: (c) => `${c.dataset.label}: ${fmtUsd(c.parsed.y)}`,
            },
          },
        },
        scales: {
          x: { grid: { display: false } },
          y: {
            ticks: {
              callback: (v) => "$" + Number(v).toLocaleString(),
            },
          },
        },
      },
    });
  }

  function upsertDoughnut(chartRef, canvasId, rows, labelMap) {
    const labels = rows.map((r) => labelMap[r.stage || r.status] || r.stage || r.status);
    const data = rows.map((r) => r.qty || 0);
    const colors = rows.map((r) => COLORS[r.stage || r.status] || COLORS.cost);
    const ctx = document.getElementById(canvasId);
    if (chartRef.chart) {
      chartRef.chart.data.labels = labels;
      chartRef.chart.data.datasets[0].data = data;
      chartRef.chart.data.datasets[0].backgroundColor = colors;
      chartRef.chart.update();
      return;
    }
    chartRef.chart = new Chart(ctx, {
      type: "doughnut",
      data: {
        labels,
        datasets: [{ data, backgroundColor: colors, borderWidth: 0 }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { position: "bottom" },
          tooltip: {
            callbacks: {
              label: (c) => {
                const row = rows[c.dataIndex];
                return `${c.label}: ${c.parsed} copies · ${fmtUsd(row?.profit)} profit`;
              },
            },
          },
        },
      },
    });
  }

  const moneyChartRef = { get chart() { return moneyChart; }, set chart(v) { moneyChart = v; } };
  const statusChartRef = { get chart() { return statusChart; }, set chart(v) { statusChart = v; } };
  const openMoneyChartRef = { get chart() { return openMoneyChart; }, set chart(v) { openMoneyChart = v; } };
  const openStageChartRef = { get chart() { return openStageChart; }, set chart(v) { openStageChart = v; } };

  async function loadCommitted() {
    setLoading(els.statusMsg, true, "Loading returns…");
    try {
      const params = new URLSearchParams({
        statuses: selectedStatuses().join(","),
      });
      const month = els.monthFilter.value;
      if (month) params.set("month", month);
      const res = await fetch(`/api/inventory/ck-returns?${params}`);
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      fillMonthOptions(els.monthFilter, data.months || [], data.month || month || "");
      if (activeTab === "committed") renderKpis(data.summary || {});
      const summary = data.summary || {};
      els.resultSummary.textContent = `${Number(summary.lines || 0).toLocaleString()} lines · ${Number(summary.qty || 0).toLocaleString()} copies · ${monthLabel(data.month)}`;
      if (activeTab === "committed") {
        els.meta.textContent = data.month
          ? `Committed returns for ${monthLabel(data.month)}`
          : "What you spent vs expected CK pay from Need to pack through Paid";
      }

      const chartMonths = data.month
        ? (data.by_month || []).filter((r) => r.month === data.month)
        : data.by_month || [];
      upsertBarChart(moneyChartRef, "chartMoney", chartMonths.length ? chartMonths : data.by_month || []);
      upsertDoughnut(statusChartRef, "chartStatus", data.by_status || [], {
        planned: "Need to pack",
        packed: "Packed",
        sent: "Sent",
        paid: "Paid",
      });
      renderTopCards(els.topCards, els.emptyState, data.top_cards || []);
      setLoading(els.statusMsg, false);
    } catch (err) {
      els.statusMsg.textContent = err.message || String(err);
      els.statusMsg.className = "opp-status error";
    }
  }

  async function loadOpen() {
    setLoading(els.openStatusMsg, true, "Loading open book…");
    try {
      const params = new URLSearchParams();
      const month = els.openMonthFilter.value;
      if (month) params.set("month", month);
      const res = await fetch(`/api/inventory/ck-returns/open?${params}`);
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      fillMonthOptions(els.openMonthFilter, data.months || [], data.month || month || "");
      if (activeTab === "open") renderKpis(data.summary || {});
      const summary = data.summary || {};
      els.openResultSummary.textContent = `${Number(summary.lines || 0).toLocaleString()} positions · ${Number(summary.qty || 0).toLocaleString()} copies · ${monthLabel(data.month)}`;
      if (activeTab === "open") {
        els.meta.textContent = data.month
          ? `Open unpaid inventory bought in ${monthLabel(data.month)}`
          : "Total cost and expected profit for all inventory not yet Paid";
      }

      const chartMonths = data.month
        ? (data.by_month || []).filter((r) => r.month === data.month)
        : data.by_month || [];
      upsertBarChart(
        openMoneyChartRef,
        "chartOpenMoney",
        chartMonths.length ? chartMonths : data.by_month || [],
        "Expected CK pay"
      );
      upsertDoughnut(openStageChartRef, "chartOpenStage", data.by_stage || [], {
        free: "Free stock",
        problem: "Problem / hold",
        planned: "Need to pack",
        packed: "Packed",
        sent: "Sent / awaiting",
      });
      renderTopCards(els.openTopCards, els.openEmptyState, data.top_cards || []);
      setLoading(els.openStatusMsg, false);
    } catch (err) {
      els.openStatusMsg.textContent = err.message || String(err);
      els.openStatusMsg.className = "opp-status error";
    }
  }

  function switchTab(tab) {
    activeTab = tab;
    const isCommitted = tab === "committed";
    els.tabCommitted?.classList.toggle("is-active", isCommitted);
    els.tabOpen?.classList.toggle("is-active", !isCommitted);
    els.tabCommitted?.setAttribute("aria-selected", String(isCommitted));
    els.tabOpen?.setAttribute("aria-selected", String(!isCommitted));
    if (els.panelCommitted) els.panelCommitted.hidden = !isCommitted;
    if (els.panelOpen) els.panelOpen.hidden = isCommitted;
    if (isCommitted) loadCommitted();
    else loadOpen();
  }

  els.tabCommitted?.addEventListener("click", () => switchTab("committed"));
  els.tabOpen?.addEventListener("click", () => switchTab("open"));
  els.monthFilter?.addEventListener("change", loadCommitted);
  els.openMonthFilter?.addEventListener("change", loadOpen);
  els.stPlanned?.addEventListener("change", loadCommitted);
  els.stPacked?.addEventListener("change", loadCommitted);
  els.stSent?.addEventListener("change", loadCommitted);
  els.stPaid?.addEventListener("change", loadCommitted);

  loadCommitted();
})();
