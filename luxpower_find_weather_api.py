"""Find LuxPower monitor weather/forecast API endpoints from web assets."""
from __future__ import annotations

import re
from pathlib import Path

import requests

from luxpower_fetch_month import load_env, login, post, resolve_station

BASE = "https://af.luxpowertek.com"


def main() -> None:
    cfg = load_env(Path(__file__).resolve().parent / ".env")
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0", "Accept": "*/*"})
    login(session, cfg["username"], cfg["password"])
    plant_id, plant_name = resolve_station(session, (cfg.get("station") or "andre huis").lower())
    print(f"Plant: {plant_name} id={plant_id}")

    page = session.get(f"{BASE}/WManage/web/monitor/inverter", timeout=60)
    page.raise_for_status()
    text = page.text
    print(f"Monitor HTML length: {len(text)}")

    for needle in ("weather", "forecast", "Today Yield", "Tomorrow Yield", "Add Location", "bound city"):
        print(f"  contains {needle!r}: {needle.lower() in text.lower()}")

    apis = sorted(set(re.findall(r"/WManage/api/[A-Za-z0-9_/]+", text)))
    weather_apis = [a for a in apis if re.search(r"weather|forecast|city|yield|ai", a, re.I)]
    print(f"\nWeather-ish API strings in HTML ({len(weather_apis)}):")
    for a in weather_apis:
        print(f"  {a}")

    js_urls = re.findall(r'src="([^"]+\.js[^"]*)"', text)
    needles = (
        "weatherForecast",
        "weatherCity",
        "todayYield",
        "tomorrowYield",
        "solarForecast",
        "aiSolar",
        "getWeather",
        "Add Location",
    )
    print(f"\nJS bundles: {len(js_urls)}")
    for rel in js_urls:
        url = rel if rel.startswith("http") else f"{BASE}{rel if rel.startswith('/') else '/' + rel}"
        try:
            js = session.get(url, timeout=60).text
        except Exception as exc:
            continue
        if not any(n.lower() in js.lower() for n in needles):
            continue
        print(f"\n  MATCH {rel}")
        for needle in needles:
            idx = js.lower().find(needle.lower())
            if idx >= 0:
                snippet = js[max(0, idx - 60) : idx + 100].replace("\n", " ")
                print(f"    {needle}: ...{snippet}...")
        hits = sorted(set(re.findall(r"/WManage/api/[A-Za-z0-9_/]+", js)))
        wh = [h for h in hits if re.search(r"weather|forecast|city|yield|ai", h, re.I)]
        for h in wh:
            print(f"    API {h}")

    guesses = [
        "/WManage/api/weatherForecast/getByPlantId",
        "/WManage/api/weatherForecast/get",
        "/WManage/api/weatherForecast/queryByPlantId",
        "/WManage/api/plantWeather/get",
        "/WManage/api/plantWeather/query",
        "/WManage/api/plant/getWeatherInfo",
        "/WManage/api/plant/getWeatherCity",
        "/WManage/api/weatherCity/getByPlantId",
        "/WManage/api/weatherCity/get",
        "/WManage/api/aiSolarForecast/get",
        "/WManage/api/aiSolarForecast/query",
        "/WManage/api/solarForecast/get",
        "/WManage/api/solarForecast/query",
        "/WManage/api/forecast/getSolarYield",
        "/WManage/api/forecast/getTodayTomorrow",
    ]
    print("\nEndpoint guesses:")
    for path in guesses:
        for payload in ({"plantId": plant_id}, {"plantId": plant_id, "language": "ENGLISH"}):
            try:
                resp = post(session, path, payload)
                print(f"  OK {path} keys={list(resp.keys())[:10]}")
                for key in ("obj", "data", "rows"):
                    if key in resp and resp[key]:
                        print(f"    {key}={resp[key]}")
                        break
                break
            except Exception as exc:
                msg = str(exc)
                if "404" not in msg and "500" not in msg:
                    print(f"  ? {path}: {msg[:100]}")


if __name__ == "__main__":
    main()
