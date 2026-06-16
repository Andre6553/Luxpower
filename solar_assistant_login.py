"""Try Solar Assistant local sign-in and Grafana dashboard discovery."""
from __future__ import annotations

import json
import re
from pathlib import Path

import requests

ENV_PATH = Path(__file__).resolve().parent / ".env"


def load_env() -> dict[str, str]:
    cfg: dict[str, str] = {}
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or "=" not in line:
            continue
        key, value = line.split("=", 1)
        cfg[key.strip().lower().replace(" ", "_")] = value.strip()
    return cfg


def main() -> None:
    cfg = load_env()
    password = cfg.get("password", "")
    local = cfg.get("raspberipi_ip", "192.168.10.79")

    session = requests.Session()
    sign_in = session.get(f"http://{local}/sign_in", timeout=10)
    print("sign_in page", sign_in.status_code)
    match = re.search(r'name="csrf-token"\s+content="([^"]+)"', sign_in.text)
    if not match:
        match = re.search(r'content="([^"]+)"\s+name="csrf-token"', sign_in.text)
    if not match:
        print("No CSRF token found")
        return
    csrf = match.group(1)
    print("csrf ok")

    resp = session.post(
        f"http://{local}/sign_in",
        data={"_csrf_token": csrf, "password": password, "remember_me": "true"},
        timeout=15,
        allow_redirects=True,
    )
    print("login result", resp.status_code, resp.url)
    print("authenticated", "/sign_in" not in resp.url)

    paths = [
        "/",
        "/grafana/d/sa-charts",
        "/grafana/d/sa-charts?kiosk=tv&theme=light",
        "/grafana/api/dashboards/uid/sa-charts",
        "/grafana/api/search?type=dash-db",
        "/api/v1/metrics?topic=total/*",
    ]
    print("\n=== Authenticated paths ===")
    for path in paths:
        try:
            r = session.get(f"http://{local}{path}", timeout=15)
            ctype = r.headers.get("content-type", "")
            snippet = r.text[:160].replace("\n", " ")
            print(f"{path:55} {r.status_code} {ctype[:30]} {snippet}")
        except Exception as exc:
            print(f"{path:55} ERR {exc}")

    dash = session.get(
        f"http://{local}/grafana/api/dashboards/uid/sa-charts",
        timeout=15,
    )
    if dash.status_code == 200 and dash.headers.get("content-type", "").startswith("application/json"):
        data = dash.json()
        out = Path(__file__).resolve().parent / "solar_assistant_grafana_dashboard.json"
        out.write_text(json.dumps(data, indent=2), encoding="utf-8")
        print(f"\nSaved Grafana dashboard -> {out}")
        panels = data.get("dashboard", {}).get("panels", [])
        print(f"Panels: {len(panels)}")
        for panel in panels[:20]:
            title = panel.get("title", panel.get("type", "?"))
            print(f"  - {title}")


if __name__ == "__main__":
    main()
