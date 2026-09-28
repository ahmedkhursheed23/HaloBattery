"""HyperX Cloud III S Wireless over its USB dongle, without NGENUITY.

A different protocol from the Cloud III Wireless (hyperx_cloud3.py). Source:
LennardKittner/HyperHeadset, src/devices/cloud_iii_s_wireless.rs at 57dfa2b, which lists
the product ids 0x06BE and 0x02CC:

  * request: a 64-byte *feature* report
        0c 02 03 01 00 <cmd> 00 ...
    0x0C is the report id; byte 3 = 01 asks for a value (00 would set one, which this
    provider never sends).
        cmd 0x06  battery
        cmd 0x48  charging
  * reply: an input report on the same collection
        0c .. .. .. .. <cmd> <value>
    value 0xFF = no value (the reference ignores it; here it is above 100 for the battery
    and not a charging state). Battery: the percent. Charging: 0 not charging,
    1 charging, 2 fully charged, anything else an error.
  * the headset also pushes notifications, input report 0x0D: byte 4 = 1 carries the
    battery percent in byte 5, byte 4 = 10 the charging state in byte 5.
  * the collection: on Windows the reference sends the battery request to every HID
    interface of the dongle and keeps the first one that accepts it and answers. Windows
    refuses a feature report whose id the collection does not declare, so the others
    fail at once and nothing reaches them. This provider does the same, vendor pages
    first, and remembers the collection that answered.

A level above 100 is refused rather than shown as a made-up number.
"""
from __future__ import annotations

import time
from typing import Dict, List, Optional, Tuple

try:
    import hid
except ImportError:              # pragma: no cover
    hid = None

from . import hidlist
from .base import DeviceStatus, Provider, hexdump, log

HP_VID = 0x03F0

PIDS = {
    0x02CC: "HyperX Cloud III S Wireless",
    0x06BE: "HyperX Cloud III S Wireless",   # the other id the reference lists
}

REPORT_ID = 0x0C
NOTIFICATION_ID = 0x0D
PACKET_LEN = 64
CMD_BATTERY = 0x06
CMD_CHARGING = 0x48
NOTE_BATTERY = 1
NOTE_CHARGING = 10

READ_LEN = 64
READ_WINDOW = 1.0            # s: the reference waits up to 1 s for the reply
READ_TIMEOUT_MS = 100
WRITE_PAUSE = 0.05           # the reference's RESPONSE_DELAY

KIND_BATTERY, KIND_CHARGING = "battery", "charging"


def make_request(cmd: int) -> List[int]:
    return [REPORT_ID, 0x02, 0x03, 0x01, 0x00, cmd] + [0x00] * (PACKET_LEN - 6)


def parse(r) -> Optional[Tuple[str, int]]:
    """An input report -> ("battery", percent) or ("charging", state), or None."""
    if not r or len(r) < 7:
        return None
    if r[0] == REPORT_ID:
        value = r[6]                      # 0xFF, "no value", fails both checks below
        if r[5] == CMD_BATTERY:
            return (KIND_BATTERY, value) if value <= 100 else None
        if r[5] == CMD_CHARGING:
            return KIND_CHARGING, value
        return None
    if r[0] == NOTIFICATION_ID:
        if r[4] == NOTE_BATTERY:
            return (KIND_BATTERY, r[5]) if r[5] <= 100 else None
        if r[4] == NOTE_CHARGING:
            return KIND_CHARGING, r[5]
    return None


def charging_flag(state: Optional[int]) -> Optional[bool]:
    if state == 0:
        return False
    if state in (1, 2):                   # charging, fully charged: on the cable
        return True
    return None                           # the reference's error value: no claim


def _order(d: dict) -> Tuple[int, int]:
    page = d.get("usage_page") or 0
    return (0 if page >= 0xFF00 else 1, page)


class HyperXCloud3SProvider(Provider):
    name = "hyperx_cloud3s"

    def __init__(self):
        self._diag: List[str] = []
        self._path: Dict[int, bytes] = {}      # pid -> the collection that answered

    def _ask(self, path: bytes, cmd: int, want: str) -> Tuple[bool, Optional[int]]:
        """-> (accepted, value). accepted is False when the collection refused the report."""
        dev = hid.device()
        try:
            dev.open_path(path)
        except (OSError, IOError) as e:
            self._diag.append(f"  open: {e}")
            return False, None
        try:
            try:
                dev.send_feature_report(make_request(cmd))
            except (OSError, IOError, ValueError) as e:
                self._diag.append(f"  cmd {cmd:02x}: refused ({e})")
                return False, None
            time.sleep(WRITE_PAUSE)
            end = time.time() + READ_WINDOW
            while time.time() < end:
                try:
                    r = list(dev.read(READ_LEN, READ_TIMEOUT_MS) or [])
                except (OSError, IOError, ValueError) as e:
                    self._diag.append(f"  cmd {cmd:02x} read: {e}")
                    return True, None
                res = parse(r)
                if res is not None and res[0] == want:
                    self._diag.append(f"  cmd {cmd:02x} reply: {hexdump(r, 8)}")
                    return True, res[1]
                if r:
                    self._diag.append(f"  cmd {cmd:02x} ignored: {hexdump(r, 8)}")
            self._diag.append(f"  cmd {cmd:02x}: no reply")
            return True, None
        finally:
            try:
                dev.close()
            except Exception:
                pass

    def _battery(self, pid: int, mine: List[dict]) -> Tuple[Optional[bytes], Optional[int]]:
        cached = self._path.get(pid)
        if cached is not None and any(d["path"] == cached for d in mine):
            accepted, level = self._ask(cached, CMD_BATTERY, KIND_BATTERY)
            if accepted:
                return cached, level
            self._path.pop(pid, None)
        for d in sorted(mine, key=_order):
            self._diag.append(f"  try iface={d.get('interface_number')} "
                              f"{d.get('usage_page', 0):04x}:{d.get('usage', 0):04x}")
            accepted, level = self._ask(d["path"], CMD_BATTERY, KIND_BATTERY)
            if accepted and level is not None:
                self._path[pid] = d["path"]
                return d["path"], level
        return None, None

    def poll(self) -> List[DeviceStatus]:
        self._diag = []
        if hid is None:
            return []
        try:
            infos = hidlist.enumerate(HP_VID)
        except Exception as e:  # pragma: no cover
            log.warning("hid.enumerate(hyperx cloud iii s): %s", e)
            return []
        out = []
        for pid, name in PIDS.items():
            mine = [d for d in infos if d["product_id"] == pid]
            if not mine:
                continue
            self._diag.append(f"[HyperX] pid={pid:04x} '{name}', collections: {len(mine)}")
            path, level = self._battery(pid, mine)
            if path is None or level is None:
                continue                  # off, or no collection answered: no icon
            _, state = self._ask(path, CMD_CHARGING, KIND_CHARGING)
            charging = charging_flag(state)
            out.append(DeviceStatus(f"hyperx:{pid:04x}", name, level, bool(charging), True,
                                    "hyperx", kind="headset"))
        return out

    def diagnostics(self) -> List[str]:
        return list(self._diag)
