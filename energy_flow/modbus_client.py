"""LuxPower local Modbus reader for live dashboard data."""
from __future__ import annotations

import socket
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from chart_smooth import sanitize_live_field
from soc_smooth import sanitize_soc

ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
DEFAULT_HOST = "192.168.10.67"
DEFAULT_PORT = 8000
DEFAULT_DONGLE = "BA24401521"
DEFAULT_INVERTER = "2453530335"
DEFAULT_STATION = "LuxPower Station"
READ_TIMEOUT = 5
RESPONSE_OVERHEAD = 37

# Input register map (function 4)
I_STATE = 0
I_VPV1, I_VPV2 = 1, 2
I_VBAT, I_SOC_SOH = 4, 5
I_PPV1, I_PPV2, I_PPV3 = 7, 8, 9
I_PCHARGE, I_PDISCHARGE = 10, 11
I_VAC_R, I_FAC = 12, 15
I_PEPS = 24
I_PTOGRID, I_PTOUSER = 26, 27
I_BMS_MAX_CHG_CURR, I_BMS_MAX_DISCHG_CURR = 81, 82
I_ONGRID_LOAD_POWER, I_PLOAD = 114, 170
I_INV_TEMP, I_BAT_TEMP, I_AC_OUT_V = 125, 133, 148
I_GEN_POWER = 120


@dataclass
class InverterConfig:
    host: str
    port: int
    dongle_sn: str
    inverter_sn: str
    station_name: str


def load_config() -> InverterConfig:
    cfg: dict[str, str] = {}
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            cfg[k.strip().lower().replace(" ", "_")] = v.strip()
    return InverterConfig(
        host=cfg.get("inverter_ip", DEFAULT_HOST),
        port=DEFAULT_PORT,
        dongle_sn=cfg.get("dongle_sn", DEFAULT_DONGLE),
        inverter_sn=cfg.get("inverter_sn", DEFAULT_INVERTER),
        station_name=cfg.get("station", DEFAULT_STATION),
    )


def compute_crc(data: bytes) -> int:
    crc = 0xFFFF
    for pos in data:
        crc ^= pos
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if (crc & 1) else crc >> 1
    return crc & 0xFFFF


def build_read_packet(dongle_sn: str, inverter_sn: str, start: int, count: int) -> bytes:
    buf = bytearray([0xA1, 0x1A, 1, 0, 32, 0, 1, 194])
    buf += dongle_sn.encode("ascii")
    buf += bytes([18, 0, 0, 4])  # read input registers
    buf += inverter_sn.encode("ascii")
    buf += start.to_bytes(2, "little")
    buf += count.to_bytes(2, "little")
    buf += compute_crc(bytes(buf[20:36])).to_bytes(2, "little")
    return bytes(buf)


def parse_response(packet: bytes, expected_sn: str) -> dict[int, int]:
    if len(packet) < 8 or packet[:2] != b"\xa1\x1a":
        raise RuntimeError("Invalid Modbus response header")
    frame_len = int.from_bytes(packet[4:6], "little")
    total = frame_len + 6
    packet = packet[:total]
    data_frame = packet[20:-2]
    if compute_crc(data_frame) != int.from_bytes(packet[-2:], "little"):
        raise RuntimeError("Modbus CRC mismatch")
    if data_frame[1] >= 0x80:
        raise RuntimeError(f"Inverter exception code {data_frame[14]}")
    sn = data_frame[2:12].decode("ascii", errors="replace")
    if sn != expected_sn:
        raise RuntimeError(f"Unexpected inverter serial in response: {sn}")
    reg = int.from_bytes(data_frame[12:14], "little")
    proto = int.from_bytes(packet[2:4], "little")
    fn = data_frame[1]
    if proto in (2, 5) and fn not in (6,) and fn < 0x80:
        value_len = data_frame[14]
        raw = data_frame[15 : 15 + value_len]
    else:
        raw = data_frame[14:]
    if len(raw) % 2:
        raise RuntimeError("Odd register payload length")
    values = {reg + i: raw[2 * i] | (raw[2 * i + 1] << 8) for i in range(len(raw) // 2)}
    return values


def read_registers(cfg: InverterConfig, start: int, count: int) -> dict[int, int]:
    sock = socket.create_connection((cfg.host, cfg.port), READ_TIMEOUT)
    sock.settimeout(READ_TIMEOUT)
    try:
        sock.settimeout(0.4)
        try:
            sock.recv(512)
        except TimeoutError:
            pass
        sock.settimeout(READ_TIMEOUT)
        req = build_read_packet(cfg.dongle_sn, cfg.inverter_sn, start, count)
        sock.sendall(req)
        chunks = bytearray()
        need = RESPONSE_OVERHEAD + count * 2
        while True:
            part = sock.recv(4096)
            if not part:
                break
            chunks.extend(part)
            if len(chunks) >= 8:
                frame_len = int.from_bytes(chunks[4:6], "little")
                total = frame_len + 6
                if len(chunks) >= max(need, total):
                    break
        return parse_response(bytes(chunks), cfg.inverter_sn)
    finally:
        sock.close()


def signed16(value: int) -> int:
    return value - 65536 if value >= 32768 else value


def current_from_power(power_w: float, voltage_v: float) -> float:
    if voltage_v <= 0:
        return 0.0
    return round(power_w / voltage_v, 2)


def fetch_live_snapshot(cfg: InverterConfig | None = None) -> dict:
    cfg = cfg or load_config()
    r1 = read_registers(cfg, 0, 40)
    r2 = read_registers(cfg, 80, 40)
    r3 = read_registers(cfg, 110, 70)
    regs = {**r1, **r2, **r3}

    soc_raw = regs.get(I_SOC_SOH, 0) & 0xFF
    soh = (regs.get(I_SOC_SOH, 0) >> 8) & 0xFF
    vbat = round(regs.get(I_VBAT, 0) / 10, 1)
    soc = int(sanitize_soc(soc_raw, vbat))
    p_charge = int(regs.get(I_PCHARGE, 0))
    p_discharge = int(regs.get(I_PDISCHARGE, 0))
    if p_discharge > 0:
        battery_power = p_discharge
        battery_mode = "discharge"
    elif p_charge > 0:
        battery_power = -p_charge
        battery_mode = "charge"
    else:
        battery_power = 0
        battery_mode = "idle"

    grid_import = max(0, signed16(regs.get(I_PTOUSER, 0)))
    grid_export = max(0, int(regs.get(I_PTOGRID, 0)))
    load_w = int(regs.get(I_PLOAD, 0) or regs.get(I_ONGRID_LOAD_POWER, 0))
    grid_net = grid_import - grid_export

    ctx: dict[str, float] = {"vbat": vbat, "soc": float(soc)}

    ppv1 = int(sanitize_live_field("ppv1", int(regs.get(I_PPV1, 0)), ctx))
    ctx["ppv1"] = float(ppv1)
    ppv2 = int(sanitize_live_field("ppv2", int(regs.get(I_PPV2, 0)), ctx))
    ctx["ppv2"] = float(ppv2)
    ppv_aux = max(0, int(regs.get(I_PPV3, 0)) - (ppv1 + ppv2))
    ppv_aux = int(sanitize_live_field("ppvAux", ppv_aux, ctx))
    ppv_total = int(sanitize_live_field("pvTotal", int(regs.get(I_PPV3, 0) or (ppv1 + ppv2)), ctx))
    ctx["pvTotal"] = float(ppv_total)

    vpv1 = round(sanitize_live_field("vpv1", regs.get(I_VPV1, 0) / 10, ctx), 1)
    ctx["vpv1"] = vpv1
    vpv2 = round(sanitize_live_field("vpv2", regs.get(I_VPV2, 0) / 10, ctx), 1)
    ctx["vpv2"] = vpv2

    vac = round(sanitize_live_field("vac", regs.get(I_VAC_R, 0) / 10, ctx), 1)
    vac_out = round(sanitize_live_field("vacOut", regs.get(I_AC_OUT_V, vac * 10) / 10, ctx), 1)
    freq = round(sanitize_live_field("freq", regs.get(I_FAC, 0) / 100, ctx), 2)
    inv_temp = round(sanitize_live_field("invTemp", regs.get(I_INV_TEMP, 0) / 10, ctx), 1)
    bat_temp = round(sanitize_live_field("batTemp", regs.get(I_BAT_TEMP, 0) / 10, ctx), 1)
    gen_power = int(sanitize_live_field("genPower", int(regs.get(I_GEN_POWER, 0)), ctx))

    vbat = round(sanitize_live_field("vbat", vbat, ctx), 1)
    ctx["vbat"] = vbat

    load_w = int(sanitize_live_field("load", load_w, ctx))
    ctx["load"] = float(load_w)
    grid_import = int(sanitize_live_field("gridImport", grid_import, ctx))
    grid_export = int(sanitize_live_field("gridExport", grid_export, ctx))
    grid_net = int(sanitize_live_field("grid", grid_net, ctx))
    battery_power = int(sanitize_live_field("battery", battery_power, ctx))

    bms_chg_a = round(regs.get(I_BMS_MAX_CHG_CURR, 0) / 100, 0)
    bms_dis_a = round(regs.get(I_BMS_MAX_DISCHG_CURR, 0) / 100, 0)

    now = datetime.now()
    return {
        "timestamp": now.strftime("%Y-%m-%d %H:%M:%S"),
        "station": cfg.station_name,
        "inverterSn": cfg.inverter_sn,
        "dongleSn": cfg.dongle_sn,
        "stateCode": int(regs.get(I_STATE, 0)),
        "pv": {
            "pv1": {
                "powerW": ppv1,
                "voltageV": vpv1,
                "currentA": current_from_power(ppv1, vpv1),
            },
            "pv2": {
                "powerW": ppv2,
                "voltageV": vpv2,
                "currentA": current_from_power(ppv2, vpv2),
            },
            "auxPowerW": ppv_aux,
            "totalPowerW": ppv_total,
        },
        "battery": {
            "powerW": battery_power,
            "mode": battery_mode,
            "socPercent": soc,
            "sohPercent": soh,
            "voltageV": vbat,
            "currentA": current_from_power(abs(battery_power), vbat) * (1 if battery_power >= 0 else -1),
            "temperatureC": bat_temp,
            "bmsLimitChargeA": int(bms_chg_a),
            "bmsLimitDischargeA": int(bms_dis_a),
            "bmsCharge": "Allowed" if bms_chg_a > 0 else "--",
            "bmsDischarge": "Allowed" if bms_dis_a > 0 else "--",
            "bmsForceCharge": "OFF",
        },
        "grid": {
            "importW": grid_import,
            "exportW": grid_export,
            "netW": grid_net,
            "voltageV": vac,
            "acOutputVoltageV": vac_out,
            "frequencyHz": freq,
            "genDryContact": "OFF",
        },
        "inverter": {"temperatureC": inv_temp},
        "generator": {"powerW": gen_power},
        "consumption": {"powerW": load_w},
        "eps": {"powerW": int(regs.get(I_PEPS, 0)), "status": "StandBy"},
        "flow": {
            "pvToInverter": ppv_total > 20,
            "batteryToInverter": battery_mode == "discharge" and p_discharge > 20,
            "inverterToBattery": battery_mode == "charge" and p_charge > 20,
            "gridToInverter": grid_import > 20,
            "inverterToGrid": grid_export > 20,
            "inverterToLoad": load_w > 20,
            "gridToLoad": grid_import > 20 and load_w > 20,
        },
    }
