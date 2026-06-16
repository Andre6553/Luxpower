"""LuxPower Energy Overview (grouped bar chart) data."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from luxpower_fetch_month import (
    DATA_ROOT,
    ENV_PATH,
    load_env,
    login,
    post,
    primary_inverter,
    resolve_station,
)

_SESSION: requests.Session | None = None
_SESSION_AT = 0.0
_SESSION_TTL_S = 600
CACHE_DIR = DATA_ROOT / "_cache"


def _session() -> requests.Session:
    global _SESSION, _SESSION_AT
    now = time.time()
    if _SESSION is None or now - _SESSION_AT > _SESSION_TTL_S:
        cfg = load_env(ENV_PATH)
        login(_SESSION := requests.Session(), cfg["username"], cfg["password"])
        _SESSION.headers.update({"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
        _SESSION_AT = now
    return _SESSION


def _serial() -> str:
    cfg = load_env(ENV_PATH)
    station_hint = (cfg.get("station") or "andre huis").lower()
    session = _session()
    plant_id, _ = resolve_station(session, station_hint)
    return primary_inverter(session, plant_id)


def _metrics_from_row(obj: dict) -> dict[str, float]:
    pv = float(obj.get("ePv1Day") or 0) + float(obj.get("ePv2Day") or 0) + float(obj.get("ePv3Day") or 0)
    grid_used = round(float(obj.get("eToUserDay") or 0) / 10.0, 1)
    load = round(float(obj.get("eConsumptionDay") or 0) / 10.0, 1)
    return {
        "solarKwh": round(pv / 10.0, 1),
        "loadKwh": load,
        "batteryChargeKwh": round(float(obj.get("eChgDay") or 0) / 10.0, 1),
        "batteryDischargeKwh": round(float(obj.get("eDisChgDay") or 0) / 10.0, 1),
        "gridUsedKwh": grid_used,
        "gridExportKwh": round(float(obj.get("eToGridDay") or 0) / 10.0, 1),
        # Legacy keys used by the Energy Overview chart UI.
        "importToUserKwh": grid_used,
        "consumptionKwh": load,
    }


def _overview_path(year: int, month: int) -> Path:
    return DATA_ROOT / f"{year:04d}-{month:02d}" / "energy_overview.json"


def _year_cache_path(year: int) -> Path:
    return CACHE_DIR / f"energy_overview_{year}_year.json"


def _total_cache_path() -> Path:
    return CACHE_DIR / "energy_overview_total.json"


def normalize_month_column(resp: dict, *, year: int, month: int) -> dict:
    days: list[dict] = []
    for obj in resp.get("data") or []:
        day = int(obj.get("day") or 0)
        if day <= 0:
            continue
        days.append({"day": day, **_metrics_from_row(obj)})
    days.sort(key=lambda row: row["day"])
    return {
        "ok": True,
        "mode": "month",
        "source": "luxpower",
        "year": year,
        "month": month,
        "label": f"{year:04d}-{month:02d}",
        "dayMax": int(resp.get("dayMax") or len(days) or 31),
        "days": days,
    }


def normalize_year_column(resp: dict, *, year: int) -> dict:
    months: list[dict] = []
    for obj in resp.get("data") or []:
        month = int(obj.get("month") or 0)
        if month <= 0:
            continue
        months.append({"month": month, **_metrics_from_row(obj)})
    months.sort(key=lambda row: row["month"])
    return {
        "ok": True,
        "mode": "year",
        "source": "luxpower",
        "year": year,
        "label": str(year),
        "monthMax": 12,
        "months": months,
    }


def normalize_total_column(resp: dict) -> dict:
    years: list[dict] = []
    for obj in resp.get("data") or []:
        year = int(obj.get("year") or 0)
        if year <= 0:
            continue
        metrics = _metrics_from_row(obj)
        if metrics["solarKwh"] <= 0 and metrics["consumptionKwh"] <= 0:
            continue
        years.append({"year": year, **metrics})
    years.sort(key=lambda row: row["year"])
    return {
        "ok": True,
        "mode": "total",
        "source": "luxpower",
        "label": "Total",
        "years": years,
    }


def fetch_month_overview(year: int, month: int, *, use_cache: bool = True) -> dict:
    cache_path = _overview_path(year, month)
    if use_cache and cache_path.exists():
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        if cached.get("ok") and cached.get("days"):
            cached["source"] = "cache"
            cached["mode"] = "month"
            return cached

    session = _session()
    serial = _serial()
    resp = post(
        session,
        "/WManage/api/inverterChart/monthColumn",
        {"serialNum": serial, "year": year, "month": month},
    )
    payload = normalize_month_column(resp, year=year, month=month)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    payload["source"] = "luxpower"
    return payload


def fetch_year_overview(year: int, *, use_cache: bool = True) -> dict:
    cache_path = _year_cache_path(year)
    if use_cache and cache_path.exists():
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        if cached.get("ok") and cached.get("months"):
            cached["source"] = "cache"
            cached["mode"] = "year"
            return cached

    session = _session()
    serial = _serial()
    resp = post(
        session,
        "/WManage/api/inverterChart/yearColumn",
        {"serialNum": serial, "year": year},
    )
    payload = normalize_year_column(resp, year=year)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    payload["source"] = "luxpower"
    return payload


def fetch_total_overview(*, use_cache: bool = True) -> dict:
    cache_path = _total_cache_path()
    if use_cache and cache_path.exists():
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        if cached.get("ok") and cached.get("years"):
            cached["source"] = "cache"
            cached["mode"] = "total"
            return cached

    session = _session()
    serial = _serial()
    resp = post(
        session,
        "/WManage/api/inverterChart/totalColumn",
        {"serialNum": serial},
    )
    payload = normalize_total_column(resp)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    payload["source"] = "luxpower"
    return payload
