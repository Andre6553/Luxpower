"""LuxPower cloud Remote Set — read/write inverter settings (Maintenance API)."""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from luxpower_fetch_month import (  # noqa: E402
    ENV_PATH,
    load_env,
    login,
    post,
    primary_inverter,
    resolve_station,
)

READ_RANGES: list[tuple[int, int, str]] = [
    (0, 127, "system_and_grid"),
    (127, 127, "additional_config"),
    (240, 127, "extended_config"),
]

_SESSION: requests.Session | None = None
_SESSION_AT = 0.0
_SESSION_TTL_S = 600

from remote_set_sections import SETTINGS_SECTIONS


def _cloud_session() -> requests.Session:
    global _SESSION, _SESSION_AT
    now = time.time()
    if _SESSION is None or now - _SESSION_AT > _SESSION_TTL_S:
        cfg = load_env(ENV_PATH)
        username = cfg.get("username")
        password = cfg.get("password")
        if not username or not password:
            raise RuntimeError("Missing LuxPower username/password in .env")
        _SESSION = requests.Session()
        _SESSION.headers.update({"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
        login(_SESSION, username, password)
        _SESSION_AT = now
    return _SESSION


def default_inverter_sn() -> str:
    cfg = load_env(ENV_PATH)
    station_hint = (cfg.get("station") or "andre huis").lower()
    session = _cloud_session()
    plant_id, _ = resolve_station(session, station_hint)
    return primary_inverter(session, plant_id)


def station_info() -> dict[str, Any]:
    cfg = load_env(ENV_PATH)
    station_hint = (cfg.get("station") or "andre huis").lower()
    session = _cloud_session()
    plant_id, plant_name = resolve_station(session, station_hint)
    return {
        "plantId": plant_id,
        "stationName": plant_name,
        "inverterSn": primary_inverter(session, plant_id),
    }


def _extract_parameters(payload: dict) -> dict[str, Any]:
    skip = {
        "success",
        "msg",
        "message",
        "inverterSn",
        "deviceType",
        "startRegister",
        "pointNumber",
        "autoRetry",
    }
    params: dict[str, Any] = {}
    for key, value in payload.items():
        if key in skip or value in (None, "", "--"):
            continue
        if key.startswith("_"):
            continue
        params[key] = value
    return params


def read_register_range(session: requests.Session, inverter_sn: str, start: int, count: int) -> dict:
    return post(
        session,
        "/WManage/web/maintain/remoteRead/read",
        {
            "inverterSn": inverter_sn,
            "startRegister": start,
            "pointNumber": count,
            "autoRetry": "true",
        },
    )


def read_all_parameters(inverter_sn: str | None = None) -> dict[str, Any]:
    sn = inverter_sn or default_inverter_sn()
    session = _cloud_session()
    combined: dict[str, Any] = {}
    for start, count, _label in READ_RANGES:
        block = read_register_range(session, sn, start, count)
        combined.update(_extract_parameters(block))
    info = station_info()
    return {
        "ok": True,
        "source": "luxpower_cloud",
        "fetchedAtUtc": datetime.now(timezone.utc).isoformat(),
        "stationName": info["stationName"],
        "inverterSn": sn,
        "parameters": combined,
        "parameterCount": len(combined),
    }


def write_hold_parameter(inverter_sn: str, hold_param: str, value_text: str) -> dict:
    session = _cloud_session()
    result = post(
        session,
        "/WManage/web/maintain/remoteSet/write",
        {
            "inverterSn": inverter_sn,
            "holdParam": hold_param,
            "valueText": str(value_text),
            "clientType": "WEB",
            "remoteSetType": "NORMAL",
        },
    )
    return {"ok": True, "result": result}


def write_bit_parameter(inverter_sn: str, bit_param: str, value: int | str) -> dict:
    session = _cloud_session()
    result = post(
        session,
        "/WManage/web/maintain/remoteSet/bitParamControl",
        {
            "inverterSn": inverter_sn,
            "bitParam": bit_param,
            "value": str(int(value)),
            "clientType": "WEB",
            "remoteSetType": "NORMAL",
        },
    )
    return {"ok": True, "result": result}


def write_function_parameter(inverter_sn: str, function_param: str, enable: bool) -> dict:
    session = _cloud_session()
    result = post(
        session,
        "/WManage/web/maintain/remoteSet/functionControl",
        {
            "inverterSn": inverter_sn,
            "functionParam": function_param,
            "enable": "true" if enable else "false",
            "clientType": "WEB",
            "remoteSetType": "NORMAL",
        },
    )
    return {"ok": True, "result": result}


def apply_setting_write(
    inverter_sn: str,
    *,
    write_type: str,
    param: str,
    value: Any,
) -> dict:
    if write_type == "hold":
        return write_hold_parameter(inverter_sn, param, str(value))
    if write_type == "func":
        enable = value in (True, "true", "1", 1, "on", "enable")
        return write_function_parameter(inverter_sn, param, enable)
    if write_type == "bit":
        return write_bit_parameter(inverter_sn, param, value)
    raise ValueError(f"Unsupported write type: {write_type}")


def apply_setting_action(inverter_sn: str, action: str) -> dict:
    session = _cloud_session()
    if action == "restart":
        for path, payload in (
            (
                "/WManage/web/maintain/remoteSet/restartInverter",
                {"inverterSn": inverter_sn, "clientType": "WEB"},
            ),
            (
                "/WManage/web/maintain/remoteSet/functionControl",
                {
                    "inverterSn": inverter_sn,
                    "functionParam": "FUNC_RESTART_INVERTER",
                    "enable": "true",
                    "clientType": "WEB",
                    "remoteSetType": "NORMAL",
                },
            ),
        ):
            try:
                result = post(session, path, payload)
                return {"ok": True, "action": action, "endpoint": path, "result": result}
            except RuntimeError:
                continue
        raise RuntimeError(
            "Restart command failed on all known endpoints — use the official LuxPower portal."
        )
    if action == "reset_defaults":
        raise RuntimeError(
            "Factory reset is not enabled in this clone. Use the official LuxPower portal "
            "(Maintenance → Remote Set → Reset)."
        )
    raise ValueError(f"Unknown action: {action}")


def settings_schema_payload() -> dict[str, Any]:
    info = station_info()
    return {
        "ok": True,
        "stationName": info["stationName"],
        "inverterSn": info["inverterSn"],
        "sections": SETTINGS_SECTIONS,
        "dongleSn": "BA24401521",
        "cluster": (load_env(ENV_PATH).get("cluster") or "Middle East & Africa"),
        "writeEndpoints": {
            "hold": "/WManage/web/maintain/remoteSet/write",
            "func": "/WManage/web/maintain/remoteSet/functionControl",
            "bit": "/WManage/web/maintain/remoteSet/bitParamControl",
            "read": "/WManage/web/maintain/remoteRead/read",
        },
    }
