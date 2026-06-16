"""Try many SA metrics auth styles on local Pi."""
from __future__ import annotations

import re
from pathlib import Path

import requests
from requests.auth import HTTPBasicAuth

from solar_assistant_login import load_env


def local_session(host: str, password: str) -> requests.Session:
    session = requests.Session()
    sign_in = session.get(f"http://{host}/sign_in", timeout=15)
    match = re.search(r'content="([^"]+)"\s+name="csrf-token"', sign_in.text) or re.search(
        r'name="csrf-token"\s+content="([^"]+)"', sign_in.text
    )
    if not match:
        raise RuntimeError("no csrf")
    session.post(
        f"http://{host}/sign_in",
        data={"_csrf_token": match.group(1), "password": password, "remember_me": "true"},
        timeout=15,
        allow_redirects=True,
    )
    return session


def try_get(url: str, **kwargs) -> tuple[int, str]:
    resp = requests.get(url, timeout=15, **kwargs)
    text = resp.text[:180].replace("\n", " ")
    return resp.status_code, text


def main() -> None:
    cfg = load_env()
    host = cfg.get("raspberipi_ip", "192.168.10.79")
    pw = cfg.get("password", "")
    topic = "total/monthly/solar_energy"
    base = f"http://{host}/api/v1/metrics?topic={topic}"

    session = local_session(host, pw)
    print("session cookies", list(session.cookies.keys()))

    attempts = [
        ("session only", {"cookies": session.cookies}),
        ("session + pw query", {"cookies": session.cookies, "params": {"topic": topic, "password": pw}}),
        ("basic solar-assistant", {"auth": HTTPBasicAuth("solar-assistant", pw)}),
        ("basic admin", {"auth": HTTPBasicAuth("admin", pw)}),
        ("basic empty user", {"auth": HTTPBasicAuth("", pw)}),
        ("basic password user", {"auth": HTTPBasicAuth(pw, pw)}),
    ]
    for label, kwargs in attempts:
        if "params" in kwargs:
            url = f"http://{host}/api/v1/metrics"
        else:
            url = base
        code, text = try_get(url, **kwargs)
        print(f"{label:22} {code} {text}")

    for path in [
        "/api/v1/totals",
        "/api/totals",
        "/totals.json",
        "/api/v1/history/totals",
        "/api/v1/history/monthly",
    ]:
        code, text = try_get(f"http://{host}{path}", cookies=session.cookies)
        print(f"path {path:28} {code} {text}")


if __name__ == "__main__":
    main()
