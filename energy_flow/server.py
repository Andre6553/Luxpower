"""Local energy-flow dashboard server (live Modbus + static HTML + history API)."""
from __future__ import annotations

import json
import sys
import threading
import webbrowser
from datetime import date, datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import requests

ROOT_PARENT = Path(__file__).resolve().parent.parent
if str(ROOT_PARENT) not in sys.path:
    sys.path.insert(0, str(ROOT_PARENT))

from luxpower_fetch_backfill import fetch_backfill  # noqa: E402
from luxpower_fetch_month import DATA_ROOT, fetch_month  # noqa: E402

from history_loader import (
    DEFAULT_YEAR,
    INVERTER_SN,
    load_day_chart,
    load_month_year_compare_payload,
    load_totals_payload,
    load_year_bootstrap,
    load_year_daily,
    load_year_events,
    monthly_summary,
)
from live_buffer import append_snapshot, today_chart_payload
from luxpower_energy_overview import fetch_month_overview, fetch_total_overview, fetch_year_overview
from luxpower_forecast import fetch_solar_forecast_payload
from luxpower_remote_settings import (
    apply_setting_action,
    apply_setting_write,
    read_all_parameters,
    settings_schema_payload,
)
from chart_smooth import reset_chart_filters
from modbus_client import fetch_live_snapshot, load_config
from system_analyze import analyze_system_range, history_coverage
from system_profile import load_system_profile, profile_payload, save_system_profile

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
STATIC = ROOT / "static"
PORT = 8765
BACKFILL_MIN_YEAR = 2020

_sync_lock = threading.RLock()
_sync_state: dict = {
    "running": False,
    "syncMode": None,
    "year": None,
    "month": None,
    "startedAt": None,
    "finishedAt": None,
    "ok": None,
    "error": None,
    "cloudOffline": False,
    "monthDir": None,
    "phase": None,
    "progressCurrent": 0,
    "progressTotal": 0,
    "progressMessage": "",
    "progressPercent": 0,
    "fetchedAtUtc": None,
    "backfillIndex": 0,
    "backfillTotal": 0,
    "savedMonths": 0,
    "skippedMonths": 0,
}

_SYNC_PHASE_RANGE = {
    "login": (0, 8),
    "daily_totals": (8, 22),
    "events": (22, 26),
    "charts": (26, 92),
    "overview": (92, 98),
    "backfill": (0, 98),
    "done": (100, 100),
}


def _is_cloud_offline(exc: Exception) -> bool:
    if isinstance(exc, (requests.ConnectionError, requests.Timeout)):
        return True
    msg = str(exc).lower()
    return any(
        token in msg
        for token in (
            "connection",
            "network",
            "unreachable",
            "failed to establish",
            "getaddrinfo",
            "timed out",
            "name resolution",
            "max retries exceeded",
        )
    )


def _format_sync_error(exc: Exception) -> str:
    if isinstance(exc, requests.ConnectionError):
        return "LuxPower cloud is offline or unreachable. Check your internet connection and try again."
    if isinstance(exc, requests.Timeout):
        return "LuxPower cloud timed out. The service may be offline or slow — try again later."
    if _is_cloud_offline(exc):
        return f"LuxPower cloud appears offline: {exc}"
    return str(exc).strip() or exc.__class__.__name__


def _make_month_progress_callback(month_index: int, month_total: int, label: str):
    def callback(phase: str, current: int, total: int, message: str) -> None:
        lo, hi = _SYNC_PHASE_RANGE.get(phase, (0, 100))
        if phase == "done":
            inner = 100.0
        elif total <= 0:
            inner = float(lo)
        else:
            inner = lo + (hi - lo) * (current / total)
        slice_lo = (month_index - 1) / max(month_total, 1) * 98.0
        slice_hi = month_index / max(month_total, 1) * 98.0
        percent = int(slice_lo + (slice_hi - slice_lo) * (inner / 100.0))
        with _sync_lock:
            _sync_state.update(
                {
                    "phase": phase,
                    "progressCurrent": month_index,
                    "progressTotal": month_total,
                    "progressMessage": f"{label}: {message}",
                    "progressPercent": max(0, min(98, percent)),
                }
            )

    return callback


def _backfill_month_hook(month_index: int, month_total: int, year: int, month: int, event: str):
    label = f"{year:04d}-{month:02d}"
    with _sync_lock:
        _sync_state.update(
            {
                "year": year,
                "month": month,
                "backfillIndex": month_index,
                "backfillTotal": month_total,
                "syncMode": "all",
            }
        )
    if event == "skip":
        percent = int(month_index / max(month_total, 1) * 98)
        with _sync_lock:
            _sync_state.update(
                {
                    "progressPercent": percent,
                    "progressMessage": f"Month {month_index}/{month_total} — skipped {label} (already complete)",
                }
            )
        return None
    return _make_month_progress_callback(month_index, month_total, label)


def _sync_progress(phase: str, current: int, total: int, message: str) -> None:
    lo, hi = _SYNC_PHASE_RANGE.get(phase, (0, 100))
    if phase == "done":
        percent = 100
    elif total <= 0:
        percent = lo
    else:
        percent = int(lo + (hi - lo) * (current / total))
    percent = max(0, min(100, percent))
    with _sync_lock:
        _sync_state.update(
            {
                "phase": phase,
                "progressCurrent": current,
                "progressTotal": total,
                "progressMessage": message,
                "progressPercent": percent,
            }
        )


def _last_fetched_at_utc(year: int, month: int) -> str | None:
    manifest_path = DATA_ROOT / f"{year:04d}-{month:02d}" / "manifest.json"
    if not manifest_path.exists():
        return None
    try:
        return json.loads(manifest_path.read_text(encoding="utf-8")).get("fetchedAtUtc")
    except (json.JSONDecodeError, OSError):
        return None


def _sync_status_payload() -> dict:
    today = date.today()
    with _sync_lock:
        payload = {**_sync_state}
    if payload.get("running"):
        payload["ok"] = True
    elif payload.get("ok") is None:
        payload["ok"] = True
    if not payload.get("running"):
        last = payload.get("fetchedAtUtc") or _last_fetched_at_utc(today.year, today.month)
        if last:
            payload["lastFetchedAtUtc"] = last
    return payload


def _run_cloud_sync(year: int, month: int) -> None:
    global _sync_state
    try:
        _sync_progress("login", 0, 1, "Starting cloud sync…")
        month_dir = fetch_month(
            year,
            month,
            with_daily_charts=True,
            on_progress=_sync_progress,
        )
        from luxpower_energy_overview import fetch_month_overview

        _sync_progress("overview", 1, 1, "Updating energy overview…")
        fetch_month_overview(year, month, use_cache=False)
        chart_cache = DATA_ROOT / "_cache" / "chart_solar_kwh.json"
        if chart_cache.exists():
            chart_cache.unlink()
        manifest_path = month_dir / "manifest.json"
        fetched_at = None
        if manifest_path.exists():
            fetched_at = json.loads(manifest_path.read_text(encoding="utf-8")).get("fetchedAtUtc")
        _sync_progress("done", 1, 1, "Sync complete")
        with _sync_lock:
            _sync_state.update(
                {
                    "running": False,
                    "ok": True,
                    "error": None,
                    "cloudOffline": False,
                    "syncMode": "month",
                    "finishedAt": datetime.now(timezone.utc).isoformat(),
                    "monthDir": str(month_dir),
                    "fetchedAtUtc": fetched_at,
                }
            )
    except Exception as exc:
        err = _format_sync_error(exc)
        with _sync_lock:
            _sync_state.update(
                {
                    "running": False,
                    "ok": False,
                    "error": err,
                    "cloudOffline": _is_cloud_offline(exc),
                    "finishedAt": datetime.now(timezone.utc).isoformat(),
                    "progressMessage": err,
                }
            )


def _run_cloud_sync_all(*, min_year: int = BACKFILL_MIN_YEAR) -> None:
    global _sync_state
    try:
        today = date.today()
        _sync_progress("login", 0, 1, "Starting full history sync from LuxPower cloud…")
        chart_cache = DATA_ROOT / "_cache" / "chart_solar_kwh.json"
        result = fetch_backfill(
            start_year=today.year,
            start_month=today.month,
            min_year=min_year,
            skip_complete=True,
            with_daily_charts=True,
            on_month=_backfill_month_hook,
            fail_fast=True,
        )
        if chart_cache.exists():
            chart_cache.unlink()
        saved = int(result.get("saved") or 0)
        skipped = int(result.get("skipped") or 0)
        summary = f"Full sync complete — downloaded {saved} month(s), skipped {skipped} already complete."
        if result.get("stoppedEarly"):
            summary += " Stopped early (no data on older months)."
        _sync_progress("done", 1, 1, summary)
        with _sync_lock:
            _sync_state.update(
                {
                    "running": False,
                    "ok": True,
                    "error": None,
                    "cloudOffline": False,
                    "syncMode": "all",
                    "finishedAt": datetime.now(timezone.utc).isoformat(),
                    "savedMonths": saved,
                    "skippedMonths": skipped,
                    "progressMessage": summary,
                    "fetchedAtUtc": _last_fetched_at_utc(today.year, today.month),
                }
            )
    except Exception as exc:
        err = _format_sync_error(exc)
        with _sync_lock:
            _sync_state.update(
                {
                    "running": False,
                    "ok": False,
                    "error": err,
                    "cloudOffline": _is_cloud_offline(exc),
                    "finishedAt": datetime.now(timezone.utc).isoformat(),
                    "progressMessage": err,
                }
            )


def _sync_start_response(*, status: str, mode: str | None = None) -> dict:
    with _sync_lock:
        payload = {**_sync_state, "status": status, "ok": True}
    if mode is not None:
        payload["syncMode"] = mode
    return payload


def _start_cloud_sync(*, mode: str, year: int, month: int, min_year: int = BACKFILL_MIN_YEAR) -> dict:
    with _sync_lock:
        if _sync_state.get("running"):
            return _sync_start_response(status="running")
        _sync_state.update(
            {
                "running": True,
                "syncMode": mode,
                "year": year,
                "month": month,
                "startedAt": datetime.now(timezone.utc).isoformat(),
                "finishedAt": None,
                "ok": None,
                "error": None,
                "cloudOffline": False,
                "monthDir": None,
                "phase": "login",
                "progressCurrent": 0,
                "progressTotal": 1,
                "progressMessage": "Starting cloud sync…",
                "progressPercent": 0,
                "fetchedAtUtc": None,
                "backfillIndex": 0,
                "backfillTotal": 0,
                "savedMonths": 0,
                "skippedMonths": 0,
            }
        )
    if mode == "all":
        target = _run_cloud_sync_all
        args: tuple = ()
        kwargs = {"min_year": min_year}
    else:
        target = _run_cloud_sync
        args = (year, month)
        kwargs = {}
    thread = threading.Thread(target=target, args=args, kwargs=kwargs, daemon=True)
    thread.start()
    return _sync_start_response(status="started", mode=mode)


def _start_cloud_sync_month(year: int, month: int) -> dict:
    return _start_cloud_sync(mode="month", year=year, month=month)


class DashboardHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC), **kwargs)

    def log_message(self, fmt: str, *args) -> None:
        path = str(args[0]) if args else ""
        if "/api/live" in path or "/api/history/" in path:
            return
        super().log_message(fmt, *args)

    def _read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON body: {exc}") from exc
        if not isinstance(data, dict):
            raise ValueError("JSON body must be an object")
        return data

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/settings/action":
            try:
                body = self._read_json_body()
            except ValueError as exc:
                self._json_response({"ok": False, "error": str(exc)}, 400)
                return
            if not body.get("confirm"):
                self._json_response(
                    {"ok": False, "error": "Set confirm=true to run this action."},
                    400,
                )
                return
            action = (body.get("action") or "").strip()
            inverter_sn = (body.get("inverterSn") or INVERTER_SN).strip()
            if not action:
                self._json_response({"ok": False, "error": "action is required"}, 400)
                return
            try:
                result = apply_setting_action(inverter_sn, action)
                payload = {"ok": True, "inverterSn": inverter_sn, "action": action, **result}
            except Exception as exc:
                payload = {"ok": False, "error": _format_sync_error(exc)}
            self._json_response(payload)
            return

        if parsed.path == "/api/settings/write":
            try:
                body = self._read_json_body()
            except ValueError as exc:
                self._json_response({"ok": False, "error": str(exc)}, 400)
                return
            if not body.get("confirm"):
                self._json_response(
                    {
                        "ok": False,
                        "error": "Set confirm=true to write settings to the inverter.",
                    },
                    400,
                )
                return
            write_type = (body.get("type") or "").strip().lower()
            param = (body.get("param") or "").strip()
            value = body.get("value")
            inverter_sn = (body.get("inverterSn") or INVERTER_SN).strip()
            if not write_type or not param:
                self._json_response({"ok": False, "error": "type and param are required"}, 400)
                return
            try:
                result = apply_setting_write(
                    inverter_sn,
                    write_type=write_type,
                    param=param,
                    value=value,
                )
                payload = {
                    "ok": True,
                    "inverterSn": inverter_sn,
                    "type": write_type,
                    "param": param,
                    "value": value,
                    **result,
                }
            except Exception as exc:
                payload = {"ok": False, "error": _format_sync_error(exc)}
            self._json_response(payload)
            return

        if parsed.path == "/api/system/profile":
            try:
                body = self._read_json_body()
            except ValueError as exc:
                self._json_response({"ok": False, "error": str(exc)}, 400)
                return
            try:
                profile = save_system_profile(body)
                self._json_response({"ok": True, "profile": profile})
            except Exception as exc:
                self._json_response({"ok": False, "error": _format_sync_error(exc)}, 400)
            return

        if parsed.path == "/api/history/sync":
            qs = parse_qs(parsed.query)
            today = date.today()
            year = self._int_query(qs, "year", today.year) or today.year
            month = self._int_query(qs, "month", today.month) or today.month
            mode = (qs.get("mode") or ["month"])[0].lower()
            min_year = self._int_query(qs, "minYear", BACKFILL_MIN_YEAR) or BACKFILL_MIN_YEAR
            if month < 1 or month > 12:
                self._json_response({"ok": False, "error": "month must be 1-12"}, 400)
                return
            if mode not in ("month", "all"):
                self._json_response({"ok": False, "error": "mode must be month or all"}, 400)
                return
            try:
                payload = _start_cloud_sync(mode=mode, year=year, month=month, min_year=min_year)
            except Exception as exc:
                payload = {"ok": False, "error": _format_sync_error(exc)}
            self._json_response(payload)
            return
        self.send_error(404)

    def _json_response(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)

        if path == "/favicon.ico":
            icon = STATIC / "favicon.svg"
            if icon.exists():
                body = icon.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "image/svg+xml")
                self.send_header("Cache-Control", "public, max-age=86400")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_response(204)
                self.end_headers()
            return

        if path == "/api/history/sync":
            self._json_response(_sync_status_payload())
            return

        if path == "/api/live":
            try:
                payload = fetch_live_snapshot()
                payload["ok"] = True
                payload["source"] = "dongle"
                append_snapshot(payload)
            except Exception as exc:
                payload = {"ok": False, "error": str(exc)}
            self._json_response(payload)
            return

        if path == "/api/live/today":
            try:
                cfg = load_config()
                payload = today_chart_payload(cfg.station_name, cfg.inverter_sn)
            except Exception as exc:
                payload = {"ok": False, "error": str(exc)}
            self._json_response(payload)
            return

        if path == "/api/charts/panels":
            from chart_panels import SA_CHART_PANELS

            self._json_response({"ok": True, "panels": SA_CHART_PANELS})
            return

        if path == "/api/system/profile":
            self._json_response(profile_payload())
            return

        if path == "/api/system/analyze":
            start = (qs.get("start") or [""])[0].strip()
            end = (qs.get("end") or [""])[0].strip()
            if not start or not end:
                self._json_response({"ok": True, "coverage": history_coverage()})
                return
            try:
                profile = load_system_profile()
                payload = analyze_system_range(start, end, profile)
            except ValueError as exc:
                self._json_response({"ok": False, "error": str(exc)}, 400)
                return
            except Exception as exc:
                self._json_response({"ok": False, "error": str(exc)}, 500)
                return
            status = 200 if payload.get("ok") else 404
            self._json_response(payload, status)
            return

        if path == "/api/settings/schema":
            try:
                self._json_response(settings_schema_payload())
            except Exception as exc:
                self._json_response({"ok": False, "error": _format_sync_error(exc)}, 502)
            return

        if path == "/api/settings/read":
            sn = (qs.get("inverterSn") or [INVERTER_SN])[0].strip() or INVERTER_SN
            try:
                self._json_response(read_all_parameters(sn))
            except Exception as exc:
                self._json_response({"ok": False, "error": _format_sync_error(exc)}, 502)
            return

        if path == "/api/luxpower/forecast":
            try:
                payload = fetch_solar_forecast_payload()
            except Exception as exc:
                payload = {"ok": False, "error": str(exc)}
            self._json_response(payload)
            return

        if path == "/api/history/bootstrap":
            year = self._history_year(qs)
            try:
                self._json_response(load_year_bootstrap(year))
            except Exception as exc:
                self._json_response({"ok": False, "error": str(exc)}, 404)
            return

        if path == "/api/history/meta":
            year = self._history_year(qs)
            try:
                boot = load_year_bootstrap(year)
                self._json_response(
                    {
                        "ok": True,
                        "inverterSerial": boot["inverterSerial"],
                        "station": boot["station"],
                        "year": boot["year"],
                        "months": boot["months"],
                        "monthRange": boot["monthRange"],
                        "dates": boot["dates"],
                        "summary": boot["summary"],
                    }
                )
            except Exception as exc:
                self._json_response({"ok": False, "error": str(exc)}, 404)
            return

        if path == "/api/history/monthly":
            year = self._history_year(qs)
            try:
                daily = load_year_daily(year)
                self._json_response(
                    {
                        "ok": True,
                        "inverterSerial": INVERTER_SN,
                        "year": year,
                        "daily": daily,
                        "summary": monthly_summary(daily),
                    }
                )
            except Exception as exc:
                self._json_response({"ok": False, "error": str(exc)}, 404)
            return

        if path == "/api/history/totals":
            daily_offset = self._int_query(qs, "dailyOffset", 0)
            monthly_offset = self._int_query(qs, "monthlyOffset", 0)
            daily_end = (qs.get("dailyEnd") or [""])[0].strip() or None
            monthly_end = (qs.get("monthlyEnd") or [""])[0].strip() or None
            try:
                payload = load_totals_payload(
                    daily_offset=daily_offset,
                    monthly_offset=monthly_offset,
                    daily_end=daily_end,
                    monthly_end=monthly_end,
                )
            except Exception as exc:
                payload = {"ok": False, "error": str(exc)}
            self._json_response(payload)
            return

        if path == "/api/history/totals/compare":
            month_key = (qs.get("monthKey") or [""])[0].strip()
            if not month_key or len(month_key) < 7:
                self._json_response({"ok": False, "error": "monthKey query required (YYYY-MM)"}, 400)
                return
            try:
                year_s, month_s = month_key.split("-", 1)
                payload = load_month_year_compare_payload(
                    month=int(month_s),
                    through_year=int(year_s),
                )
            except Exception as exc:
                payload = {"ok": False, "error": str(exc)}
            self._json_response(payload)
            return

        if path == "/api/history/energy-overview":
            year = self._history_year(qs)
            mode = (qs.get("mode") or ["month"])[0].lower()
            try:
                if mode == "total":
                    payload = fetch_total_overview()
                elif mode == "year":
                    payload = fetch_year_overview(year)
                else:
                    month_raw = (qs.get("month") or [""])[0]
                    if not month_raw:
                        self._json_response({"ok": False, "error": "month query required (1-12)"}, 400)
                        return
                    month = int(month_raw)
                    if month < 1 or month > 12:
                        raise ValueError("month must be 1-12")
                    payload = fetch_month_overview(year, month)
            except Exception as exc:
                payload = {"ok": False, "error": str(exc)}
            self._json_response(payload)
            return

        if path == "/api/history/day":
            date = (qs.get("date") or [""])[0]
            if not date:
                self._json_response({"ok": False, "error": "date query required"}, 400)
                return
            try:
                chart = load_day_chart(date)
                self._json_response(
                    {
                        "ok": True,
                        "source": "luxpower",
                        "inverterSerial": INVERTER_SN,
                        **chart,
                    }
                )
            except Exception as exc:
                self._json_response({"ok": False, "error": str(exc)}, 404)
            return

        if path == "/api/history/events":
            year = self._history_year(qs)
            try:
                events = load_year_events(year)
                self._json_response({"ok": True, "inverterSerial": INVERTER_SN, "year": year, "events": events})
            except Exception as exc:
                self._json_response({"ok": False, "error": str(exc)}, 404)
            return

        if path in ("/", ""):
            self._serve_index()
            return
        if path.startswith("/api/"):
            self._json_response({"ok": False, "error": f"Unknown API: {path}"}, 404)
            return
        return super().do_GET()

    def _int_query(self, qs: dict, key: str, default: int = 0) -> int:
        raw = (qs.get(key) or [""])[0]
        if not raw:
            return default
        try:
            return max(0, int(raw))
        except ValueError:
            return default

    def _history_year(self, qs: dict) -> int:
        raw = (qs.get("year") or [""])[0]
        if not raw:
            return DEFAULT_YEAR
        try:
            return int(raw)
        except ValueError:
            return DEFAULT_YEAR

    def _history_bootstrap(self, year: int = DEFAULT_YEAR) -> dict:
        return load_year_bootstrap(year)

    def _serve_index(self) -> None:
        template = (STATIC / "index.html").read_text(encoding="utf-8")
        try:
            bootstrap = self._history_bootstrap()
        except Exception as exc:
            bootstrap = {"ok": False, "error": str(exc)}
        payload = json.dumps(bootstrap).replace("</", "<\\/")
        html = template.replace("/*__HISTORY_BOOTSTRAP__*/null", payload)
        html = html.replace("/*__HISTORY_YEAR__*/2026", str(DEFAULT_YEAR))
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    STATIC.mkdir(parents=True, exist_ok=True)
    reset_chart_filters()
    url = f"http://127.0.0.1:{PORT}/"
    print(f"Energy flow dashboard: {url}")
    print(f"Live dongle Modbus + LuxPower cloud history (inverter {INVERTER_SN})")
    print("Press Ctrl+C to stop")
    try:
        webbrowser.open(url)
    except Exception:
        pass
    server = ThreadingHTTPServer(("127.0.0.1", PORT), DashboardHandler)
    server.serve_forever()


if __name__ == "__main__":
    main()
