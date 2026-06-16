"""Persist user-entered inverter and solar panel details (My system tab)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROFILE_PATH = Path(__file__).resolve().parent / "data" / "system_profile.json"
MAX_STRINGS = 4
MAX_TILT_CHANGE_LOG = 40
TILT_COMPARE_EPSILON = 0.05

# Compass + flat roof; empty = user has not set yet
PANEL_FACING_OPTIONS: tuple[str, ...] = ("", "N", "NE", "E", "SE", "S", "SW", "W", "NW", "flat")

PANEL_FACING_LABELS: dict[str, str] = {
    "": "Not set",
    "N": "North",
    "NE": "North-east",
    "E": "East",
    "SE": "South-east",
    "S": "South",
    "SW": "South-west",
    "W": "West",
    "NW": "North-west",
    "flat": "Flat / no fixed tilt",
}

_FACING_ALIASES: dict[str, str] = {
    "NORTH": "N",
    "NORTHEAST": "NE",
    "NORTH-EAST": "NE",
    "EAST": "E",
    "SOUTHEAST": "SE",
    "SOUTH-EAST": "SE",
    "SOUTH": "S",
    "SOUTHWEST": "SW",
    "SOUTH-WEST": "SW",
    "WEST": "W",
    "NORTHWEST": "NW",
    "NORTH-WEST": "NW",
    "FLAT": "flat",
}


def _parse_facing_direction(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    upper = text.upper().replace("_", "-")
    if upper in _FACING_ALIASES:
        return _FACING_ALIASES[upper]
    code = upper if len(text) <= 3 else upper
    if code in PANEL_FACING_OPTIONS:
        return code
    return ""


def facing_direction_label(code: str) -> str:
    return PANEL_FACING_LABELS.get(code or "", PANEL_FACING_LABELS[""])


def _parse_tilt_degrees(value: Any) -> float | None:
    f = _coerce_float(value)
    if f is None:
        return None
    return round(max(0.0, min(90.0, f)), 1)


def _parse_effective_date(value: Any) -> str | None:
    text = str(value or "").strip()[:10]
    if not text:
        return None
    try:
        datetime.strptime(text, "%Y-%m-%d")
        return text
    except ValueError:
        return None


def _tilt_equal(a: float | None, b: float | None) -> bool:
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    return abs(a - b) < TILT_COMPARE_EPSILON


def _parse_tilt_change_log(raw_list: list | None) -> list[dict]:
    out: list[dict] = []
    for item in raw_list or []:
        if not isinstance(item, dict):
            continue
        idx = _coerce_int(item.get("stringIndex"))
        eff = _parse_effective_date(item.get("effectiveDate"))
        new_tilt = _parse_tilt_degrees(item.get("newTiltDegrees"))
        if not idx or not eff or new_tilt is None or not (1 <= idx <= MAX_STRINGS):
            continue
        prev = _parse_tilt_degrees(item.get("previousTiltDegrees"))
        out.append(
            {
                "stringIndex": idx,
                "effectiveDate": eff,
                "previousTiltDegrees": prev,
                "newTiltDegrees": new_tilt,
                "recordedAt": str(item.get("recordedAt") or "").strip()[:32],
            }
        )
    out.sort(key=lambda row: (row["effectiveDate"], row["stringIndex"]), reverse=True)
    return out[:MAX_TILT_CHANGE_LOG]


def _append_tilt_changes(
    existing_log: list[dict],
    pending: list | None,
    *,
    now: datetime | None = None,
) -> list[dict]:
    """Merge saved log with new tilt-change entries from the latest Save."""
    log = _parse_tilt_change_log(existing_log)
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%d %H:%M:%S UTC")
    today = (now or datetime.now(timezone.utc)).date().isoformat()

    for item in pending or []:
        if not isinstance(item, dict):
            continue
        idx = _coerce_int(item.get("stringIndex"))
        new_tilt = _parse_tilt_degrees(item.get("newTiltDegrees"))
        if not idx or new_tilt is None or not (1 <= idx <= MAX_STRINGS):
            continue
        prev = _parse_tilt_degrees(item.get("previousTiltDegrees"))
        if _tilt_equal(prev, new_tilt):
            continue
        eff = _parse_effective_date(item.get("effectiveDate")) or today
        duplicate = any(
            row["stringIndex"] == idx
            and row["effectiveDate"] == eff
            and _tilt_equal(row.get("newTiltDegrees"), new_tilt)
            and _tilt_equal(row.get("previousTiltDegrees"), prev)
            for row in log
        )
        if duplicate:
            continue
        log.insert(
            0,
            {
                "stringIndex": idx,
                "effectiveDate": eff,
                "previousTiltDegrees": prev,
                "newTiltDegrees": new_tilt,
                "recordedAt": stamp,
            },
        )

    return _parse_tilt_change_log(log)


DEFAULT_PANEL_SPEC: dict[str, Any] = {
    "brand": "",
    "panelMaxPowerW": None,
    "maxPowerCurrentImpA": None,
    "maxOpenCircuitVoltageVocV": None,
    "panelsPerString": None,
}


def _default_string_label(index: int) -> str:
    return f"PV{index}"


def _parse_string_label(value: Any, index: int) -> str:
    text = str(value or "").strip()[:32]
    return text or _default_string_label(index)


def _empty_string_specs() -> list[dict]:
    return [
        {
            "stringIndex": i,
            "label": _default_string_label(i),
            "facingDirection": "",
            "tiltDegrees": None,
            **json.loads(json.dumps(DEFAULT_PANEL_SPEC)),
        }
        for i in range(1, MAX_STRINGS + 1)
    ]


DEFAULT_PROFILE: dict[str, Any] = {
    "inverter": {
        "name": "",
        "powerKw": None,
        "maxVocV": None,
        "mpptVoltageMinV": None,
        "mpptVoltageMaxV": None,
        "stringCount": None,
        "maxChargeCurrentA": None,
    },
    "solar": {
        "installed": True,
        "sameBrandOnAllStrings": True,
        "stringCount": None,
        "shared": dict(DEFAULT_PANEL_SPEC),
        "strings": _empty_string_specs(),
        "tiltChangeLog": [],
        "notes": "",
    },
}


def _merge_defaults(data: dict | None) -> dict:
    base = json.loads(json.dumps(DEFAULT_PROFILE))
    if not data:
        return base
    inv = {**base["inverter"], **(data.get("inverter") or {})}
    sol = _normalize_solar(data.get("solar") or {})
    return {
        "updatedAt": data.get("updatedAt"),
        "inverter": inv,
        "solar": sol,
    }


def _coerce_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _coerce_int(value: Any) -> int | None:
    f = _coerce_float(value)
    if f is None:
        return None
    return int(f) if f == int(f) else int(round(f))


def _parse_panel_spec(raw: dict | None) -> dict:
    raw = raw or {}
    return {
        "brand": str(raw.get("brand") or "").strip()[:120],
        "panelMaxPowerW": _coerce_float(raw.get("panelMaxPowerW")),
        "maxPowerCurrentImpA": _coerce_float(raw.get("maxPowerCurrentImpA")),
        "maxOpenCircuitVoltageVocV": _coerce_float(raw.get("maxOpenCircuitVoltageVocV")),
        "panelsPerString": _coerce_int(raw.get("panelsPerString")),
    }


def _parse_strings_list(raw_list: list | None) -> list[dict]:
    by_idx: dict[int, dict] = {}
    for item in raw_list or []:
        if not isinstance(item, dict):
            continue
        idx = _coerce_int(item.get("stringIndex"))
        if idx and 1 <= idx <= MAX_STRINGS:
            by_idx[idx] = item
    out: list[dict] = []
    for i in range(1, MAX_STRINGS + 1):
        raw = by_idx.get(i, {})
        spec = _parse_panel_spec({**DEFAULT_PANEL_SPEC, **raw})
        label = _parse_string_label(raw.get("label"), i)
        facing = _parse_facing_direction(raw.get("facingDirection"))
        tilt = _parse_tilt_degrees(raw.get("tiltDegrees"))
        out.append(
            {
                "stringIndex": i,
                "label": label,
                "facingDirection": facing,
                "tiltDegrees": tilt,
                **spec,
            }
        )
    return out


def _normalize_solar(sol: dict) -> dict:
    """Merge saved solar block; migrate legacy flat fields."""
    base = json.loads(json.dumps(DEFAULT_PROFILE["solar"]))
    installed = sol.get("installed", base["installed"])
    if isinstance(installed, str):
        installed = installed.lower() in ("yes", "true", "1")
    else:
        installed = bool(installed)

    if "shared" not in sol:
        shared = _parse_panel_spec(
            {
                "brand": sol.get("brand"),
                "panelMaxPowerW": sol.get("panelMaxPowerW"),
                "maxPowerCurrentImpA": sol.get("maxPowerCurrentImpA"),
                "maxOpenCircuitVoltageVocV": sol.get("maxOpenCircuitVoltageVocV"),
                "panelsPerString": sol.get("panelsPerString"),
            }
        )
        strings = _empty_string_specs()
        for row in strings:
            row.update({k: v for k, v in shared.items() if k != "stringIndex"})
        return {
            "installed": installed,
            "sameBrandOnAllStrings": True,
            "stringCount": _coerce_int(sol.get("stringCount")),
            "shared": shared,
            "strings": strings,
            "tiltChangeLog": [],
            "notes": str(sol.get("notes") or "").strip()[:2000],
        }

    same = sol.get("sameBrandOnAllStrings", True)
    if isinstance(same, str):
        same = same.lower() in ("yes", "true", "1", "same")
    else:
        same = bool(same)

    shared = _parse_panel_spec({**base["shared"], **(sol.get("shared") or {})})
    strings = _parse_strings_list(sol.get("strings"))
    tilt_log = _parse_tilt_change_log(sol.get("tiltChangeLog"))

    return {
        "installed": installed,
        "sameBrandOnAllStrings": same,
        "stringCount": _coerce_int(sol.get("stringCount")),
        "shared": shared,
        "strings": strings,
        "tiltChangeLog": tilt_log,
        "notes": str(sol.get("notes") or "").strip()[:2000],
    }


def _validate_profile(body: dict) -> dict:
    inv_in = body.get("inverter") or {}
    sol_in = body.get("solar") or {}

    installed = sol_in.get("installed")
    if isinstance(installed, str):
        installed = installed.lower() in ("yes", "true", "1")
    else:
        installed = bool(installed)

    same = sol_in.get("sameBrandOnAllStrings", True)
    if isinstance(same, str):
        same = same.lower() in ("yes", "true", "1", "same")
    else:
        same = bool(same)

    profile = {
        "updatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "inverter": {
            "name": str(inv_in.get("name") or "").strip()[:120],
            "powerKw": _coerce_float(inv_in.get("powerKw")),
            "maxVocV": _coerce_float(inv_in.get("maxVocV")),
            "mpptVoltageMinV": _coerce_float(inv_in.get("mpptVoltageMinV")),
            "mpptVoltageMaxV": _coerce_float(inv_in.get("mpptVoltageMaxV")),
            "stringCount": _coerce_int(inv_in.get("stringCount")),
            "maxChargeCurrentA": _coerce_float(inv_in.get("maxChargeCurrentA")),
        },
        "solar": {
            "installed": installed,
            "sameBrandOnAllStrings": same,
            "stringCount": _coerce_int(sol_in.get("stringCount")),
            "shared": _parse_panel_spec(sol_in.get("shared") or {}),
            "strings": _parse_strings_list(sol_in.get("strings")),
            "tiltChangeLog": _parse_tilt_change_log(sol_in.get("tiltChangeLog")),
            "notes": str(sol_in.get("notes") or "").strip()[:2000],
        },
    }
    return profile


def load_system_profile() -> dict:
    if not PROFILE_PATH.exists():
        return _merge_defaults(None)
    try:
        raw = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
        return _merge_defaults(raw if isinstance(raw, dict) else None)
    except (json.JSONDecodeError, OSError):
        return _merge_defaults(None)


def save_system_profile(body: dict) -> dict:
    previous = load_system_profile()
    profile = _validate_profile(body)
    sol_in = body.get("solar") or {}
    old_log = (previous.get("solar") or {}).get("tiltChangeLog") or []
    profile["solar"]["tiltChangeLog"] = _append_tilt_changes(
        old_log,
        sol_in.get("tiltChangePending"),
    )
    PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    PROFILE_PATH.write_text(json.dumps(profile, indent=2), encoding="utf-8")
    return _merge_defaults(profile)


def profile_payload() -> dict:
    return {
        "ok": True,
        "profile": load_system_profile(),
        "facingOptions": [
            {"value": code, "label": PANEL_FACING_LABELS[code]}
            for code in PANEL_FACING_OPTIONS
        ],
    }
