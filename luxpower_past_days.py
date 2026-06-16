"""Quick check: fetch solar data for yesterday and last Saturday."""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import requests

ENV_PATH = Path(__file__).resolve().parent / ".env"
BASE_URL = "https://af.luxpowertek.com"


def load_env() -> dict[str, str]:
    cfg: dict[str, str] = {}
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or "=" not in line:
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


def main() -> None:
    cfg = load_env()
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0"})
    post(
        session,
        "/WManage/api/login",
        {"account": cfg["username"], "password": cfg["password"], "language": "ENGLISH"},
    )

    plants = post(
        session,
        "/WManage/web/config/plant/list",
        {"sort": "createDate", "order": "desc", "searchText": "andre huis", "page": 1, "rows": 20},
    )
    plant = next(r for r in plants["rows"] if "andre huis" in r["name"].lower())
    devices = post(
        session,
        "/WManage/api/inverterOverview/list",
        {
            "page": 1,
            "rows": 30,
            "plantId": plant["plantId"],
            "searchText": "",
            "statusText": "all",
        },
    )
    serial = devices["rows"][0]["serialNum"]

    today = date(2026, 5, 27)
    yesterday = today - timedelta(days=1)
    # Last Saturday before today (Wed 27 May -> Sat 24 May)
    days_since_sat = (today.weekday() - 5) % 7
    last_sat = today - timedelta(days=days_since_sat if days_since_sat else 7)

    month = post(
        session,
        "/WManage/api/analyze/energy/monthColumn",
        {
            "serialNum": serial,
            "parallel": "false",
            "year": today.year,
            "month": today.month,
            "energyType": "eInvDay",
        },
    )
    daily = {row["day"]: row["energy"] for row in month.get("data", [])}

    for label, day in [("Yesterday", yesterday), ("Last Saturday", last_sat)]:
        chart = post(
            session,
            "/WManage/api/analyze/chart/dayLine",
            {"serialNum": serial, "attr": "ppv", "dateText": day.isoformat()},
        )
        points = chart.get("data") or []
        peak = max((p.get("value", 0) for p in points), default=0)
        total_units = daily.get(day.day)
        kwh = total_units / 10 if isinstance(total_units, (int, float)) else None
        print(f"{label}: {day.isoformat()}")
        print(f"  Intraday chart points: {len(points)}")
        print(f"  Peak PV power: {peak:.0f} W")
        if kwh is not None:
            print(f"  Total solar that day: ~{kwh:.1f} kWh")
        print()

    for parallel in ("false", "true"):
        col = post(
            session,
            "/WManage/api/analyze/energy/dayColumn",
            {
                "serialNum": serial,
                "parallel": parallel,
                "year": yesterday.year,
                "month": yesterday.month,
                "day": yesterday.day,
                "energyType": "eInvDay",
            },
        )
        total = sum(row.get("energy", 0) for row in col.get("data", []))
        print(f"Yesterday hourly breakdown (parallel={parallel}): {total/10:.1f} kWh total")


if __name__ == "__main__":
    main()
