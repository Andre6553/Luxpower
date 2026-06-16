"""Backfill extra LuxPower dayLine attrs into existing daily_charts JSON files."""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from luxpower_fetch_month import patch_month_chart_attrs

ROOT = Path(__file__).resolve().parent
LOG_DIR = ROOT / "Data" / "_logs"


def patch_year(year: int, *, through_month: int | None = None) -> int:
    today = date.today()
    if through_month is None:
        through_month = today.month if today.year == year else 12
    through_month = max(1, min(12, through_month))

    total = 0
    for month in range(1, through_month + 1):
        month_dir = ROOT / "Data" / f"{year:04d}-{month:02d}" / "daily_charts"
        if not month_dir.exists():
            print(f"SKIP {year:04d}-{month:02d} (no daily_charts folder)")
            continue
        print(f"Patching {year:04d}-{month:02d} ...")
        total += patch_month_chart_attrs(year, month)
    return total


def main() -> int:
    parser = argparse.ArgumentParser(description="Patch vpv1/vpv2/vBat into saved LuxPower chart JSON.")
    parser.add_argument("--year", type=int, default=2026)
    parser.add_argument("--month", type=int, help="Single month only (1-12)")
    parser.add_argument("--through-month", type=int, help="Patch months 1..N for the year")
    args = parser.parse_args()

    try:
        if args.month:
            patch_month_chart_attrs(args.year, args.month)
        else:
            patch_year(args.year, through_month=args.through_month)
        return 0
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
