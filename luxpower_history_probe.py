"""Read-only LuxPower history/analytics probe (analyze/chart page APIs)."""
from __future__ import annotations

import json
import sys
from datetime import date, timedelta
from pathlib import Path

import requests

ENV_PATH = Path(__file__).resolve().parent / ".env"
BASE_URL = "https://af.luxpowertek.com"


def load_env(path: Path) -> dict[str, str]:
    cfg: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        cfg[k.strip().lower()] = v.strip()
    return cfg


def post(session: requests.Session, path: str, payload: dict) -> dict:
    resp = session.post(
        f"{BASE_URL}{path}",
        data=payload,
        headers={
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Accept": "application/json",
        },
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()
    if isinstance(data, dict) and data.get("success") is False:
        raise RuntimeError(data.get("msg") or data.get("message") or str(data))
    return data


def main() -> int:
    cfg = load_env(ENV_PATH)
    username, password = cfg.get("username"), cfg.get("password")
    station_hint = (cfg.get("station") or "andre huis").lower()
    if not username or not password:
        print("Missing credentials in .env", file=sys.stderr)
        return 1

    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
    post(session, "/WManage/api/login", {"account": username, "password": password, "language": "ENGLISH"})

    plants = post(
        session,
        "/WManage/web/config/plant/list",
        {"sort": "createDate", "order": "desc", "searchText": station_hint, "page": 1, "rows": 20},
    )
    plant = next(
        (r for r in plants.get("rows", []) if station_hint in (r.get("name") or "").lower()),
        None,
    )
    if not plant:
        print("Station not found", file=sys.stderr)
        return 1

    devices = post(
        session,
        "/WManage/api/inverterOverview/list",
        {"page": 1, "rows": 30, "plantId": int(plant["plantId"]), "searchText": "", "statusText": "all"},
    )
    serial = devices["rows"][0]["serialNum"]
    today = date.today()
    yesterday = today - timedelta(days=1)

    print(f"Station: {plant['name']}  inverter: {serial}")
    print(f"Date samples: {yesterday} and {today}\n")

    # 1) Hourly chart line (what the chart page plots)
    for label, d, attr in [
        ("PV power today", today.isoformat(), "ppv"),
        ("Battery SOC today", today.isoformat(), "soc"),
        ("Load power today", today.isoformat(), "pToUser"),
    ]:
        chart = post(
            session,
            "/WManage/api/analyze/chart/dayLine",
            {"serialNum": serial, "attr": attr, "dateText": d},
        )
        points = chart.get("dataPoints") or chart.get("rows") or []
        print(f"=== dayLine {label} ({attr}) ===")
        print(f"  points: {len(points)}")
        if points:
            sample = points[:3] + (["..."] if len(points) > 6 else []) + points[-3:]
            print(f"  sample: {sample}")

    # 2) Hourly energy columns
    y, m, d = today.year, today.month, today.day
    energy = post(
        session,
        "/WManage/api/analyze/energy/dayColumn",
        {
            "serialNum": serial,
            "parallel": "false",
            "year": y,
            "month": m,
            "day": d,
            "energyType": "eInvDay",
        },
    )
    epoints = energy.get("dataPoints") or energy.get("rows") or []
    total_wh = sum(p.get("value", 0) for p in epoints if isinstance(p, dict))
    print(f"\n=== dayColumn solar production ({today}) ===")
    print(f"  hourly buckets: {len(epoints)}  total raw: {total_wh} (typically Wh)")

    # 3) Monthly daily totals
    month = post(
        session,
        "/WManage/api/analyze/energy/monthColumn",
        {"serialNum": serial, "parallel": "false", "year": y, "month": m, "energyType": "eInvDay"},
    )
    mpoints = month.get("dataPoints") or month.get("rows") or []
    print(f"\n=== monthColumn solar ({y}-{m:02d}) ===")
    print(f"  daily buckets: {len(mpoints)}")
    if mpoints:
        print(f"  last day value: {mpoints[-1]}")

    # 4) Yearly monthly totals
    year = post(
        session,
        "/WManage/api/analyze/energy/yearColumn",
        {"serialNum": serial, "parallel": "false", "year": y, "energyType": "eInvDay"},
    )
    ypoints = year.get("dataPoints") or year.get("rows") or []
    print(f"\n=== yearColumn solar ({y}) ===")
    print(f"  monthly buckets: {len(ypoints)}")

    # 5) Event log
    events = post(
        session,
        "/WManage/api/analyze/event/list",
        {"page": 1, "rows": 5, "plantId": int(plant["plantId"]), "serialNum": serial, "eventText": "_all"},
    )
    erows = events.get("rows") or []
    print(f"\n=== event/list (latest 5) ===")
    print(f"  total events: {events.get('total', len(erows))}")
    for ev in erows[:3]:
        print(f"  - {ev.get('startTime')} [{ev.get('eventType')}] {ev.get('eventText')}")

    out = Path(__file__).resolve().parent / "luxpower_history_sample.json"
    out.write_text(
        json.dumps(
            {
                "readOnly": True,
                "serialNum": serial,
                "station": plant["name"],
                "dayLine_ppv": chart,
                "dayColumn_eInvDay": energy,
                "monthColumn_eInvDay": month,
                "yearColumn_eInvDay": year,
                "events": events,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    print(f"\nSaved sample JSON: {out}")
    print("Read-only: no settings or data were modified.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(2)
