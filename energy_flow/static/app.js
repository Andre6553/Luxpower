const REFRESH_MS = 6000;

const el = (id) => document.getElementById(id);

function setFlowPipe(id, active, reverse = false) {
  const node = el(id);
  if (!node) return;
  node.classList.toggle("active", active);
  node.classList.toggle("reverse", reverse);
}

function applyFlow(data) {
  const f = data.flow;
  const gridImport = f.gridToInverter;
  const gridExport = f.inverterToGrid;
  const batDischarge = f.batteryToInverter;
  const batCharge = f.inverterToBattery;
  const pvActive = f.pvToInverter;
  const loadActive = f.inverterToLoad;

  setFlowPipe("pipePv", pvActive, false);
  setFlowPipe("pipeBat", batDischarge || batCharge, batCharge);
  const gridActive = gridImport || gridExport;
  setFlowPipe("pipeGrid", gridActive, gridImport);
  // Off-grid / no grid import: inverter hub straight down, then to house.
  setFlowPipe("pipeInvToLoad", loadActive && !gridImport, false);
  // Grid import: power on horizontal bus (hub → house), not via grid-tower vertical.
  setFlowPipe("pipeBusToLoad", loadActive && gridImport, false);

  el("inverterGlow").classList.toggle(
    "active",
    pvActive || batDischarge || batCharge || gridImport || gridExport || loadActive
  );
}

function setAllowed(id, text) {
  const node = el(id);
  if (!node) return;
  node.textContent = text;
  node.classList.toggle("allowed", text === "Allowed");
}

function setBatterySegments(soc) {
  const segs = el("batterySegments")?.querySelectorAll("span");
  if (!segs) return;
  const filled = Math.round((soc / 100) * segs.length);
  segs.forEach((seg, i) => seg.classList.toggle("on", i < filled));
}

function formatGridPower(grid) {
  if (grid.exportW > 0) return `${grid.exportW} W`;
  if (grid.importW > 0) return `${grid.importW} W`;
  return "0 W";
}

function applyData(data) {
  el("timestamp").textContent = data.timestamp || "--";

  el("pv1Power").textContent = `${data.pv.pv1.powerW} W`;
  el("pv1Volt").textContent = `${data.pv.pv1.voltageV} V`;
  el("pv2Power").textContent = `${data.pv.pv2.powerW} W`;
  el("pv2Volt").textContent = `${data.pv.pv2.voltageV} V`;

  const bat = data.battery;
  el("batPower").textContent = `${Math.abs(bat.powerW)} W`;
  el("batSoc").textContent = `${bat.socPercent}%`;
  el("batVolt").textContent = `${bat.voltageV} Vdc`;
  setBatterySegments(bat.socPercent);
  el("bmsChg").textContent = bat.bmsLimitChargeA;
  el("bmsDis").textContent = bat.bmsLimitDischargeA;
  setAllowed("bmsChargeOk", bat.bmsCharge);
  setAllowed("bmsDisOk", bat.bmsDischarge);
  el("bmsForce").textContent = bat.bmsForceCharge;

  el("gridPower").textContent = formatGridPower(data.grid);
  el("gridVolt").textContent = `${data.grid.voltageV} Vac`;
  el("gridFreq").textContent = `${data.grid.frequencyHz} Hz`;
  el("genContact").textContent = data.grid.genDryContact;

  el("loadPower").textContent = `${data.consumption.powerW} W`;
  el("epsStatus").textContent = data.eps.status;

  applyFlow(data);

  el("statusBadge").innerHTML = '<i class="dot"></i> Notice';
  el("statusBadge").className = "lux-notice";
  el("errorNote").textContent = "";
}

async function refresh() {
  try {
    const res = await fetch("/api/live", { cache: "no-store" });
    const data = await res.json();
    if (!data.ok) throw new Error(data.error || "API error");
    applyData(data);
  } catch (err) {
    el("statusBadge").innerHTML = '<i class="dot"></i> Notice';
    el("statusBadge").className = "lux-notice error";
    el("errorNote").textContent = String(err.message || err);
  }
}

el("refreshBtn").addEventListener("click", () => {
  refresh();
  window.refreshForecast?.().catch(console.error);
});

const SYNC_POLL_MS = 900;
const syncMonthBtn = el("syncMonthBtn");
const syncAllBtn = el("syncAllBtn");
const syncButtons = [syncMonthBtn, syncAllBtn].filter(Boolean);
const syncPanel = el("syncProgressPanel");
const syncTitle = el("syncProgressTitle");
const syncPercent = el("syncProgressPercent");
const syncBar = el("syncProgressBar");
const syncTrack = el("syncProgressTrack");
const syncMessage = el("syncProgressMessage");

function formatSyncLabel(year, month) {
  if (!year || !month) return "";
  return `${year}-${String(month).padStart(2, "0")}`;
}

function formatFetchedAt(iso) {
  if (!iso) return "";
  const dt = new Date(iso);
  if (Number.isNaN(dt.getTime())) return iso;
  return dt.toLocaleString();
}

function setSyncButtonsDisabled(disabled) {
  syncButtons.forEach((btn) => {
    btn.disabled = disabled;
  });
}

function setSyncPanelVisible(visible) {
  syncPanel?.classList.toggle("hidden", !visible);
}

function syncTitleForStatus(status, { success = false, error = false } = {}) {
  const label = formatSyncLabel(status.year, status.month);
  if (success) {
    return status.syncMode === "all"
      ? "All cloud history updated"
      : `This month updated (${label})`;
  }
  if (error) {
    return status.cloudOffline ? "LuxPower cloud offline" : "Cloud sync failed";
  }
  return status.syncMode === "all"
    ? "Syncing all LuxPower history"
    : `Syncing this month (${label})`;
}

function applySyncProgress(status, { success = false, error = false } = {}) {
  if (!syncPanel) return;
  syncPanel.classList.toggle("is-success", success);
  syncPanel.classList.toggle("is-error", error);
  setSyncPanelVisible(true);

  const pct = Math.max(0, Math.min(100, Number(status.progressPercent) || 0));
  syncPercent.textContent = `${pct}%`;
  syncBar.style.width = `${pct}%`;
  if (syncTrack) syncTrack.setAttribute("aria-valuenow", String(pct));

  syncTitle.textContent = syncTitleForStatus(status, { success, error });
  syncMessage.textContent =
    status.progressMessage ||
    status.error ||
    (status.running ? "Downloading from LuxPower…" : "Waiting for sync status…");
}

async function pollSyncStatus() {
  const res = await fetch("/api/history/sync", { cache: "no-store" });
  const status = await res.json();
  if (!status.ok) throw new Error(status.error || "Sync status failed");
  return status;
}

async function reloadDashboardHistory() {
  applySyncProgress(
    { syncMode: "month", progressPercent: 99, progressMessage: "Refreshing dashboard charts…" },
    {}
  );
  await window.reloadHistoryAfterSync?.().catch(console.error);
  if (!el("panelTotals")?.classList.contains("hidden")) {
    await window.initTotals?.().catch(console.error);
  }
}

async function waitForSyncCompletion(activeBtn) {
  while (true) {
    const status = await pollSyncStatus();
    applySyncProgress(status);
    if (status.running) {
      if (activeBtn) {
        activeBtn.textContent =
          status.syncMode === "all"
            ? `Syncing all (${status.backfillIndex || "?"}/${status.backfillTotal || "?"})…`
            : `Syncing ${formatSyncLabel(status.year, status.month)}…`;
      }
      await new Promise((resolve) => setTimeout(resolve, SYNC_POLL_MS));
      continue;
    }
    if (status.ok === false) {
      const err = new Error(status.error || "Cloud sync failed");
      err.cloudOffline = status.cloudOffline;
      throw err;
    }
    return status;
  }
}

function restoreSyncButtonLabels() {
  if (syncMonthBtn) syncMonthBtn.textContent = "Sync this month";
  if (syncAllBtn) syncAllBtn.textContent = "Sync all data";
}

async function runCloudSync(mode, activeBtn) {
  if (syncButtons.some((btn) => btn.disabled)) return;

  const prevLabel = activeBtn.textContent;
  setSyncButtonsDisabled(true);
  activeBtn.textContent = "Starting…";
  el("errorNote").textContent = "";
  applySyncProgress(
    {
      syncMode: mode,
      year: new Date().getFullYear(),
      month: new Date().getMonth() + 1,
      progressPercent: 0,
      progressMessage: mode === "all" ? "Preparing full history sync…" : "Starting this month sync…",
    },
    {}
  );

  try {
    const startRes = await fetch(`/api/history/sync?mode=${encodeURIComponent(mode)}`, {
      method: "POST",
      cache: "no-store",
    });
    const start = await startRes.json();
    if (start.ok === false) throw new Error(start.error || "Could not start sync");
    if (start.status === "running") {
      syncMessage.textContent = "Sync already running — showing progress…";
    }

    const status = await waitForSyncCompletion(activeBtn);
    activeBtn.textContent = "Updating charts…";
    await reloadDashboardHistory();

    applySyncProgress(status, { success: true });

    let doneText = status.progressMessage || "Cloud sync complete.";
    if (status.syncMode === "all") {
      doneText = `Downloaded ${status.savedMonths ?? 0} month(s), skipped ${status.skippedMonths ?? 0} already complete.`;
    } else {
      const fetched = formatFetchedAt(status.fetchedAtUtc);
      const label = formatSyncLabel(status.year, status.month);
      doneText = fetched
        ? `This month (${label}) updated. Last LuxPower fetch: ${fetched}.`
        : `This month (${label}) updated.`;
    }
    syncMessage.textContent = doneText;
    el("errorNote").textContent = doneText;
    if (status.lastFetchedAtUtc || status.fetchedAtUtc) {
      el("sourceNote").textContent = `Dongle Modbus · 192.168.10.67 · cloud data ${formatFetchedAt(status.fetchedAtUtc || status.lastFetchedAtUtc)}`;
    }
  } catch (err) {
    applySyncProgress(
      {
        syncMode: mode,
        cloudOffline: err.cloudOffline,
        progressMessage: String(err.message || err),
        year: new Date().getFullYear(),
        month: new Date().getMonth() + 1,
      },
      { error: true }
    );
    el("errorNote").textContent = String(err.message || err);
  } finally {
    setSyncButtonsDisabled(false);
    restoreSyncButtonLabels();
    if (activeBtn && activeBtn !== syncMonthBtn && activeBtn !== syncAllBtn) {
      activeBtn.textContent = prevLabel;
    }
  }
}

async function resumeSyncIfRunning() {
  try {
    const status = await pollSyncStatus();
    if (status.lastFetchedAtUtc && !status.running) {
      el("sourceNote").textContent = `Dongle Modbus · 192.168.10.67 · cloud data ${formatFetchedAt(status.lastFetchedAtUtc)}`;
    }
    if (!status.running) return;

    setSyncButtonsDisabled(true);
    setSyncPanelVisible(true);
    applySyncProgress({
      ...status,
      progressMessage: status.progressMessage || "Resuming cloud sync in progress…",
    });
    const finalStatus = await waitForSyncCompletion(null);
    await reloadDashboardHistory();
    applySyncProgress(finalStatus, { success: true });
    el("errorNote").textContent = finalStatus.progressMessage || "Cloud sync complete.";
  } catch (err) {
    applySyncProgress(
      {
        progressMessage: String(err.message || err),
        cloudOffline: err.cloudOffline,
      },
      { error: true }
    );
    el("errorNote").textContent = String(err.message || err);
  } finally {
    setSyncButtonsDisabled(false);
    restoreSyncButtonLabels();
  }
}

syncMonthBtn?.addEventListener("click", () => {
  runCloudSync("month", syncMonthBtn).catch(console.error);
});

syncAllBtn?.addEventListener("click", () => {
  runCloudSync("all", syncAllBtn).catch(console.error);
});

resumeSyncIfRunning().catch(console.error);

refresh();
setInterval(refresh, REFRESH_MS);

document.querySelectorAll(".sa-nav-item").forEach((tab) => {
  tab.addEventListener("click", () => {
    const name = tab.dataset.tab;
    document.querySelectorAll(".sa-nav-item").forEach((t) => t.classList.toggle("active", t === tab));
    el("panelLive").classList.toggle("hidden", name !== "live");
    el("panelCharts").classList.toggle("hidden", name !== "charts");
    el("panelTotals").classList.toggle("hidden", name !== "totals");
    el("panelSystem")?.classList.toggle("hidden", name !== "system");
    el("panelSettings")?.classList.toggle("hidden", name !== "settings");
    if (name === "charts") {
      window.initHistory?.().catch((err) => {
        console.error(err);
        const errEl = document.getElementById("historyError");
        if (errEl) {
          errEl.textContent = String(err.message || err);
          errEl.hidden = false;
        }
      });
    } else if (name === "totals") {
      window.initTotals?.().catch((err) => {
        console.error(err);
        const errEl = document.getElementById("totalsError");
        if (errEl) {
          errEl.textContent = String(err.message || err);
          errEl.hidden = false;
        }
      });
    } else if (name === "system") {
      window.initSystemProfile?.().catch((err) => {
        console.error(err);
        const errEl = document.getElementById("sysError");
        if (errEl) {
          errEl.textContent = String(err.message || err);
          errEl.hidden = false;
        }
      });
    } else if (name === "settings") {
      window.initSettings?.().catch((err) => {
        console.error(err);
        const errEl = document.getElementById("settingsError");
        if (errEl) {
          errEl.textContent = String(err.message || err);
          errEl.hidden = false;
        }
      });
    } else {
      window.stopDongleRefresh?.();
    }
  });
});
