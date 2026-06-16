/** LuxPower-style Energy Overview grouped bar chart (month / year / total). */
const LUX_ENERGY = {
  solar: "#70ad47",
  battery: "#4472c4",
  importUser: "#84592b",
  consumption: "#ed7d31",
};

const MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

let energyOverviewChart = null;
let overviewYear = window.HISTORY_YEAR || 2026;
let overviewMonth = new Date().getMonth() + 1;
let overviewMonths = [];
let overviewYears = [2023, 2024, 2025, 2026];
let overviewMode = "month";
let overviewUiBound = false;

function overviewEl(id) {
  return document.getElementById(id);
}

function padMonth(month) {
  return String(month).padStart(2, "0");
}

function overviewMonthLabel() {
  return `${overviewYear}-${padMonth(overviewMonth)}`;
}

function syncOverviewNav() {
  const label = overviewEl("energyOverviewPeriod");
  const nav = overviewEl("energyOverviewMonthNav");
  const prev = overviewEl("energyOverviewPrev");
  const next = overviewEl("energyOverviewNext");

  if (overviewMode === "month") {
    if (label) label.textContent = overviewMonthLabel();
    nav?.classList.remove("hidden");
    const idx = overviewMonths.indexOf(overviewMonthLabel());
    if (prev) prev.disabled = idx <= 0;
    if (next) next.disabled = idx < 0 || idx >= overviewMonths.length - 1;
  } else if (overviewMode === "year") {
    if (label) label.textContent = String(overviewYear);
    nav?.classList.remove("hidden");
    const idx = overviewYears.indexOf(overviewYear);
    if (prev) prev.disabled = idx <= 0;
    if (next) next.disabled = idx < 0 || idx >= overviewYears.length - 1;
  } else {
    nav?.classList.add("hidden");
  }
}

function setOverviewMonths(months) {
  overviewMonths = (months || []).slice().sort();
  if (!overviewMonths.length) return;
  const latest = overviewMonths[overviewMonths.length - 1];
  const [y, m] = latest.split("-").map(Number);
  overviewYear = y;
  overviewMonth = m;
}

function setOverviewYears(years) {
  if (!years?.length) return;
  overviewYears = years.slice().sort((a, b) => a - b);
  if (!overviewYears.includes(overviewYear)) {
    overviewYear = overviewYears[overviewYears.length - 1];
  }
}

function destroyEnergyOverviewChart() {
  if (energyOverviewChart) {
    energyOverviewChart.destroy();
    energyOverviewChart = null;
  }
}

function yAxisMax(rows) {
  let max = 0;
  for (const row of rows || []) {
    max = Math.max(
      max,
      row.solarKwh || 0,
      row.batteryDischargeKwh || 0,
      row.importToUserKwh || 0,
      row.consumptionKwh || 0
    );
  }
  if (max <= 0) return 25;
  return Math.ceil(max / 5) * 5;
}

function chartRows(payload) {
  const mode = payload?.mode || "month";
  if (mode === "year") {
    const rows = payload.months || [];
    return {
      mode,
      title: `Energy Overview (${payload.year})`,
      labels: rows.map((row) => MONTH_NAMES[row.month - 1] || String(row.month)),
      rows,
      apiNote: "yearColumn",
    };
  }
  if (mode === "total") {
    const rows = payload.years || [];
    setOverviewYears(rows.map((row) => row.year));
    return {
      mode,
      title: "Energy Overview (Total)",
      labels: rows.map((row) => String(row.year)),
      rows,
      apiNote: "totalColumn",
    };
  }
  const dayMax = payload.dayMax || 31;
  const days = payload.days || [];
  const byDay = new Map(days.map((row) => [row.day, row]));
  const rows = Array.from({ length: dayMax }, (_, i) => byDay.get(i + 1) || null);
  return {
    mode: "month",
    title: `Energy Overview (${payload.label || overviewMonthLabel()})`,
    labels: Array.from({ length: dayMax }, (_, i) => String(i + 1)),
    rows,
    apiNote: "monthColumn",
  };
}

function seriesValues(rows, key) {
  return rows.map((row) => (row ? row[key] ?? null : null));
}

function renderEnergyOverview(payload) {
  if (typeof Chart === "undefined") return;

  const canvas = overviewEl("energyOverviewCanvas");
  const title = overviewEl("energyOverviewTitle");
  if (!canvas) return;

  const spec = chartRows(payload);
  if (title) title.textContent = spec.title;

  destroyEnergyOverviewChart();
  const ymax = yAxisMax(spec.rows.filter(Boolean));

  energyOverviewChart = new Chart(canvas, {
    type: "bar",
    data: {
      labels: spec.labels,
      datasets: [
        {
          label: "Solar Production",
          data: seriesValues(spec.rows, "solarKwh"),
          backgroundColor: LUX_ENERGY.solar,
          borderWidth: 0,
          maxBarThickness: spec.mode === "month" ? 8 : 14,
        },
        {
          label: "Battery Discharged",
          data: seriesValues(spec.rows, "batteryDischargeKwh"),
          backgroundColor: LUX_ENERGY.battery,
          borderWidth: 0,
          maxBarThickness: spec.mode === "month" ? 8 : 14,
        },
        {
          label: "Import to User",
          data: seriesValues(spec.rows, "importToUserKwh"),
          backgroundColor: LUX_ENERGY.importUser,
          borderWidth: 0,
          maxBarThickness: spec.mode === "month" ? 8 : 14,
        },
        {
          label: "Consumption",
          data: seriesValues(spec.rows, "consumptionKwh"),
          backgroundColor: LUX_ENERGY.consumption,
          borderWidth: 0,
          maxBarThickness: spec.mode === "month" ? 8 : 14,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: { display: false },
        tooltip: {
          borderColor: LUX_ENERGY.solar,
          borderWidth: 1,
          backgroundColor: "#fff",
          titleColor: "#333",
          bodyColor: "#333",
          titleFont: { weight: "600" },
          bodyFont: { weight: "600" },
          callbacks: {
            title(items) {
              return items[0]?.label || "";
            },
            label(ctx) {
              const v = ctx.parsed.y;
              if (v == null) return null;
              return `${ctx.dataset.label}: ${v} kWh`;
            },
          },
        },
      },
      scales: {
        x: {
          grid: { display: false },
          ticks: { font: { size: 11 }, maxRotation: 0 },
        },
        y: {
          beginAtZero: true,
          suggestedMax: ymax,
          ticks: {
            stepSize: ymax <= 25 ? 5 : undefined,
            font: { size: 11 },
          },
          title: {
            display: true,
            text: "Energy(kWh)",
            font: { size: 12 },
          },
          grid: { color: "rgba(0,0,0,0.06)" },
        },
      },
    },
  });

  const note = overviewEl("energyOverviewNote");
  if (note) {
    note.textContent = payload?.source
      ? `LuxPower ${spec.apiNote} · ${payload.source}`
      : "";
  }
}

async function loadEnergyOverview() {
  const errEl = overviewEl("energyOverviewError");
  const wrap = overviewEl("energyOverviewWrap");
  if (errEl) {
    errEl.hidden = true;
    errEl.textContent = "";
  }
  wrap?.classList.add("loading");
  syncOverviewNav();

  try {
    let qs = `year=${overviewYear}&mode=${overviewMode}`;
    if (overviewMode === "month") qs += `&month=${overviewMonth}`;
    const res = await fetch(`/api/history/energy-overview?${qs}&_=${Date.now()}`, {
      cache: "no-store",
    });
    const data = await res.json();
    if (!data.ok) throw new Error(data.error || "Energy overview failed");
    renderEnergyOverview(data);
  } catch (err) {
    if (errEl) {
      errEl.textContent = String(err.message || err);
      errEl.hidden = false;
    }
    destroyEnergyOverviewChart();
    console.error(err);
  } finally {
    wrap?.classList.remove("loading");
  }
}

function navigateOverview(delta) {
  if (overviewMode === "month") {
    const idx = overviewMonths.indexOf(overviewMonthLabel());
    if (idx < 0) return;
    const target = overviewMonths[idx + delta];
    if (!target) return;
    const [y, m] = target.split("-").map(Number);
    overviewYear = y;
    overviewMonth = m;
  } else if (overviewMode === "year") {
    const idx = overviewYears.indexOf(overviewYear);
    if (idx < 0) return;
    const target = overviewYears[idx + delta];
    if (target == null) return;
    overviewYear = target;
  } else {
    return;
  }
  loadEnergyOverview();
}

function bindEnergyOverviewUi() {
  if (overviewUiBound) return;
  overviewUiBound = true;
  overviewEl("energyOverviewPrev")?.addEventListener("click", () => navigateOverview(-1));
  overviewEl("energyOverviewNext")?.addEventListener("click", () => navigateOverview(1));

  document.querySelectorAll(".lux-energy-mode").forEach((btn) => {
    btn.addEventListener("click", () => {
      const mode = btn.dataset.mode;
      if (!mode || btn.disabled) return;
      overviewMode = mode;
      document.querySelectorAll(".lux-energy-mode").forEach((b) => {
        b.classList.toggle("active", b.dataset.mode === mode);
      });
      syncOverviewNav();
      loadEnergyOverview();
    });
  });
}

function initEnergyOverviewFromBootstrap(boot) {
  if (boot?.months?.length) setOverviewMonths(boot.months);
  else if (boot?.monthRange?.last) {
    setOverviewMonths([boot.monthRange.last.slice(0, 7)]);
  }
  syncOverviewNav();
}

window.initEnergyOverview = async function initEnergyOverview(boot) {
  initEnergyOverviewFromBootstrap(boot || window.__HISTORY_BOOTSTRAP__);
  bindEnergyOverviewUi();
  try {
    const res = await fetch(`/api/history/energy-overview?year=${overviewYear}&mode=total&_=${Date.now()}`, {
      cache: "no-store",
    });
    const data = await res.json();
    if (data.ok && data.years?.length) {
      setOverviewYears(data.years.map((row) => row.year));
    }
  } catch (_) {
    /* keep default years */
  }
  await loadEnergyOverview();
};

window.resizeEnergyOverview = function resizeEnergyOverview() {
  energyOverviewChart?.resize();
};

document.addEventListener("DOMContentLoaded", () => {
  bindEnergyOverviewUi();
});
