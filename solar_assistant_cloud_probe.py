"""Try Solar Assistant cloud authorize + proxy metrics for totals."""
from __future__ import annotations

import json
import re
from pathlib import Path

import requests

from solar_assistant_cloud_login import cloud_session, find_csrf, load_env


def main() -> int:
    cfg = load_env()
    email = cfg["solarassistant_email"]
    password = cfg["password"]
    cloud = cfg.get("cloudproxy", "https://andre6553.za.solar-assistant.io").rstrip("/")

    central = requests.Session()
    central.headers.update({"User-Agent": "Mozilla/5.0"})
    auth_page = central.get("https://solar-assistant.io/sign_in", timeout=30)
    csrf = find_csrf(auth_page.text)
    central.post(
        "https://solar-assistant.io/sign_in",
        data={
            "_csrf_token": csrf,
            "user[email]": email,
            "user[password]": password,
            "user[remember_me]": "true",
        },
        timeout=30,
        allow_redirects=True,
    )

    for url in [
        "https://solar-assistant.io/api/v1/sites",
        "https://solar-assistant.io/user/edit",
    ]:
        resp = central.get(url, timeout=30)
        print(url, resp.status_code, resp.text[:300].replace("\n", " "))

    proxy = cloud_session(email, password, cloud)
    for path in [
        "/api/v1/metrics?topic=total/monthly/solar_energy",
        "/api/v1/history/totals",
    ]:
        resp = proxy.get(f"{cloud}{path}", timeout=30)
        print("proxy", path, resp.status_code, resp.text[:200])

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
