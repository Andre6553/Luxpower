"""Probe LuxPower hourly solar generation forecast API."""
from __future__ import annotations

import json
import re
from pathlib import Path

import requests

from luxpower_fetch_month import load_env, login, post, resolve_station, primary_inverter

BASE = "https://af.luxpowertek.com"


def dump_response(label: str, resp: dict) -> None:
    print(f"\n=== {label} ===")
    print(json.dumps(resp, indent=2, ensure_ascii=False)[:4000])


def main() -> None:
    cfg = load_env(Path(__file__).resolve().parent / ".env")
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
    login(session, cfg["username"], cfg["password"])
    plant_id, plant_name = resolve_station(session, (cfg.get("station") or "andre huis").lower())
    serial = primary_inverter(session, plant_id)
    print(f"Plant: {plant_name} serial={serial}")

    forecast = post(session, "/WManage/api/weather/forecast", {"serialNum": serial})
    dump_response("weather/forecast", forecast)
    if forecast.get("ePvPredict"):
        print("ePvPredict keys:", list(forecast["ePvPredict"].keys()))

    guesses = [
        ("/WManage/api/weather/forecast/hourly", {"serialNum": serial}),
        ("/WManage/api/weather/solarForecast", {"serialNum": serial}),
        ("/WManage/api/weather/pvForecast", {"serialNum": serial}),
        ("/WManage/api/weather/forecast/chart", {"serialNum": serial}),
        ("/WManage/api/weather/forecast/detail", {"serialNum": serial}),
        ("/WManage/api/weather/ePvPredict", {"serialNum": serial}),
        ("/WManage/api/weather/forecast/epv", {"serialNum": serial}),
        ("/WManage/api/weather/plant/forecast", {"plantId": plant_id}),
        ("/WManage/api/weather/plant/forecast", {"plantId": plant_id, "serialNum": serial}),
        ("/WManage/api/weather/plant/forecast/chart", {"plantId": plant_id, "serialNum": serial}),
        ("/WManage/api/weather/plant/solarGenerationForecast", {"plantId": plant_id, "serialNum": serial}),
        ("/WManage/api/weather/solarGenerationForecast", {"serialNum": serial}),
        ("/WManage/api/weather/generationForecast", {"serialNum": serial}),
        ("/WManage/api/ai/solarGenerationForecast", {"serialNum": serial}),
        ("/WManage/api/ai/pvForecast/hourly", {"serialNum": serial}),
    ]
    for path, payload in guesses:
        try:
            resp = post(session, path, payload)
            print(f"OK {path} keys={list(resp.keys())[:12]}")
            for key in ("data", "obj", "hours", "today", "tomorrow", "ePvPredict", "chart"):
                if key in resp and resp[key]:
                    print(f"  {key} sample: {str(resp[key])[:200]}")
        except Exception as exc:
            if "404" not in str(exc):
                print(f"? {path}: {exc}")

    inv_js = session.get(
        f"https://resource.solarcloudsystem.com/WManage/web/js/monitor/inverter/inverter_20240906.js?v=2.6.9.0",
        timeout=60,
    ).text
    for needle in ("Solar Generation", "solarGeneration", "Generation Forecast", "todayPv", "hourlyPv"):
        idx = inv_js.find(needle)
        if idx >= 0:
            print(f"\n--- JS hit: {needle} ---")
            print(inv_js[max(0, idx - 80) : idx + 400].replace("\n", " ")[:480])

    apis = sorted(set(re.findall(r"/WManage/api/weather[A-Za-z0-9_/]+", inv_js)))
    print("\nweather APIs in inverter JS:")
    for a in apis:
        print(" ", a)


if __name__ == "__main__":
    main()
