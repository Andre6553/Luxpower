"""Fetch Solar Assistant totals metrics from local Pi after sign-in."""
from __future__ import annotations

import json
import re
from pathlib import Path

import requests

ENV_PATH = Path(__file__).resolve().parent / ".env"
OUT = Path(__file__).resolve().parent / "Data" / "_cache" / "sa_totals_metrics.json"


def load_env() -> dict[str, str]:
    cfg: dict[str, str] = {}
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        cfg[key.strip().lower().replace(" ", "_")] = value.strip()
    return cfg


def local_session(host: str, password: str) -> requests.Session:
    session = requests.Session()
    sign_in = session.get(f"http://{host}/sign_in", timeout=15)
    match = re.search(r'content="([^"]+)"\s+name="csrf-token"', sign_in.text) or re.search(
        r'name="csrf-token"\s+content="([^"]+)"', sign_in.text
    )
    if not match:
        raise RuntimeError("CSRF token not found on local SA sign_in")
    session.post(
        f"http://{host}/sign_in",
        data={"_csrf_token": match.group(1), "password": password, "remember_me": "true"},
        timeout=15,
        allow_redirects=True,
    )
    return session


def main() -> int:
    cfg = load_env()
    host = cfg.get("raspberipi_ip", "192.168.10.79")
    password = cfg.get("password", "")
    session = local_session(host, password)

    topics = [
        "total/daily/load_energy",
        "total/daily/solar_energy",
        "total/daily/battery_charge_energy",
        "total/daily/battery_discharge_energy",
        "total/daily/grid_import_energy",
        "total/daily/grid_export_energy",
        "total/monthly/load_energy",
        "total/monthly/solar_energy",
        "total/monthly/battery_charge_energy",
        "total/monthly/battery_discharge_energy",
        "total/monthly/grid_import_energy",
        "total/monthly/grid_export_energy",
    ]

    payload: dict[str, object] = {"host": host, "topics": {}}
    for topic in topics:
        resp = session.get(f"http://{host}/api/v1/metrics?topic={topic}", timeout=20)
        entry = {"status": resp.status_code, "contentType": resp.headers.get("content-type", "")}
        if resp.headers.get("content-type", "").startswith("application/json"):
            try:
                entry["data"] = resp.json()
            except Exception:
                entry["text"] = resp.text[:500]
        else:
            entry["text"] = resp.text[:500]
        payload["topics"][topic] = entry
        print(topic, resp.status_code, str(entry.get("data") or entry.get("text", ""))[:120])

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print("saved", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
