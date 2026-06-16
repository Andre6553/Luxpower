"""Download LuxPower history backwards from a start month (default 2025-12)."""
from __future__ import annotations

import argparse
import csv
import sys
from calendar import monthrange
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from luxpower_fetch_month import DATA_ROOT, ProgressFn, fetch_month
from luxpower_fetch_year import LOG_DIR, month_complete

ROOT = Path(__file__).resolve().parent

MonthHook = Callable[[int, int, int, int, str], ProgressFn | None]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from energy_flow.luxpower_energy_overview import fetch_month_overview  # noqa: E402


def month_solar_total(year: int, month: int) -> float:
    csv_path = DATA_ROOT / f"{year:04d}-{month:02d}" / "energy_daily.csv"
    if not csv_path.exists():
        return 0.0
    total = 0.0
    with csv_path.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            try:
                total += float(row.get("solar_kwh") or 0)
            except ValueError:
                continue
    return total


def iter_months_backwards(start_year: int, start_month: int, min_year: int) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    year, month = start_year, start_month
    while year >= min_year:
        out.append((year, month))
        month -= 1
        if month < 1:
            month = 12
            year -= 1
    return out


def fetch_backfill(
    *,
    start_year: int = 2025,
    start_month: int = 12,
    min_year: int = 2020,
    skip_complete: bool = True,
    with_daily_charts: bool = True,
    max_empty_months: int = 2,
    on_month: MonthHook | None = None,
    fail_fast: bool = False,
) -> dict[str, int | bool]:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = LOG_DIR / f"backfill_{start_year}{start_month:02d}_{stamp}.log"

    empty_streak = 0
    saved = 0
    skipped = 0
    stopped_early = False
    months = iter_months_backwards(start_year, start_month, min_year)
    total_months = len(months)

    with log_path.open("w", encoding="utf-8") as log:
        log.write(f"LuxPower backfill started {datetime.now(timezone.utc).isoformat()}\n")
        log.write(f"From {start_year:04d}-{start_month:02d} backwards to {min_year}\n\n")

        for idx, (year, month) in enumerate(months):
            month_index = idx + 1
            label = f"{year:04d}-{month:02d}"
            if skip_complete and month_complete(year, month):
                msg = f"SKIP {label} (already complete)\n"
                print(msg.strip())
                log.write(msg)
                skipped += 1
                if on_month:
                    on_month(month_index, total_months, year, month, "skip")
                continue

            month_progress = on_month(month_index, total_months, year, month, "fetch") if on_month else None

            try:
                print(f"Fetching {label} ...")
                log.write(f"START {label}\n")
                log.flush()
                fetch_month(
                    year,
                    month,
                    with_daily_charts=with_daily_charts,
                    on_progress=month_progress,
                )
                try:
                    fetch_month_overview(year, month, use_cache=False)
                except Exception as exc:
                    log.write(f"WARN overview {label}: {exc}\n")
                solar = month_solar_total(year, month)
                log.write(f"OK {label} solar_kwh_total={solar:.1f}\n\n")
                log.flush()
                saved += 1
                if solar <= 0:
                    empty_streak += 1
                    if empty_streak >= max_empty_months:
                        log.write(f"STOP after {max_empty_months} empty month(s)\n")
                        print(f"Stopping: {max_empty_months} consecutive months with no solar data.")
                        stopped_early = True
                        break
                else:
                    empty_streak = 0
            except Exception as exc:
                msg = f"FAIL {label}: {exc}\n"
                print(msg.strip(), file=sys.stderr)
                log.write(msg + "\n")
                log.flush()
                if fail_fast:
                    raise
                empty_streak += 1
                if empty_streak >= max_empty_months:
                    log.write(f"STOP after {max_empty_months} failed/empty month(s)\n")
                    stopped_early = True
                    break

        log.write(f"Done. Saved {saved} month(s), skipped {skipped}.\n")

    print(f"Log: {log_path}")
    return {
        "saved": saved,
        "skipped": skipped,
        "stoppedEarly": stopped_early,
        "totalMonths": total_months,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill LuxPower history backwards month by month.")
    parser.add_argument("--start-year", type=int, default=2025)
    parser.add_argument("--start-month", type=int, default=12)
    parser.add_argument("--min-year", type=int, default=2020)
    parser.add_argument("--force", action="store_true", help="Re-download even if month looks complete")
    parser.add_argument("--no-charts", action="store_true")
    args = parser.parse_args()

    if not 1 <= args.start_month <= 12:
        print("start-month must be 1-12", file=sys.stderr)
        return 2

    try:
        fetch_backfill(
            start_year=args.start_year,
            start_month=args.start_month,
            min_year=args.min_year,
            skip_complete=not args.force,
            with_daily_charts=not args.no_charts,
        )
        return 0
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
