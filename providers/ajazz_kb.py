"""AJAZZ AK820 Max Ultra over its 2.4 GHz receiver (#256).

The receiver (0c45:fefc, "AJAZZ AK820MAX") publishes two vendor collections:
`ff80:0001` on interface 2 and `ff70:0071` on interface 3. The AK820 Pro family answers
its configuration tool on the interface-3 vendor page (0xFF67/0xFF68 there), with 64-byte
**output** reports, report id 0, magic `0xAA` out and `0x55` back - documented by
wsclx/ak820pro-modder from AJAZZ's own online driver:

    request   00 | AA 10 00 00 00 00 ...     (report id 0, 0x10 = GET_DEVICE_INFO)
    reply     [00 |] 55 10 .. .. .. .. .. .. <payload>   payload 48 bytes
    payload   17 = battery percent, 18 = charge status (0 discharging, 1 charging, ...)

hidapi's write/read buffers carry the report id in front on Windows, and the online driver
sends `sendReport(0, frame)` - so the wire request is 65 bytes and the reply may or may not
carry the same 0x00 in front. `parse_reply` finds the 0x55 wherever it sits and reads the
payload relative to it.

Nothing proves the Max Ultra uses the same command set - the vendor is the same and the
protocol is AJAZZ's, but the usage pages differ from the AK820 Pro's (0xFF70/0xFF80 here,
0xFF67/0xFF68 there). This provider is the experiment; it logs every reply so a wrong
offset or command is visible in the diagnostics rather than guessed at.
"""
from __future__ import annotations

import time
from typing import List, Optional, Tuple

from . import hidlist
from .base import DeviceStatus, Provider, hexdump, log

try:
    import hid  # type: ignore
except Exception:  # pragma: no cover - only when the package is missing
    hid = None

VID = 0x0C45
PID = 0xFEFC
NAME = "AJAZZ AK820 Max Ultra"
KEY = f"ajazz-kb:{PID:04x}"

FRAME_LEN = 64                # the frame itself (AA ...), without the report id
WIRE_LEN = FRAME_LEN + 1      # what hidapi is given: [report id, frame...]
OUT_MAGIC = 0xAA
IN_MAGIC = 0x55
GET_DEVICE_INFO = 0x10
PAYLOAD_OFFSET = 8            # [0]=55 [1]=cmd [2]=len [3..4]=addr, payload from 8
LEVEL_OFFSET = PAYLOAD_OFFSET + 17
CHARGE_OFFSET = PAYLOAD_OFFSET + 18

READ_ATTEMPTS = 6
READ_TIMEOUT_MS = 250
ASLEEP_KEEP = 300


def make_request() -> List[int]:
    frame = [0x00] * FRAME_LEN
    frame[0] = OUT_MAGIC
    frame[1] = GET_DEVICE_INFO
    return [0x00] + frame          # report id 0, as the online driver sends it


def parse_reply(r) -> Optional[Tuple[int, bool]]:
    """(level, charging) from a GET_DEVICE_INFO reply, or None when it is not one.

    The 0x55 magic is looked for at the start and one byte in, because hidapi returns the
    report id in front on some builds and not on others.
    """
    if not r or len(r) < PAYLOAD_OFFSET + 18:
        return None
    start = next((i for i in (0, 1) if len(r) > i + 1 and r[i] == IN_MAGIC
                  and r[i + 1] == GET_DEVICE_INFO), None)
    if start is None:
        return None
    level_at = start + LEVEL_OFFSET
    charge_at = start + CHARGE_OFFSET
    if len(r) <= charge_at:
        return None
    level = r[level_at]
    if not 1 <= level <= 100:      # 0 is the "not reported" value in this protocol
        return None
    return level, r[charge_at] != 0


def pick(infos: List[dict]) -> List[dict]:
    """Interface-3 vendor page first (as on the AK820 Pro), then any vendor page."""
    vendor = [d for d in infos if (d.get("usage_page") or 0) >= 0xFF00]
    third = [d for d in vendor if d.get("interface_number") == 3]
    return third + [d for d in vendor if d not in third]


class AjazzKeyboardProvider(Provider):
    name = "ajazz_kb"

    def __init__(self):
        self._diag: List[str] = []
        self._last: Optional[Tuple[int, float]] = None

    def poll(self) -> List[DeviceStatus]:
        self._diag = []
        if hid is None:
            return []
        try:
            infos = hidlist.enumerate(VID)
        except Exception as e:  # pragma: no cover
            log.warning("hid.enumerate(ajazz kb): %s", e)
            return []
        mine = [d for d in infos if d.get("product_id") == PID]
        if not mine:
            return []
        self._diag.append(f"[AJAZZ KB] pid={PID:04x} '{NAME}'")
        parsed = None
        for d in pick(mine):
            self._diag.append(f"  trying iface={d.get('interface_number')} "
                              f"{d.get('usage_page', 0):04x}:{d.get('usage', 0):04x}")
            parsed = self._ask(d["path"])
            if parsed is not None:
                break
        if parsed is None:
            self._diag.append("  no device-info answer")
            if self._last and time.time() - self._last[1] < ASLEEP_KEEP:
                return [DeviceStatus(KEY, NAME, self._last[0], False, False, "ajazz_kb",
                                     kind="keyboard")]
            return [DeviceStatus(KEY, NAME, None, False, False, "ajazz_kb", kind="keyboard")]
        level, charging = parsed
        self._last = (level, time.time())
        self._diag.append(f"  -> {level}%{' charging' if charging else ''}")
        return [DeviceStatus(KEY, NAME, level, charging, True, "ajazz_kb", kind="keyboard")]

    def _ask(self, path) -> Optional[Tuple[int, bool]]:
        dev = hid.device()  # type: ignore[union-attr]
        try:
            dev.open_path(path)
        except (OSError, IOError) as e:
            self._diag.append(f"    open: {e}")
            return None
        try:
            sent = dev.write(make_request())
            if sent is not None and sent < 0:
                self._diag.append(f"    write refused ({sent})")
                return None
            for _ in range(READ_ATTEMPTS):
                r = dev.read(WIRE_LEN, READ_TIMEOUT_MS)
                if not r:
                    continue
                self._diag.append(f"    reply: {hexdump(r, 16)}")
                parsed = parse_reply(r)
                if parsed is not None:
                    return parsed
        except (OSError, IOError, ValueError) as e:
            self._diag.append(f"    error: {e}")
        finally:
            try:
                dev.close()
            except Exception:
                pass
        return None

    def diagnostics(self) -> List[str]:
        return list(self._diag)
