"""Search LuxPower CDN JS for solar generation forecast chart API."""
from __future__ import annotations

import re
from pathlib import Path

import requests

from luxpower_fetch_month import load_env, login

BASE = "https://resource.solarcloudsystem.com"
HOST = "https://af.luxpowertek.com"
PAGES = [
    "/WManage/web/monitor/inverter",
    "/WManage/web/monitor/overview",
    "/WManage/web/data/analyze",
]

NEEDLES = (
    "Solar Generation Forecast",
    "Today Solar Energy",
    "Tomorrow Solar Energy",
    "todayPvEnergy",
    "tomorrowPvEnergy",
    "ePvPredict",
    "predictSolar",
    "generationForecast",
    "solarGeneration",
    "hourlyForecast",
)


def collect_js(session: requests.Session, html: str) -> list[str]:
    urls = re.findall(r'src="([^"]+\.js[^"]*)"', html)
    out: list[str] = []
    for rel in urls:
        if rel.startswith("http"):
            out.append(rel)
        else:
            out.append(BASE + (rel if rel.startswith("/") else "/" + rel))
    return out


def main() -> None:
    cfg = load_env(Path(__file__).resolve().parent / ".env")
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0"})
    login(session, cfg["username"], cfg["password"])
    seen: set[str] = set()
    for page in PAGES:
        try:
            html = session.get(HOST + page, timeout=60).text
        except Exception as exc:
            print("page fail", page, exc)
            continue
        for url in collect_js(session, html):
            if url in seen:
                continue
            seen.add(url)
            try:
                js = session.get(url, timeout=60).text
            except Exception:
                continue
            if not any(n.lower() in js.lower() for n in NEEDLES):
                continue
            print("\n===", url.split("/")[-1][:80], "===")
            for needle in NEEDLES:
                idx = js.lower().find(needle.lower())
                if idx < 0:
                    continue
                print(f"  {needle}:")
                print("   ", js[max(0, idx - 90) : idx + 220].replace("\n", " ")[:320])
            apis = sorted(set(re.findall(r"/WManage/api/[A-Za-z0-9_/]+", js)))
            for api in apis:
                if re.search(r"weather|forecast|predict|solar|epv|generation", api, re.I):
                    print("  API", api)


if __name__ == "__main__":
    main()
