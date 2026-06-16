"""Load saved LuxPower history for a configured inverter."""
from __future__ import annotations

import csv
import json
from datetime import date, datetime
from pathlib import Path

from load_source import load_source_series, luxpower_rows_from_series

ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
DEFAULT_INVERTER_SN = "2453530335"
DATA_ROOT = Path(__file__).resolve().parent.parent / "Data"
DEFAULT_YEAR = 2026
DAY_SERIES = (
    "ppv1",
    "ppv2",
    "vpv1",
    "vpv2",
    "vBat",
    "soc",
    "pToUser",
    "pToGrid",
    "pCharge",
    "pDischarge",
)
MAX_DAY_POINTS = 240
CHART_KWH_CACHE = DATA_ROOT / "_cache" / "chart_solar_kwh.json"
_chart_kwh_cache: dict[str, float] | None = None


def _load_env() -> dict[str, str]:
    cfg: dict[str, str] = {}
    if not ENV_PATH.exists():
        return cfg
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        cfg[k.strip().lower().replace(" ", "_")] = v.strip()
    return cfg


INVERTER_SN = _load_env().get("inverter_sn", DEFAULT_INVERTER_SN)


def _load_chart_kwh_cache() -> dict[str, float]:
    global _chart_kwh_cache
    if _chart_kwh_cache is not None:
        return _chart_kwh_cache
    if CHART_KWH_CACHE.exists():
        _chart_kwh_cache = json.loads(CHART_KWH_CACHE.read_text(encoding="utf-8"))
    else:
        _chart_kwh_cache = {}
    return _chart_kwh_cache


def _save_chart_kwh_cache(cache: dict[str, float]) -> None:
    global _chart_kwh_cache
    CHART_KWH_CACHE.parent.mkdir(parents=True, exist_ok=True)
    CHART_KWH_CACHE.write_text(json.dumps(cache, indent=2), encoding="utf-8")
    _chart_kwh_cache = cache


def _parse_chart_time(text: str) -> datetime:
    return datetime.strptime(text, "%Y-%m-%d %H:%M:%S")


def _integrate_power_kwh(points: list[dict]) -> float:
    if len(points) < 2:
        return 0.0
    energy_wh = 0.0
    for i in range(1, len(points)):
        t0 = _parse_chart_time(points[i - 1]["time"])
        t1 = _parse_chart_time(points[i]["time"])
        dt_h = max(0.0, (t1 - t0).total_seconds() / 3600.0)
        p_avg = (float(points[i - 1]["value"]) + float(points[i]["value"])) / 2.0
        energy_wh += p_avg * dt_h
    return energy_wh / 1000.0


def _merge_power_points(blocks: list[list[dict]]) -> list[dict]:
    totals: dict[str, float] = {}
    for block in blocks:
        for pt in block:
            totals[pt["time"]] = totals.get(pt["time"], 0.0) + float(pt.get("value") or 0)
    return [{"time": t, "value": v} for t, v in sorted(totals.items())]


def chart_solar_kwh(year: int, month: int, date_text: str) -> float | None:
    cache = _load_chart_kwh_cache()
    if date_text in cache:
        value = cache[date_text]
        return value if value > 0 else None

    path = month_dir(year, month) / "daily_charts" / f"{date_text}.json"
    if not path.exists():
        cache[date_text] = 0.0
        _save_chart_kwh_cache(cache)
        return None

    raw = json.loads(path.read_text(encoding="utf-8"))
    series = raw.get("series", {})
    ppv = (series.get("ppv") or {}).get("points") or []
    if ppv:
        kwh = round(_integrate_power_kwh(ppv), 1)
    else:
        merged = _merge_power_points(
            [
                (series.get("ppv1") or {}).get("points") or [],
                (series.get("ppv2") or {}).get("points") or [],
            ]
        )
        kwh = round(_integrate_power_kwh(merged), 1) if merged else 0.0

    cache[date_text] = kwh
    _save_chart_kwh_cache(cache)
    return kwh if kwh > 0 else None


def enrich_daily_solar(rows: list[dict]) -> list[dict]:
    enriched: list[dict] = []
    for row in rows:
        item = dict(row)
        if item["solarKwh"] <= 0:
            year, month, _ = parse_chart_date(item["date"])
            chart_kwh = chart_solar_kwh(year, month, item["date"])
            if chart_kwh:
                item["solarKwh"] = chart_kwh
                item["solarSource"] = "chart"
        enriched.append(item)
    return enriched


def month_dir(year: int, month: int) -> Path:
    return DATA_ROOT / f"{year:04d}-{month:02d}"


TOTALS_FIELDS = (
    "loadKwh",
    "solarKwh",
    "batteryChargeKwh",
    "batteryDischargeKwh",
    "gridUsedKwh",
    "gridExportKwh",
)


def list_all_month_dirs() -> list[tuple[int, int, Path]]:
    months: list[tuple[int, int, Path]] = []
    for path in sorted(DATA_ROOT.glob("20*-*")):
        if not path.is_dir() or not (path / "manifest.json").exists():
            continue
        try:
            year_s, month_s = path.name.split("-", 1)
            months.append((int(year_s), int(month_s), path))
        except (IndexError, ValueError):
            continue
    return months


def _overview_day_row(year: int, month: int, day_obj: dict) -> dict | None:
    day_num = int(day_obj.get("day") or 0)
    if day_num <= 0:
        return None
    date_text = f"{year:04d}-{month:02d}-{day_num:02d}"
    load = float(day_obj.get("loadKwh") or day_obj.get("consumptionKwh") or 0)
    return {
        "date": date_text,
        "label": date_text,
        "loadKwh": round(load, 1),
        "solarKwh": round(float(day_obj.get("solarKwh") or 0), 1),
        "batteryChargeKwh": round(float(day_obj.get("batteryChargeKwh") or 0), 1),
        "batteryDischargeKwh": round(float(day_obj.get("batteryDischargeKwh") or 0), 1),
        "gridUsedKwh": round(float(day_obj.get("gridUsedKwh") or day_obj.get("importToUserKwh") or 0), 1),
        "gridExportKwh": round(float(day_obj.get("gridExportKwh") or 0), 1),
    }


def _empty_totals_row(label: str) -> dict:
    row = {"label": label}
    for key in TOTALS_FIELDS:
        row[key] = 0.0
    return row


def _overview_is_stale(payload: dict) -> bool:
    days = payload.get("days") or []
    if not days:
        return True
    sample = days[0]
    return "batteryChargeKwh" not in sample or "gridExportKwh" not in sample


def _load_month_overview_rows(year: int, month: int, month_path: Path) -> list[dict]:
    overview_path = month_path / "energy_overview.json"
    payload: dict | None = None
    if overview_path.exists():
        payload = json.loads(overview_path.read_text(encoding="utf-8"))

    if payload is None or _overview_is_stale(payload):
        try:
            from luxpower_energy_overview import fetch_month_overview

            payload = fetch_month_overview(year, month, use_cache=False)
        except Exception:
            if payload is None:
                return []
    elif payload is None:
        return []
    rows: list[dict] = []
    for day_obj in payload.get("days") or []:
        row = _overview_day_row(year, month, day_obj)
        if row:
            rows.append(row)
    return rows


def load_totals_daily_rows() -> list[dict]:
    rows: list[dict] = []
    for year, month, month_path in list_all_month_dirs():
        rows.extend(_load_month_overview_rows(year, month, month_path))
    rows.sort(key=lambda item: item["date"])
    return rows


def _nearest_index(items: list[str], target: str) -> int:
    if target in items:
        return items.index(target)
    prior = [i for i, value in enumerate(items) if value <= target]
    if not prior:
        return 0
    return prior[-1]


def load_totals_payload(
    *,
    daily_offset: int = 0,
    monthly_offset: int = 0,
    daily_end: str | None = None,
    monthly_end: str | None = None,
) -> dict:
    daily_rows = load_totals_daily_rows()
    if not daily_rows:
        raise FileNotFoundError("No LuxPower daily totals on disk")

    dates = [row["date"] for row in daily_rows]
    monthly_map: dict[str, dict] = {}
    for row in daily_rows:
        month_label = row["date"][:7]
        bucket = monthly_map.setdefault(month_label, _empty_totals_row(month_label))
        for key in TOTALS_FIELDS:
            bucket[key] = round(bucket[key] + float(row[key]), 1)
    month_keys = sorted(monthly_map.keys())

    if daily_end:
        end_daily = _nearest_index(dates, daily_end.strip())
        daily_offset = len(daily_rows) - 1 - end_daily
    else:
        daily_offset = max(0, daily_offset)
        end_daily = len(daily_rows) - 1 - daily_offset

    start_daily = max(0, end_daily - 29)
    daily_window = daily_rows[start_daily : end_daily + 1] if end_daily >= 0 else []

    monthly_all = [monthly_map[key] for key in month_keys]
    if monthly_end:
        end_monthly = _nearest_index(month_keys, monthly_end.strip()[:7])
        monthly_offset = len(month_keys) - 1 - end_monthly
    else:
        monthly_offset = max(0, monthly_offset)
        end_monthly = len(monthly_all) - 1 - monthly_offset

    start_monthly = max(0, end_monthly - 11)
    monthly_window = monthly_all[start_monthly : end_monthly + 1] if end_monthly >= 0 else []

    manifest_year, manifest_month, _ = list_all_month_dirs()[0]
    manifest = load_manifest(manifest_year, manifest_month)

    daily_start = daily_window[0]["date"] if daily_window else None
    daily_end_date = daily_window[-1]["date"] if daily_window else None
    monthly_start = month_keys[start_monthly] if monthly_window else None
    monthly_end_month = month_keys[end_monthly] if monthly_window else None

    return {
        "ok": True,
        "station": manifest.get("station", {}).get("name", ""),
        "inverterSerial": INVERTER_SN,
        "range": {
            "firstDate": daily_rows[0]["date"],
            "lastDate": daily_rows[-1]["date"],
        },
        "pickers": {
            "months": month_keys,
            "dates": dates,
            "firstDate": daily_rows[0]["date"],
            "lastDate": daily_rows[-1]["date"],
        },
        "daily": {
            "offset": daily_offset,
            "startDate": daily_start,
            "endDate": daily_end_date,
            "canPrev": start_daily > 0,
            "canNext": daily_offset > 0,
            "rows": daily_window,
        },
        "monthly": {
            "offset": monthly_offset,
            "startMonth": monthly_start,
            "endMonth": monthly_end_month,
            "canPrev": start_monthly > 0,
            "canNext": monthly_offset > 0,
            "rows": monthly_window,
        },
        "source": "luxpower_month_column",
    }


def load_month_year_compare_payload(*, month: int, through_year: int) -> dict:
    if month < 1 or month > 12:
        raise ValueError("month must be 1-12")

    daily_rows = load_totals_daily_rows()
    if not daily_rows:
        raise FileNotFoundError("No LuxPower daily totals on disk")

    monthly_map: dict[str, dict] = {}
    for row in daily_rows:
        month_label = row["date"][:7]
        bucket = monthly_map.setdefault(month_label, _empty_totals_row(month_label))
        for key in TOTALS_FIELDS:
            bucket[key] = round(bucket[key] + float(row[key]), 1)

    compare_rows: list[dict] = []
    for ym in sorted(monthly_map.keys()):
        year_s, month_s = ym.split("-", 1)
        year = int(year_s)
        month_num = int(month_s)
        if month_num != month or year > through_year:
            continue
        source = monthly_map[ym]
        compare_rows.append(
            {
                "year": year,
                "month": month_num,
                "label": ym,
                "loadKwh": source["loadKwh"],
                "solarKwh": source["solarKwh"],
                "batteryChargeKwh": source["batteryChargeKwh"],
                "batteryDischargeKwh": source["batteryDischargeKwh"],
                "gridUsedKwh": source["gridUsedKwh"],
                "gridExportKwh": source["gridExportKwh"],
            }
        )

    if not compare_rows:
        raise FileNotFoundError(f"No history for month {month:02d} through {through_year}")

    manifest_year, manifest_month, _ = list_all_month_dirs()[0]
    manifest = load_manifest(manifest_year, manifest_month)
    month_name = date(through_year, month, 1).strftime("%B")

    return {
        "ok": True,
        "station": manifest.get("station", {}).get("name", ""),
        "inverterSerial": INVERTER_SN,
        "compare": {
            "month": month,
            "throughYear": through_year,
            "monthName": month_name,
            "label": f"{month_name} {compare_rows[0]['year']} – {month_name} {compare_rows[-1]['year']}",
            "rows": compare_rows,
        },
        "source": "luxpower_month_column",
    }


def list_month_dirs(year: int = DEFAULT_YEAR) -> list[tuple[int, Path]]:
    months: list[tuple[int, Path]] = []
    for path in sorted(DATA_ROOT.glob(f"{year:04d}-*")):
        if not path.is_dir() or not (path / "manifest.json").exists():
            continue
        try:
            month = int(path.name.split("-", 1)[1])
        except (IndexError, ValueError):
            continue
        months.append((month, path))
    return months


def parse_chart_date(date_text: str) -> tuple[int, int, int]:
    year_s, month_s, day_s = date_text.split("-", 2)
    return int(year_s), int(month_s), int(day_s)


def load_manifest(year: int = DEFAULT_YEAR, month: int = 5) -> dict:
    path = month_dir(year, month) / "manifest.json"
    if not path.exists():
        raise FileNotFoundError(f"No data folder: {path}")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("inverterSerial") != INVERTER_SN:
        raise ValueError(f"Expected inverter {INVERTER_SN}, got {manifest.get('inverterSerial')}")
    return manifest


def load_monthly_daily(year: int = DEFAULT_YEAR, month: int = 5) -> list[dict]:
    csv_path = month_dir(year, month) / "energy_daily.csv"
    rows: list[dict] = []
    with csv_path.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            rows.append(
                {
                    "date": row["date"].strip(),
                    "day": int(row["day"]),
                    "solarKwh": float(row["solar_kwh"]),
                    "loadKwh": float(row["load_kwh"]),
                    "exportKwh": float(row["export_kwh"]),
                    "batteryChargeKwh": float(row["battery_charge_kwh"]),
                    "batteryDischargeKwh": float(row["battery_discharge_kwh"]),
                }
            )
    return rows


def load_events(year: int = DEFAULT_YEAR, month: int = 5) -> list[dict]:
    csv_path = month_dir(year, month) / "events.csv"
    if not csv_path.exists():
        return []
    rows: list[dict] = []
    with csv_path.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            if row.get("serialNum") and row["serialNum"] != INVERTER_SN:
                continue
            rows.append(
                {
                    "startTime": row["startTime"],
                    "eventType": row["eventType"],
                    "eventText": row["eventText"],
                    "event": row["event"],
                    "status": row["status"],
                    "faultDuration": row.get("faultDuration", ""),
                }
            )
    return rows


def _downsample(points: list[dict]) -> list[dict]:
    if len(points) <= MAX_DAY_POINTS:
        return points
    step = len(points) / MAX_DAY_POINTS
    out: list[dict] = []
    i = 0.0
    while int(i) < len(points) and len(out) < MAX_DAY_POINTS:
        p = points[int(i)]
        out.append({"time": p["time"], "value": p["value"]})
        i += step
    if points and out[-1]["time"] != points[-1]["time"]:
        out.append({"time": points[-1]["time"], "value": points[-1]["value"]})
    return out


def load_day_chart(date: str, year: int | None = None, month: int | None = None) -> dict:
    if year is None or month is None:
        year, month, _ = parse_chart_date(date)
    path = month_dir(year, month) / "daily_charts" / f"{date}.json"
    if not path.exists():
        raise FileNotFoundError(f"No chart data for {date}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    series = raw.get("series", {})
    out: dict[str, dict] = {}
    for key in DAY_SERIES:
        block = series.get(key, {})
        points = block.get("points") or []
        out[key] = {
            "unit": block.get("unit", ""),
            "maxValueText": block.get("maxValueText", ""),
            "avgValueText": block.get("avgValueText", ""),
            "points": _downsample(points),
        }

    rows = luxpower_rows_from_series(out)
    if rows:
        out["loadFromSolar"] = load_source_series(rows, "loadFromSolar")
        out["loadFromBattery"] = load_source_series(rows, "loadFromBattery")
        out["loadFromGrid"] = load_source_series(rows, "loadFromGrid")
        out["loadEstimated"] = {
            "unit": "W",
            "maxValueText": "",
            "avgValueText": "",
            "points": [{"time": r["time"], "value": r["load"]} for r in rows],
        }

    return {"date": date, "series": out}


def monthly_summary(daily: list[dict]) -> dict:
    solar = sum(d["solarKwh"] for d in daily)
    load = sum(d["loadKwh"] for d in daily)
    export = sum(d["exportKwh"] for d in daily)
    best = max(daily, key=lambda d: d["solarKwh"]) if daily else None
    active_days = [d for d in daily if d["solarKwh"] > 0]
    return {
        "totalSolarKwh": round(solar, 1),
        "totalLoadKwh": round(load, 1),
        "totalExportKwh": round(export, 1),
        "bestSolarDay": best["date"] if best else None,
        "bestSolarKwh": best["solarKwh"] if best else 0,
        "avgSolarKwh": round(solar / len(active_days), 1) if active_days else 0,
        "daysWithProduction": len(active_days),
    }


def load_year_daily(year: int = DEFAULT_YEAR) -> list[dict]:
    rows: list[dict] = []
    for month, month_path in list_month_dirs(year):
        csv_path = month_path / "energy_daily.csv"
        if not csv_path.exists():
            continue
        rows.extend(load_monthly_daily(year, month))
    rows.sort(key=lambda row: row["date"])
    return enrich_daily_solar(rows)


def load_year_events(year: int = DEFAULT_YEAR) -> list[dict]:
    events: list[dict] = []
    for month, _ in list_month_dirs(year):
        events.extend(load_events(year, month))
    events.sort(key=lambda row: row["startTime"])
    return events


def load_year_bootstrap(year: int = DEFAULT_YEAR) -> dict:
    months = list_month_dirs(year)
    if not months:
        raise FileNotFoundError(f"No LuxPower data folders for {year}")

    manifest = load_manifest(year, months[0][0])
    daily = load_year_daily(year)
    if not daily:
        raise FileNotFoundError(f"No daily energy rows for {year}")

    month_labels = [f"{year:04d}-{month:02d}" for month, _ in months]
    default_date = default_history_date(daily)
    return {
        "ok": True,
        "inverterSerial": INVERTER_SN,
        "station": manifest.get("station", {}).get("name", ""),
        "year": year,
        "months": month_labels,
        "monthRange": {
            "first": month_labels[0],
            "last": month_labels[-1],
        },
        "defaultDate": default_date,
        "dates": [row["date"] for row in daily],
        "daily": daily,
        "summary": monthly_summary(daily),
        "events": load_year_events(year),
    }


def default_history_date(daily: list[dict]) -> str | None:
    if not daily:
        return None
    today = date.today().isoformat()
    if any(row["date"] == today for row in daily):
        return today
    best = max(daily, key=lambda row: row["solarKwh"])
    return best["date"] if best["solarKwh"] > 0 else daily[-1]["date"]
