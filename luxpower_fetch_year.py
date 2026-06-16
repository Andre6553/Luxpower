"""Download LuxPower cloud history for every month in a calendar year."""
from __future__ import annotations

import argparse
import sys
from calendar import monthrange
from datetime import date, datetime, timezone
from pathlib import Path

from luxpower_fetch_month import DATA_ROOT, fetch_month

ROOT = Path(__file__).resolve().parent
LOG_DIR = ROOT / "Data" / "_logs"


def month_complete(year: int, month: int) -> bool:
    month_dir = DATA_ROOT / f"{year:04d}-{month:02d}"
    manifest = month_dir / "manifest.json"
    daily_csv = month_dir / "energy_daily.csv"
    charts_dir = month_dir / "daily_charts"
    if not manifest.exists() or not daily_csv.exists():
        return False
    expected_days = monthrange(year, month)[1]
    chart_count = len(list(charts_dir.glob("*.json"))) if charts_dir.exists() else 0
    return chart_count >= expected_days


def fetch_year(
    year: int,
    *,
    through_month: int | None = None,
    skip_complete: bool = True,
    with_daily_charts: bool = True,
    parallel: bool = False,
) -> list[Path]:
    today = date.today()
    if through_month is None:
        through_month = today.month if today.year == year else 12
    through_month = max(1, min(12, through_month))

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = LOG_DIR / f"fetch_{year}_{stamp}.log"

    saved: list[Path] = []
    with log_path.open("w", encoding="utf-8") as log:
        log.write(f"LuxPower year fetch started {datetime.now(timezone.utc).isoformat()}\n")
        log.write(f"Year={year} months=1..{through_month} skip_complete={skip_complete}\n\n")

        for month in range(1, through_month + 1):
            label = f"{year:04d}-{month:02d}"
            if skip_complete and month_complete(year, month):
                msg = f"SKIP {label} (already complete)\n"
                print(msg.strip())
                log.write(msg)
                continue
            try:
                print(f"Fetching {label} ...")
                log.write(f"START {label}\n")
                log.flush()
                path = fetch_month(
                    year,
                    month,
                    with_daily_charts=with_daily_charts,
                    parallel=parallel,
                )
                saved.append(path)
                log.write(f"OK {label} -> {path}\n\n")
                log.flush()
            except Exception as exc:
                msg = f"FAIL {label}: {exc}\n"
                print(msg.strip(), file=sys.stderr)
                log.write(msg + "\n")
                log.flush()

        log.write(f"Done. Saved {len(saved)} month(s).\n")
    print(f"Log: {log_path}")
    return saved


def main() -> int:
    parser = argparse.ArgumentParser(description="Download LuxPower cloud history for a full year.")
    parser.add_argument("--year", type=int, default=date.today().year)
    parser.add_argument("--through-month", type=int, default=None, help="Last month to fetch (default: current month)")
    parser.add_argument("--force", action="store_true", help="Re-download even if month folder looks complete")
    parser.add_argument("--no-charts", action="store_true", help="Skip per-day chart JSON files")
    parser.add_argument("--parallel", action="store_true", help="Use parallel group totals")
    args = parser.parse_args()

    try:
        fetch_year(
            args.year,
            through_month=args.through_month,
            skip_complete=not args.force,
            with_daily_charts=not args.no_charts,
            parallel=args.parallel,
        )
        return 0
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
