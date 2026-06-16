"""Smooth Modbus glitches on live dongle chart series (V-shaped spikes, zero drops)."""
from __future__ import annotations

from soc_smooth import reset_soc_filter, sanitize_soc, smooth_soc_series

# Per-field smoothing profile (used for buffer + live sanitize)
FIELD_PROFILES: dict[str, dict] = {
    "soc": {"kind": "soc"},
    "vbat": {"kind": "voltage_bat"},
    "vpv1": {"kind": "voltage_pv", "power_key": "ppv1"},
    "vpv2": {"kind": "voltage_pv", "power_key": "ppv2"},
    "vac": {"kind": "voltage_ac"},
    "vacOut": {"kind": "voltage_ac"},
    "ppv1": {"kind": "power", "min_spike": 80},
    "ppv2": {"kind": "power", "min_spike": 80},
    "ppvAux": {"kind": "power", "min_spike": 50},
    "pvTotal": {"kind": "power", "min_spike": 100},
    "load": {"kind": "power", "min_spike": 100},
    "charge": {"kind": "power", "min_spike": 80},
    "discharge": {"kind": "power", "min_spike": 80},
    "battery": {"kind": "power_signed", "min_spike": 150},
    "grid": {"kind": "power_signed", "min_spike": 100},
    "gridExport": {"kind": "power", "min_spike": 80},
    "gridImport": {"kind": "power", "min_spike": 80},
    "ipv1": {"kind": "current", "power_key": "ppv1", "volt_key": "vpv1"},
    "ipv2": {"kind": "current", "power_key": "ppv2", "volt_key": "vpv2"},
    "ibat": {"kind": "current", "power_key": "battery", "volt_key": "vbat"},
    "invTemp": {"kind": "temperature"},
    "batTemp": {"kind": "temperature"},
    "freq": {"kind": "frequency"},
}

_last_live: dict[str, float] = {}


def reset_chart_filters() -> None:
    global _last_live
    _last_live.clear()
    reset_soc_filter()


def _v_shape_spike(last: float, raw: float, nxt: float | None, *, min_mag: float) -> bool:
    """Single-sample dip or spike that recovers on the next poll (~6 s)."""
    if nxt is None or abs(last) < min_mag:
        return False
    if last > 0 and raw < last * 0.15 and nxt >= last * 0.55:
        return True
    if last > 0 and raw > last * 3.5 and nxt <= last * 1.4:
        return True
    return False


def _smooth_scalar(
    key: str,
    raw: float,
    last: float | None,
    nxt: float | None,
    row: dict | None = None,
) -> float:
    profile = FIELD_PROFILES.get(key, {"kind": "generic"})
    kind = profile["kind"]
    raw = float(raw)

    if kind == "soc":
        vbat = float((row or {}).get("vbat", 0))
        return sanitize_soc(raw, vbat)

    if kind == "voltage_bat":
        bat_v_min, bat_v_max = 20.0, 70.0
        raw = max(0.0, raw)
        if last is not None and (last > bat_v_max or last < bat_v_min):
            last = None
        if raw > bat_v_max or (0 < raw < bat_v_min):
            if last is not None and bat_v_min <= last <= bat_v_max:
                return last
            return 0.0
        if last is not None:
            if bat_v_min <= last <= bat_v_max and raw < 10:
                return last
            if bat_v_min <= last <= bat_v_max and raw < last * 0.25:
                return last

    elif kind == "voltage_pv":
        raw = max(0.0, raw)
        pw = float((row or {}).get(profile.get("power_key", ""), 0))
        if last is not None:
            if last >= 80 and raw < 8 and pw > 25:
                return last
            if last >= 40 and raw < 5 and pw > 40:
                return last

    elif kind == "voltage_ac":
        raw = max(0.0, raw)
        if last is not None:
            if last >= 150 and raw < 80:
                return last
            if last >= 180 and abs(raw - last) > 80:
                return last

    elif kind == "power":
        max_w = profile.get("max_w", 65000)
        raw = max(0.0, min(max_w, raw))
        min_spike = profile.get("min_spike", 100)
        if last is not None:
            if raw > max_w * 0.95:
                return last
            if _v_shape_spike(last, raw, nxt, min_mag=min_spike):
                return last

    elif kind == "power_signed":
        max_w = profile.get("max_w", 65000)
        raw = max(-max_w, min(max_w, raw))
        min_spike = profile.get("min_spike", 100)
        if last is not None:
            if abs(raw) > max_w * 0.95:
                return last
            if _v_shape_spike(abs(last), abs(raw), abs(nxt) if nxt is not None else None, min_mag=min_spike):
                if (last > min_spike and raw < last * 0.1) or (last < -min_spike and raw > last * 0.1):
                    return last

    elif kind == "temperature":
        if last is not None and 5 < last < 95:
            if raw <= 0 or raw < -25 or raw > 110:
                return last
            if abs(raw - last) > 22:
                return last

    elif kind == "frequency":
        if last is not None and 47 <= last <= 53:
            if raw < 40 or raw > 56:
                return last

    elif kind == "current":
        max_a = profile.get("max_a", 500)
        raw = max(-max_a, min(max_a, raw))
        if row and last is not None:
            pw = abs(float(row.get(profile.get("power_key", ""), 0)))
            vv = float(row.get(profile.get("volt_key", ""), 0))
            if pw > 30 and vv > 20 and abs(raw) < 0.5:
                return last
        if last is not None and _v_shape_spike(abs(last), abs(raw), abs(nxt) if nxt is not None else None, min_mag=2):
            if abs(last) > 1 and abs(raw) < abs(last) * 0.1:
                return last

    elif kind == "generic":
        if last is not None and _v_shape_spike(last, raw, nxt, min_mag=15):
            return last

    if last is not None and nxt is not None:
        min_mag = profile.get("min_spike", 15)
        if _v_shape_spike(last, raw, nxt, min_mag=min_mag):
            return last

    return raw


def smooth_column(values: list[float], key: str, rows: list[dict]) -> list[float]:
    out: list[float] = []
    for i, raw in enumerate(values):
        last = out[-1] if out else None
        nxt = float(values[i + 1]) if i + 1 < len(values) else None
        row = rows[i] if i < len(rows) else None
        v = _smooth_scalar(key, float(raw), last, nxt, row)
        out.append(round(v, 2) if key != "soc" else round(v, 1))
    return out


def smooth_today_rows(rows: list[dict]) -> list[dict]:
    """Smooth all numeric fields on today's buffer rows (order: voltages before currents)."""
    if not rows:
        return rows
    out = [dict(r) for r in rows]
    order = [
        "soc",
        "vbat",
        "vpv1",
        "vpv2",
        "vac",
        "vacOut",
        "freq",
        "invTemp",
        "batTemp",
        "ppv1",
        "ppv2",
        "ppvAux",
        "pvTotal",
        "load",
        "charge",
        "discharge",
        "battery",
        "grid",
        "gridExport",
        "gridImport",
        "ipv1",
        "ipv2",
        "ibat",
    ]
    for key in order:
        if key not in FIELD_PROFILES:
            continue
        if key == "soc":
            pts = [{"time": r["time"], "value": r["soc"], "vbat": r.get("vbat", 0)} for r in out]
            smoothed = smooth_soc_series(pts)
            for i, pt in enumerate(smoothed):
                out[i]["soc"] = pt["value"]
            continue
        vals = [float(r.get(key, 0)) for r in out]
        sm = smooth_column(vals, key, out)
        for i, v in enumerate(sm):
            out[i][key] = v
    return out


def sanitize_live_field(key: str, raw: float, context: dict | None = None) -> float:
    """One-shot filter for /api/live snapshot fields."""
    global _last_live
    ctx = context or {}
    if key == "vbat" and _last_live.get(key, 0) > 70:
        _last_live.pop(key, None)
    last = _last_live.get(key)
    row = {**ctx, key: raw}
    v = _smooth_scalar(key, float(raw), last, None, row)
    if key == "soc":
        v = sanitize_soc(v, float(ctx.get("vbat", 0)))
    if key == "vbat":
        if not (20.0 <= v <= 70.0):
            sane_raw = float(raw) if 20.0 <= float(raw) <= 70.0 else None
            sane_last = last if last is not None and 20.0 <= last <= 70.0 else None
            v = sane_raw if sane_raw is not None else (sane_last if sane_last is not None else 0.0)
        if 20.0 <= v <= 70.0:
            _last_live[key] = v
        else:
            _last_live.pop(key, None)
        return v
    _last_live[key] = v
    return v


def smooth_series_points(points: list[dict], key: str) -> list[dict]:
    """Smooth a chart API series block (points list only)."""
    if not points or key not in FIELD_PROFILES:
        return points
    if key == "soc":
        return smooth_soc_series(points)
    rows = [{"time": p["time"], key: p["value"]} for p in points]
    vals = [float(p["value"]) for p in points]
    sm = smooth_column(vals, key, rows)
    return [{"time": p["time"], "value": v} for p, v in zip(points, sm)]
