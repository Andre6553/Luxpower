"""Fetch a month's LuxPower history from the cloud and save under Data/YYYY-MM/."""
from __future__ import annotations

import argparse
import csv
import json
import sys
from calendar import monthrange
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

import requests

ProgressFn = Callable[[str, int, int, str], None]

ROOT = Path(__file__).resolve().parent
ENV_PATH = ROOT / ".env"
DATA_ROOT = ROOT / "Data"
BASE_URL = "https://af.luxpowertek.com"

ENERGY_TYPES = {
    "eInvDay": "solar_kwh",
    "eToUserDay": "load_kwh",
    "eToGridDay": "export_kwh",
    "eAcChargeDay": "ac_charge_kwh",
    "eBatChargeDay": "battery_charge_kwh",
    "eBatDischargeDay": "battery_discharge_kwh",
}

CHART_ATTRS = (
    "ppv",
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
PATCH_CHART_ATTRS = ("vpv1", "vpv2", "vBat")


def load_env(path: Path) -> dict[str, str]:
    cfg: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        cfg[key.strip().lower().replace(" ", "_")] = value.strip()
    return cfg


def post(session: requests.Session, path: str, payload: dict) -> dict:
    resp = session.post(
        f"{BASE_URL}{path}",
        data=payload,
        headers={
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Accept": "application/json",
        },
        timeout=90,
    )
    resp.raise_for_status()
    data = resp.json()
    if isinstance(data, dict) and data.get("success") is False:
        raise RuntimeError(data.get("msg") or data.get("message") or str(data))
    return data


def login(session: requests.Session, username: str, password: str) -> None:
    post(session, "/WManage/api/login", {"account": username, "password": password, "language": "ENGLISH"})


def resolve_station(session: requests.Session, station_hint: str) -> tuple[int, str]:
    plants = post(
        session,
        "/WManage/web/config/plant/list",
        {"sort": "createDate", "order": "desc", "searchText": station_hint, "page": 1, "rows": 20},
    )
    for row in plants.get("rows", []):
        name = row.get("name") or row.get("plantName") or ""
        if station_hint in name.lower():
            return int(row["plantId"]), name
    raise RuntimeError(f"Station not found: {station_hint!r}")


def primary_inverter(session: requests.Session, plant_id: int) -> str:
    devices = post(
        session,
        "/WManage/api/inverterOverview/list",
        {"page": 1, "rows": 30, "plantId": plant_id, "searchText": "", "statusText": "all"},
    )
    rows = devices.get("rows") or []
    if not rows:
        raise RuntimeError("No inverters found for station")
    return rows[0]["serialNum"]


def to_kwh(raw: int | float | None) -> float:
    if raw is None:
        return 0.0
    return float(raw) / 10.0


def fetch_month_columns(
    session: requests.Session,
    serial: str,
    year: int,
    month: int,
    *,
    parallel: bool,
    on_progress: ProgressFn | None = None,
) -> dict[str, dict[int, float]]:
    out: dict[str, dict[int, float]] = {}
    energy_items = list(ENERGY_TYPES.items())
    for index, (energy_type, _label) in enumerate(energy_items, start=1):
        if on_progress:
            on_progress(
                "daily_totals",
                index,
                len(energy_items),
                f"Daily energy totals ({index}/{len(energy_items)})",
            )
        resp = post(
            session,
            "/WManage/api/analyze/energy/monthColumn",
            {
                "serialNum": serial,
                "parallel": "true" if parallel else "false",
                "year": year,
                "month": month,
                "energyType": energy_type,
            },
        )
        daily: dict[int, float] = {}
        for row in resp.get("data") or []:
            day = int(row.get("day", 0))
            daily[day] = to_kwh(row.get("energy", 0))
        out[energy_type] = daily
    return out


def fetch_day_chart(session: requests.Session, serial: str, date_text: str, attr: str) -> dict:
    return post(
        session,
        "/WManage/api/analyze/chart/dayLine",
        {"serialNum": serial, "attr": attr, "dateText": date_text},
    )


def chart_attr_block(chart: dict) -> dict:
    return {
        "unit": chart.get("unit"),
        "maxValueText": chart.get("maxValueText"),
        "avgValueText": chart.get("avgValueText"),
        "points": chart.get("data") or [],
    }


def patch_month_chart_attrs(
    year: int,
    month: int,
    *,
    attrs: tuple[str, ...] = PATCH_CHART_ATTRS,
    only_missing: bool = True,
) -> int:
    """Fetch extra dayLine attrs and merge into existing daily_charts/*.json files."""
    cfg = load_env(ENV_PATH)
    username = cfg.get("username")
    password = cfg.get("password")
    station_hint = (cfg.get("station") or "andre huis").lower()
    if not username or not password:
        raise RuntimeError("Missing LuxPower credentials in .env")

    charts_dir = DATA_ROOT / f"{year:04d}-{month:02d}" / "daily_charts"
    if not charts_dir.exists():
        raise FileNotFoundError(f"No charts folder: {charts_dir}")

    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
    login(session, username, password)
    plant_id, plant_name = resolve_station(session, station_hint)
    serial = primary_inverter(session, plant_id)

    updated = 0
    for path in sorted(charts_dir.glob("*.json")):
        day_payload = json.loads(path.read_text(encoding="utf-8"))
        series = day_payload.setdefault("series", {})
        date_text = day_payload.get("date") or path.stem
        todo = []
        for attr in attrs:
            block = series.get(attr) or {}
            has_points = bool(block.get("points"))
            if only_missing and has_points:
                continue
            todo.append(attr)
        if not todo:
            continue
        for attr in todo:
            chart = fetch_day_chart(session, serial, date_text, attr)
            series[attr] = chart_attr_block(chart)
        path.write_text(json.dumps(day_payload, indent=2, ensure_ascii=False), encoding="utf-8")
        updated += 1
        print(f"  patched {date_text} ({', '.join(todo)})")

    print(f"Patched {updated} day file(s) for {year:04d}-{month:02d} ({plant_name})")
    return updated


def fetch_month_events(session: requests.Session, plant_id: int, serial: str, year: int, month: int) -> list[dict]:
    prefix = f"{year:04d}-{month:02d}-"
    events: list[dict] = []
    page = 1
    while page <= 20:
        resp = post(
            session,
            "/WManage/api/analyze/event/list",
            {
                "page": page,
                "rows": 100,
                "plantId": plant_id,
                "serialNum": serial,
                "eventText": "_all",
            },
        )
        rows = resp.get("rows") or []
        if not rows:
            break
        matched = [r for r in rows if str(r.get("startTime", "")).startswith(prefix)]
        events.extend(matched)
        if not any(str(r.get("startTime", "")).startswith(prefix) for r in rows):
            # Events are newest-first; once an entire page is before this month, stop.
            if rows and str(rows[-1].get("startTime", "")) < prefix:
                break
        if len(rows) < 100:
            break
        page += 1
    return events


def write_daily_csv(path: Path, year: int, month: int, columns: dict[str, dict[int, float]]) -> None:
    days_in_month = monthrange(year, month)[1]
    fieldnames = ["date", "day", *ENERGY_TYPES.values()]
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for day in range(1, days_in_month + 1):
            row = {
                "date": f"{year:04d}-{month:02d}-{day:02d}",
                "day": day,
            }
            for energy_type, col_name in ENERGY_TYPES.items():
                row[col_name] = round(columns.get(energy_type, {}).get(day, 0.0), 2)
            writer.writerow(row)


def write_events_csv(path: Path, events: list[dict]) -> None:
    fields = [
        "startTime",
        "renormalTime",
        "eventType",
        "eventText",
        "event",
        "status",
        "faultDuration",
        "serialNum",
    ]
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for event in sorted(events, key=lambda e: e.get("startTime", "")):
            writer.writerow(event)


def fetch_month(
    year: int,
    month: int,
    *,
    with_daily_charts: bool = True,
    parallel: bool = False,
    on_progress: ProgressFn | None = None,
) -> Path:
    cfg = load_env(ENV_PATH)
    username = cfg.get("username")
    password = cfg.get("password")
    station_hint = (cfg.get("station") or "andre huis").lower()
    if not username or not password:
        raise RuntimeError("Missing LuxPower credentials in .env")

    month_dir = DATA_ROOT / f"{year:04d}-{month:02d}"
    charts_dir = month_dir / "daily_charts"
    month_dir.mkdir(parents=True, exist_ok=True)
    if with_daily_charts:
        charts_dir.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
    if on_progress:
        on_progress("login", 1, 1, "Signing in to LuxPower cloud…")
    login(session, username, password)
    plant_id, plant_name = resolve_station(session, station_hint)
    serial = primary_inverter(session, plant_id)

    print(f"Fetching {year:04d}-{month:02d} for {plant_name} ({serial})")

    columns = fetch_month_columns(
        session, serial, year, month, parallel=parallel, on_progress=on_progress
    )
    if on_progress:
        on_progress("events", 1, 1, "Downloading inverter events…")
    events = fetch_month_events(session, plant_id, serial, year, month)

    write_daily_csv(month_dir / "energy_daily.csv", year, month, columns)
    write_events_csv(month_dir / "events.csv", events)

    with (month_dir / "energy_by_type.json").open("w", encoding="utf-8") as fh:
        json.dump(
            {
                energy_type: {str(day): value for day, value in sorted(days.items())}
                for energy_type, days in columns.items()
            },
            fh,
            indent=2,
        )

    if with_daily_charts:
        days_in_month = monthrange(year, month)[1]
        for day in range(1, days_in_month + 1):
            date_text = f"{year:04d}-{month:02d}-{day:02d}"
            if on_progress:
                on_progress(
                    "charts",
                    day,
                    days_in_month,
                    f"Downloading chart data for {date_text} ({day}/{days_in_month})",
                )
            day_payload = {"date": date_text, "series": {}}
            for attr in CHART_ATTRS:
                chart = fetch_day_chart(session, serial, date_text, attr)
                day_payload["series"][attr] = {
                    "unit": chart.get("unit"),
                    "maxValueText": chart.get("maxValueText"),
                    "avgValueText": chart.get("avgValueText"),
                    "points": chart.get("data") or [],
                }
            out = charts_dir / f"{date_text}.json"
            out.write_text(json.dumps(day_payload, indent=2, ensure_ascii=False), encoding="utf-8")
            print(f"  saved chart {date_text}")
    elif on_progress:
        on_progress("charts", 1, 1, "Skipping daily charts")

    manifest = {
        "fetchedAtUtc": datetime.now(timezone.utc).isoformat(),
        "source": "cloud",
        "baseUrl": BASE_URL,
        "station": {"plantId": plant_id, "name": plant_name},
        "inverterSerial": serial,
        "parallel": parallel,
        "year": year,
        "month": month,
        "files": {
            "energy_daily_csv": "energy_daily.csv",
            "energy_by_type_json": "energy_by_type.json",
            "events_csv": "events.csv",
            "daily_charts_dir": "daily_charts/" if with_daily_charts else None,
        },
        "energyTypes": ENERGY_TYPES,
        "notes": "Energy values in CSV are kWh (API raw / 10). Charts are time-series points from dayLine.",
    }
    (month_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Saved month data to {month_dir}")
    return month_dir


def main() -> int:
    parser = argparse.ArgumentParser(description="Download LuxPower cloud history for one month.")
    parser.add_argument("--year", type=int, default=2026)
    parser.add_argument("--month", type=int, default=5)
    parser.add_argument("--no-charts", action="store_true", help="Skip per-day chart JSON files")
    parser.add_argument("--parallel", action="store_true", help="Use parallel group totals")
    args = parser.parse_args()

    try:
        fetch_month(
            args.year,
            args.month,
            with_daily_charts=not args.no_charts,
            parallel=args.parallel,
        )
        return 0
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
