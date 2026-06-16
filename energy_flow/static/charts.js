/** Charts — SolarAssistant layout (21 panels), data from dongle + optional LuxPower history. */
const SA = {
  load: "#1f77b4",
  grid: "#d62728",
  pv: "#f2c200",
  battery: "#111111",
  soc: "#2ca02c",
};

/** MPPT line colours on combined chart: orange / green / alternate for 3+. */
const MPPT_LINE_ORANGE = "#ff8c00";
const MPPT_LINE_GREEN = "#2ca02c";

const SA_PANELS = [
  { id: "chartOverview", title: "Overview", full: true, kind: "overview" },
  {
    id: "chartLoadSources",
    title: "Where your load comes from",
    full: true,
    kind: "load_sources",
  },
  { id: "chartBatteryPower", title: "Battery power", full: true, series: "battery", unit: "W", color: SA.battery, label: "Battery power" },
  { id: "chartBatterySoc", title: "Battery state of charge", full: true, series: "soc", unit: "%", color: SA.soc, label: "Battery state of charge", ymin: 0, ymax: 100 },
  { id: "chartMppt1Voltage", title: "MPPT 1 voltage", series: "vpv1", unit: "V", color: SA.pv, label: "PV voltage 1" },
  { id: "chartMppt1Current", title: "MPPT 1 current", series: "ipv1", unit: "A", color: SA.pv, label: "PV current 1" },
  { id: "chartMppt2Voltage", title: "MPPT 2 voltage", series: "vpv2", unit: "V", color: SA.pv, label: "PV voltage 2" },
  { id: "chartMppt2Current", title: "MPPT 2 current", series: "ipv2", unit: "A", color: SA.pv, label: "PV current 2" },
  { id: "chartMppt1Power", title: "MPPT 1 power", series: "ppv1", unit: "W", color: SA.pv, label: "PV power 1", kind: "mppt_power" },
  { id: "chartMppt2Power", title: "MPPT 2 power", series: "ppv2", unit: "W", color: SA.pv, label: "PV power 2", kind: "mppt_power" },
  {
    id: "chartMpptPowerAll",
    title: "MPPT power & state of charge",
    full: true,
    kind: "mppt_power_combined",
    unit: "W",
  },
  { id: "chartAuxPvPower", title: "Auxiliary PV power", series: "ppvAux", unit: "W", color: SA.pv, label: "Auxiliary PV power" },
  { id: "chartPvPower", title: "PV power", series: "pvTotal", unit: "W", color: SA.pv, label: "PV power" },
  { id: "chartBatteryVoltage", title: "Battery voltage", series: "vbat", unit: "V", color: SA.soc, label: "Battery voltage" },
  { id: "chartBatteryCurrent", title: "Battery current", series: "ibat", unit: "A", color: SA.battery, label: "Battery current" },
  { id: "chartInverterTemp", title: "Inverter temperature", series: "invTemp", unit: "°C", color: SA.battery, label: "Inverter temperature" },
  { id: "chartBatteryTemp", title: "Battery temperature", series: "batTemp", unit: "°C", color: SA.battery, label: "Battery temperature" },
  { id: "chartGridVoltage", title: "Grid voltage", series: "vac", unit: "V", color: SA.grid, label: "Grid voltage" },
  { id: "chartGridFrequency", title: "Grid frequency", series: "freq", unit: "Hz", color: SA.grid, label: "Grid frequency" },
  { id: "chartAcOutputVoltage", title: "AC output voltage", series: "vacOut", unit: "V", color: SA.load, label: "AC output voltage" },
  { id: "chartLoadPower", title: "Load power", series: "load", unit: "W", color: SA.load, label: "Load power" },
];

const chartInstances = {};
let monthlyData = [];
let dailyByDate = new Map();
let selectedDate = null;
let chartSource = "dongle";
let dayFetchController = null;
let chartsLoaded = false;
let dongleRefreshTimer = null;
let chartDomBuilt = false;

function byId(id) {
  return document.getElementById(id);
}

function ensureChartJs() {
  if (typeof Chart === "undefined") {
    throw new Error("Chart.js did not load — hard refresh with Ctrl+F5.");
  }
}

function waitForLayout() {
  return new Promise((resolve) => {
    requestAnimationFrame(() => requestAnimationFrame(resolve));
  });
}

function showHistoryError(msg) {
  const node = byId("historyError");
  if (!node) return;
  node.textContent = msg || "";
  node.hidden = !msg;
}

function fmtTime(iso) {
  const d = new Date(iso.replace(" ", "T"));
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function pointsOf(block) {
  return block?.points || [];
}

function mergeTimes(blocks) {
  const times = new Set();
  for (const block of blocks) {
    if (!block) continue;
    for (const point of pointsOf(block)) times.add(point.time);
  }
  return [...times].sort();
}

function mergeLabels(blocks) {
  return mergeTimes(blocks).map(fmtTime);
}

function valuesOf(block) {
  return pointsOf(block).map((p) => p.value);
}

const SMOOTH_KIND = {
  soc: "soc",
  vbat: "voltage_bat",
  vpv1: "voltage_pv",
  vpv2: "voltage_pv",
  vac: "voltage_ac",
  vacOut: "voltage_ac",
  ppv1: "power",
  ppv2: "power",
  ppvAux: "power",
  pvTotal: "power",
  load: "power",
  charge: "power",
  discharge: "power",
  battery: "power_signed",
  gridNet: "power_signed",
  pToGrid: "power",
  pToUser: "power",
  ipv1: "current",
  ipv2: "current",
  ibat: "current",
  invTemp: "temperature",
  batTemp: "temperature",
  freq: "frequency",
};

function vShapeSpike(last, raw, nxt, minMag) {
  if (nxt == null || Math.abs(last) < minMag) return false;
  if (last > 0 && raw < last * 0.15 && nxt >= last * 0.55) return true;
  if (last > 0 && raw > last * 3.5 && nxt <= last * 1.4) return true;
  return false;
}

function smoothPoint(kind, raw, last, nxt) {
  let v = Number(raw);
  if (!Number.isFinite(v)) v = 0;
  if (last == null) return v;

  if (kind === "soc") {
    v = Math.max(0, Math.min(100, v));
    if (v <= 3 && last >= 12) return last;
    if (last - v > 20 && v <= last * 0.4) return last;
    return v;
  }
  if (kind === "voltage_bat") {
    if (last >= 40 && v < 10) return last;
    if (last >= 35 && v < last * 0.25) return last;
  } else if (kind === "voltage_pv") {
    if (last >= 80 && v < 8) return last;
    if (last >= 40 && v < 5) return last;
  } else if (kind === "voltage_ac") {
    if (last >= 150 && v < 80) return last;
    if (last >= 180 && Math.abs(v - last) > 80) return last;
  } else if (kind === "power") {
    v = Math.max(0, v);
    if (vShapeSpike(last, v, nxt, 80)) return last;
  } else if (kind === "power_signed") {
    if (vShapeSpike(Math.abs(last), Math.abs(v), nxt != null ? Math.abs(nxt) : null, 100)) {
      if (last > 100 && v < last * 0.1) return last;
      if (last < -100 && v > last * 0.1) return last;
    }
  } else if (kind === "temperature") {
    if (last > 5 && last < 95 && (v <= 0 || v < -25 || v > 110 || Math.abs(v - last) > 22)) return last;
  } else if (kind === "frequency") {
    if (last >= 47 && last <= 53 && (v < 40 || v > 56)) return last;
  } else if (kind === "current") {
    if (vShapeSpike(Math.abs(last), Math.abs(v), nxt != null ? Math.abs(nxt) : null, 2)) {
      if (Math.abs(last) > 1 && Math.abs(v) < Math.abs(last) * 0.1) return last;
    }
  } else if (vShapeSpike(last, v, nxt, 15)) {
    return last;
  }
  return v;
}

function smoothSeriesBlock(block, kind) {
  const pts = pointsOf(block);
  if (!pts.length || !kind) return block;
  const out = [];
  for (let i = 0; i < pts.length; i++) {
    const last = out.length ? out[out.length - 1].value : null;
    const nxt = i + 1 < pts.length ? Number(pts[i + 1].value) : null;
    const v = smoothPoint(kind, pts[i].value, last, nxt);
    out.push({ time: pts[i].time, value: v });
  }
  return { ...(block || {}), points: out };
}

function smoothDongleSeries(series) {
  const out = { ...series };
  for (const [key, block] of Object.entries(out)) {
    const kind = SMOOTH_KIND[key];
    if (kind && block?.points?.length) out[key] = smoothSeriesBlock(block, kind);
  }
  return out;
}

function valueAt(block, time) {
  if (!block) return 0;
  const hit = pointsOf(block).find((p) => p.time === time);
  return hit ? hit.value : 0;
}

/** MPPT power series keys present in data (ppv1 … ppv8). */
const MPPT_POWER_KEY_RE = /^ppv(\d+)$/;

function fmtPowerW(w) {
  const n = Math.round(Number(w) || 0);
  return `${n.toLocaleString()} W`;
}

/**
 * Detect installed MPPT power inputs from today's series.
 * A channel counts if it has samples and ever exceeded ~10 W (or has steady daytime data).
 */
function detectMpptPowerChannels(series) {
  const found = [];
  for (let n = 1; n <= 8; n++) {
    const key = `ppv${n}`;
    const block = series[key];
    if (!block?.points?.length) continue;
    const vals = block.points.map((p) => Number(p.value) || 0);
    const max = Math.max(0, ...vals);
    const activeSamples = vals.filter((v) => v > 10).length;
    if (max > 10 || activeSamples >= 2) {
      found.push({
        key,
        index: n,
        label: `PV power ${n}`,
        title: `MPPT ${n} power`,
      });
    }
  }
  if (found.length) return found;
  return SA_PANELS.filter((p) => p.kind === "mppt_power").map((p) => {
    const m = p.series?.match(MPPT_POWER_KEY_RE);
    const n = m ? Number(m[1]) : 0;
    return { key: p.series, index: n, label: p.label || `PV power ${n}`, title: p.title };
  });
}

function mpptPowerTooltipCallbacks(series, channels, selfKey, times) {
  return {
    label(ctx) {
      const v = ctx.parsed?.y ?? ctx.raw ?? 0;
      return `${ctx.dataset.label}: ${fmtPowerW(v)}`;
    },
    afterBody(tooltipItems) {
      if (!tooltipItems.length || !channels.length) return [];
      const idx = tooltipItems[0].dataIndex;
      const time = times[idx];
      if (!time) return [];
      const lines = [];
      for (const ch of channels) {
        if (ch.key === selfKey) continue;
        const v = valueAt(series[ch.key], time);
        lines.push(`${ch.label}: ${fmtPowerW(v)}`);
      }
      return lines;
    },
  };
}

function emptySeries() {
  return { unit: "", points: [] };
}

function deriveCurrentFromPower(powerBlock, voltageBlock) {
  const power = powerBlock || emptySeries();
  const voltage = voltageBlock || emptySeries();
  const times = mergeTimes([power, voltage]);
  return {
    unit: "A",
    points: times.map((time) => {
      const v = valueAt(voltage, time);
      const p = valueAt(power, time);
      return { time, value: v > 0 ? p / v : 0 };
    }),
  };
}

function normalizeLuxpowerSeries(raw) {
  const s = raw || {};
  const ppv1 = s.ppv1 || emptySeries();
  const ppv2 = s.ppv2 || emptySeries();
  const vpv1 = s.vpv1 || emptySeries();
  const vpv2 = s.vpv2 || emptySeries();
  const vbat = s.vBat || s.vbat || emptySeries();
  const times = mergeTimes([ppv1, ppv2]);
  const pvTotalPts = times.map((time) => ({
    time,
    value: valueAt(ppv1, time) + valueAt(ppv2, time),
  }));
  const batteryPts = mergeTimes([s.pCharge, s.pDischarge]).map((time) => ({
    time,
    value: valueAt(s.pDischarge, time) - valueAt(s.pCharge, time),
  }));

  const loadEstPts = (s.loadEstimated?.points?.length
    ? s.loadEstimated
    : {
        unit: "W",
        points: times.map((time) => ({ time, value: estimateHouseLoadAt(
          { _luxpowerHistory: true, ppv1, ppv2, pCharge: s.pCharge, pDischarge: s.pDischarge, pToUser: s.pToUser, pToGrid: s.pToGrid },
          time
        ) })),
      });

  return {
    _luxpowerHistory: true,
    ppv1,
    ppv2,
    ppvAux: emptySeries(),
    pvTotal: { unit: "W", points: pvTotalPts },
    soc: s.soc || emptySeries(),
    load: loadEstPts,
    loadEstimated: loadEstPts,
    pToUser: s.pToUser || emptySeries(),
    gridImport: s.pToUser || emptySeries(),
    pToGrid: s.pToGrid || emptySeries(),
    pCharge: s.pCharge || emptySeries(),
    pDischarge: s.pDischarge || emptySeries(),
    loadFromSolar: s.loadFromSolar || emptySeries(),
    loadFromBattery: s.loadFromBattery || emptySeries(),
    loadFromGrid: s.loadFromGrid || emptySeries(),
    battery: { unit: "W", points: batteryPts },
    gridNet: {
      unit: "W",
      points: (s.pToGrid?.points || []).map((p) => ({
        time: p.time,
        value: p.value > 0 ? -p.value : 0,
      })),
    },
    vpv1,
    vpv2,
    ipv1: deriveCurrentFromPower(ppv1, vpv1),
    ipv2: deriveCurrentFromPower(ppv2, vpv2),
    vbat,
    ibat: deriveCurrentFromPower(
      { unit: "W", points: batteryPts },
      vbat
    ),
    invTemp: emptySeries(),
    batTemp: emptySeries(),
    vac: emptySeries(),
    vacOut: emptySeries(),
    freq: emptySeries(),
  };
}

function buildChartDom() {
  if (chartDomBuilt) return;
  const stack = byId("saChartStack");
  if (!stack) return;
  stack.innerHTML = "";

  let row = null;
  for (const panel of SA_PANELS) {
    if (panel.full) {
      row = null;
      const article = document.createElement("article");
      article.className = "sa-chart sa-chart-full";
      article.innerHTML = `<h3>${panel.title}</h3><canvas id="${panel.id}"></canvas>`;
      stack.appendChild(article);
      continue;
    }
    if (!row) {
      row = document.createElement("div");
      row.className = "sa-chart-row";
      stack.appendChild(row);
    }
    const article = document.createElement("article");
    article.className = "sa-chart sa-chart-half";
    article.innerHTML = `<h3>${panel.title}</h3><canvas id="${panel.id}"></canvas>`;
    row.appendChild(article);
    if (row.children.length >= 2) row = null;
  }
  chartDomBuilt = true;
}

function baseOptions(yLabel, yMin, yMax) {
  return {
    responsive: true,
    maintainAspectRatio: false,
    interaction: { mode: "index", intersect: false },
    plugins: {
      legend: {
        position: "top",
        labels: { boxWidth: 12, usePointStyle: true, font: { size: 11 } },
      },
      tooltip: { mode: "index", intersect: false },
    },
    scales: {
      x: {
        grid: { color: "#eef0f2" },
        ticks: { maxTicksLimit: 10, color: "#888", font: { size: 10 } },
      },
      y: {
        grid: { color: "#eef0f2" },
        ticks: { color: "#888", font: { size: 10 } },
        title: yLabel
          ? { display: true, text: yLabel, color: "#aaa", font: { size: 10 } }
          : undefined,
        min: yMin,
        max: yMax,
      },
    },
  };
}

function lineDataset(label, data, color, fill = false, yAxisID = "y") {
  return {
    label,
    data,
    borderColor: color,
    backgroundColor: fill ? `${color}22` : "transparent",
    fill,
    tension: 0.15,
    pointRadius: 0,
    borderWidth: 1.5,
    yAxisID,
  };
}

function destroyChart(id) {
  if (chartInstances[id]) {
    chartInstances[id].destroy();
    delete chartInstances[id];
  }
}

function destroyAllCharts() {
  for (const panel of SA_PANELS) destroyChart(panel.id);
}

function resizeAllCharts() {
  Object.values(chartInstances).forEach((chart) => chart?.resize());
}

function chartsNeedRebuild() {
  const canvas = byId("chartOverview");
  return !canvas || canvas.clientWidth < 10 || !chartInstances.chartOverview;
}

function setDayLoading(loading) {
  byId("chartsFootnote")?.classList.toggle("loading", loading);
  if (byId("historyDaySelect")) byId("historyDaySelect").disabled = loading;
  if (byId("chartsSourceSelect")) byId("chartsSourceSelect").disabled = loading;
}

function splitLoadSource(load, pv, discharge, gridImport) {
  const L = Math.max(0, Number(load) || 0);
  const PV = Math.max(0, Number(pv) || 0);
  const D = Math.max(0, Number(discharge) || 0);
  const G = Math.max(0, Number(gridImport) || 0);
  if (L <= 0) return { solar: 0, battery: 0, grid: 0 };

  let solar = Math.min(L, PV);
  let rem = L - solar;
  let battery = Math.min(rem, D);
  rem -= battery;
  let grid = Math.min(rem, G);
  rem -= grid;

  if (rem > 1) {
    if (G > grid) grid += rem;
    else if (D > battery) battery += rem;
    else if (PV > solar) solar += rem;
    else grid += rem;
  }

  const total = solar + battery + grid;
  if (total > L + 1 && total > 0) {
    const scale = L / total;
    solar *= scale;
    battery *= scale;
    grid *= scale;
  }
  return { solar, battery, grid };
}

function gridImportAt(series, time) {
  if (series.gridImport?.points?.length) {
    return valueAt(series.gridImport, time);
  }
  // LuxPower cloud: pToUser is grid → user (import), not house load
  if (series._luxpowerHistory && series.pToUser?.points?.length) {
    return valueAt(series.pToUser, time);
  }
  const net = valueAt(series.gridNet, time);
  return net < 0 ? -net : 0;
}

/** LuxPower dayLine has no load register — estimate from power balance. */
function estimateHouseLoadAt(series, time) {
  const pvVal =
    valueAt(series.ppv1, time) +
    valueAt(series.ppv2, time) ||
    valueAt(series.pvTotal, time);
  const charge = valueAt(series.pCharge, time);
  const discharge = valueAt(series.pDischarge, time);
  const gridImport = gridImportAt(series, time);
  const gridExport = valueAt(series.pToGrid, time);
  return Math.max(0, pvVal + discharge + gridImport - charge - gridExport);
}

function houseLoadAt(series, time) {
  if (series.loadEstimated?.points?.length) {
    return valueAt(series.loadEstimated, time);
  }
  if (series._luxpowerHistory) {
    return estimateHouseLoadAt(series, time);
  }
  return valueAt(series.load || series.pToUser, time);
}

function deriveLoadSourceSeries(series) {
  if (series.loadFromSolar?.points?.length) {
    return {
      solar: series.loadFromSolar,
      battery: series.loadFromBattery || emptySeries(),
      grid: series.loadFromGrid || emptySeries(),
    };
  }

  const pv = series.pvTotal || emptySeries();
  const discharge = series.pDischarge || emptySeries();
  const times = mergeTimes([
    series.load,
    series.loadEstimated,
    series.pToUser,
    pv,
    discharge,
    series.ppv1,
    series.ppv2,
    series.pCharge,
    series.pToGrid,
    series.gridNet,
    series.gridImport,
  ]);

  const solarPts = [];
  const batPts = [];
  const gridPts = [];
  for (const time of times) {
    const L = houseLoadAt(series, time);
    const parts = splitLoadSource(
      L,
      valueAt(pv, time) ||
        valueAt(series.ppv1, time) + valueAt(series.ppv2, time),
      valueAt(discharge, time),
      gridImportAt(series, time)
    );
    solarPts.push({ time, value: parts.solar });
    batPts.push({ time, value: parts.battery });
    gridPts.push({ time, value: parts.grid });
  }

  return {
    solar: { unit: "W", points: solarPts },
    battery: { unit: "W", points: batPts },
    grid: { unit: "W", points: gridPts },
  };
}

function renderLoadSourcesPanel(series) {
  const src = deriveLoadSourceSeries(series);
  const times = mergeTimes([src.solar, src.battery, src.grid]);
  const labels = times.map(fmtTime);

  const datasets = [
    lineDataset(
      "Solar",
      times.map((t) => valueAt(src.solar, t)),
      SA.pv,
      true,
      "y"
    ),
    lineDataset(
      "Battery",
      times.map((t) => valueAt(src.battery, t)),
      SA.soc,
      true,
      "y"
    ),
    lineDataset(
      "Grid",
      times.map((t) => valueAt(src.grid, t)),
      SA.grid,
      true,
      "y"
    ),
  ];
  for (const ds of datasets) {
    ds.stack = "load";
  }

  const base = baseOptions("W");
  destroyChart("chartLoadSources");
  chartInstances.chartLoadSources = new Chart(byId("chartLoadSources"), {
    type: "line",
    data: { labels, datasets },
    options: {
      ...base,
      plugins: {
        legend: {
          display: true,
          position: "top",
          labels: { boxWidth: 12, usePointStyle: true, font: { size: 11 } },
        },
        tooltip: {
          mode: "index",
          intersect: false,
          callbacks: {
            label(ctx) {
              const v = ctx.parsed?.y ?? ctx.raw ?? 0;
              return `${ctx.dataset.label}: ${fmtPowerW(v)}`;
            },
            footer(tooltipItems) {
              if (!tooltipItems.length) return [];
              const total = tooltipItems.reduce(
                (sum, item) => sum + (item.parsed?.y ?? 0),
                0
              );
              return [`Total load: ${fmtPowerW(total)}`];
            },
          },
        },
      },
      scales: {
        ...base.scales,
        x: { ...base.scales.x, stacked: true },
        y: {
          ...base.scales.y,
          stacked: true,
          min: 0,
          title: { display: true, text: "W", color: "#aaa", font: { size: 10 } },
        },
      },
    },
  });
}

function renderOverview(series) {
  const blocks = [series.load || series.pToUser, series.gridNet, series.ppv1, series.ppv2];
  const times = mergeTimes(blocks);
  const labels = times.map(fmtTime);
  destroyChart("chartOverview");
  chartInstances.chartOverview = new Chart(byId("chartOverview"), {
    type: "line",
    data: {
      labels,
      datasets: [
        lineDataset(
          "Load power",
          times.map((t) => valueAt(series.load || series.pToUser, t)),
          SA.load,
          true
        ),
        lineDataset(
          "Grid power",
          times.map((t) => valueAt(series.gridNet, t) || (valueAt(series.pToGrid, t) > 0 ? -valueAt(series.pToGrid, t) : 0)),
          SA.grid,
          true
        ),
        lineDataset(
          "PV power",
          times.map((t) => {
            const fromMppt = valueAt(series.ppv1, t) + valueAt(series.ppv2, t);
            return fromMppt || valueAt(series.pvTotal, t);
          }),
          SA.pv,
          true
        ),
      ],
    },
    options: baseOptions("W"),
  });
}

function mpptLineColor(index) {
  return index % 2 === 1 ? MPPT_LINE_ORANGE : MPPT_LINE_GREEN;
}

function renderMpptPowerCombinedPanel(series, mpptChannels) {
  const socBlock = series.soc || emptySeries();
  const blocks = [
    ...mpptChannels.map((ch) => series[ch.key] || emptySeries()),
    socBlock,
  ];
  const times = mergeTimes(blocks);
  const labels = times.map(fmtTime);

  const datasets = mpptChannels.map((ch) =>
    lineDataset(
      ch.label,
      times.map((t) => valueAt(series[ch.key], t)),
      mpptLineColor(ch.index),
      true,
      "y"
    )
  );

  if (pointsOf(socBlock).length) {
    datasets.push(
      lineDataset(
        "Battery state of charge",
        times.map((t) => valueAt(socBlock, t)),
        "#2563eb",
        false,
        "ySoc"
      )
    );
  }

  const base = baseOptions("W");
  destroyChart("chartMpptPowerAll");
  chartInstances.chartMpptPowerAll = new Chart(byId("chartMpptPowerAll"), {
    type: "line",
    data: { labels, datasets },
    options: {
      ...base,
      plugins: {
        legend: {
          display: datasets.length > 0,
          position: "top",
          labels: { boxWidth: 12, usePointStyle: true, font: { size: 11 } },
        },
        tooltip: {
          mode: "index",
          intersect: false,
          callbacks: {
            label(ctx) {
              const v = ctx.parsed?.y ?? ctx.raw ?? 0;
              if (ctx.dataset.yAxisID === "ySoc") {
                return `${ctx.dataset.label}: ${Math.round(v)}%`;
              }
              return `${ctx.dataset.label}: ${fmtPowerW(v)}`;
            },
          },
        },
      },
      scales: {
        ...base.scales,
        y: {
          ...base.scales.y,
          position: "left",
          title: { display: true, text: "W", color: "#aaa", font: { size: 10 } },
          min: 0,
        },
        ySoc: {
          position: "right",
          min: 0,
          max: 100,
          grid: { drawOnChartArea: false },
          ticks: { color: "#2563eb", font: { size: 10 } },
          title: {
            display: true,
            text: "%",
            color: "#2563eb",
            font: { size: 10 },
          },
        },
      },
    },
  });
}

function renderMpptPowerPanel(panel, series, mpptChannels) {
  const blocks = mpptChannels.map((ch) => series[ch.key] || emptySeries());
  const times = mergeTimes(blocks);
  const labels = times.map(fmtTime);
  const values = times.map((t) => valueAt(series[panel.series], t));
  const tooltipCallbacks = mpptPowerTooltipCallbacks(
    series,
    mpptChannels,
    panel.series,
    times
  );

  destroyChart(panel.id);
  chartInstances[panel.id] = new Chart(byId(panel.id), {
    type: "line",
    data: {
      labels,
      datasets: [lineDataset(panel.label || panel.title, values, panel.color, true)],
    },
    options: {
      ...baseOptions(panel.unit, panel.ymin, panel.ymax),
      plugins: {
        legend: { display: false },
        tooltip: {
          mode: "index",
          intersect: false,
          callbacks: tooltipCallbacks,
        },
      },
    },
  });
}

function renderSinglePanel(panel, series, mpptChannels) {
  if (panel.kind === "overview") return;
  if (panel.kind === "load_sources") {
    renderLoadSourcesPanel(series);
    return;
  }
  if (panel.kind === "mppt_power_combined") {
    renderMpptPowerCombinedPanel(series, mpptChannels);
    return;
  }
  if (panel.kind === "mppt_power") {
    renderMpptPowerPanel(panel, series, mpptChannels);
    return;
  }
  const block = series[panel.series] || emptySeries();
  const labels = mergeLabels([block]);
  const values = valuesOf(block);
  destroyChart(panel.id);
  chartInstances[panel.id] = new Chart(byId(panel.id), {
    type: "line",
    data: {
      labels,
      datasets: [lineDataset(panel.label || panel.title, values, panel.color, true)],
    },
    options: {
      ...baseOptions(panel.unit, panel.ymin, panel.ymax),
      plugins: { legend: { display: false } },
    },
  });
}

function renderSaCharts(payload) {
  destroyAllCharts();
  ensureChartJs();
  const stack = byId("saChartStack");
  if (stack && stack.querySelectorAll("article").length !== SA_PANELS.length) {
    chartDomBuilt = false;
  }
  buildChartDom();

  const series =
    payload.source === "luxpower"
      ? normalizeLuxpowerSeries(payload.series)
      : smoothDongleSeries(payload.series || {});

  const mpptChannels = detectMpptPowerChannels(series);

  renderOverview(series);
  for (const panel of SA_PANELS) {
    if (panel.kind !== "overview") renderSinglePanel(panel, series, mpptChannels);
  }

  const badge = byId("chartsDataBadge");
  if (badge) {
    badge.textContent =
      payload.source === "dongle"
        ? `Dongle Modbus · today · ${payload.pointCount || 0} samples`
        : `LuxPower cloud · ${payload.date}`;
  }

  const foot = byId("chartsFootnote");
  if (foot) {
    const summary = monthlyData.find((d) => d.date === payload.date);
    foot.textContent = [
      payload.source === "dongle"
        ? `Dongle ${payload.pointCount || 0} samples · ${payload.date}`
        : `LuxPower cloud · ${payload.date}${summary ? ` · ${summary.solarKwh} kWh solar` : ""}`,
      "21 panels · estimated load split (solar → battery → grid) · empty chart = no data yet",
    ].join(" · ");
  }

  resizeAllCharts();
}

function historyYear() {
  return window.HISTORY_YEAR || window.__HISTORY_BOOTSTRAP__?.year || 2026;
}

function dayOptionLabel(date, summary) {
  const day = date.slice(8);
  if (!summary) return day;
  const solar = Number(summary.solarKwh ?? summary.solar_kwh);
  if (!Number.isFinite(solar) || solar <= 0) return `${day} (no solar)`;
  return `${day} · ${solar.toFixed(1)} kWh`;
}

function fillDaySelect(dates, selected) {
  const sel = byId("historyDaySelect");
  if (!sel) return;
  sel.innerHTML = "";
  let group = null;
  let currentMonth = "";
  for (const d of dates) {
    const month = d.slice(0, 7);
    if (month !== currentMonth) {
      group = document.createElement("optgroup");
      group.label = month;
      sel.appendChild(group);
      currentMonth = month;
    }
    const opt = document.createElement("option");
    opt.value = d;
    opt.textContent = dayOptionLabel(d, dailyByDate.get(d));
    group.appendChild(opt);
  }
  if (selected && dates.includes(selected)) sel.value = selected;
}

function applyBootstrap(boot) {
  if (!boot?.ok) {
    showHistoryError(boot?.error || "LuxPower history not available.");
    return null;
  }
  monthlyData = boot.daily || [];
  dailyByDate = new Map(
    monthlyData.map((row) => [String(row.date).trim(), row])
  );
  const dates = monthlyData.map((row) => String(row.date).trim());
  const defaultDate =
    boot.defaultDate ||
    boot.summary?.bestSolarDay ||
    dates[dates.length - 1];
  fillDaySelect(dates, defaultDate);
  const station = byId("chartsStation");
  if (station) {
    const range = boot.monthRange
      ? `${boot.monthRange.first} → ${boot.monthRange.last}`
      : boot.months?.length
        ? `${boot.months.length} months`
        : "";
    station.textContent = `${boot.station || "Andre Huis"} · ${boot.year || 2026} LuxPower cloud${range ? ` · ${range}` : ""}`;
  }
  showHistoryError("");
  return defaultDate;
}

async function fetchHistoryBootstrap() {
  const year = historyYear();
  const res = await fetch(`/api/history/bootstrap?year=${year}&_=${Date.now()}`, {
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`History bootstrap HTTP ${res.status}`);
  const boot = await res.json();
  if (!boot.ok) throw new Error(boot.error || "History bootstrap failed");
  return boot;
}

async function loadChartMeta() {
  try {
    const boot = await fetchHistoryBootstrap();
    window.__HISTORY_BOOTSTRAP__ = boot;
    return applyBootstrap(boot);
  } catch (err) {
    const boot = window.__HISTORY_BOOTSTRAP__;
    if (boot?.ok && boot.daily?.length) return applyBootstrap(boot);
    throw err;
  }
}

async function loadLuxpowerDay(date) {
  const res = await fetch(
    `/api/history/day?date=${encodeURIComponent(date)}&_=${Date.now()}`,
    { cache: "no-store" }
  );
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const data = await res.json();
  if (!data.ok) throw new Error(data.error || "Day load failed");
  return { ...data, source: "luxpower" };
}

async function loadDongleToday() {
  const res = await fetch(`/api/live/today?_=${Date.now()}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const data = await res.json();
  if (!data.ok) throw new Error(data.error || "Dongle buffer unavailable");
  if (!data.pointCount) {
    throw new Error("No dongle samples yet — stay on Dashboard ~30s, then open Charts again.");
  }
  return data;
}

function updateSourceUi() {
  byId("dayPickerWrap")?.classList.toggle("hidden", chartSource !== "luxpower");
}

async function refreshCharts() {
  setDayLoading(true);
  try {
    let payload;
    if (chartSource === "dongle") {
      payload = await loadDongleToday();
    } else {
      const date = selectedDate || byId("historyDaySelect")?.value;
      if (!date) throw new Error("Pick a day");
      payload = await loadLuxpowerDay(date);
      selectedDate = date;
    }
    ensureChartJs();
    buildChartDom();
    await waitForLayout();
    renderSaCharts(payload);
    showHistoryError("");
  } catch (err) {
    showHistoryError(String(err.message || err));
    buildChartDom();
    renderSaCharts({ source: chartSource, date: selectedDate || "today", series: {}, pointCount: 0 });
    console.error(err);
  } finally {
    setDayLoading(false);
  }
}

function stopDongleRefresh() {
  if (dongleRefreshTimer) {
    clearInterval(dongleRefreshTimer);
    dongleRefreshTimer = null;
  }
}

function startDongleRefresh() {
  stopDongleRefresh();
  dongleRefreshTimer = setInterval(() => {
    if (chartSource === "dongle" && !byId("panelCharts")?.classList.contains("hidden")) {
      refreshCharts().catch(console.error);
    }
  }, 6000);
}

async function selectDay(date) {
  if (!date || chartSource !== "luxpower") return;
  selectedDate = date;
  const sel = byId("historyDaySelect");
  if (sel && sel.value !== date) sel.value = date;
  await refreshCharts();
}

async function initHistory() {
  showHistoryError("");
  updateSourceUi();
  buildChartDom();
  await waitForLayout();

  if (chartsLoaded && !chartsNeedRebuild()) {
    await loadChartMeta();
    window.initEnergyOverview?.(window.__HISTORY_BOOTSTRAP__).catch(console.error);
    resizeAllCharts();
    window.resizeEnergyOverview?.();
    await refreshCharts();
    return;
  }

  destroyAllCharts();
  chartsLoaded = false;

  try {
    const boot = await loadChartMeta();
    chartsLoaded = true;
    window.initEnergyOverview?.(window.__HISTORY_BOOTSTRAP__).catch(console.error);
    await refreshCharts();
    startDongleRefresh();
  } catch (err) {
    showHistoryError(String(err.message || err));
    buildChartDom();
    renderSaCharts({ source: "dongle", date: "today", series: {}, pointCount: 0 });
    console.error(err);
  }
}

function bootstrapStaticFields() {
  applyBootstrap(window.__HISTORY_BOOTSTRAP__);
}

async function reloadHistoryAfterSync() {
  showHistoryError("");
  const boot = await loadChartMeta();
  window.__HISTORY_BOOTSTRAP__ = boot;
  applyBootstrap(boot);
  await window.initEnergyOverview?.(boot);
  if (!byId("panelCharts")?.classList.contains("hidden")) {
    await refreshCharts();
  }
}

window.initHistory = initHistory;
window.selectHistoryDay = selectDay;
window.refreshCharts = refreshCharts;
window.stopDongleRefresh = stopDongleRefresh;
window.reloadHistoryAfterSync = reloadHistoryAfterSync;

document.addEventListener("DOMContentLoaded", () => {
  chartSource = byId("chartsSourceSelect")?.value || "dongle";
  updateSourceUi();
  byId("historyDaySelect")?.addEventListener("change", (e) => {
    chartSource = "luxpower";
    byId("chartsSourceSelect").value = "luxpower";
    updateSourceUi();
    selectDay(e.target.value);
  });
  byId("chartsSourceSelect")?.addEventListener("change", (e) => {
    chartSource = e.target.value;
    updateSourceUi();
    refreshCharts().catch(console.error);
  });
});
