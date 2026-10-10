"""BLE link to the ultrasonic patch (bleak).

Packet layout (little-endian, 14 bytes) notified on TELEMETRY_CHAR_UUID:
    6 x uint16  echo times in 0.1 us units: ap_front, ap_back, tr_front, tr_back, si_front, si_back
    uint8       battery %
    uint8       signal quality 0-100
Replace the UUIDs / layout with your firmware's. The phone acts as a gateway and forwards
frames to the backend.
"""
from __future__ import annotations

import asyncio
import struct
from datetime import datetime, timezone
from typing import Callable, Optional

import httpx
from bleak import BleakClient, BleakScanner

SERVICE_UUID = "6e400001-b5a3-f393-e0a9-e50e24dcca9e"          # placeholder (Nordic UART)
TELEMETRY_CHAR_UUID = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"   # placeholder
PACKET = struct.Struct("<6HBB")


def parse_packet(data: bytes) -> dict:
    ap_f, ap_b, tr_f, tr_b, si_f, si_b, batt, q = PACKET.unpack(data[:PACKET.size])
    u = 0.1
    return {
        "ap_echo_us": [ap_f * u, ap_b * u],
        "tr_echo_us": [tr_f * u, tr_b * u],
        "si_echo_us": [si_f * u, si_b * u],
        "battery_pct": float(batt),
        "signal_quality": min(q, 100) / 100.0,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


async def scan(name_prefix: str = "BladderPatch", timeout: float = 8.0):
    devices = await BleakScanner.discover(timeout=timeout)
    return [d for d in devices if d.name and d.name.startswith(name_prefix)]


async def stream_to_backend(api_url: str, address: Optional[str] = None,
                            on_status: Optional[Callable[[str], None]] = None,
                            stop: Optional[asyncio.Event] = None) -> None:
    """Connect to the patch, forward each notification to POST /telemetry."""
    say = on_status or print
    stop = stop or asyncio.Event()
    if address is None:
        say("Scanning for patch...")
        found = await scan()
        if not found:
            say("No patch found")
            return
        address = found[0].address

    queue: asyncio.Queue = asyncio.Queue()

    def handler(_, data: bytearray):
        try:
            queue.put_nowait(parse_packet(bytes(data)))
        except struct.error:
            pass

    async with httpx.AsyncClient(base_url=api_url, timeout=5) as http:
        async with BleakClient(address) as ble:
            await ble.start_notify(TELEMETRY_CHAR_UUID, handler)
            say(f"Connected to {address}")
            while not stop.is_set():
                try:
                    body = await asyncio.wait_for(queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue
                try:
                    await http.post("/telemetry", json=body)
                except httpx.HTTPError as e:
                    say(f"Backend error: {e}")
            await ble.stop_notify(TELEMETRY_CHAR_UUID)
        say("Disconnected")
