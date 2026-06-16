"""Log in to Solar Assistant cloud proxy and verify charts access."""
from __future__ import annotations

import re
from pathlib import Path

import requests

ENV_PATH = Path(__file__).resolve().parent / ".env"


def load_env() -> dict[str, str]:
    cfg: dict[str, str] = {}
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        cfg[key.strip().lower().replace(" ", "_")] = value.strip()
    return cfg


def find_csrf(html: str) -> str | None:
    for pattern in (
        r'name="_csrf_token"\s+value="([^"]+)"',
        r'value="([^"]+)"\s+name="_csrf_token"',
        r'name="csrf-token"\s+content="([^"]+)"',
        r'content="([^"]+)"\s+name="csrf-token"',
    ):
        match = re.search(pattern, html)
        if match:
            return match.group(1)
    return None


def cloud_session(email: str, password: str, cloud: str) -> requests.Session:
    """Authenticate via solar-assistant.io and return a cloud-proxy session."""
    session = requests.Session()
    session.headers.update(
        {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) SolarAssistantClient/1.0"}
    )

    # Proxy login redirects to central authorize if not already signed in.
    session.get(f"{cloud}/login", timeout=30)

    auth_page = session.get("https://solar-assistant.io/sign_in", timeout=30)
    csrf = find_csrf(auth_page.text)
    if not csrf:
        raise RuntimeError("CSRF token not found on solar-assistant.io sign_in")

    session.post(
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
    return session


def main() -> int:
    cfg = load_env()
    password = cfg.get("password", "")
    email = cfg.get("solarassistant_email", "")
    cloud = cfg.get("cloudproxy", "https://andre6553.za.solar-assistant.io").rstrip("/")

    if not email:
        print("Missing solarassistant_email in .env")
        return 1

    print(f"Cloud: {cloud}")
    print(f"Email: {email}")

    session = cloud_session(email, password, cloud)

    dash = session.get(f"{cloud}/", timeout=30)
    charts = session.get(f"{cloud}/grafana/d/sa-charts?kiosk=tv&theme=light", timeout=30)
    signed_in = "sign_in" not in dash.url and "Sign in" not in dash.text[:2000]

    print(f"Dashboard: {dash.status_code} signed_in={signed_in}")
    print(f"Grafana charts: {charts.status_code} len={len(charts.text)}")

    api = session.get(f"{cloud}/api/v1/metrics?topic=total/*", timeout=30)
    print(f"REST API: {api.status_code} {api.text[:120]}")

    return 0 if signed_in and charts.status_code == 200 else 2


if __name__ == "__main__":
    raise SystemExit(main())
