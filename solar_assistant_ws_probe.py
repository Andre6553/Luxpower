"""Try Solar Assistant Phoenix websocket for totals/history data."""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from urllib.parse import quote

import requests

try:
    import websocket
except ImportError:
    websocket = None

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


def try_metrics_socket(host: str, password: str) -> None:
    if websocket is None:
        print("websocket-client missing")
        return
    url = f"ws://{host}/api/socket/websocket?password={quote(password)}&vsn=2.0.0"
    print("connect", url)

    messages: list[str] = []

    def on_message(_ws, message: str) -> None:
        messages.append(message)
        print("MSG", message[:500])

    def on_open(ws) -> None:
        join = [
            "1",
            "1",
            "metrics:lobby",
            "phx_join",
            {
                "topics": [
                    {"topic": "total/monthly/*"},
                    {"topic": "total/daily/*"},
                ]
            },
        ]
        ws.send(json.dumps(join))
        time.sleep(2)
        ws.close()

    ws = websocket.WebSocketApp(url, on_message=on_message, on_open=on_open)
    ws.run_forever(ping_timeout=5)
    print("received", len(messages), "messages")


def try_live_socket(host: str, session: requests.Session) -> None:
    if websocket is None:
        return
    page = session.get(f"http://{host}/totals", timeout=20)
    match = re.search(r'data-phx-session="([^"]+)"', page.text)
    if not match:
        print("no phx session on totals page")
        return
    phx_session = match.group(1)
    url = f"ws://{host}/live/websocket?vsn=2.0.0"
    print("live ws", url)

    def on_message(_ws, message: str) -> None:
        if "monthly" in message.lower() or "daily" in message.lower() or "energy" in message.lower():
            print("LIVE", message[:800])

    def on_open(ws) -> None:
        join = [
            None,
            None,
            "lv:totals",
            "phx_join",
            {"session": phx_session, "static": "", "sticky": False, "params": {}},
        ]
        ws.send(json.dumps(join))
        time.sleep(3)
        ws.close()

    headers = [f"Cookie: {k}={v}" for k, v in session.cookies.get_dict().items()]
    ws = websocket.WebSocketApp(url, header=headers, on_message=on_message, on_open=on_open)
    ws.run_forever(ping_timeout=5)


def main() -> int:
    cfg = load_env()
    host = cfg.get("raspberipi_ip", "192.168.10.79")
    password = cfg.get("password", "")
    session = local_session(host, password)
    try_metrics_socket(host, password)
    try_live_socket(host, session)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
