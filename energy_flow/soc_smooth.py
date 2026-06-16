"""Reject impossible SOC spikes from Modbus (byte often reads 0 on bad polls)."""
from __future__ import annotations

_last_soc: float | None = None


def reset_soc_filter() -> None:
    global _last_soc
    _last_soc = None


def sanitize_soc(raw: float, voltage_v: float = 0.0) -> float:
    """
    Drop single-sample cliffs to 0% while pack voltage is still normal.
    A LiFePO4/LFP pack at ~48 V cannot be at 0% SOC in one 6 s poll.
    """
    global _last_soc

    raw = max(0.0, min(100.0, float(raw)))
    v = float(voltage_v or 0)
    last = _last_soc

    if last is not None:
        # Classic dongle glitch: SOC byte = 0, voltage unchanged
        if raw <= 3 and last >= 12 and v >= 46.0:
            return last
        # Impossible cliff (e.g. 45% -> 0% in one sample)
        if last - raw > 20 and raw <= last * 0.4:
            return last
        # Moderate dip with healthy voltage — still treat as noise
        if raw < last - 12 and v >= 48.0 and raw <= 5:
            return last

    if raw <= 3 and v >= 48.0:
        if last is not None:
            return last
        # No history yet: rough LFP estimate from voltage (48 V nominal)
        est = max(0.0, min(100.0, (v - 44.0) / 12.0 * 100.0))
        if est >= 10.0:
            raw = est

    _last_soc = raw
    return round(raw, 1)


def smooth_soc_series(points: list[dict]) -> list[dict]:
    """Walk stored chart points and remove SOC spikes (for today's buffer)."""
    if not points:
        return points
    out: list[dict] = []
    last: float | None = None
    for p in points:
        raw = max(0.0, min(100.0, float(p.get("value", 0))))
        v = float(p.get("vbat", 0) or 0)
        if last is not None:
            if raw <= 3 and last >= 12 and v >= 46.0:
                raw = last
            elif last - raw > 20 and raw <= last * 0.4:
                raw = last
            elif raw < last - 12 and v >= 48.0 and raw <= 5:
                raw = last
        last = raw
        out.append({**p, "value": raw})
    return out
