"""Find LuxPower Energy Overview month column energy types."""
from __future__ import annotations

import re
from pathlib import Path

import requests

from luxpower_fetch_month import load_env, login

BASE = "https://af.luxpowertek.com"


def main() -> None:
    cfg = load_env(Path(__file__).resolve().parent / ".env")
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0"})
    login(session, cfg["username"], cfg["password"])
    page = session.get(f"{BASE}/WManage/web/monitor/inverter", timeout=60).text
    js_urls = re.findall(r'src="([^"]+\.js[^"]*)"', page)
    needles = (
        "Energy Overview",
        "Solar Production",
        "Battery Discharged",
        "Import to User",
        "Consumption",
        "monthColumn",
        "energyType",
    )
    for rel in js_urls:
        url = rel if rel.startswith("http") else f"https://resource.solarcloudsystem.com{rel if rel.startswith('/') else '/' + rel}"
        if not url.startswith("http"):
            url = BASE + rel
        try:
            js = session.get(url, timeout=60).text
        except Exception:
            continue
        if not any(n.lower() in js.lower() for n in needles):
            continue
        print("\n===", rel.split("/")[-1][:70], "===")
        for needle in needles:
            idx = js.lower().find(needle.lower())
            if idx >= 0:
                print(needle, ":", js[max(0, idx - 60) : idx + 180].replace("\n", " ")[:240])

if __name__ == "__main__":
    main()
