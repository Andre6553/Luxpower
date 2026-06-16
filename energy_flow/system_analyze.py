"""Analyze PV strings vs SOC over a LuxPower history date range."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from statistics import median
from typing import Any

from history_loader import _integrate_power_kwh, load_day_chart, load_totals_daily_rows
from system_profile import facing_direction_label, load_system_profile

MAX_ANALYZE_DAYS = 365
TIE_KWH = 0.05
TILT_COMPARE_WINDOW_DAYS = 14
TILT_COMPARE_MIN_DAYS = 5
TILT_CHANGE_MIN_PCT = 3.0
YOY_MIN_DAYS = 3
YOY_CHANGE_MIN_PCT = 5.0


def _parse_date(text: str) -> date:
    return datetime.strptime(text.strip()[:10], "%Y-%m-%d").date()


def history_coverage() -> dict[str, Any]:
    """First/last dates that have daily chart files (via totals rows)."""
    try:
        rows = load_totals_daily_rows()
    except FileNotFoundError:
        rows = []
    if not rows:
        return {
            "hasHistory": False,
            "firstDate": None,
            "lastDate": None,
            "dateCount": 0,
            "message": "No LuxPower history on this PC. Use Sync on the Live tab to download history.",
        }
    dates = [row["date"] for row in rows]
    return {
        "hasHistory": True,
        "firstDate": dates[0],
        "lastDate": dates[-1],
        "dateCount": len(dates),
        "message": None,
    }


def _display_string_name(label: str, facing: str) -> str:
    facing_text = facing_direction_label(facing)
    if facing_text and facing_text != "Not set":
        return f"{label} ({facing_text})"
    return label


def _string_labels(profile: dict, count: int = 2) -> tuple[str, str]:
    sol = profile.get("solar") or {}
    strings = sol.get("strings") or []
    by_idx: dict[int, dict] = {}
    for s in strings:
        if not isinstance(s, dict):
            continue
        idx = int(s.get("stringIndex") or 0)
        if idx:
            by_idx[idx] = s

    def label_for(i: int, fallback: str) -> str:
        row = by_idx.get(i, {})
        text = str(row.get("label") or "").strip() or fallback
        facing = str(row.get("facingDirection") or "").strip()
        return _display_string_name(text, facing)

    n = _coerce_string_count(sol, count)
    return label_for(1, "PV1"), label_for(2, "PV2") if n >= 2 else ("PV1", "PV2")


def _coerce_string_count(sol: dict, default: int = 2) -> int:
    raw = sol.get("stringCount")
    try:
        n = int(raw) if raw not in (None, "") else default
    except (TypeError, ValueError):
        n = default
    return max(1, min(4, n))


def _hour_from_time(time_text: str) -> int:
    try:
        return int(time_text[11:13])
    except (ValueError, IndexError):
        return 0


def _minutes_from_midnight(time_text: str) -> int:
    try:
        dt = datetime.strptime(time_text, "%Y-%m-%d %H:%M:%S")
        return dt.hour * 60 + dt.minute
    except ValueError:
        return 0


def _format_minutes(mins: int) -> str:
    mins = max(0, min(24 * 60 - 1, int(mins)))
    return f"{mins // 60:02d}:{mins % 60:02d}"


def _shift_to_year(day: date, year: int) -> date | None:
    """Same month/day in another year (Feb 29 → Feb 28 on non-leap years)."""
    try:
        return day.replace(year=year)
    except ValueError:
        if day.month == 2 and day.day == 29:
            try:
                return date(year, 2, 28)
            except ValueError:
                return None
        return None


def _window_label(start: date, end: date) -> str:
    if start.year == end.year and start.month == end.month:
        return f"{start.strftime('%d %b')}–{end.strftime('%d %b %Y')}"
    if start.year == end.year:
        return f"{start.strftime('%d %b')}–{end.strftime('%d %b %Y')}"
    return f"{start.isoformat()} – {end.isoformat()}"


def _period_window_label(start: date, end: date) -> str:
    """Calendar window without year (for cross-year compare)."""
    if start.month == end.month:
        return f"{start.day}–{end.day} {start.strftime('%b')}"
    return f"{start.strftime('%d %b')}–{end.strftime('%d %b')}"


def _pct_change(selected: float, other: float) -> float | None:
    if selected <= 0:
        return None
    return round(100.0 * (other - selected) / selected, 1)


def _yoy_verdict(change_pct: float | None) -> str:
    if change_pct is None:
        return "unknown"
    if change_pct > YOY_CHANGE_MIN_PCT:
        return "higher"
    if change_pct < -YOY_CHANGE_MIN_PCT:
        return "lower"
    return "similar"


def _peak_point(points: list[dict]) -> dict | None:
    best: dict | None = None
    for pt in points:
        try:
            val = float(pt.get("value") or 0)
        except (TypeError, ValueError):
            continue
        if best is None or val > float(best.get("value") or 0):
            best = pt
    return best


def analyze_period(start: date, end: date) -> dict | None:
    """Run full period metrics for one inclusive date range. None if no chart days."""
    if end < start:
        start, end = end, start

    days_requested = (end - start).days + 1

    hourly_pv1 = [0.0] * 24
    hourly_pv2 = [0.0] * 24
    hourly_soc = [0.0] * 24
    hourly_pv1_n = [0] * 24
    hourly_pv2_n = [0] * 24
    hourly_soc_n = [0] * 24

    daily_rows: list[dict] = []
    missing_dates: list[str] = []
    peak_soc_minutes: list[int] = []
    peak_soc_values: list[float] = []
    soc_peak_hour_hist = [0] * 24

    pv1_total = 0.0
    pv2_total = 0.0
    pv1_wins = 0
    pv2_wins = 0
    tie_days = 0

    cur = start
    while cur <= end:
        date_text = cur.isoformat()
        try:
            chart = load_day_chart(date_text)
        except FileNotFoundError:
            missing_dates.append(date_text)
            cur += timedelta(days=1)
            continue

        series = chart.get("series") or {}
        ppv1_pts = (series.get("ppv1") or {}).get("points") or []
        ppv2_pts = (series.get("ppv2") or {}).get("points") or []
        soc_pts = (series.get("soc") or {}).get("points") or []

        pv1_kwh = round(_integrate_power_kwh(ppv1_pts), 2)
        pv2_kwh = round(_integrate_power_kwh(ppv2_pts), 2)
        pv1_total += pv1_kwh
        pv2_total += pv2_kwh

        if abs(pv1_kwh - pv2_kwh) <= TIE_KWH:
            winner = "tie"
            tie_days += 1
        elif pv1_kwh > pv2_kwh:
            winner = "pv1"
            pv1_wins += 1
        else:
            winner = "pv2"
            pv2_wins += 1

        soc_peak = _peak_point(soc_pts)
        soc_peak_time = soc_peak["time"] if soc_peak else None
        soc_peak_pct = round(float(soc_peak["value"]), 1) if soc_peak else None
        if soc_peak_time:
            peak_soc_minutes.append(_minutes_from_midnight(soc_peak_time))
            soc_peak_hour_hist[_hour_from_time(soc_peak_time)] += 1
        if soc_peak_pct is not None:
            peak_soc_values.append(soc_peak_pct)

        for pt in ppv1_pts:
            h = _hour_from_time(pt["time"])
            hourly_pv1[h] += float(pt.get("value") or 0)
            hourly_pv1_n[h] += 1
        for pt in ppv2_pts:
            h = _hour_from_time(pt["time"])
            hourly_pv2[h] += float(pt.get("value") or 0)
            hourly_pv2_n[h] += 1
        for pt in soc_pts:
            h = _hour_from_time(pt["time"])
            hourly_soc[h] += float(pt.get("value") or 0)
            hourly_soc_n[h] += 1

        daily_rows.append(
            {
                "date": date_text,
                "pv1Kwh": pv1_kwh,
                "pv2Kwh": pv2_kwh,
                "winner": winner,
                "socPeakTime": soc_peak_time[11:16] if soc_peak_time else None,
                "socPeakPct": soc_peak_pct,
            }
        )
        cur += timedelta(days=1)

    days_with_data = len(daily_rows)
    if days_with_data == 0:
        return None

    for h in range(24):
        if hourly_pv1_n[h] > 0:
            hourly_pv1[h] /= hourly_pv1_n[h]
        if hourly_pv2_n[h] > 0:
            hourly_pv2[h] /= hourly_pv2_n[h]
        if hourly_soc_n[h] > 0:
            hourly_soc[h] /= hourly_soc_n[h]

    combined = pv1_total + pv2_total
    pv1_share = round(100.0 * pv1_total / combined, 1) if combined > 0 else 0.0
    median_peak_soc_mins = int(median(peak_soc_minutes)) if peak_soc_minutes else None
    typical_soc_peak = _format_minutes(median_peak_soc_mins) if median_peak_soc_mins is not None else None
    avg_peak_soc = (
        round(sum(peak_soc_values) / len(peak_soc_values), 1) if peak_soc_values else None
    )

    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "daysRequested": days_requested,
        "daysWithData": days_with_data,
        "daysMissing": len(missing_dates),
        "missingSample": missing_dates[:8],
        "pv1TotalKwh": round(pv1_total, 1),
        "pv2TotalKwh": round(pv2_total, 1),
        "totalSolarKwh": round(combined, 1),
        "pv1SharePercent": pv1_share,
        "pv2SharePercent": round(100.0 - pv1_share, 1) if combined > 0 else 0.0,
        "pv1WinsDays": pv1_wins,
        "pv2WinsDays": pv2_wins,
        "tieDays": tie_days,
        "avgDailyPv1Kwh": round(pv1_total / days_with_data, 2),
        "avgDailyPv2Kwh": round(pv2_total / days_with_data, 2),
        "avgDailyTotalKwh": round(combined / days_with_data, 2),
        "typicalSocPeakTime": typical_soc_peak,
        "avgDailySocPeakPct": avg_peak_soc,
        "medianSocPeakPct": round(median(peak_soc_values), 1) if peak_soc_values else None,
        "daily": daily_rows,
        "hourlyProfile": {
            "hours": list(range(24)),
            "labels": [f"{h:02d}:00" for h in range(24)],
            "pv1AvgW": [round(v, 0) for v in hourly_pv1],
            "pv2AvgW": [round(v, 0) for v in hourly_pv2],
            "socAvgPct": [round(v, 1) for v in hourly_soc],
        },
        "socPeakHourHistogram": {
            "hours": list(range(24)),
            "labels": [f"{h:02d}:00" for h in range(24)],
            "counts": soc_peak_hour_hist,
        },
    }


def _period_summary_row(year: int, period: dict, *, is_selected: bool, selected: dict | None) -> dict:
    row: dict[str, Any] = {
        "year": year,
        "isSelected": is_selected,
        "rangeLabel": f"{period['start']} → {period['end']}",
        "start": period["start"],
        "end": period["end"],
        "daysWithData": period["daysWithData"],
        "daysRequested": period["daysRequested"],
        "pv1TotalKwh": period["pv1TotalKwh"],
        "pv2TotalKwh": period["pv2TotalKwh"],
        "totalSolarKwh": period["totalSolarKwh"],
        "avgDailyTotalKwh": period["avgDailyTotalKwh"],
        "avgDailyPv1Kwh": period["avgDailyPv1Kwh"],
        "avgDailyPv2Kwh": period["avgDailyPv2Kwh"],
        "pv1SharePercent": period["pv1SharePercent"],
        "typicalSocPeakTime": period["typicalSocPeakTime"],
        "avgDailySocPeakPct": period["avgDailySocPeakPct"],
        "vsSelected": None,
    }
    if not is_selected and selected:
        pv1_chg = _pct_change(selected["pv1TotalKwh"], period["pv1TotalKwh"])
        pv2_chg = _pct_change(selected["pv2TotalKwh"], period["pv2TotalKwh"])
        total_chg = _pct_change(selected["totalSolarKwh"], period["totalSolarKwh"])
        avg_chg = _pct_change(selected["avgDailyTotalKwh"], period["avgDailyTotalKwh"])
        row["vsSelected"] = {
            "pv1TotalPct": pv1_chg,
            "pv2TotalPct": pv2_chg,
            "totalSolarPct": total_chg,
            "avgDailyTotalPct": avg_chg,
            "verdict": _yoy_verdict(total_chg),
        }
    return row


def analyze_year_comparison(
    start: date,
    end: date,
    selected_period: dict,
    coverage: dict,
) -> dict[str, Any]:
    """Same calendar dates in other years when history exists."""
    selected_year = start.year
    calendar_window = _period_window_label(start, end)
    periods: list[dict] = [
        _period_summary_row(selected_year, selected_period, is_selected=True, selected=None)
    ]

    first_year = int((coverage.get("firstDate") or "2020")[:4])
    last_year = int((coverage.get("lastDate") or str(selected_year))[:4])

    for year in range(first_year, last_year + 1):
        if year == selected_year:
            continue
        y_start = _shift_to_year(start, year)
        y_end = _shift_to_year(end, year)
        if not y_start or not y_end or y_end < y_start:
            continue
        alt = analyze_period(y_start, y_end)
        if not alt or alt["daysWithData"] < YOY_MIN_DAYS:
            continue
        periods.append(
            _period_summary_row(year, alt, is_selected=False, selected=selected_period)
        )

    periods.sort(key=lambda row: row["year"], reverse=True)

    insights: list[str] = []
    sel_total = selected_period["totalSolarKwh"]
    for row in periods:
        if row["isSelected"]:
            continue
        vs = row.get("vsSelected") or {}
        total_pct = vs.get("totalSolarPct")
        if total_pct is None:
            continue
        y = row["year"]
        other_total = row["totalSolarKwh"]
        days_note = f"{row['daysWithData']}/{row['daysRequested']} days"
        if vs.get("verdict") == "higher":
            insights.append(
                f"{calendar_window} {y}: {abs(total_pct):.1f}% more solar than {selected_year} "
                f"({other_total} vs {sel_total} kWh, {days_note})."
            )
        elif vs.get("verdict") == "lower":
            insights.append(
                f"{calendar_window} {y}: {abs(total_pct):.1f}% less solar than {selected_year} "
                f"({other_total} vs {sel_total} kWh, {days_note})."
            )
        else:
            insights.append(
                f"{calendar_window} {y}: similar solar to {selected_year} "
                f"({other_total} vs {sel_total} kWh, {days_note})."
            )

    if len(periods) <= 1:
        insights.append(
            f"No other years with enough history for {calendar_window} "
            f"(need at least {YOY_MIN_DAYS} days per year). Sync more past years to compare."
        )

    return {
        "calendarWindow": calendar_window,
        "selectedYear": selected_year,
        "otherYearsFound": len(periods) - 1,
        "periods": periods,
        "insights": insights,
    }


def analyze_system_range(start_text: str, end_text: str, profile: dict | None = None) -> dict:
    profile = profile or load_system_profile()
    start = _parse_date(start_text)
    end = _parse_date(end_text)
    if end < start:
        start, end = end, start

    days_requested = (end - start).days + 1
    if days_requested > MAX_ANALYZE_DAYS:
        raise ValueError(f"Date range too long (max {MAX_ANALYZE_DAYS} days).")

    label1, label2 = _string_labels(profile)
    coverage = history_coverage()

    selected_period = analyze_period(start, end)
    if not selected_period:
        return {
            "ok": False,
            "error": (
                "No chart data for this date range. "
                "Sync LuxPower history on the Live tab, then try again."
            ),
            "coverage": coverage,
            "range": {
                "start": start.isoformat(),
                "end": end.isoformat(),
                "daysRequested": days_requested,
                "daysWithData": 0,
                "daysMissing": 0,
                "missingSample": [],
            },
        }

    year_comparison = analyze_year_comparison(start, end, selected_period, coverage)
    strings_meta = _strings_facing_meta(profile)
    tilt_analysis = analyze_tilt_changes(profile)
    insights = _build_insights(
        label1=label1,
        label2=label2,
        pv1_total=selected_period["pv1TotalKwh"],
        pv2_total=selected_period["pv2TotalKwh"],
        pv1_share=selected_period["pv1SharePercent"],
        pv1_wins=selected_period["pv1WinsDays"],
        pv2_wins=selected_period["pv2WinsDays"],
        tie_days=selected_period["tieDays"],
        days_with_data=selected_period["daysWithData"],
        typical_soc_peak=selected_period["typicalSocPeakTime"],
        avg_peak_soc=selected_period["avgDailySocPeakPct"],
        strings_meta=strings_meta,
        tilt_analysis=tilt_analysis,
        year_comparison=year_comparison,
    )

    return {
        "ok": True,
        "labels": {"pv1": label1, "pv2": label2},
        "strings": strings_meta,
        "coverage": coverage,
        "range": {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "daysRequested": days_requested,
            "daysWithData": selected_period["daysWithData"],
            "daysMissing": selected_period["daysMissing"],
            "missingSample": selected_period["missingSample"],
        },
        "summary": {
            "pv1TotalKwh": selected_period["pv1TotalKwh"],
            "pv2TotalKwh": selected_period["pv2TotalKwh"],
            "totalSolarKwh": selected_period["totalSolarKwh"],
            "pv1SharePercent": selected_period["pv1SharePercent"],
            "pv2SharePercent": selected_period["pv2SharePercent"],
            "pv1WinsDays": selected_period["pv1WinsDays"],
            "pv2WinsDays": selected_period["pv2WinsDays"],
            "tieDays": selected_period["tieDays"],
            "typicalSocPeakTime": selected_period["typicalSocPeakTime"],
            "avgDailySocPeakPct": selected_period["avgDailySocPeakPct"],
            "medianSocPeakPct": selected_period["medianSocPeakPct"],
            "avgDailyTotalKwh": selected_period["avgDailyTotalKwh"],
        },
        "insights": insights,
        "hourlyProfile": selected_period["hourlyProfile"],
        "daily": selected_period["daily"],
        "socPeakHourHistogram": selected_period["socPeakHourHistogram"],
        "tiltAnalysis": tilt_analysis,
        "yearComparison": year_comparison,
    }


def _load_string_daily_kwh(string_index: int, start: date, end: date) -> dict[str, float]:
    """Load per-day kWh for one MPPT from saved charts (may extend outside analyze range)."""
    if string_index not in (1, 2):
        return {}
    series_key = "ppv1" if string_index == 1 else "ppv2"
    out: dict[str, float] = {}
    cur = start
    while cur <= end:
        date_text = cur.isoformat()
        try:
            chart = load_day_chart(date_text)
            pts = (chart.get("series") or {}).get(series_key, {}).get("points") or []
            out[date_text] = round(_integrate_power_kwh(pts), 2)
        except FileNotFoundError:
            pass
        cur += timedelta(days=1)
    return out


def _avg_kwh(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 2)


def analyze_tilt_changes(profile: dict) -> list[dict]:
    """Before/after daily kWh around each recorded tilt change."""
    log = (profile.get("solar") or {}).get("tiltChangeLog") or []
    if not log:
        return []

    strings_by_idx = {
        int(s.get("stringIndex") or 0): s
        for s in (profile.get("solar") or {}).get("strings") or []
        if isinstance(s, dict)
    }
    results: list[dict] = []

    for entry in log:
        idx = int(entry.get("stringIndex") or 0)
        if idx not in (1, 2):
            continue
        eff_text = entry.get("effectiveDate")
        if not eff_text:
            continue
        try:
            eff = _parse_date(eff_text)
        except ValueError:
            continue

        meta = strings_by_idx.get(idx, {})
        label = _display_string_name(
            str(meta.get("label") or "").strip() or f"PV{idx}",
            str(meta.get("facingDirection") or "").strip(),
        )
        prev_tilt = entry.get("previousTiltDegrees")
        new_tilt = entry.get("newTiltDegrees")

        before_start = eff - timedelta(days=TILT_COMPARE_WINDOW_DAYS)
        before_end = eff - timedelta(days=1)
        after_start = eff
        after_end = eff + timedelta(days=TILT_COMPARE_WINDOW_DAYS - 1)

        daily = _load_string_daily_kwh(idx, before_start, after_end)
        before_vals = [
            daily[d]
            for d in sorted(daily.keys())
            if before_start.isoformat() <= d <= before_end.isoformat()
        ]
        after_vals = [
            daily[d]
            for d in sorted(daily.keys())
            if after_start.isoformat() <= d <= after_end.isoformat()
        ]

        before_avg = _avg_kwh(before_vals)
        after_avg = _avg_kwh(after_vals)
        before_days = len(before_vals)
        after_days = len(after_vals)

        row: dict[str, Any] = {
            "stringIndex": idx,
            "label": label,
            "effectiveDate": eff_text,
            "previousTiltDegrees": prev_tilt,
            "newTiltDegrees": new_tilt,
            "compareDaysEachSide": TILT_COMPARE_WINDOW_DAYS,
            "beforeDays": before_days,
            "afterDays": after_days,
            "beforeAvgKwhPerDay": before_avg,
            "afterAvgKwhPerDay": after_avg,
            "changePercent": None,
            "verdict": "insufficient_data",
            "summary": "",
        }

        if before_days < TILT_COMPARE_MIN_DAYS or after_days < TILT_COMPARE_MIN_DAYS:
            row["summary"] = (
                f"Need at least {TILT_COMPARE_MIN_DAYS} days of history before and after "
                f"{eff_text} (have {before_days} before, {after_days} after). Sync more history."
            )
            results.append(row)
            continue

        if before_avg is None or after_avg is None or before_avg <= 0:
            row["summary"] = "Not enough production before the change to compare."
            results.append(row)
            continue

        change_pct = round(100.0 * (after_avg - before_avg) / before_avg, 1)
        row["changePercent"] = change_pct

        prev_s = "?" if prev_tilt is None else f"{prev_tilt:g}"
        new_s = f"{new_tilt:g}" if new_tilt is not None else "?"
        if change_pct > TILT_CHANGE_MIN_PCT:
            row["verdict"] = "better"
            row["summary"] = (
                f"After changing tilt from {prev_s}° to {new_s}° on {eff_text}, "
                f"average daily output rose {change_pct}% "
                f"({before_avg} → {after_avg} kWh/day, ±{TILT_COMPARE_WINDOW_DAYS}d windows)."
            )
        elif change_pct < -TILT_CHANGE_MIN_PCT:
            row["verdict"] = "worse"
            row["summary"] = (
                f"After changing tilt from {prev_s}° to {new_s}° on {eff_text}, "
                f"average daily output fell {abs(change_pct)}% "
                f"({before_avg} → {after_avg} kWh/day, ±{TILT_COMPARE_WINDOW_DAYS}d windows)."
            )
        else:
            row["verdict"] = "similar"
            row["summary"] = (
                f"Tilt change {prev_s}° → {new_s}° on {eff_text}: production similar "
                f"({before_avg} vs {after_avg} kWh/day avg, within {TILT_CHANGE_MIN_PCT}%)."
            )
        results.append(row)

    return results


def _strings_facing_meta(profile: dict) -> list[dict]:
    sol = profile.get("solar") or {}
    out: list[dict] = []
    for s in sol.get("strings") or []:
        if not isinstance(s, dict):
            continue
        idx = int(s.get("stringIndex") or 0)
        if not idx:
            continue
        facing = str(s.get("facingDirection") or "").strip()
        label = str(s.get("label") or "").strip() or f"PV{idx}"
        tilt = s.get("tiltDegrees")
        out.append(
            {
                "stringIndex": idx,
                "label": label,
                "facingDirection": facing,
                "facingLabel": facing_direction_label(facing),
                "tiltDegrees": tilt,
            }
        )
    return sorted(out, key=lambda x: x["stringIndex"])


def _build_insights(
    *,
    label1: str,
    label2: str,
    pv1_total: float,
    pv2_total: float,
    pv1_share: float,
    pv1_wins: int,
    pv2_wins: int,
    tie_days: int,
    days_with_data: int,
    typical_soc_peak: str | None,
    avg_peak_soc: float | None,
    strings_meta: list[dict] | None = None,
    tilt_analysis: list[dict] | None = None,
    year_comparison: dict | None = None,
) -> list[str]:
    lines: list[str] = []
    meta = strings_meta or []
    yoy = year_comparison or {}
    if yoy.get("otherYearsFound", 0) > 0:
        lines.append(
            f"Same calendar window ({yoy.get('calendarWindow', '')}) compared across "
            f"{yoy['otherYearsFound'] + 1} year(s) — see table below."
        )
        lines.extend(yoy.get("insights") or [])
    elif yoy.get("insights"):
        lines.extend(yoy.get("insights"))
    for row in tilt_analysis or []:
        if row.get("summary") and row.get("verdict") != "insufficient_data":
            lines.append(row["summary"])
        elif row.get("summary"):
            lines.append(row["summary"])
    facing_bits = [
        f"{m['label']} → {m['facingLabel']}"
        for m in meta
        if m.get("facingDirection") and m.get("facingLabel") != "Not set"
    ]
    if facing_bits:
        lines.append(f"Panel directions: {', '.join(facing_bits)}.")

    diff = abs(pv1_total - pv2_total)
    if pv1_total > pv2_total + TIE_KWH:
        pct = round(100.0 * diff / max(pv2_total, 0.01), 0)
        lines.append(f"{label1} produced {diff:.1f} kWh more than {label2} ({pct}% more energy).")
    elif pv2_total > pv1_total + TIE_KWH:
        pct = round(100.0 * diff / max(pv1_total, 0.01), 0)
        lines.append(f"{label2} produced {diff:.1f} kWh more than {label1} ({pct}% more energy).")
    else:
        lines.append(f"{label1} and {label2} produced similar total energy over this period.")

    lines.append(
        f"{label1} led on {pv1_wins} day(s), {label2} on {pv2_wins}, tied on {tie_days} "
        f"(of {days_with_data} days with data)."
    )

    if typical_soc_peak:
        lines.append(
            f"Battery SOC usually peaks around {typical_soc_peak} "
            f"(median time of daily maximum)."
        )
    if avg_peak_soc is not None:
        lines.append(f"Average daily peak SOC was {avg_peak_soc}%.")

    return lines
