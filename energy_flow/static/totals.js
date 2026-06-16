/** Solar Assistant-style Totals page (30-day + 12-month charts and tables). */
const SA_TOTALS = {
  load: "#5470c6",
  solar: "#fac858",
  batteryCharge: "#91cc75",
  batteryDischarge: "#333333",
  gridUsed: "#ee6666",
  gridExport: "#73c0de",
};

const TOTALS_SERIES = [
  { key: "loadKwh", label: "Load", color: SA_TOTALS.load },
  { key: "solarKwh", label: "Solar PV", color: SA_TOTALS.solar },
  { key: "batteryChargeKwh", label: "Battery charged", color: SA_TOTALS.batteryCharge },
  { key: "batteryDischargeKwh", label: "Battery discharged", color: SA_TOTALS.batteryDischarge },
  { key: "gridUsedKwh", label: "Grid used", color: SA_TOTALS.gridUsed },
  { key: "gridExportKwh", label: "Grid exported", color: SA_TOTALS.gridExport },
];

let dailyTotalsChart = null;
let monthlyTotalsChart = null;
let monthCompareChart = null;
let totalsDailyEnd = null;
let totalsMonthlyEnd = null;
let totalsDailyOffset = 0;
let totalsMonthlyOffset = 0;
let totalsPickerMonths = [];
let totalsAvailableDates = [];
let monthCompareKey = null;
let totalsLoaded = false;
let totalsUiBound = false;

function totalsEl(id) {
  return document.getElementById(id);
}

function fmtDayLabel(dateText, withYear = true) {
  const d = new Date(`${dateText}T12:00:00`);
  return d.toLocaleDateString([], {
    day: "numeric",
    month: "short",
    year: withYear ? "numeric" : undefined,
  });
}

function fmtMonthLabel(label) {
  const [year, month] = label.split("-").map(Number);
  return new Date(year, month - 1, 1).toLocaleDateString([], { month: "short", year: "numeric" });
}

function fmtMonthPickerLabel(label) {
  const [year, month] = label.split("-").map(Number);
  return new Date(year, month - 1, 1).toLocaleDateString([], { month: "long", year: "numeric" });
}

function fmtKwh(value) {
  const n = Number(value) || 0;
  if (Math.abs(n - Math.round(n)) < 0.05) return `${Math.round(n)} kWh`;
  return `${n.toFixed(1)} kWh`;
}

function destroyTotalsCharts() {
  if (dailyTotalsChart) {
    dailyTotalsChart.destroy();
    dailyTotalsChart = null;
  }
  if (monthlyTotalsChart) {
    monthlyTotalsChart.destroy();
    monthlyTotalsChart = null;
  }
  if (monthCompareChart) {
    monthCompareChart.destroy();
    monthCompareChart = null;
  }
}

function chartMax(rows) {
  let max = 0;
  for (const row of rows || []) {
    let stack = 0;
    for (const series of TOTALS_SERIES) stack += row[series.key] || 0;
    max = Math.max(max, stack);
  }
  if (max <= 0) return 10;
  return Math.ceil(max / 5) * 5;
}

function buildDatasets(rows) {
  return TOTALS_SERIES.map((series) => ({
    label: series.label,
    data: rows.map((row) => row[series.key] ?? 0),
    backgroundColor: series.color,
    borderWidth: 0,
    stack: "totals",
    maxBarThickness: 18,
  }));
}

function renderTotalsChart(canvas, rows, { titleDateKey = "date" } = {}) {
  if (typeof Chart === "undefined" || !canvas) return null;
  return new Chart(canvas, {
    type: "bar",
    data: {
      labels: rows.map((row) => row.chartLabel || row.label),
      datasets: buildDatasets(rows),
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: {
          position: "bottom",
          labels: { boxWidth: 10, boxHeight: 10, font: { size: 11 } },
        },
        tooltip: {
          callbacks: {
            title(items) {
              const row = rows[items[0]?.dataIndex];
              if (!row) return items[0]?.label || "";
              const key = row[titleDateKey] || row.date || row.label;
              return titleDateKey === "date" ? fmtDayLabel(key) : fmtMonthLabel(key);
            },
            label(ctx) {
              return `${ctx.dataset.label}: ${ctx.parsed.y} kWh`;
            },
            footer(items) {
              const total = items.reduce((sum, item) => sum + (item.parsed.y || 0), 0);
              return `Total: ${total.toFixed(1)} kWh`;
            },
          },
        },
      },
      scales: {
        x: { stacked: true, grid: { display: false }, ticks: { font: { size: 10 }, maxRotation: 0 } },
        y: {
          stacked: true,
          beginAtZero: true,
          suggestedMax: chartMax(rows),
          title: { display: true, text: "kWh", font: { size: 12 } },
          grid: { color: "rgba(0,0,0,0.06)" },
        },
      },
    },
  });
}

function renderTotalsTable(tbody, rows, wrap) {
  if (!tbody) return;
  tbody.innerHTML = rows
    .map((row) => {
      const cells = TOTALS_SERIES.map((series) => `<td class="number">${fmtKwh(row[series.key] ?? 0)}</td>`).join("");
      const title = row.date ? ` title="${row.date}"` : row.monthKey ? ` title="${row.monthKey}"` : "";
      return `<tr><th scope="row"${title}>${row.label}</th>${cells}</tr>`;
    })
    .join("");
  if (wrap) wrap.scrollTop = 0;
}

function buildMonthRange(firstDate, lastDate) {
  if (!firstDate || !lastDate) return [];
  const out = [];
  const [y0, m0] = firstDate.slice(0, 7).split("-").map(Number);
  const [y1, m1] = lastDate.slice(0, 7).split("-").map(Number);
  let year = y0;
  let month = m0;
  while (year < y1 || (year === y1 && month <= m1)) {
    out.push(`${year}-${String(month).padStart(2, "0")}`);
    month += 1;
    if (month > 12) {
      month = 1;
      year += 1;
    }
  }
  return out;
}

function fillMonthPicker(months, selected) {
  const picker = totalsEl("monthlyTotalsPicker");
  if (!picker || !months.length) return;
  const safeSelected = selected && months.includes(selected) ? selected : months[months.length - 1];
  picker.innerHTML = months
    .map((ym) => `<option value="${ym}"${ym === safeSelected ? " selected" : ""}>${fmtMonthPickerLabel(ym)}</option>`)
    .join("");
  picker.value = safeSelected;
}

function currentMonthlyEnd() {
  if (totalsMonthlyEnd && totalsPickerMonths.includes(totalsMonthlyEnd)) return totalsMonthlyEnd;
  if (!totalsPickerMonths.length) return null;
  const idx = totalsPickerMonths.length - 1 - totalsMonthlyOffset;
  return totalsPickerMonths[Math.max(0, Math.min(totalsPickerMonths.length - 1, idx))];
}

function currentDailyEnd() {
  if (totalsDailyEnd && totalsAvailableDates.includes(totalsDailyEnd)) return totalsDailyEnd;
  if (!totalsAvailableDates.length) return null;
  const idx = totalsAvailableDates.length - 1 - totalsDailyOffset;
  return totalsAvailableDates[Math.max(0, Math.min(totalsAvailableDates.length - 1, idx))];
}

function syncPickers(payload) {
  const pickers = payload.pickers || {};
  if (pickers.months?.length) {
    totalsPickerMonths = pickers.months;
  } else if (!totalsPickerMonths.length) {
    totalsPickerMonths = buildMonthRange(payload.range?.firstDate, payload.range?.lastDate);
  }
  if (pickers.dates?.length) {
    totalsAvailableDates = pickers.dates;
  } else if (!totalsAvailableDates.length) {
    totalsAvailableDates = buildDateRange(payload.range?.firstDate, payload.range?.lastDate);
  }

  const dailyPicker = totalsEl("dailyTotalsPicker");
  if (dailyPicker) {
    const first = pickers.firstDate || payload.range?.firstDate;
    const last = pickers.lastDate || payload.range?.lastDate;
    if (first) dailyPicker.min = first;
    if (last) dailyPicker.max = last;
  }

  totalsMonthlyEnd = payload.monthly?.endMonth || currentMonthlyEnd();
  totalsDailyEnd = payload.daily?.endDate || currentDailyEnd();

  if (dailyPicker && totalsDailyEnd) dailyPicker.value = totalsDailyEnd;
  if (totalsPickerMonths.length && totalsMonthlyEnd) {
    fillMonthPicker(totalsPickerMonths, totalsMonthlyEnd);
  }
}

function buildDateRange(firstDate, lastDate) {
  if (!firstDate || !lastDate) return [];
  const out = [];
  const start = new Date(`${firstDate}T12:00:00`);
  const end = new Date(`${lastDate}T12:00:00`);
  for (let d = new Date(start); d <= end; d.setDate(d.getDate() + 1)) {
    out.push(d.toISOString().slice(0, 10));
  }
  return out;
}

function applyTotalsPayload(payload) {
  const dailyRows = (payload.daily?.rows || []).map((row) => ({
    ...row,
    chartLabel: fmtDayLabel(row.date || row.label, false),
    label: fmtDayLabel(row.date || row.label, true),
  }));
  const monthlyRows = (payload.monthly?.rows || []).map((row) => ({
    ...row,
    monthKey: row.label,
    chartLabel: fmtMonthLabel(row.label).replace(/\s+\d{4}$/, ""),
    label: fmtMonthLabel(row.label),
  }));

  const dailyRange = totalsEl("dailyTotalsRange");
  if (dailyRange) {
    dailyRange.textContent =
      payload.daily?.startDate && payload.daily?.endDate
        ? `${fmtDayLabel(payload.daily.startDate)} → ${fmtDayLabel(payload.daily.endDate)}`
        : "No daily data";
  }

  const monthlyRange = totalsEl("monthlyTotalsRange");
  if (monthlyRange) {
    monthlyRange.textContent =
      payload.monthly?.startMonth && payload.monthly?.endMonth
        ? `${fmtMonthLabel(payload.monthly.startMonth)} → ${fmtMonthLabel(payload.monthly.endMonth)}`
        : "No monthly data";
  }

  const note = totalsEl("totalsSourceNote");
  if (note) {
    note.textContent = payload?.source
      ? `LuxPower inverter totals · ${payload.source} · downloaded data ${payload.range?.firstDate || "?"} to ${payload.range?.lastDate || "?"}`
      : "";
  }

  syncPickers(payload);
  totalsDailyOffset = payload.daily?.offset || 0;
  totalsMonthlyOffset = payload.monthly?.offset || 0;

  destroyTotalsCharts();
  dailyTotalsChart = renderTotalsChart(totalsEl("dailyTotalsChart"), dailyRows, { titleDateKey: "date" });
  monthlyTotalsChart = renderTotalsChart(totalsEl("monthlyTotalsChart"), monthlyRows, { titleDateKey: "monthKey" });
  renderTotalsTable(totalsEl("dailyTotalsTable"), dailyRows, totalsEl("dailyTotalsTable")?.closest(".totals-table-wrap"));
  renderTotalsTable(totalsEl("monthlyTotalsTable"), monthlyRows, totalsEl("monthlyTotalsTable")?.closest(".totals-table-wrap"));

  totalsEl("dailyTotalsPrev").disabled = !payload.daily?.canPrev;
  totalsEl("dailyTotalsNext").disabled = !payload.daily?.canNext;
  totalsEl("monthlyTotalsPrev").disabled = !payload.monthly?.canPrev;
  totalsEl("monthlyTotalsNext").disabled = !payload.monthly?.canNext;

  syncMonthComparePicker(totalsMonthlyEnd || payload.range?.lastDate?.slice(0, 7));
  loadMonthCompare();

  const err = totalsEl("totalsError");
  if (err) {
    err.hidden = true;
    err.textContent = "";
  }
}

function totalsQuery() {
  const params = new URLSearchParams();
  if (totalsDailyEnd) params.set("dailyEnd", totalsDailyEnd);
  else params.set("dailyOffset", String(totalsDailyOffset));
  if (totalsMonthlyEnd) params.set("monthlyEnd", totalsMonthlyEnd);
  else params.set("monthlyOffset", String(totalsMonthlyOffset));
  return params.toString();
}

async function loadTotals() {
  totalsEl("totalsWrap")?.classList.add("loading");
  try {
    const qs = totalsQuery();
    const res = await fetch(`/api/history/totals?${qs}&_=${Date.now()}`, { cache: "no-store" });
    const data = await res.json();
    if (!data.ok) throw new Error(data.error || "Totals load failed");
    applyTotalsPayload(data);
    totalsLoaded = true;
  } catch (err) {
    const errEl = totalsEl("totalsError");
    if (errEl) {
      errEl.textContent = String(err.message || err);
      errEl.hidden = false;
    }
    destroyTotalsCharts();
    console.error(err);
  } finally {
    totalsEl("totalsWrap")?.classList.remove("loading");
  }
}

function stepDaily(delta) {
  const dates = totalsAvailableDates.length
    ? totalsAvailableDates
    : buildDateRange(totalsEl("dailyTotalsPicker")?.min, totalsEl("dailyTotalsPicker")?.max);
  const current = currentDailyEnd();
  if (!dates.length || !current) return;
  const idx = dates.indexOf(current);
  if (idx < 0) return;
  const targetIdx = idx + delta * 30;
  if (targetIdx < 0 || targetIdx >= dates.length) return;
  totalsDailyEnd = dates[targetIdx];
  totalsDailyOffset = 0;
  loadTotals();
}

function syncMonthComparePicker(defaultKey) {
  const picker = totalsEl("monthComparePicker");
  if (!picker) return;
  if (totalsPickerMonths.length) {
    picker.min = totalsPickerMonths[0];
    picker.max = totalsPickerMonths[totalsPickerMonths.length - 1];
  }
  if (!monthCompareKey && defaultKey) monthCompareKey = defaultKey;
  if (monthCompareKey) picker.value = monthCompareKey;
}

function applyMonthComparePayload(payload) {
  const compare = payload.compare || {};
  const rows = (compare.rows || []).map((row) => ({
    ...row,
    monthKey: row.label,
    chartLabel: String(row.year),
    label: fmtMonthLabel(row.label),
  }));

  const range = totalsEl("monthCompareRange");
  if (range) {
    const monthName = compare.monthName || "Month";
    range.textContent =
      rows.length > 1
        ? `${monthName}: ${rows[0].label} → ${rows[rows.length - 1].label}`
        : rows.length === 1
          ? rows[0].label
          : "No data";
  }

  if (monthCompareChart) {
    monthCompareChart.destroy();
    monthCompareChart = null;
  }
  monthCompareChart = renderTotalsChart(totalsEl("monthCompareChart"), rows, { titleDateKey: "monthKey" });
  renderTotalsTable(
    totalsEl("monthCompareTable"),
    rows,
    totalsEl("monthCompareTable")?.closest(".totals-table-wrap"),
  );
}

async function loadMonthCompare() {
  const picker = totalsEl("monthComparePicker");
  const key = monthCompareKey || picker?.value;
  if (!key) return;
  monthCompareKey = key;
  if (picker) picker.value = key;

  try {
    const res = await fetch(`/api/history/totals/compare?monthKey=${encodeURIComponent(key)}&_=${Date.now()}`, {
      cache: "no-store",
    });
    const data = await res.json();
    if (!data.ok) throw new Error(data.error || "Month compare load failed");
    applyMonthComparePayload(data);
  } catch (err) {
    console.error(err);
    if (monthCompareChart) {
      monthCompareChart.destroy();
      monthCompareChart = null;
    }
    const tbody = totalsEl("monthCompareTable");
    if (tbody) tbody.innerHTML = "";
    const range = totalsEl("monthCompareRange");
    if (range) range.textContent = String(err.message || err);
  }
}

function stepMonthly(delta) {
  if (!totalsPickerMonths.length) return;
  const current = currentMonthlyEnd();
  if (!current) return;
  const idx = totalsPickerMonths.indexOf(current);
  if (idx < 0) return;
  const targetIdx = idx + delta;
  if (targetIdx < 0 || targetIdx >= totalsPickerMonths.length) return;
  totalsMonthlyEnd = totalsPickerMonths[targetIdx];
  totalsMonthlyOffset = 0;
  loadTotals();
}

function bindTotalsUi() {
  if (totalsUiBound) return;
  totalsUiBound = true;

  totalsEl("dailyTotalsPrev")?.addEventListener("click", () => stepDaily(-1));
  totalsEl("dailyTotalsNext")?.addEventListener("click", () => stepDaily(1));
  totalsEl("monthlyTotalsPrev")?.addEventListener("click", () => stepMonthly(-1));
  totalsEl("monthlyTotalsNext")?.addEventListener("click", () => stepMonthly(1));

  totalsEl("dailyTotalsPicker")?.addEventListener("change", (e) => {
    totalsDailyEnd = e.target.value || null;
    totalsDailyOffset = 0;
    loadTotals();
  });

  totalsEl("monthlyTotalsPicker")?.addEventListener("change", (e) => {
    totalsMonthlyEnd = e.target.value || null;
    totalsMonthlyOffset = 0;
    loadTotals();
  });

  totalsEl("monthComparePicker")?.addEventListener("change", (e) => {
    monthCompareKey = e.target.value || null;
    loadMonthCompare();
  });
}

window.initTotals = async function initTotals() {
  if (typeof Chart === "undefined") {
    throw new Error("Chart.js did not load — hard refresh with Ctrl+F5.");
  }
  bindTotalsUi();
  await loadTotals();
};

window.resizeTotals = function resizeTotals() {
  dailyTotalsChart?.resize();
  monthlyTotalsChart?.resize();
  monthCompareChart?.resize();
};

document.addEventListener("DOMContentLoaded", bindTotalsUi);
