/** My system tab — inverter and solar panel details (saved locally on server). */

const MAX_MPPT_STRINGS = 4;
let saveHandlerBound = false;
let profileHydrated = false;
/** @type {Record<number, number|string|null|undefined>} */
const loadedTilts = {};

const FACING_OPTIONS = [
  { value: "", label: "Not set" },
  { value: "N", label: "North" },
  { value: "NE", label: "North-east" },
  { value: "E", label: "East" },
  { value: "SE", label: "South-east" },
  { value: "S", label: "South" },
  { value: "SW", label: "South-west" },
  { value: "W", label: "West" },
  { value: "NW", label: "North-west" },
  { value: "flat", label: "Flat / no fixed tilt" },
];

function facingOptionsHtml(selected) {
  const sel = (selected || "").trim();
  return FACING_OPTIONS.map(
    (o) =>
      `<option value="${o.value}"${o.value === sel ? " selected" : ""}>${o.label}</option>`
  ).join("");
}

function facingLabel(code) {
  const row = FACING_OPTIONS.find((o) => o.value === (code || "").trim());
  return row?.label && row.value ? row.label : "";
}

function sysEl(id) {
  return document.getElementById(id);
}

function val(id) {
  const el = sysEl(id);
  return el ? el.value : "";
}

function defaultInverterLabel(n) {
  return `PV${n}`;
}

function buildStringLabels() {
  const host = sysEl("sysStringLabels");
  if (!host) return;
  const needsBuild =
    host.childElementCount < MAX_MPPT_STRINGS || !host.querySelector('[data-field="tilt"]');
  if (!needsBuild) return;

  const today = new Date().toISOString().slice(0, 10);
  host.innerHTML = "";
  for (let n = 1; n <= MAX_MPPT_STRINGS; n++) {
    const item = document.createElement("div");
    item.className = "sys-string-setup-item";
    item.dataset.stringIndex = String(n);
    item.innerHTML = `
      <span class="sys-string-setup-heading">String ${n} (MPPT ${n})</span>
      <label class="sys-string-setup-field">
        <span>Inverter name</span>
        <input type="text" data-field="label" autocomplete="off" maxlength="32" placeholder="${defaultInverterLabel(n)}" />
      </label>
      <label class="sys-string-setup-field">
        <span>Panel direction</span>
        <select data-field="facing">${facingOptionsHtml("")}</select>
      </label>
      <label class="sys-string-setup-field">
        <span>Tilt angle (°)</span>
        <input type="number" data-field="tilt" min="0" max="90" step="0.5" placeholder="e.g. 25" />
      </label>
      <label class="sys-string-setup-field sys-tilt-effective-wrap hidden">
        <span>Change effective from</span>
        <input type="date" data-field="tiltEffective" value="${today}" />
      </label>
    `;
    host.appendChild(item);
  }

  host.querySelectorAll('[data-field="tilt"]').forEach((input) => {
    input.addEventListener("input", onTiltInputChanged);
    input.addEventListener("change", onTiltInputChanged);
  });
}

function onTiltInputChanged(ev) {
  const item = ev.target.closest(".sys-string-setup-item");
  if (!item) return;
  const n = parseInt(item.dataset.stringIndex, 10);
  updateTiltEffectiveVisibility(n);
}

function updateTiltEffectiveVisibility(n) {
  const item = stringSetupItem(n);
  if (!item) return;
  const wrap = item.querySelector(".sys-tilt-effective-wrap");
  const tiltInput = item.querySelector('[data-field="tilt"]');
  if (!wrap || !tiltInput) return;
  const newRaw = (tiltInput.value || "").trim();
  const oldRaw = loadedTilts[n];
  if (oldRaw === undefined || oldRaw === null || oldRaw === "") {
    wrap.classList.add("hidden");
    return;
  }
  const newNum = parseFloat(newRaw);
  const oldNum = parseFloat(oldRaw);
  if (!Number.isFinite(newNum) || !Number.isFinite(oldNum)) {
    wrap.classList.add("hidden");
    return;
  }
  wrap.classList.toggle("hidden", Math.abs(newNum - oldNum) < 0.05);
}

function stringSetupItem(n) {
  return document.querySelector(`.sys-string-setup-item[data-string-index="${n}"]`);
}

function readStringLabel(n) {
  const input = stringSetupItem(n)?.querySelector('[data-field="label"]');
  const text = (input?.value || "").trim();
  return text || defaultInverterLabel(n);
}

function readStringFacing(n) {
  return (stringSetupItem(n)?.querySelector('[data-field="facing"]')?.value || "").trim();
}

function readStringTilt(n) {
  return (stringSetupItem(n)?.querySelector('[data-field="tilt"]')?.value ?? "").trim();
}

function readStringTiltEffective(n) {
  return (stringSetupItem(n)?.querySelector('[data-field="tiltEffective"]')?.value || "").trim();
}

function readTiltChangePending() {
  const today = new Date().toISOString().slice(0, 10);
  const pending = [];
  for (let n = 1; n <= MAX_MPPT_STRINGS; n++) {
    const newRaw = readStringTilt(n);
    if (newRaw === "") continue;
    const newNum = parseFloat(newRaw);
    if (!Number.isFinite(newNum)) continue;
    const oldRaw = loadedTilts[n];
    if (oldRaw === undefined || oldRaw === null || oldRaw === "") continue;
    const oldNum = parseFloat(oldRaw);
    if (!Number.isFinite(oldNum)) continue;
    if (Math.abs(newNum - oldNum) < 0.05) continue;
    pending.push({
      stringIndex: n,
      previousTiltDegrees: oldNum,
      newTiltDegrees: newNum,
      effectiveDate: readStringTiltEffective(n) || today,
    });
  }
  return pending;
}

function displayStringName(n) {
  const label = readStringLabel(n);
  const facing = facingLabel(readStringFacing(n));
  const tilt = readStringTilt(n);
  const parts = [];
  if (facing) parts.push(facing);
  if (tilt !== "" && Number.isFinite(parseFloat(tilt))) parts.push(`${tilt}°`);
  if (!parts.length) return label;
  return `${label} (${parts.join(", ")})`;
}

function renderTiltHistory(log) {
  const host = sysEl("sysTiltHistory");
  if (!host) return;
  const rows = log || [];
  if (!rows.length) {
    host.innerHTML =
      '<p class="sys-hint">No tilt changes recorded yet. When you change a tilt angle and Save, it is logged here for before/after analysis.</p>';
    return;
  }
  const head =
    "<thead><tr><th>String</th><th>Effective</th><th>Was</th><th>Now</th><th>Recorded</th></tr></thead>";
  const body = rows
    .map((r) => {
      const prev = r.previousTiltDegrees != null ? `${r.previousTiltDegrees}°` : "—";
      const now = r.newTiltDegrees != null ? `${r.newTiltDegrees}°` : "—";
      return `<tr>
        <td>MPPT ${r.stringIndex}</td>
        <td>${r.effectiveDate || "—"}</td>
        <td>${prev}</td>
        <td>${now}</td>
        <td>${(r.recordedAt || "").replace(" UTC", "")}</td>
      </tr>`;
    })
    .join("");
  host.innerHTML = `<table class="sys-tilt-table">${head}<tbody>${body}</tbody></table>`;
}

function fillStringLabels(strings) {
  buildStringLabels();
  for (let n = 1; n <= MAX_MPPT_STRINGS; n++) {
    const row = (strings || []).find((r) => Number(r.stringIndex) === n);
    const item = stringSetupItem(n);
    if (!item) continue;
    const input = item.querySelector('[data-field="label"]');
    const select = item.querySelector('[data-field="facing"]');
    if (input) {
      input.value = (row?.label || "").trim();
      input.placeholder = defaultInverterLabel(n);
    }
    if (select) {
      select.innerHTML = facingOptionsHtml(row?.facingDirection || "");
    }
    const tiltInput = item.querySelector('[data-field="tilt"]');
    if (tiltInput) {
      const t = row?.tiltDegrees;
      tiltInput.value = t != null && t !== "" ? String(t) : "";
      loadedTilts[n] = t != null && t !== "" ? Number(t) : null;
    }
    updateTiltEffectiveVisibility(n);
  }
  updateStringLabelVisibility();
}

function updateStringLabelVisibility() {
  const count = activeStringCount();
  document.querySelectorAll(".sys-string-setup-item").forEach((item) => {
    const idx = parseInt(item.dataset.stringIndex, 10);
    item.classList.toggle("hidden", idx > count);
  });
}

function updateStringCardTitles() {
  document.querySelectorAll(".sys-string-card").forEach((card) => {
    const n = parseInt(card.dataset.stringIndex, 10);
    const title = card.querySelector(".sys-block-title");
    if (title) {
      title.textContent = `${displayStringName(n)} — MPPT ${n}`;
    }
  });
}

function buildStringCards() {
  const host = sysEl("sysStringCards");
  if (!host) return;
  if (host.childElementCount >= MAX_MPPT_STRINGS) return;

  host.innerHTML = "";
  for (let n = 1; n <= MAX_MPPT_STRINGS; n++) {
    const card = document.createElement("article");
    card.className = "sys-string-card";
    card.dataset.stringIndex = String(n);
    card.innerHTML = `
      <h3 class="sys-block-title">${defaultInverterLabel(n)} — String ${n} (MPPT ${n})</h3>
      <div class="sys-grid">
        <label class="sys-field sys-field-wide">
          <span>Panel brand / model</span>
          <input type="text" data-field="brand" autocomplete="off" placeholder="Brand for MPPT ${n}" />
        </label>
        <label class="sys-field">
          <span>Panel max power (W)</span>
          <input type="number" data-field="panelMaxPowerW" min="0" step="1" />
        </label>
        <label class="sys-field">
          <span>Max power current Imp (A)</span>
          <input type="number" data-field="maxPowerCurrentImpA" min="0" step="0.01" />
        </label>
        <label class="sys-field">
          <span>Max open-circuit voltage Voc (V)</span>
          <input type="number" data-field="maxOpenCircuitVoltageVocV" min="0" step="0.1" />
        </label>
        <label class="sys-field">
          <span>Panels on this string</span>
          <input type="number" data-field="panelsPerString" min="0" step="1" />
        </label>
      </div>
    `;
    host.appendChild(card);
  }
}

function setSolarSectionVisible(installed) {
  const block = sysEl("sysSolarFields");
  if (!block) return;
  block.classList.toggle("hidden", !installed);
  if (!installed) {
    block.querySelectorAll("input, textarea").forEach((el) => {
      if (el.type === "radio") return;
      el.disabled = true;
    });
  } else {
    block.querySelectorAll("input, textarea").forEach((el) => {
      if (el.type === "radio") return;
      el.disabled = false;
    });
    updateBrandModeUi();
  }
}

function isSameBrandMode() {
  return sysEl("sysBrandSame")?.checked ?? true;
}

function activeStringCount() {
  const n = parseInt(val("sysStringCount"), 10);
  if (Number.isFinite(n) && n >= 1 && n <= MAX_MPPT_STRINGS) return n;
  return MAX_MPPT_STRINGS;
}

function updateBrandModeUi() {
  const same = isSameBrandMode();
  sysEl("sysSameBrandBlock")?.classList.toggle("hidden", !same);
  sysEl("sysDiffBrandBlock")?.classList.toggle("hidden", same);

  const count = activeStringCount();
  document.querySelectorAll(".sys-string-card").forEach((card) => {
    const idx = parseInt(card.dataset.stringIndex, 10);
    card.classList.toggle("hidden", same || idx > count);
  });
  updateStringLabelVisibility();
  updateStringCardTitles();
}

function stringCard(n) {
  return document.querySelector(`.sys-string-card[data-string-index="${n}"]`);
}

function setInput(el, value) {
  if (!el) return;
  el.value = value ?? "";
}

function fillPanelSpec(prefix, spec) {
  const s = spec || {};
  if (prefix === "shared") {
    setInput(sysEl("sysSharedBrand"), s.brand);
    setInput(sysEl("sysSharedMaxW"), s.panelMaxPowerW);
    setInput(sysEl("sysSharedImp"), s.maxPowerCurrentImpA);
    setInput(sysEl("sysSharedVoc"), s.maxOpenCircuitVoltageVocV);
    setInput(sysEl("sysSharedPanelsPerString"), s.panelsPerString);
    return;
  }
  const card = stringCard(Number(prefix));
  if (!card) return;
  setInput(card.querySelector('[data-field="brand"]'), s.brand);
  setInput(card.querySelector('[data-field="panelMaxPowerW"]'), s.panelMaxPowerW);
  setInput(card.querySelector('[data-field="maxPowerCurrentImpA"]'), s.maxPowerCurrentImpA);
  setInput(card.querySelector('[data-field="maxOpenCircuitVoltageVocV"]'), s.maxOpenCircuitVoltageVocV);
  setInput(card.querySelector('[data-field="panelsPerString"]'), s.panelsPerString);
}

function readPanelSpecShared() {
  return {
    brand: val("sysSharedBrand").trim(),
    panelMaxPowerW: val("sysSharedMaxW"),
    maxPowerCurrentImpA: val("sysSharedImp"),
    maxOpenCircuitVoltageVocV: val("sysSharedVoc"),
    panelsPerString: val("sysSharedPanelsPerString"),
  };
}

function readStringCard(card, n) {
  if (!card) {
    return {
      stringIndex: n,
      label: readStringLabel(n),
      facingDirection: readStringFacing(n),
      tiltDegrees: readStringTilt(n),
      brand: "",
      panelMaxPowerW: "",
      maxPowerCurrentImpA: "",
      maxOpenCircuitVoltageVocV: "",
      panelsPerString: "",
    };
  }
  return {
    stringIndex: n,
    label: readStringLabel(n),
    facingDirection: readStringFacing(n),
    tiltDegrees: readStringTilt(n),
    brand: (card.querySelector('[data-field="brand"]')?.value || "").trim(),
    panelMaxPowerW: card.querySelector('[data-field="panelMaxPowerW"]')?.value ?? "",
    maxPowerCurrentImpA: card.querySelector('[data-field="maxPowerCurrentImpA"]')?.value ?? "",
    maxOpenCircuitVoltageVocV: card.querySelector('[data-field="maxOpenCircuitVoltageVocV"]')?.value ?? "",
    panelsPerString: card.querySelector('[data-field="panelsPerString"]')?.value ?? "",
  };
}

function readStringsFromForm() {
  buildStringCards();
  const strings = [];
  for (let n = 1; n <= MAX_MPPT_STRINGS; n++) {
    strings.push(readStringCard(stringCard(n), n));
  }
  return strings;
}

function fillForm(profile) {
  buildStringLabels();
  buildStringCards();
  const inv = profile.inverter || {};
  const sol = profile.solar || {};

  setInput(sysEl("sysInvName"), inv.name);
  setInput(sysEl("sysInvPowerKw"), inv.powerKw);
  setInput(sysEl("sysInvMaxVoc"), inv.maxVocV);
  setInput(sysEl("sysInvMpptMin"), inv.mpptVoltageMinV);
  setInput(sysEl("sysInvMpptMax"), inv.mpptVoltageMaxV);
  setInput(sysEl("sysInvStrings"), inv.stringCount);
  setInput(sysEl("sysInvMaxChargeA"), inv.maxChargeCurrentA);

  const installed = sol.installed !== false;
  if (sysEl("sysSolarYes")) sysEl("sysSolarYes").checked = installed;
  if (sysEl("sysSolarNo")) sysEl("sysSolarNo").checked = !installed;

  const same = sol.sameBrandOnAllStrings !== false;
  if (sysEl("sysBrandSame")) sysEl("sysBrandSame").checked = same;
  if (sysEl("sysBrandDifferent")) sysEl("sysBrandDifferent").checked = !same;

  setInput(sysEl("sysStringCount"), sol.stringCount ?? inv.stringCount ?? "");
  fillStringLabels(sol.strings || []);
  renderTiltHistory(sol.tiltChangeLog || []);
  fillPanelSpec("shared", sol.shared || {});
  for (let n = 1; n <= MAX_MPPT_STRINGS; n++) {
    const row = (sol.strings || []).find((r) => Number(r.stringIndex) === n);
    fillPanelSpec(String(n), row || {});
  }
  setInput(sysEl("sysNotes"), sol.notes);

  setSolarSectionVisible(installed);
  updateStringCardTitles();
  const stamp = sysEl("sysUpdatedAt");
  if (stamp) {
    stamp.textContent = profile.updatedAt
      ? `Last saved: ${profile.updatedAt}`
      : "Not saved yet — fill in your hardware and click Save.";
  }
}

function readForm() {
  buildStringLabels();
  buildStringCards();
  const installed = sysEl("sysSolarYes")?.checked ?? true;
  const sameBrand = isSameBrandMode();
  return {
    inverter: {
      name: val("sysInvName").trim(),
      powerKw: val("sysInvPowerKw"),
      maxVocV: val("sysInvMaxVoc"),
      mpptVoltageMinV: val("sysInvMpptMin"),
      mpptVoltageMaxV: val("sysInvMpptMax"),
      stringCount: val("sysInvStrings"),
      maxChargeCurrentA: val("sysInvMaxChargeA"),
    },
    solar: {
      installed,
      sameBrandOnAllStrings: sameBrand,
      stringCount: val("sysStringCount"),
      shared: readPanelSpecShared(),
      strings: readStringsFromForm(),
      tiltChangePending: readTiltChangePending(),
      notes: val("sysNotes").trim(),
    },
  };
}

function setStatus(msg, isError = false) {
  const node = sysEl("sysStatus");
  if (!node) return;
  node.textContent = msg || "";
  node.classList.toggle("sys-status-error", isError);
}

async function fetchProfile() {
  const res = await fetch(`/api/system/profile?_=${Date.now()}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`HTTP ${res.status} — restart the dashboard server (python server.py)`);
  const data = await res.json();
  if (!data.ok) throw new Error(data.error || "Failed to load profile");
  return data.profile;
}

async function saveProfile() {
  const payload = readForm();
  const res = await fetch("/api/system/profile", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  let data;
  try {
    data = await res.json();
  } catch {
    throw new Error(`Save failed (HTTP ${res.status}) — is the server running?`);
  }
  if (!res.ok || !data.ok) {
    throw new Error(data.error || `Save failed (HTTP ${res.status})`);
  }
  return data.profile;
}

function bindSaveHandler() {
  if (saveHandlerBound) return;
  const btn = sysEl("sysSaveBtn");
  if (!btn) return;
  saveHandlerBound = true;

  btn.addEventListener("click", async () => {
    btn.disabled = true;
    setStatus("Saving…");
    const errEl = sysEl("sysError");
    if (errEl) {
      errEl.hidden = true;
      errEl.textContent = "";
    }
    try {
      const hadTiltChange = readTiltChangePending().length > 0;
      const profile = await saveProfile();
      fillForm(profile);
      profileHydrated = true;
      setStatus(hadTiltChange ? "Saved. Tilt change recorded in history." : "Saved.");
    } catch (err) {
      const msg = String(err.message || err);
      setStatus(msg, true);
      if (errEl) {
        errEl.textContent = msg;
        errEl.hidden = false;
      }
      console.error("System profile save failed:", err);
    } finally {
      btn.disabled = false;
    }
  });
}

function bindFormHandlers() {
  document.querySelectorAll('input[name="sysSolarInstalled"]').forEach((radio) => {
    radio.addEventListener("change", () => {
      setSolarSectionVisible(sysEl("sysSolarYes")?.checked ?? false);
    });
  });

  document.querySelectorAll('input[name="sysBrandMode"]').forEach((radio) => {
    radio.addEventListener("change", updateBrandModeUi);
  });

  sysEl("sysStringCount")?.addEventListener("input", updateBrandModeUi);

  buildStringLabels();
  sysEl("sysStringLabels")?.addEventListener("input", (ev) => {
    if (ev.target?.matches?.('[data-field="label"]')) {
      updateStringCardTitles();
    }
  });
  sysEl("sysStringLabels")?.addEventListener("change", (ev) => {
    if (ev.target?.matches?.('[data-field="facing"], [data-field="label"]')) {
      updateStringCardTitles();
    }
  });

  bindSaveHandler();
}

async function initSystemProfile() {
  buildStringLabels();
  buildStringCards();
  bindFormHandlers();
  window.initSystemAnalyze?.().catch(console.error);
  if (profileHydrated) return;

  const errEl = sysEl("sysError");
  if (errEl) {
    errEl.hidden = true;
    errEl.textContent = "";
  }
  setStatus("Loading…");
  try {
    const profile = await fetchProfile();
    fillForm(profile);
    profileHydrated = true;
    setStatus("");
  } catch (err) {
    const msg = String(err.message || err);
    setStatus(msg, true);
    if (errEl) {
      errEl.textContent = msg;
      errEl.hidden = false;
    }
  }
}

document.addEventListener("DOMContentLoaded", () => {
  buildStringLabels();
  buildStringCards();
  bindFormHandlers();
});

window.initSystemProfile = initSystemProfile;
