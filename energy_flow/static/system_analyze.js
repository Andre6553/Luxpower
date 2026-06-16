/** My system — Analyze System (PV strings vs SOC over history range). */

const SYS_ANALYZE_COLORS = {
  pv1: "#e67e22",
  pv2: "#2ca02c",
  soc: "#1f77b4",
};

let analyzeCharts = {};
let analyzeCoverage = null;

function analyzeEl(id) {
  return document.getElementById(id);
}

function destroyAnalyzeCharts() {
  Object.values(analyzeCharts).forEach((ch) => ch?.destroy?.());
  analyzeCharts = {};
}

function setAnalyzeStatus(msg, isError = false) {
  const node = analyzeEl("sysAnalyzeStatus");
  if (!node) return;
  node.textContent = msg || "";
  node.classList.toggle("sys-status-error", isError);
}

async function fetchAnalyzeCoverage() {
  const res = await fetch(`/api/system/analyze?_=${Date.now()}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const data = await res.json();
  if (!data.ok) throw new Error(data.error || "Failed to load history info");
  return data.coverage;
}

function applyCoverageToUi(coverage) {
  analyzeCoverage = coverage;
  const note = analyzeEl("sysAnalyzeHistoryNote");
  const start = analyzeEl("sysAnalyzeStart");
  const end = analyzeEl("sysAnalyzeEnd");
  const btn = analyzeEl("sysAnalyzeBtn");

  if (!coverage?.hasHistory) {
    if (note) {
      note.innerHTML =
        "No LuxPower history found on this PC. " +
        'Go to the <strong>Live</strong> tab and use <strong>Sync this month</strong> or ' +
        "<strong>Sync all data</strong>, then return here.";
      note.classList.add("sys-analyze-warn");
    }
    if (start) start.disabled = true;
    if (end) end.disabled = true;
    if (btn) btn.disabled = true;
    return;
  }

  if (note) {
    note.textContent = `History available: ${coverage.firstDate} → ${coverage.lastDate} (${coverage.dateCount} days).`;
    note.classList.remove("sys-analyze-warn");
  }

  const last = coverage.lastDate;
  const first = coverage.firstDate;
  if (start) {
    start.min = first;
    start.max = last;
    start.disabled = false;
  }
  if (end) {
    end.min = first;
    end.max = last;
    end.disabled = false;
  }

  const endDate = new Date(`${last}T12:00:00`);
  const begin = new Date(endDate);
  begin.setDate(begin.getDate() - 13);
  const beginIso = begin.toISOString().slice(0, 10);
  const beginClamped = beginIso < first ? first : beginIso;

  if (start && !start.value) start.value = beginClamped;
  if (end && !end.value) end.value = last;
  if (btn) btn.disabled = false;
}

function renderStatCards(data) {
  const host = analyzeEl("sysAnalyzeStats");
  if (!host) return;
  const s = data.summary || {};
  const l1 = data.labels?.pv1 || "PV1";
  const l2 = data.labels?.pv2 || "PV2";
  const range = data.range || {};

  host.innerHTML = `
    <div class="sys-analyze-stat">
      <span class="sys-analyze-stat-label">${l1} total</span>
      <strong>${s.pv1TotalKwh ?? "—"} kWh</strong>
    </div>
    <div class="sys-analyze-stat">
      <span class="sys-analyze-stat-label">${l2} total</span>
      <strong>${s.pv2TotalKwh ?? "—"} kWh</strong>
    </div>
    <div class="sys-analyze-stat">
      <span class="sys-analyze-stat-label">Share</span>
      <strong>${l1} ${s.pv1SharePercent ?? "—"}% · ${l2} ${s.pv2SharePercent ?? "—"}%</strong>
    </div>
    <div class="sys-analyze-stat">
      <span class="sys-analyze-stat-label">Daily wins</span>
      <strong>${l1} ${s.pv1WinsDays ?? 0} · ${l2} ${s.pv2WinsDays ?? 0} · tie ${s.tieDays ?? 0}</strong>
    </div>
    <div class="sys-analyze-stat">
      <span class="sys-analyze-stat-label">Typical SOC peak time</span>
      <strong>${s.typicalSocPeakTime ?? "—"}</strong>
    </div>
    <div class="sys-analyze-stat">
      <span class="sys-analyze-stat-label">Avg peak SOC</span>
      <strong>${s.avgDailySocPeakPct != null ? `${s.avgDailySocPeakPct}%` : "—"}</strong>
    </div>
    <div class="sys-analyze-stat sys-analyze-stat-wide">
      <span class="sys-analyze-stat-label">Period</span>
      <strong>${range.start} → ${range.end} (${range.daysWithData} days with chart data${
        range.daysMissing ? `, ${range.daysMissing} missing` : ""
      })</strong>
    </div>
  `;
}

function renderInsights(data) {
  const host = analyzeEl("sysAnalyzeInsights");
  if (!host) return;
  const tiltRows = data.tiltAnalysis || [];
  const tiltSummaries = new Set(tiltRows.map((r) => r.summary).filter(Boolean));
  const yoyLines = new Set(data.yearComparison?.insights || []);
  const lines = (data.insights || []).filter(
    (t) => !tiltSummaries.has(t) && !yoyLines.has(t)
  );
  if (!lines.length) {
    host.hidden = true;
    return;
  }
  host.hidden = false;
  host.innerHTML = `<ul>${lines.map((t) => `<li>${t}</li>`).join("")}</ul>`;
}

function renderTiltAnalysis(data) {
  const host = analyzeEl("sysAnalyzeTilt");
  if (!host) return;
  const rows = data.tiltAnalysis || [];
  if (!rows.length) {
    host.hidden = true;
    return;
  }
  host.hidden = false;
  const cards = rows
    .map((r) => {
      const verdict = r.verdict || "insufficient_data";
      const title = `${r.label || `MPPT ${r.stringIndex}`} — ${r.previousTiltDegrees != null ? `${r.previousTiltDegrees}°` : "?"} → ${r.newTiltDegrees}° from ${r.effectiveDate}`;
      const stats =
        r.beforeAvgKwhPerDay != null && r.afterAvgKwhPerDay != null
          ? `<div class="sys-analyze-tilt-stats">Before: <strong>${r.beforeAvgKwhPerDay}</strong> kWh/day (${r.beforeDays}d) · After: <strong>${r.afterAvgKwhPerDay}</strong> kWh/day (${r.afterDays}d)${
              r.changePercent != null ? ` · <strong>${r.changePercent > 0 ? "+" : ""}${r.changePercent}%</strong>` : ""
            }</div>`
          : "";
      return `<article class="sys-analyze-tilt-card verdict-${verdict}">
        <strong>${title}</strong>
        <p>${r.summary || ""}</p>
        ${stats}
      </article>`;
    })
    .join("");
  host.innerHTML = `<h3>Tilt change — before vs after</h3><div class="sys-analyze-tilt-list">${cards}</div>`;
}

function chartBaseOptions() {
  return {
    responsive: true,
    maintainAspectRatio: false,
    interaction: { mode: "index", intersect: false },
    plugins: {
      legend: { position: "top", labels: { boxWidth: 12, usePointStyle: true, font: { size: 11 } } },
    },
  };
}

function renderHourlyChart(data) {
  const canvas = analyzeEl("sysChartHourly");
  if (!canvas || typeof Chart === "undefined") return;
  const hp = data.hourlyProfile || {};
  const l1 = data.labels?.pv1 || "PV1";
  const l2 = data.labels?.pv2 || "PV2";

  analyzeCharts.hourly = new Chart(canvas, {
    type: "line",
    data: {
      labels: hp.labels || [],
      datasets: [
        {
          label: `${l1} avg (W)`,
          data: hp.pv1AvgW || [],
          borderColor: SYS_ANALYZE_COLORS.pv1,
          backgroundColor: `${SYS_ANALYZE_COLORS.pv1}22`,
          yAxisID: "y",
          tension: 0.2,
          pointRadius: 0,
          borderWidth: 2,
        },
        {
          label: `${l2} avg (W)`,
          data: hp.pv2AvgW || [],
          borderColor: SYS_ANALYZE_COLORS.pv2,
          backgroundColor: `${SYS_ANALYZE_COLORS.pv2}22`,
          yAxisID: "y",
          tension: 0.2,
          pointRadius: 0,
          borderWidth: 2,
        },
        {
          label: "SOC avg (%)",
          data: hp.socAvgPct || [],
          borderColor: SYS_ANALYZE_COLORS.soc,
          backgroundColor: `${SYS_ANALYZE_COLORS.soc}18`,
          yAxisID: "y1",
          tension: 0.2,
          pointRadius: 0,
          borderWidth: 1.5,
          borderDash: [4, 3],
        },
      ],
    },
    options: {
      ...chartBaseOptions(),
      scales: {
        x: { grid: { color: "#eef0f2" }, ticks: { maxTicksLimit: 12, font: { size: 10 } } },
        y: {
          position: "left",
          title: { display: true, text: "Power (W)", font: { size: 10 } },
          grid: { color: "#eef0f2" },
        },
        y1: {
          position: "right",
          min: 0,
          max: 100,
          title: { display: true, text: "SOC (%)", font: { size: 10 } },
          grid: { drawOnChartArea: false },
        },
      },
    },
  });
}

function renderDailyChart(data) {
  const canvas = analyzeEl("sysChartDaily");
  if (!canvas || typeof Chart === "undefined") return;
  const daily = data.daily || [];
  const l1 = data.labels?.pv1 || "PV1";
  const l2 = data.labels?.pv2 || "PV2";

  analyzeCharts.daily = new Chart(canvas, {
    type: "bar",
    data: {
      labels: daily.map((d) => d.date.slice(5)),
      datasets: [
        {
          label: `${l1} (kWh)`,
          data: daily.map((d) => d.pv1Kwh),
          backgroundColor: SYS_ANALYZE_COLORS.pv1,
        },
        {
          label: `${l2} (kWh)`,
          data: daily.map((d) => d.pv2Kwh),
          backgroundColor: SYS_ANALYZE_COLORS.pv2,
        },
      ],
    },
    options: {
      ...chartBaseOptions(),
      scales: {
        x: { stacked: false, ticks: { maxRotation: 45, minRotation: 0, font: { size: 9 } } },
        y: { title: { display: true, text: "kWh" }, beginAtZero: true },
      },
    },
  });
}

function renderSocPeakChart(data) {
  const canvas = analyzeEl("sysChartSocPeak");
  if (!canvas || typeof Chart === "undefined") return;
  const hist = data.socPeakHourHistogram || {};

  analyzeCharts.socPeak = new Chart(canvas, {
    type: "bar",
    data: {
      labels: hist.labels || [],
      datasets: [
        {
          label: "Days SOC peaked in this hour",
          data: hist.counts || [],
          backgroundColor: SYS_ANALYZE_COLORS.soc,
        },
      ],
    },
    options: {
      ...chartBaseOptions(),
      plugins: { legend: { display: false } },
      scales: {
        x: { ticks: { maxTicksLimit: 12, font: { size: 9 } } },
        y: { beginAtZero: true, ticks: { stepSize: 1 } },
      },
    },
  });
}

function formatVsSelected(vs) {
  if (!vs || vs.totalSolarPct == null) return "—";
  const p = vs.totalSolarPct;
  const sign = p > 0 ? "+" : "";
  const word = vs.verdict === "higher" ? "more" : vs.verdict === "lower" ? "less" : "≈";
  return `${sign}${p}% ${word}`;
}

function renderYearComparison(data) {
  const host = analyzeEl("sysAnalyzeYoy");
  const chartArticle = analyzeEl("sysChartYoyArticle");
  const yoy = data.yearComparison;
  if (!host || !yoy?.periods?.length) {
    if (host) host.hidden = true;
    if (chartArticle) chartArticle.hidden = true;
    return;
  }

  host.hidden = false;
  const cal = yoy.calendarWindow || "same dates";
  const selYear = yoy.selectedYear;
  const insights = (yoy.insights || [])
    .map((t) => `<li>${t}</li>`)
    .join("");
  const insightBlock = insights
    ? `<ul class="sys-analyze-yoy-insights">${insights}</ul>`
    : "";

  const rows = yoy.periods
    .map((p) => {
      const vs = formatVsSelected(p.vsSelected);
      const rowClass = p.isSelected ? "sys-yoy-row-selected" : "";
      const vsClass =
        p.vsSelected?.verdict === "higher"
          ? "sys-yoy-higher"
          : p.vsSelected?.verdict === "lower"
            ? "sys-yoy-lower"
            : "";
      return `<tr class="${rowClass}">
        <td><strong>${p.year}</strong>${p.isSelected ? " ★" : ""}</td>
        <td>${p.start?.slice(5) || ""} → ${p.end?.slice(5) || ""}</td>
        <td>${p.daysWithData}/${p.daysRequested}</td>
        <td>${p.pv1TotalKwh}</td>
        <td>${p.pv2TotalKwh}</td>
        <td>${p.totalSolarKwh}</td>
        <td>${p.avgDailyTotalKwh}</td>
        <td class="${vsClass}">${p.isSelected ? "selected" : vs}</td>
      </tr>`;
    })
    .join("");

  host.innerHTML = `
    <h3>Compare same calendar window in other years</h3>
    <p class="sys-hint">${cal} — selected range is <strong>${selYear}</strong>. Other years use the same month/day span when history is available.</p>
    ${insightBlock}
    <table class="sys-yoy-table">
      <thead>
        <tr>
          <th>Year</th><th>Dates</th><th>Days</th>
          <th>PV1 kWh</th><th>PV2 kWh</th><th>Total</th><th>Avg/day</th><th>vs ${selYear}</th>
        </tr>
      </thead>
      <tbody>${rows}</tbody>
    </table>
  `;

  if (chartArticle) {
    chartArticle.hidden = yoy.periods.length < 2;
    const hint = analyzeEl("sysChartYoyHint");
    if (hint) {
      hint.textContent =
        yoy.otherYearsFound > 0
          ? `Total solar (kWh) for ${cal} in each year.`
          : "";
    }
  }
}

function renderYoyChart(data) {
  const canvas = analyzeEl("sysChartYoy");
  if (!canvas || typeof Chart === "undefined") return;
  const periods = data.yearComparison?.periods || [];
  if (periods.length < 2) return;

  const labels = periods.map((p) => String(p.year));
  const totals = periods.map((p) => p.totalSolarKwh);
  const colors = periods.map((p) =>
    p.isSelected ? "#1a5276" : p.vsSelected?.verdict === "higher" ? "#2ca02c" : p.vsSelected?.verdict === "lower" ? "#d62728" : "#888"
  );

  analyzeCharts.yoy = new Chart(canvas, {
    type: "bar",
    data: {
      labels,
      datasets: [
        {
          label: "Total solar (kWh)",
          data: totals,
          backgroundColor: colors,
        },
      ],
    },
    options: {
      ...chartBaseOptions(),
      plugins: { legend: { display: false } },
      scales: {
        y: { beginAtZero: true, title: { display: true, text: "kWh in period" } },
      },
    },
  });
}

function renderShareChart(data) {
  const canvas = analyzeEl("sysChartShare");
  if (!canvas || typeof Chart === "undefined") return;
  const s = data.summary || {};
  const l1 = data.labels?.pv1 || "PV1";
  const l2 = data.labels?.pv2 || "PV2";

  analyzeCharts.share = new Chart(canvas, {
    type: "doughnut",
    data: {
      labels: [l1, l2],
      datasets: [
        {
          data: [s.pv1TotalKwh || 0, s.pv2TotalKwh || 0],
          backgroundColor: [SYS_ANALYZE_COLORS.pv1, SYS_ANALYZE_COLORS.pv2],
          borderWidth: 0,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { position: "bottom" },
      },
    },
  });
}

function showAnalyzeResults(data) {
  const panel = analyzeEl("sysAnalyzeResults");
  if (panel) panel.classList.remove("hidden");
  renderInsights(data);
  renderTiltAnalysis(data);
  renderYearComparison(data);
  renderStatCards(data);
  destroyAnalyzeCharts();
  renderHourlyChart(data);
  renderDailyChart(data);
  renderYoyChart(data);
  renderSocPeakChart(data);
  renderShareChart(data);
}

async function runSystemAnalyze() {
  const start = analyzeEl("sysAnalyzeStart")?.value;
  const end = analyzeEl("sysAnalyzeEnd")?.value;
  const btn = analyzeEl("sysAnalyzeBtn");

  if (!start || !end) {
    setAnalyzeStatus("Choose a begin and end date.", true);
    return;
  }
  if (end < start) {
    setAnalyzeStatus("End date must be on or after begin date.", true);
    return;
  }

  if (btn) btn.disabled = true;
  setAnalyzeStatus("Analyzing history…");
  analyzeEl("sysAnalyzeResults")?.classList.add("hidden");

  try {
    const res = await fetch(
      `/api/system/analyze?start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}&_=${Date.now()}`,
      { cache: "no-store" }
    );
    const data = await res.json();
    if (!data.ok) {
      throw new Error(data.error || `Analyze failed (HTTP ${res.status})`);
    }
    showAnalyzeResults(data);
    setAnalyzeStatus("Analysis complete.");
  } catch (err) {
    setAnalyzeStatus(String(err.message || err), true);
  } finally {
    if (btn) btn.disabled = !analyzeCoverage?.hasHistory;
  }
}

function bindAnalyzeHandlers() {
  analyzeEl("sysAnalyzeBtn")?.addEventListener("click", () => {
    runSystemAnalyze().catch(console.error);
  });
}

async function initSystemAnalyze() {
  bindAnalyzeHandlers();
  try {
    const coverage = await fetchAnalyzeCoverage();
    applyCoverageToUi(coverage);
    setAnalyzeStatus("");
  } catch (err) {
    setAnalyzeStatus(String(err.message || err), true);
  }
}

window.initSystemAnalyze = initSystemAnalyze;
