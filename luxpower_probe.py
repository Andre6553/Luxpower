"""One-off probe: login to LuxPower cloud API and print live inverter data."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import requests

ENV_PATH = Path(__file__).resolve().parent / ".env"
BASE_URL = "https://af.luxpowertek.com"  # Middle East & Africa cluster


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
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    if isinstance(data, dict) and data.get("success") is False:
        raise RuntimeError(data.get("msg") or data.get("message") or str(data))
    return data


def main() -> int:
    cfg = load_env(ENV_PATH)
    username = cfg.get("username")
    password = cfg.get("password")
    station_hint = (cfg.get("station") or "").lower()

    if not username or not password:
        print("Missing username/password in .env", file=sys.stderr)
        return 1

    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json, text/plain, */*",
        }
    )

    print(f"Logging in to {BASE_URL} ...")
    login = post(
        session,
        "/WManage/api/login",
        {"account": username, "password": password, "language": "ENGLISH"},
    )
    print("Login OK")
    if isinstance(login, dict):
        print(f"  user role: {login.get('role')}  userId: {login.get('userId')}")
        user_role = login.get("role")
    else:
        user_role = None

    list_endpoint = (
        "/WManage/web/config/plant/list"
        if user_role == "INSTALLER"
        else "/WManage/web/config/plant/list/viewer"
    )
    plants_resp = post(
        session,
        list_endpoint,
        {
            "sort": "createDate",
            "order": "desc",
            "searchText": station_hint,
            "page": 1,
            "rows": 20,
        },
    )
    print("Plant list keys:", list(plants_resp.keys()) if isinstance(plants_resp, dict) else type(plants_resp))
    if isinstance(plants_resp, dict) and not (plants_resp.get("rows") or []):
        overview = post(
            session,
            "/WManage/api/plantOverview/list/viewer",
            {"searchText": station_hint},
        )
        print("Overview keys:", list(overview.keys()))
        if overview.get("rows"):
            plants_resp = overview
    rows = plants_resp.get("rows") or plants_resp.get("data") or []
    if not rows and isinstance(plants_resp.get("obj"), list):
        rows = plants_resp["obj"]

    print("\n=== STATIONS ===")
    for row in rows:
        name = row.get("plantName") or row.get("name") or "?"
        pid = row.get("plantId") or row.get("id")
        mark = " <-- match" if station_hint and station_hint in name.lower() else ""
        print(f"  id={pid}  name={name!r}{mark}")

    target = None
    for row in rows:
        name = row.get("plantName") or row.get("name") or ""
        if station_hint and station_hint in name.lower():
            target = row
            break
    if not target:
        print("\nNo matching station found.")
        print(f"Set station= in .env to match one of your plant names (searched: {cfg.get('station')!r}).")
        return 1

    plant_id = target.get("plantId") or target.get("id")
    plant_name = target.get("plantName") or target.get("name")
    print(f"\nUsing station: {plant_name} (id={plant_id})")

    devices_resp = post(
        session,
        "/WManage/api/inverterOverview/list",
        {
            "page": 1,
            "rows": 30,
            "plantId": int(plant_id),
            "searchText": "",
            "statusText": "all",
        },
    )
    devices = devices_resp.get("rows") or devices_resp.get("data") or []
    if not devices and isinstance(devices_resp.get("obj"), list):
        devices = devices_resp["obj"]

    print("\n=== DEVICES ===")
    for dev in devices:
        print(
            f"  SN={dev.get('serialNum')}  role={dev.get('role')}  "
            f"type={dev.get('deviceType') or dev.get('type')}"
        )
    if not devices:
        print("No devices returned.")
        return 1

    serial = devices[0].get("serialNum")
    if not serial:
        print("Device has no serial number.")
        return 1

    runtime = post(
        session,
        "/WManage/api/inverter/getInverterRuntime",
        {"serialNum": serial},
    )
    energy = post(
        session,
        "/WManage/api/inverter/getInverterEnergyInfo",
        {"serialNum": serial},
    )

    runtime_obj = runtime.get("obj") or runtime.get("data") or runtime
    energy_obj = energy.get("obj") or energy.get("data") or energy

    print(f"\n=== LIVE DATA ({serial}) ===")
    scale = {
        "vBat": 100,
        "vacr": 100,
        "vacs": 100,
        "vact": 100,
        "fac": 100,
        "facr": 100,
    }
    interesting = [
        "ppv", "ppv1", "ppv2", "soc", "pbat", "vBat", "prec", "pToGrid",
        "pload", "pac", "vacr", "fac", "status", "pCharge", "pDischarge",
    ]
    for key in interesting:
        if key not in runtime_obj:
            continue
        val = runtime_obj[key]
        if isinstance(val, (int, float)) and key in scale:
            val = val / scale[key]
        print(f"  {key}: {val}")

    print("\n=== ENERGY (raw API fields) ===")
    for key, val in sorted(energy_obj.items()):
        if key in ("success", "msg", "code") or val in (None, "", "--"):
            continue
        if isinstance(val, (int, float, str, bool)):
            print(f"  {key}: {val}")

    print("\n=== SAMPLE RAW KEYS ===")
    print("  runtime:", ", ".join(sorted(runtime_obj.keys())[:20]), "...")
    print("  energy:", ", ".join(sorted(energy_obj.keys())[:20]), "...")

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except requests.HTTPError as exc:
        print(f"HTTP error: {exc.response.status_code} {exc.response.text[:500]}", file=sys.stderr)
        raise SystemExit(2)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(2)
