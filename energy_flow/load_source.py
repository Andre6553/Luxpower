"""Estimate how household load is split across solar, battery, and grid (per sample)."""
from __future__ import annotations


def estimate_house_load_w(
    pv_w: float,
    charge_w: float,
    discharge_w: float,
    grid_import_w: float,
    grid_export_w: float,
) -> float:
    """
    Estimate AC load from power balance (LuxPower dayLine has no true load register).
    load ≈ PV + battery discharge + grid import − battery charge − grid export.
    """
    load = (
        max(0.0, float(pv_w))
        + max(0.0, float(discharge_w))
        + max(0.0, float(grid_import_w))
        - max(0.0, float(charge_w))
        - max(0.0, float(grid_export_w))
    )
    return max(0.0, round(load, 1))


def split_load_source(
    load_w: float,
    pv_w: float,
    discharge_w: float,
    grid_import_w: float,
) -> tuple[float, float, float]:
    """
    Priority model: solar serves load first, then battery discharge, then grid import.
    Returns (solar_to_load, battery_to_load, grid_to_load) in watts.
    """
    load_w = max(0.0, float(load_w))
    pv_w = max(0.0, float(pv_w))
    discharge_w = max(0.0, float(discharge_w))
    grid_import_w = max(0.0, float(grid_import_w))

    if load_w <= 0:
        return 0.0, 0.0, 0.0

    solar = min(load_w, pv_w)
    rem = load_w - solar
    battery = min(rem, discharge_w)
    rem -= battery
    grid = min(rem, grid_import_w)
    rem -= grid

    if rem > 1.0:
        if grid_import_w > grid:
            grid += rem
        elif discharge_w > battery:
            battery += rem
        elif pv_w > solar:
            solar += rem
        else:
            grid += rem

    total = solar + battery + grid
    if total > load_w + 1.0 and total > 0:
        scale = load_w / total
        solar *= scale
        battery *= scale
        grid *= scale

    return round(solar, 1), round(battery, 1), round(grid, 1)


def _value_at(points: list[dict], time: str) -> float:
    for p in points:
        if p.get("time") == time:
            return float(p.get("value") or 0)
    return 0.0


def luxpower_rows_from_series(series: dict) -> list[dict]:
    """Build aligned rows from LuxPower cloud day chart series."""
    times: set[str] = set()
    blocks: dict[str, list[dict]] = {}
    for key in ("ppv1", "ppv2", "pCharge", "pDischarge", "pToUser", "pToGrid"):
        pts = (series.get(key) or {}).get("points") or []
        blocks[key] = pts
        for p in pts:
            times.add(str(p["time"]))
    rows: list[dict] = []
    for time in sorted(times):
        pv = _value_at(blocks["ppv1"], time) + _value_at(blocks["ppv2"], time)
        charge = _value_at(blocks["pCharge"], time)
        discharge = _value_at(blocks["pDischarge"], time)
        grid_import = _value_at(blocks["pToUser"], time)
        grid_export = _value_at(blocks["pToGrid"], time)
        rows.append(
            {
                "time": time,
                "load": estimate_house_load_w(pv, charge, discharge, grid_import, grid_export),
                "pvTotal": pv,
                "discharge": discharge,
                "gridImport": grid_import,
            }
        )
    return rows


def load_source_series(rows: list[dict], key: str) -> dict:
    """Build chart series for loadFromSolar | loadFromBattery | loadFromGrid."""
    points = []
    for p in rows:
        solar, battery, grid = split_load_source(
            p.get("load", 0),
            p.get("pvTotal", 0),
            p.get("discharge", 0),
            p.get("gridImport", 0),
        )
        val = {"loadFromSolar": solar, "loadFromBattery": battery, "loadFromGrid": grid}[key]
        points.append({"time": p["time"], "value": val})
    return {"unit": "W", "maxValueText": "", "avgValueText": "", "points": points}
