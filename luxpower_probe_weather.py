"""Probe LuxPower cloud for weather / forecast chart data."""
from __future__ import annotations

from pathlib import Path

import requests

from luxpower_fetch_month import load_env, login, post, resolve_station, primary_inverter

DAYLINE_ATTRS = [
    "outsideTemp",
    "outsideTemperature",
    "outTemp",
    "ambientTemp",
    "weatherTemp",
    "envTemp",
    "tOut",
    "cloudCover",
    "cloud",
    "clouds",
    "cloudiness",
    "pvPredicted",
    "pvForecast",
    "predictedPpv",
    "forecastPpv",
    "ppvPredict",
    "ppvForecast",
    "weather",
    "humidity",
    "windSpeed",
    "wind",
    "rain",
    "irradiance",
    "radiation",
    "solarIrradiance",
    "tInv",
    "tBat",
    "invTemp",
    "batTemp",
    "temperature",
    "temp",
]

OTHER_ENDPOINTS = [
    "/WManage/api/weather/get",
    "/WManage/api/weather/list",
    "/WManage/web/weather/list",
    "/WManage/api/analyze/weather/dayLine",
    "/WManage/api/analyze/chart/weather",
    "/WManage/api/analyze/chart/dayWeather",
    "/WManage/api/plant/getWeather",
    "/WManage/api/plant/weather",
]


def main() -> None:
    cfg = load_env(Path(__file__).resolve().parent / ".env")
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
    login(session, cfg["username"], cfg["password"])
    plant_id, plant_name = resolve_station(session, (cfg.get("station") or "andre huis").lower())
    serial = primary_inverter(session, plant_id)
    date_text = "2026-05-15"

    print(f"Plant: {plant_name} (id={plant_id})  serial={serial}  date={date_text}\n")
    print("=== dayLine weather-like attrs (non-zero points only) ===")
    hits = 0
    for attr in DAYLINE_ATTRS:
        try:
            chart = post(
                session,
                "/WManage/api/analyze/chart/dayLine",
                {"serialNum": serial, "attr": attr, "dateText": date_text},
            )
            pts = chart.get("data") or []
            if pts:
                hits += 1
                print(
                    f"  {attr:18} pts={len(pts):4} unit={chart.get('unit')!r} "
                    f"max={chart.get('maxValueText', '')}"
                )
        except Exception as exc:
            print(f"  {attr:18} ERROR: {exc}")
    if not hits:
        print("  (none returned data points)")

    print("\n=== other endpoints ===")
    for path in OTHER_ENDPOINTS:
        payload = {"plantId": plant_id, "serialNum": serial, "dateText": date_text}
        try:
            resp = post(session, path, payload)
            if isinstance(resp, dict):
                data = resp.get("data") or resp.get("rows") or resp.get("obj")
                n = len(data) if isinstance(data, list) else type(data).__name__
                print(f"  OK {path} keys={list(resp.keys())[:6]} data={n}")
            else:
                print(f"  OK {path} type={type(resp).__name__}")
        except Exception as exc:
            print(f"  FAIL {path}: {exc}")


if __name__ == "__main__":
    main()
