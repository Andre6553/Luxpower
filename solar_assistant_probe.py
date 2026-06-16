"""Probe Solar Assistant local/cloud APIs and chart endpoints."""
from __future__ import annotations

import json
import re
import sys
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


def main() -> int:
    cfg = load_env()
    password = cfg.get("password", "")
    email = cfg.get("solarassistant_email") or cfg.get("username", "")
    local = cfg.get("raspberipi_ip", "192.168.10.79")
    cloud = cfg.get("cloudproxy", "https://andre6553.za.solar-assistant.io").rstrip("/")

    print("=== Local paths ===")
    paths = [
        "/",
        "/api/v1/metrics",
        "/api/history",
        "/api/charts",
        "/charts",
        "/api/v1/history",
        "/api/v1/charts",
        "/api/socket/websocket",
    ]
    for path in paths:
        try:
            resp = requests.get(f"http://{local}{path}", timeout=8, allow_redirects=False)
            snippet = resp.text[:100].replace("\n", " ")
            print(f"{path:28} {resp.status_code} {snippet}")
        except Exception as exc:
            print(f"{path:28} ERR {exc}")

    print("\n=== Local auth variants ===")
    for user in ("admin", "solar-assistant", "solar"):
        try:
            resp = requests.get(
                f"http://{local}/api/v1/metrics?topic=total/*",
                auth=(user, password),
                timeout=8,
            )
            print(f"{user:18} {resp.status_code} {resp.text[:160].replace(chr(10), ' ')}")
        except Exception as exc:
            print(f"{user:18} ERR {exc}")

    print("\n=== Local password query (websocket style) ===")
    try:
        resp = requests.get(
            f"http://{local}/api/v1/metrics?topic=total/*&password={password}",
            timeout=8,
        )
        print(resp.status_code, resp.text[:200])
    except Exception as exc:
        print("ERR", exc)

    print("\n=== Cloud login ===")
    session = requests.Session()
    login_page = session.get(f"{cloud}/login", timeout=20)
    print("login page", login_page.status_code)
    csrf = None
    for pattern in (
        r'name="_csrf_token"[^>]*value="([^"]+)"',
        r'csrf-token" content="([^"]+)"',
        r'name="csrf_token"[^>]*value="([^"]+)"',
    ):
        match = re.search(pattern, login_page.text)
        if match:
            csrf = match.group(1)
            break
    print("csrf", "found" if csrf else "missing")

    emails = [email] if email else []
    if not emails:
        print("No solarassistant_email in .env")
        return 1
    for candidate in emails:
        payload = {
            "email": candidate,
            "password": password,
            "remember_me": "true",
        }
        if csrf:
            payload["_csrf_token"] = csrf
        resp = session.post(
            f"{cloud}/login",
            data=payload,
            timeout=20,
            allow_redirects=False,
        )
        loc = resp.headers.get("location", "")
        print(f"POST {candidate!r} -> {resp.status_code} loc={loc!r}")

    print("\n=== Cloud charts page (after login attempt) ===")
    charts = session.get(f"{cloud}/#charts", timeout=20)
    print("status", charts.status_code, "url", charts.url, "len", len(charts.text))
    if "Sign in" in charts.text:
        print("Still on login page")
    else:
        print("Got authenticated content snippet:", charts.text[:300].replace("\n", " "))

    print("\n=== Cloud API paths ===")
    api_paths = [
        "/api/v1/metrics",
        "/api/v1/metrics?topic=total/*",
        "/api/history",
        "/api/charts",
    ]
    for path in api_paths:
        try:
            resp = session.get(f"{cloud}{path}", timeout=15)
            print(f"{path:35} {resp.status_code} {resp.text[:120].replace(chr(10), ' ')}")
        except Exception as exc:
            print(f"{path:35} ERR {exc}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
