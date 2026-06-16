/** Remote Set tab — LuxPower cloud read/write (Maintenance API). */

let settingsSchema = null;
let settingsParams = {};
let settingsInverterSn = "";
let settingsLoaded = false;

function byId(id) {
  return document.getElementById(id);
}

function setSettingsStatus(msg, isError = false) {
  const el = byId("settingsStatus");
  const err = byId("settingsError");
  if (el) {
    el.textContent = msg || "";
    el.classList.toggle("rs-status-error", isError);
  }
  if (err) {
    err.hidden = !isError;
    err.textContent = isError ? msg : "";
  }
}

function paramValue(key) {
  if (!(key in settingsParams)) return undefined;
  const v = settingsParams[key];
  if (typeof v === "boolean") return v;
  return String(v);
}

function pad2(n) {
  return String(Math.max(0, Math.min(99, Number(n) || 0))).padStart(2, "0");
}

function isSocMode(disableWhen) {
  if (!disableWhen?.socValues?.length) return false;
  const raw = paramValue(disableWhen.param);
  return disableWhen.socValues.includes(String(raw));
}

async function apiJson(url, options = {}) {
  const res = await fetch(url, {
    headers: { Accept: "application/json", ...(options.headers || {}) },
    ...options,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok || data.ok === false) {
    throw new Error(data.error || data.msg || `Request failed (${res.status})`);
  }
  return data;
}

function buildToggle(field, current) {
  const labels = field.labels || ["Disable", "Enable"];
  const invert = field.invert === true;
  const on = current === true || current === "true";
  const wrap = document.createElement("div");
  wrap.className = "rs-toggle";
  wrap.dataset.param = field.param;
  wrap.dataset.type = "func";
  labels.forEach((label, idx) => {
    const isEnableSide = idx === 1;
    const active = invert ? !isEnableSide === !on : isEnableSide === on;
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = `rs-toggle-btn${active ? " active" : ""}`;
    btn.textContent = label;
    btn.dataset.enable = invert
      ? (isEnableSide ? "false" : "true")
      : (isEnableSide ? "true" : "false");
    btn.addEventListener("click", () => {
      wrap.querySelectorAll(".rs-toggle-btn").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
    });
    wrap.appendChild(btn);
  });
  return wrap;
}

function buildMode(field, current) {
  const standby = current === true || current === "true";
  const wrap = document.createElement("div");
  wrap.className = "rs-toggle";
  wrap.dataset.param = field.param;
  wrap.dataset.type = "func";
  field.modes.forEach((mode) => {
    const active = Boolean(mode.value) === standby;
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = `rs-toggle-btn${active ? " active" : ""}`;
    btn.textContent = mode.label;
    btn.dataset.enable = mode.value ? "true" : "false";
    btn.addEventListener("click", () => {
      wrap.querySelectorAll(".rs-toggle-btn").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
    });
    wrap.appendChild(btn);
  });
  return wrap;
}

function buildSelect(field, current, writeType = "hold") {
  const sel = document.createElement("select");
  sel.className = "rs-select";
  sel.dataset.param = field.param;
  sel.dataset.type = writeType;
  const cur = current !== undefined ? String(current) : "";
  (field.options || []).forEach((opt) => {
    const o = document.createElement("option");
    o.value = opt.value;
    o.textContent = opt.label;
    if (opt.value === cur) o.selected = true;
    sel.appendChild(o);
  });
  return sel;
}

function buildText(field, current) {
  const inp = document.createElement("input");
  inp.type = "text";
  inp.className = "rs-input rs-input-wide";
  inp.dataset.param = field.param;
  inp.dataset.type = "hold";
  if (field.hint) inp.placeholder = field.hint;
  inp.value = current !== undefined ? String(current) : "";
  return inp;
}

function buildNumber(field, current, writeType = "hold") {
  const inp = document.createElement("input");
  inp.type = "number";
  inp.className = "rs-input";
  inp.dataset.param = field.param;
  inp.dataset.type = writeType;
  if (field.min != null) inp.min = field.min;
  if (field.max != null) inp.max = field.max;
  if (field.placeholder) inp.placeholder = field.placeholder;
  inp.value = current !== undefined ? String(current) : "";
  if (field.disableWhen && isSocMode(field.disableWhen)) {
    inp.disabled = true;
    inp.classList.add("rs-disabled");
  }
  return inp;
}

function buildTimeRange(field) {
  const wrap = document.createElement("div");
  wrap.className = "rs-time-range";
  const pairs = [
    ["Start", field.startHour, field.startMinute],
    ["End", field.endHour, field.endMinute],
  ];
  pairs.forEach(([label, hourKey, minKey]) => {
    const row = document.createElement("div");
    row.className = "rs-time-row";
    const lbl = document.createElement("span");
    lbl.className = "rs-time-label";
    lbl.textContent = label;
    row.appendChild(lbl);
    const h = document.createElement("input");
    h.type = "number";
    h.min = 0;
    h.max = 23;
    h.className = "rs-time-input";
    h.dataset.param = hourKey;
    h.dataset.type = "hold";
    h.value = pad2(paramValue(hourKey));
    const sep = document.createElement("span");
    sep.className = "rs-time-sep";
    sep.textContent = ":";
    const m = document.createElement("input");
    m.type = "number";
    m.min = 0;
    m.max = 59;
    m.className = "rs-time-input";
    m.dataset.param = minKey;
    m.dataset.type = "hold";
    m.value = pad2(paramValue(minKey));
    row.append(h, sep, m);
    wrap.appendChild(row);
  });
  return wrap;
}

function buildTimePair(field) {
  const wrap = document.createElement("div");
  wrap.className = "rs-time-pair";
  const h = document.createElement("input");
  h.type = "number";
  h.min = 0;
  h.max = 23;
  h.className = "rs-time-input";
  h.dataset.param = field.hourParam;
  h.dataset.type = "hold";
  h.value = pad2(paramValue(field.hourParam));
  const sep = document.createElement("span");
  sep.className = "rs-time-sep";
  sep.textContent = ":";
  const m = document.createElement("input");
  m.type = "number";
  m.min = 0;
  m.max = 59;
  m.className = "rs-time-input";
  m.dataset.param = field.minuteParam;
  m.dataset.type = "hold";
  m.value = pad2(paramValue(field.minuteParam));
  wrap.append(h, sep, m);
  return wrap;
}

function attachSetButton(row, getPayloads) {
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "rs-set-btn";
  btn.textContent = "Set";
  btn.addEventListener("click", async () => {
    const payloads = getPayloads();
    const summary = payloads.map((p) => `${p.param}=${p.value}`).join(", ");
    const ok = window.confirm(
      `Write to inverter ${settingsInverterSn}?\n\n${summary}\n\nThis changes live hardware settings.`
    );
    if (!ok) return;
    btn.disabled = true;
    setSettingsStatus("Writing…");
    try {
      for (const p of payloads) {
        await apiJson("/api/settings/write", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            confirm: true,
            inverterSn: settingsInverterSn,
            type: p.type,
            param: p.param,
            value: p.value,
          }),
        });
        settingsParams[p.param] = p.value;
      }
      setSettingsStatus(`Updated: ${summary}`);
      renderSections();
    } catch (err) {
      setSettingsStatus(String(err.message || err), true);
    } finally {
      btn.disabled = false;
    }
  });
  row.appendChild(btn);
}

function renderNote(field) {
  const p = document.createElement("p");
  p.className = "rs-note";
  let text = field.text || "";
  if (field.id === "dongle_note" && settingsSchema) {
    text = `Dongle Wi‑Fi / server region is configured on the dongle web UI or official portal. Cluster: ${settingsSchema.cluster || "—"}. Dongle SN: ${settingsSchema.dongleSn || "—"}.`;
  }
  p.textContent = text;
  return p;
}

function renderSubgroup(field) {
  const box = document.createElement("fieldset");
  box.className = "rs-subgroup";
  const legend = document.createElement("legend");
  legend.textContent = field.title;
  box.appendChild(legend);
  const inner = document.createElement("div");
  inner.className = `rs-subgroup-body${field.layout === "two-col" ? " rs-two-col" : ""}`;
  (field.fields || []).forEach((sub) => inner.appendChild(renderField(sub)));
  box.appendChild(inner);
  const wrap = document.createElement("div");
  wrap.className = "rs-field rs-field-full";
  wrap.appendChild(box);
  return wrap;
}

function renderAction(field) {
  const row = document.createElement("div");
  row.className = "rs-field";
  const label = document.createElement("label");
  label.className = "rs-field-label";
  label.textContent = field.label || "";
  row.appendChild(label);
  const controlWrap = document.createElement("div");
  controlWrap.className = "rs-field-control";
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = field.danger ? "rs-set-btn rs-danger-btn" : "rs-set-btn rs-action-btn";
  btn.textContent = field.buttonLabel || "Run";
  btn.addEventListener("click", async () => {
    const msg =
      field.action === "reset_defaults"
        ? "FACTORY RESET — restore ALL settings to default?\n\nThis cannot be undone from here."
        : `Restart inverter ${settingsInverterSn}?\n\nPower may drop briefly.`;
    if (!window.confirm(msg)) return;
    btn.disabled = true;
    setSettingsStatus("Sending command…");
    try {
      await apiJson("/api/settings/action", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          confirm: true,
          inverterSn: settingsInverterSn,
          action: field.action,
        }),
      });
      setSettingsStatus(`${field.buttonLabel || "Action"} completed.`);
    } catch (err) {
      setSettingsStatus(String(err.message || err), true);
    } finally {
      btn.disabled = false;
    }
  });
  controlWrap.appendChild(btn);
  row.appendChild(controlWrap);
  return row;
}

function renderField(field) {
  if (field.type === "action") {
    return renderAction(field);
  }
  if (field.type === "note") {
    const wrap = document.createElement("div");
    wrap.className = "rs-field rs-field-full";
    wrap.appendChild(renderNote(field));
    return wrap;
  }
  if (field.type === "subgroup") {
    return renderSubgroup(field);
  }

  const row = document.createElement("div");
  row.className = "rs-field";
  const label = document.createElement("label");
  label.className = "rs-field-label";
  label.textContent = field.label || "";
  if (field.label) row.appendChild(label);

  const controlWrap = document.createElement("div");
  controlWrap.className = "rs-field-control";

  if (field.type === "time_range") {
    const tr = buildTimeRange(field);
    controlWrap.appendChild(tr);
    attachSetButton(row, () =>
      [...tr.querySelectorAll("[data-param]")].map((inp) => ({
        type: inp.dataset.type,
        param: inp.dataset.param,
        value: pad2(inp.value),
      }))
    );
  } else if (field.type === "time_pair") {
    const tp = buildTimePair(field);
    controlWrap.appendChild(tp);
    attachSetButton(row, () =>
      [...tp.querySelectorAll("[data-param]")].map((inp) => ({
        type: "hold",
        param: inp.dataset.param,
        value: pad2(inp.value),
      }))
    );
  } else if (field.param) {
    const writeType = field.type === "bit" ? "bit" : field.type === "func" ? "func" : "hold";
    const current =
      writeType === "bit"
        ? paramValue(field.param)
        : field.type === "func"
          ? paramValue(field.param)
          : paramValue(field.param);
    let control;
    if (field.widget === "toggle") {
      control = buildToggle(field, current);
      attachSetButton(row, () => {
        const active = control.querySelector(".rs-toggle-btn.active");
        return [
          {
            type: "func",
            param: field.param,
            value: active?.dataset.enable === "true",
          },
        ];
      });
    } else if (field.widget === "mode") {
      control = buildMode(field, current);
      attachSetButton(row, () => {
        const active = control.querySelector(".rs-toggle-btn.active");
        return [
          {
            type: "func",
            param: field.param,
            value: active?.dataset.enable === "true",
          },
        ];
      });
    } else if (field.widget === "select") {
      control = buildSelect(field, current, writeType);
      attachSetButton(row, () => [
        { type: writeType, param: field.param, value: control.value },
      ]);
    } else if (field.widget === "number") {
      control = buildNumber(field, current, writeType);
      attachSetButton(row, () => [
        { type: writeType, param: field.param, value: control.value },
      ]);
    } else if (field.widget === "text") {
      control = buildText(field, current);
      attachSetButton(row, () => [
        { type: "hold", param: field.param, value: control.value },
      ]);
    }
    if (control) controlWrap.appendChild(control);
    if (field.note) {
      const hint = document.createElement("span");
      hint.className = "rs-field-hint";
      hint.textContent = field.note;
      controlWrap.appendChild(hint);
    }
  }

  row.appendChild(controlWrap);
  return row;
}

function renderSections() {
  const root = byId("settingsSections");
  if (!root || !settingsSchema?.sections) return;
  root.innerHTML = "";
  settingsSchema.sections.forEach((section) => {
    const card = document.createElement("section");
    card.className = "rs-section";
    const head = document.createElement("header");
    head.className = "rs-section-head";
    head.textContent = (section.title || "").replace(
      "{dongleSn}",
      settingsSchema?.dongleSn || "—"
    );
    card.appendChild(head);
    const body = document.createElement("div");
    body.className = "rs-section-body";
    if (section.layout === "two-col") body.classList.add("rs-two-col");
    if (section.layout === "wide") body.classList.add("rs-wide");
    (section.fields || []).forEach((field) => {
      body.appendChild(renderField(field));
    });
    card.appendChild(body);
    root.appendChild(card);
  });
}

async function loadSettingsSchema() {
  const data = await apiJson("/api/settings/schema");
  settingsSchema = data;
  settingsInverterSn = data.inverterSn || "";
  byId("settingsStationLabel").textContent = data.stationName || "Station";
  byId("settingsSerialLabel").textContent = `SN ${settingsInverterSn}`;
  renderSections();
}

async function readSettingsFromCloud() {
  const btn = byId("settingsReadBtn");
  if (btn) btn.disabled = true;
  setSettingsStatus("Reading from LuxPower cloud…");
  try {
    const data = await apiJson(
      `/api/settings/read?inverterSn=${encodeURIComponent(settingsInverterSn)}`
    );
    settingsParams = data.parameters || {};
    renderSections();
    setSettingsStatus(
      `Read OK — ${data.parameterCount ?? Object.keys(settingsParams).length} parameters at ${new Date().toLocaleTimeString()}`
    );
  } catch (err) {
    setSettingsStatus(String(err.message || err), true);
  } finally {
    if (btn) btn.disabled = false;
  }
}

window.initSettings = async function initSettings() {
  if (settingsLoaded) return;
  settingsLoaded = true;
  byId("settingsReadBtn")?.addEventListener("click", () => {
    readSettingsFromCloud().catch((err) => setSettingsStatus(String(err.message || err), true));
  });
  try {
    await loadSettingsSchema();
    setSettingsStatus("Click Read to load current inverter settings from the cloud.");
  } catch (err) {
    setSettingsStatus(String(err.message || err), true);
  }
};
