"""Read live inverter data locally via dongle Modbus TCP (read-only)."""
from __future__ import annotations

import socket
import struct
from pathlib import Path

ENV_PATH = Path(__file__).resolve().parent / ".env"
HOST = "192.168.10.67"
PORT = 8000
DONGLE_SN = "BA24401521"
INVERTER_SN = "2453530335"
RESPONSE_OVERHEAD = 37
READ_TIMEOUT = 5

# Input register addresses
I_STATE = 0
I_VPV1 = 1
I_VPV2 = 2
I_VBAT = 4
I_SOC_SOH = 5
I_PPV1 = 7
I_PPV2 = 8
I_PPV3 = 9
I_PCHARGE = 10
I_PDISCHARGE = 11
I_PTOUSER = 27
I_EPV1_DAY = 28


def load_env() -> dict[str, str]:
    cfg: dict[str, str] = {}
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or "=" not in line:
            continue
        k, v = line.split("=", 1)
        cfg[k.strip().lower().replace(" ", "_")] = v.strip()
    return cfg


def compute_crc(data: bytes) -> int:
    crc = 0xFFFF
    for pos in data:
        crc ^= pos
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if (crc & 1) else crc >> 1
    return crc & 0xFFFF


def build_read_packet(dongle_sn: str, inverter_sn: str, start: int, count: int) -> bytes:
    buf = bytearray([0xA1, 0x1A])
    buf += (1).to_bytes(2, "little")
    buf += (32).to_bytes(2, "little")
    buf += (1).to_bytes(1, "little")
    buf += (194).to_bytes(1, "little")
    buf += dongle_sn.encode("ascii")
    buf += (18).to_bytes(2, "little")
    buf += (0).to_bytes(1, "little")  # action
    buf += (4).to_bytes(1, "little")  # input registers
    buf += inverter_sn.encode("ascii")
    buf += start.to_bytes(2, "little")
    buf += count.to_bytes(2, "little")
    crc = compute_crc(bytes(buf[20:36]))
    buf += crc.to_bytes(2, "little")
    return bytes(buf)


def read_input_registers(sock: socket.socket, start: int, count: int) -> dict[int, int]:
    req = build_read_packet(DONGLE_SN, INVERTER_SN, start, count)
    sock.sendall(req)
    expected = RESPONSE_OVERHEAD + count * 2
    chunks = bytearray()
    while len(chunks) < expected:
        part = sock.recv(expected - len(chunks))
        if not part:
            break
        chunks.extend(part)
    if len(chunks) < RESPONSE_OVERHEAD or chunks[0:2] != b"\xa1\x1a":
        raise RuntimeError(f"Bad response ({len(chunks)} bytes)")
    data_frame = bytes(chunks[20:-2])
    if compute_crc(data_frame) != int.from_bytes(chunks[-2:], "little"):
        raise RuntimeError("CRC mismatch")
    reg = int.from_bytes(data_frame[12:14], "little")
    values = data_frame[14:]
    return {reg + i: values[2 * i] | (values[2 * i + 1] << 8) for i in range(len(values) // 2)}


def signed16(v: int) -> int:
    return v - 65536 if v >= 32768 else v


def main() -> None:
    cfg = load_env()
    host = cfg.get("inverter_ip", HOST)
    print(f"Local read-only via dongle at {host}:{PORT}")
    print(f"Dongle SN: {DONGLE_SN}  Inverter SN: {INVERTER_SN}")
    print(f"MAC in .env: {cfg.get('inverter_mac', '(not used for Modbus)')}\n")

    sock = socket.create_connection((host, PORT), READ_TIMEOUT)
    sock.settimeout(READ_TIMEOUT)
    try:
        # Dongle may push initial heartbeat data first; read and discard briefly.
        sock.settimeout(0.5)
        try:
            sock.recv(4096)
        except TimeoutError:
            pass
        sock.settimeout(READ_TIMEOUT)

        regs = read_input_registers(sock, 0, 40)
        soc = regs.get(I_SOC_SOH, 0) & 0xFF
        soh = (regs.get(I_SOC_SOH, 0) >> 8) & 0xFF
        print("=== LIVE (local Modbus) ===")
        print(f"  State code: {regs.get(I_STATE)}")
        print(f"  PV1: {regs.get(I_PPV1)} W @ {regs.get(I_VPV1, 0)/10:.1f} V")
        print(f"  PV2: {regs.get(I_PPV2)} W @ {regs.get(I_VPV2, 0)/10:.1f} V")
        print(f"  Total PV: {regs.get(I_PPV3)} W")
        print(f"  Battery: {regs.get(I_VBAT, 0)/10:.1f} V  SOC {soc}%  SOH {soh}%")
        print(f"  Charge: {regs.get(I_PCHARGE)} W  Discharge: {regs.get(I_PDISCHARGE)} W")
        print(f"  Load/import power: {signed16(regs.get(I_PTOUSER, 0))} W")
        print(f"  PV1 today: {regs.get(I_EPV1_DAY, 0)/10:.1f} kWh")
    finally:
        sock.close()

    print("\nMAC address is not used for data access — IP + dongle SN + inverter SN are enough.")


if __name__ == "__main__":
    main()
