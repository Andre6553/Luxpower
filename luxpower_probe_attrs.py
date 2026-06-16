"""Probe which dayLine attr names LuxPower accepts."""
from __future__ import annotations

from pathlib import Path

from luxpower_fetch_month import load_env, login, post, resolve_station, primary_inverter
import requests

ATTRS = (
    "vpv1", "ipv1", "vpv2", "ipv2",
    "vBat", "iBat", "vac", "freq",
    "ppv1", "ppv2", "soc", "pToUser",
)


def main() -> None:
    cfg = load_env(Path(__file__).resolve().parent / ".env")
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
    login(session, cfg["username"], cfg["password"])
    plant_id, _ = resolve_station(session, (cfg.get("station") or "andre huis").lower())
    serial = primary_inverter(session, plant_id)
    date_text = "2026-05-15"

    for attr in ATTRS:
        try:
            chart = post(
                session,
                "/WManage/api/analyze/chart/dayLine",
                {"serialNum": serial, "attr": attr, "dateText": date_text},
            )
            pts = chart.get("data") or []
            print(
                f"{attr:8} unit={chart.get('unit')!r:6} "
                f"points={len(pts):4} max={chart.get('maxValueText', '')}"
            )
        except Exception as exc:
            print(f"{attr:8} ERROR: {exc}")


if __name__ == "__main__":
    main()
