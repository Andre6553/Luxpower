"""Find LuxPower month energy bar chart API."""
from __future__ import annotations

import re
from pathlib import Path

import requests

from luxpower_fetch_month import load_env, login, post, primary_inverter, resolve_station

BASE = "https://af.luxpowertek.com"
CDN = "https://resource.solarcloudsystem.com"


def main() -> None:
    cfg = load_env(Path(__file__).resolve().parent / ".env")
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0"})
    login(session, cfg["username"], cfg["password"])
    page = session.get(f"{BASE}/WManage/web/monitor/inverter", timeout=60).text
    apis: set[str] = set()
    for rel in re.findall(r'src="([^"]+\.js[^"]*)"', page):
        url = rel if rel.startswith("http") else CDN + (rel if rel.startswith("/") else "/" + rel)
        try:
            js = session.get(url, timeout=60).text
        except Exception:
            continue
        if "getBarVisible" not in js and "eConsumptionDay" not in js:
            continue
        print("\nFILE", rel.split("/")[-1][:60])
        for m in re.finditer(r"baseUrl \+ '(/api/[^']+)'", js):
            p = m.group(1)
            if "energy" in p or "column" in p or "chart" in p:
                apis.add(p)
                idx = m.start()
                print(" ", p, "->", js[idx : idx + 160].replace("\n", " ")[:160])

    serial = primary_inverter(session, resolve_station(session, (cfg.get("station") or "andre huis").lower())[0])
    print("\nProbe APIs for May 2026 day 26:")
    for path in sorted(apis):
        for payload in (
            {"serialNum": serial, "year": 2026, "month": 5, "parallel": "false"},
            {"serialNum": serial, "year": 2026, "month": 5},
            {"serialNum": serial, "year": 2026, "month": 5, "chartType": "monthColumn"},
        ):
            try:
                resp = post(session, path, payload)
                data = resp.get("data") or []
                print(f"OK {path} rows={len(data)} keys={list(data[0].keys())[:12] if data else []}")
                if data:
                    row = next((x for x in data if int(x.get("day", 0)) == 26), None)
                    if row:
                        print(
                            "  day26",
                            {
                                k: row.get(k)
                                for k in (
                                    "ePv1Day",
                                    "ePv2Day",
                                    "eDisChgDay",
                                    "eToUserDay",
                                    "eConsumptionDay",
                                )
                                if k in row
                            },
                        )
                break
            except Exception as exc:
                msg = str(exc)
                if "404" not in msg and "400" not in msg:
                    print("?", path, msg[:100])


if __name__ == "__main__":
    main()
