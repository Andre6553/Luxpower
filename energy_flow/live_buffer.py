"""In-memory ring buffer of today's dongle readings for live charts."""
from __future__ import annotations

from datetime import date, datetime
from threading import Lock

from chart_smooth import reset_chart_filters, smooth_today_rows
from load_source import load_source_series

MAX_POINTS = 5000
_lock = Lock()
_day: date | None = None
_points: list[dict] = []


def _point_from_snapshot(snapshot: dict) -> dict:
    pv = snapshot.get("pv", {})
    bat = snapshot.get("battery", {})
    grid = snapshot.get("grid", {})
    load = snapshot.get("consumption", {})
    inv = snapshot.get("inverter", {})
    gen = snapshot.get("generator", {})
    pv1 = pv.get("pv1", {})
    pv2 = pv.get("pv2", {})
    return {
        "time": snapshot.get("timestamp") or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "ppv1": float(pv1.get("powerW", 0)),
        "ppv2": float(pv2.get("powerW", 0)),
        "ppvAux": float(pv.get("auxPowerW", 0)),
        "pvTotal": float(pv.get("totalPowerW", 0)),
        "load": float(load.get("powerW", 0)),
        "grid": float(grid.get("netW", 0)),
        "gridExport": float(grid.get("exportW", 0)),
        "gridImport": float(grid.get("importW", 0)),
        "battery": float(bat.get("powerW", 0)),
        "charge": float(max(0, -bat.get("powerW", 0))),
        "discharge": float(max(0, bat.get("powerW", 0))),
        "soc": float(bat.get("socPercent", 0)),
        "vpv1": float(pv1.get("voltageV", 0)),
        "vpv2": float(pv2.get("voltageV", 0)),
        "ipv1": float(pv1.get("currentA", 0)),
        "ipv2": float(pv2.get("currentA", 0)),
        "vbat": float(bat.get("voltageV", 0)),
        "ibat": float(bat.get("currentA", 0)),
        "invTemp": float(inv.get("temperatureC", 0)),
        "batTemp": float(bat.get("temperatureC", 0)),
        "vac": float(grid.get("voltageV", 0)),
        "vacOut": float(grid.get("acOutputVoltageV", grid.get("voltageV", 0))),
        "freq": float(grid.get("frequencyHz", 0)),
        "genPower": float(gen.get("powerW", 0)),
    }


def append_snapshot(snapshot: dict) -> None:
    global _day
    today = date.today()
    point = _point_from_snapshot(snapshot)
    with _lock:
        if _day != today:
            _points.clear()
            _day = today
            reset_chart_filters()
        if _points and _points[-1]["time"] == point["time"]:
            _points[-1] = point
        else:
            _points.append(point)
        if len(_points) > MAX_POINTS:
            del _points[: len(_points) - MAX_POINTS]


def _rows_for_charts() -> list[dict]:
    return smooth_today_rows(list(_points))


def _series(unit: str, key: str, rows: list[dict]) -> dict:
    points = []
    for p in rows:
        value = p.get(key)
        if value is None:
            continue
        points.append({"time": p["time"], "value": float(value)})
    return {"unit": unit, "maxValueText": "", "avgValueText": "", "points": points}


def _combined_pv_series(rows: list[dict]) -> dict:
    by_time: dict[str, float] = {}
    for p in rows:
        by_time[p["time"]] = p["pvTotal"]
    points = [{"time": t, "value": v} for t, v in sorted(by_time.items())]
    return {"unit": "W", "maxValueText": "", "avgValueText": "", "points": points}


def today_chart_payload(station: str, inverter_sn: str) -> dict:
    with _lock:
        day = _day or date.today()
        if not _points:
            return {
                "ok": True,
                "source": "dongle",
                "date": day.isoformat(),
                "station": station,
                "inverterSerial": inverter_sn,
                "series": {},
                "pointCount": 0,
            }
        rows = _rows_for_charts()
        series = {
            "ppv1": _series("W", "ppv1", rows),
            "ppv2": _series("W", "ppv2", rows),
            "ppvAux": _series("W", "ppvAux", rows),
            "pvTotal": _combined_pv_series(rows),
            "soc": _series("%", "soc", rows),
            "load": _series("W", "load", rows),
            "pToUser": _series("W", "load", rows),
            "pToGrid": _series("W", "gridExport", rows),
            "pCharge": _series("W", "charge", rows),
            "pDischarge": _series("W", "discharge", rows),
            "battery": _series("W", "battery", rows),
            "gridNet": _series("W", "grid", rows),
            "vpv1": _series("V", "vpv1", rows),
            "vpv2": _series("V", "vpv2", rows),
            "ipv1": _series("A", "ipv1", rows),
            "ipv2": _series("A", "ipv2", rows),
            "vbat": _series("V", "vbat", rows),
            "ibat": _series("A", "ibat", rows),
            "invTemp": _series("°C", "invTemp", rows),
            "batTemp": _series("°C", "batTemp", rows),
            "vac": _series("V", "vac", rows),
            "vacOut": _series("V", "vacOut", rows),
            "freq": _series("Hz", "freq", rows),
            "loadFromSolar": load_source_series(rows, "loadFromSolar"),
            "loadFromBattery": load_source_series(rows, "loadFromBattery"),
            "loadFromGrid": load_source_series(rows, "loadFromGrid"),
        }
        return {
            "ok": True,
            "source": "dongle",
            "date": day.isoformat(),
            "station": station,
            "inverterSerial": inverter_sn,
            "series": series,
            "pointCount": len(_points),
        }
