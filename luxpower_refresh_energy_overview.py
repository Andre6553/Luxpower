"""Refresh cached LuxPower energy_overview.json for all downloaded months."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "energy_flow"))

from energy_flow.history_loader import list_all_month_dirs  # noqa: E402
from energy_flow.luxpower_energy_overview import fetch_month_overview  # noqa: E402


def main() -> int:
    months = list_all_month_dirs()
    print(f"Refreshing {len(months)} month(s)...")
    for year, month, _ in months:
        label = f"{year:04d}-{month:02d}"
        try:
            fetch_month_overview(year, month, use_cache=False)
            print(f"OK {label}")
        except Exception as exc:
            print(f"FAIL {label}: {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
