"""LuxPower cloud weather summary + hourly solar generation forecast."""
from __future__ import annotations

import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from luxpower_fetch_month import ENV_PATH, load_env, login, post, primary_inverter, resolve_station

_SESSION: requests.Session | None = None
_SESSION_AT = 0.0
_SESSION_TTL_S = 600


def _session() -> requests.Session:
    global _SESSION, _SESSION_AT
    now = time.time()
    if _SESSION is None or now - _SESSION_AT > _SESSION_TTL_S:
        cfg = load_env(ENV_PATH)
        username = cfg.get("username")
        password = cfg.get("password")
        if not username or not password:
            raise RuntimeError("Missing LuxPower credentials in .env")
        session = requests.Session()
        session.headers.update({"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
        login(session, username, password)
        _SESSION = session
        _SESSION_AT = now
    return _SESSION


def _serial() -> str:
    cfg = load_env(ENV_PATH)
    station_hint = (cfg.get("station") or "andre huis").lower()
    session = _session()
    plant_id, _ = resolve_station(session, station_hint)
    return primary_inverter(session, plant_id)


def fetch_solar_forecast_payload() -> dict:
    session = _session()
    serial = _serial()

    weather = post(session, "/WManage/api/weather/forecast", {"serialNum": serial})
    predict = post(session, "/WManage/api/predict/solar/dayPredictColumn", {"serialNum": serial})

    if not predict.get("success"):
        raise RuntimeError(predict.get("msg") or "Solar forecast unavailable")

    hours: list[dict] = []
    for row in predict.get("solarEnergys") or []:
        hours.append(
            {
                "hour": int(row.get("hour", 0)),
                "todayKwh": round(abs(float(row.get("todaySolarEnergy") or 0)) / 10.0, 2),
                "tomorrowKwh": round(abs(float(row.get("tomorrowSolarEnergy") or 0)) / 10.0, 2),
            }
        )
    hours.sort(key=lambda item: item["hour"])

    day = (weather.get("days") or [{}])[0] if weather.get("success") else {}
    predict_totals = weather.get("ePvPredict") or {}

    return {
        "ok": True,
        "source": "luxpower",
        "inverterSerial": serial,
        "location": weather.get("plantCity") or weather.get("resolvedAddress") or "",
        "timezone": weather.get("timezone") or "",
        "localDate": weather.get("localDate") or "",
        "localTomorrowDate": weather.get("localTomorrowDate") or "",
        "weather": {
            "conditions": day.get("conditions") or "",
            "icon": day.get("icon") or day.get("iconNew") or "",
            "tempMin": day.get("tempmin") or "",
            "tempMax": day.get("tempmax") or "",
            "temp": day.get("temp") or "",
            "solarradiation": day.get("solarradiation"),
        },
        "yieldTodayKwh": round(float(predict_totals.get("todayPvEnergy") or 0) / 10.0, 1)
        if predict_totals.get("todayPvEnergy") is not None
        else None,
        "yieldTomorrowKwh": round(float(predict_totals.get("tomorrowPvEnergy") or 0) / 10.0, 1)
        if predict_totals.get("tomorrowPvEnergy") is not None
        else None,
        "hours": hours,
    }
