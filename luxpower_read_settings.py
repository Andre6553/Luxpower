"""Read-only LuxPower inverter settings (remoteSetOffGrid / maintenance parameters).

Uses POST /WManage/web/maintain/remoteRead/read only — never writes.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

ENV_PATH = Path(__file__).resolve().parent / ".env"
BASE_URL = "https://af.luxpowertek.com"
OUTPUT_PATH = Path(__file__).resolve().parent / "luxpower_settings_andre_huis.json"

# Register ranges used by the LuxPower web maintenance UI (read-only).
READ_RANGES: list[tuple[int, int, str]] = [
    (0, 127, "system_and_grid"),
    (127, 127, "additional_config"),
    (240, 127, "extended_config"),
]

# Labels commonly shown on remoteSetOffGrid / backup / grid-connect pages.
OFFGRID_RELATED_KEYS = (
    "FUNC_",
    "HOLD_",
    "H_FUNCTION_",
    "EPS",
    "OFFGRID",
    "OFF_GRID",
    "GRID_OFF",
    "PV_GRID",
    "MICRO",
    "BACKUP",
    "STANDBY",
    "DISCHARGE",
    "CHARGE",
    "SOC",
    "GEN",
    "GENERATOR",
    "EXPORT",
    "IMPORT",
    "FEED",
)


def load_env(path: Path) -> dict[str, str]:
    cfg: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        cfg[key.strip().lower()] = value.strip()
    return cfg


def post(session: requests.Session, path: str, payload: dict) -> dict:
    url = f"{BASE_URL}{path}"
    resp = session.post(
        url,
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


def login(session: requests.Session, username: str, password: str) -> dict:
    return post(
        session,
        "/WManage/api/login",
        {"account": username, "password": password, "language": "ENGLISH"},
    )


def find_station(session: requests.Session, station_hint: str) -> tuple[int, str]:
    plants = post(
        session,
        "/WManage/web/config/plant/list",
        {
            "sort": "createDate",
            "order": "desc",
            "searchText": station_hint,
            "page": 1,
            "rows": 20,
        },
    )
    rows = plants.get("rows") or []
    for row in rows:
        name = row.get("name") or row.get("plantName") or ""
        if station_hint and station_hint in name.lower():
            return int(row["plantId"]), name
    raise RuntimeError(f"Station not found for search: {station_hint!r}")


def list_inverters(session: requests.Session, plant_id: int) -> list[dict]:
    resp = post(
        session,
        "/WManage/api/inverterOverview/list",
        {
            "page": 1,
            "rows": 30,
            "plantId": plant_id,
            "searchText": "",
            "statusText": "all",
        },
    )
    return resp.get("rows") or []


def read_register_range(
    session: requests.Session, inverter_sn: str, start: int, count: int
) -> dict:
    return post(
        session,
        "/WManage/web/maintain/remoteRead/read",
        {
            "inverterSn": inverter_sn,
            "startRegister": start,
            "pointNumber": count,
            "autoRetry": "true",
        },
    )


def extract_parameters(payload: dict) -> dict[str, object]:
    skip = {
        "success",
        "msg",
        "message",
        "inverterSn",
        "deviceType",
        "startRegister",
        "pointNumber",
        "autoRetry",
    }
    params: dict[str, object] = {}
    for key, value in payload.items():
        if key in skip or value in (None, "", "--"):
            continue
        if key.startswith("_"):
            continue
        params[key] = value
    return dict(sorted(params.items()))


def is_offgrid_related(name: str) -> bool:
    upper = name.upper()
    return any(token in upper for token in OFFGRID_RELATED_KEYS)


def read_all_settings(session: requests.Session, inverter_sn: str) -> dict:
    combined: dict[str, object] = {}
    ranges_out: dict[str, dict] = {}
    for start, count, label in READ_RANGES:
        block = read_register_range(session, inverter_sn, start, count)
        params = extract_parameters(block)
        ranges_out[label] = {
            "startRegister": start,
            "pointNumber": count,
            "parameterCount": len(params),
            "parameters": params,
        }
        combined.update(params)
    offgrid = {k: v for k, v in combined.items() if is_offgrid_related(k)}
    return {
        "serialNum": inverter_sn,
        "totalParameters": len(combined),
        "offgridRelatedCount": len(offgrid),
        "offgridRelated": offgrid,
        "allParameters": combined,
        "ranges": ranges_out,
    }


def main() -> int:
    cfg = load_env(ENV_PATH)
    username = cfg.get("username")
    password = cfg.get("password")
    station_hint = (cfg.get("station") or "andre huis").lower()

    if not username or not password:
        print("Missing username/password in .env", file=sys.stderr)
        return 1

    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0", "Accept": "application/json"})

    print(f"Read-only settings pull from {BASE_URL}")
    login_info = login(session, username, password)
    print(f"Logged in (role={login_info.get('role')})")

    plant_id, plant_name = find_station(session, station_hint)
    print(f"Station: {plant_name} (id={plant_id})")

    devices = list_inverters(session, plant_id)
    serials = [d["serialNum"] for d in devices if d.get("serialNum")]
    if not serials:
        print("No inverter serial numbers found.", file=sys.stderr)
        return 1

    print(f"Found {len(serials)} inverter(s): {', '.join(serials)}")

    report = {
        "readOnly": True,
        "sourcePage": "https://af.luxpowertek.com/WManage/web/maintain/remoteSetOffGrid",
        "readEndpoint": "/WManage/web/maintain/remoteRead/read",
        "fetchedAtUtc": datetime.now(timezone.utc).isoformat(),
        "station": {"plantId": plant_id, "name": plant_name},
        "inverters": [],
    }

    for sn in serials:
        print(f"Reading parameters for {sn} ...")
        try:
            report["inverters"].append(read_all_settings(session, sn))
        except RuntimeError as exc:
            msg = str(exc)
            print(f"  Skipped {sn}: {msg}")
            report["inverters"].append(
                {
                    "serialNum": sn,
                    "error": msg,
                    "readFailed": True,
                }
            )

    if not any(not inv.get("readFailed") for inv in report["inverters"]):
        print("\nAll inverters failed parameter read.", file=sys.stderr)
        OUTPUT_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        return 2

    OUTPUT_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nSaved full read-only dump: {OUTPUT_PATH}")

    for inv in report["inverters"]:
        if inv.get("readFailed"):
            print(f"\n=== {inv['serialNum']} === OFFLINE / unreadable ({inv.get('error')})")
            continue
        print(f"\n=== {inv['serialNum']} ===")
        print(f"  Total parameters read: {inv['totalParameters']}")
        print(f"  Off-grid / backup related: {inv['offgridRelatedCount']}")
        print("  Key off-grid / backup settings:")
        for key, val in inv["offgridRelated"].items():
            print(f"    {key}: {val}")

    print("\nNo write endpoints were called.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except requests.HTTPError as exc:
        print(
            f"HTTP error: {exc.response.status_code} {exc.response.text[:500]}",
            file=sys.stderr,
        )
        raise SystemExit(2)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(2)
