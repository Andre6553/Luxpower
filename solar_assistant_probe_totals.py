"""Probe Solar Assistant /totals page structure."""
from __future__ import annotations

import re
from pathlib import Path

from solar_assistant_cloud_login import cloud_session, load_env

OUT = Path(__file__).resolve().parent / "Data" / "_cache" / "sa_totals.html"


def main() -> int:
    cfg = load_env()
    cloud = cfg.get("cloudproxy", "https://andre6553.za.solar-assistant.io").rstrip("/")
    session = cloud_session(cfg["solarassistant_email"], cfg["password"], cloud)
    html = session.get(f"{cloud}/totals", timeout=30).text
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html, encoding="utf-8")
    print("saved", OUT, "len", len(html))

    for pattern in (
        r"data-phx-main[^>]+",
        r"phx-hook=\"([^\"]+)\"",
        r"id=\"([^\"]*total[^\"]*)\"",
        r"class=\"([^\"]*total[^\"]*)\"",
    ):
        matches = re.findall(pattern, html, re.I)
        if matches:
            print("\n", pattern, "->", matches[:20])

    main = re.search(r"<main[^>]*>(.*)</main>", html, re.S)
    if main:
        body = main.group(1)
        print("\nMAIN snippet:\n", body[:6000])

    # LiveView assigns sometimes embedded
    for m in re.finditer(r"data-chart[^=]*=\"([^\"]+)\"", html):
        print("chart data:", m.group(1)[:200])

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
