"""SteelSeries wireless headsets (Arctis Nova 7 and Nova 5 families), directly
over USB/HID, without SteelSeries GG. Works alongside GG.

Protocol (model list and reply layouts as documented by Sapd/HeadsetControl):
  * output report 00 b0 on interface 3 (usage page 0xFFC0) of the dongle
  * Nova 7 reply:  b0 <?> <battery> <status> ...
      battery 0..100, or 0..4 on the original firmware
      status 00 = headset off / out of range, 01 / 02 = charging, 03 = on battery
  * Nova 5 reply:  b0 <status> <?> <battery 0..100> <charging> ...
      status 02 = headset off / out of range, charging 01 = charging
  * other reports can arrive on the same interface; the b0 reply is picked out, and the
   parsers insist on it, so anything else the dongle sends yields no reading at all
   (without that check a stray report reads as a level: `01 00 63 02` as 99%)

Mouse battery (Rival 3 Wireless and family), from yurtemre7/steel-mouse:
  * same interface 3 and the same ffc0 collection, but a different exchange:
    a 64-byte request 00 aa 01 ... and a reply that echoes the command: aa <level> ...
  * a report on that interface which does not carry the aa echo is skipped, as
    steel-mouse does (they used to read as a fixed 85% / 100%)
  * steel-mouse accepts a reply with the aa echo present, while its decoder and unit
    tests read the level with no echo at all. The offsets here follow the echo, so
    they are not confirmed on hardware: a level above 100 is refused rather than
    shown, and the raw reply is logged, so a probe settles the layout
  * SteelSeries GG reads the same collection, so both can run side by side

Aerox 3 Wireless (and the CS2 Dragon Lore edition, which shares the protocol) from
alloyctl's reverse engineering of 1038:1838 on real hardware, cross-checked against
steel-mouse and the capture notes at gort818/aerox3-wireless:
  * same interface 3 and the same ffc0 collection, 64-byte reports
  * the receiver flags its configuration opcodes with 0x40 over the wired values, and the
    battery query is no exception: the wired 0x92 is silent on the receiver while 0xD2 is
    acknowledged, so 00 d2 ... is the request and a report echoing d2 comes back
  * the level byte holds the charging flag in bit 7 and a step value below it: 1..21 on the
    21-step scale these mice use, or a direct percentage above 21, as steel-mouse decodes it
  * a level byte of 0 means the mouse is off or asleep, not empty, so it yields no reading
  * the 2.4 GHz link sleeps when the mouse is idle, and the acknowledgement only arrives
    while it is awake - the mouse wakes on the next movement, so a poll that lands on a
    sleeping mouse simply produces no reading

New models go into MODELS (headsets) or MOUSE_MODELS (mice): product id -> (name, parser).
"""
from __future__ import annotations

import time
from typing import List, Optional, Tuple

import hid

from . import hidlist
from .base import DeviceStatus, Provider, hexdump, log

STEELSERIES_VID = 0x1038
INTERFACE = 3
REQUEST = [0x00, 0xB0]
TIMEOUT = 1.0

Reading = Tuple[Optional[int], bool, bool]   # level, charging, online


def parse_nova7(r) -> Reading:
    if len(r) < 4 or r[0] != 0xB0 or r[3] == 0x00:
        return None, False, False
    return min(r[2], 100), r[3] in (0x01, 0x02), True


def parse_nova7_discrete(r) -> Reading:
    level, chg, online = parse_nova7(r)
    return (None if level is None else min(level, 4) * 25), chg, online


def parse_nova5(r) -> Reading:
    if len(r) < 5 or r[0] != 0xB0 or r[1] == 0x02:
        return None, False, False
    return min(r[3], 100), r[4] == 0x01, True


# tested on hardware: 22A1. The others follow HeadsetControl's device list.
MODELS = {
    0x22A1: ("Arctis Nova 7", parse_nova7),
    0x2202: ("Arctis Nova 7", parse_nova7_discrete),
    0x227E: ("Arctis Nova 7 Gen 2", parse_nova7),
    0x2206: ("Arctis Nova 7x", parse_nova7_discrete),
    0x2258: ("Arctis Nova 7x", parse_nova7),
    0x229E: ("Arctis Nova 7x", parse_nova7),
    0x22AD: ("Arctis Nova 7x", parse_nova7),
    0x22A4: ("Arctis Nova 7X", parse_nova7_discrete),
    0x22A5: ("Arctis Nova 7X", parse_nova7),
    0x223A: ("Arctis Nova 7 Diablo IV", parse_nova7_discrete),
    0x22A9: ("Arctis Nova 7 Diablo IV", parse_nova7),
    0x227A: ("Arctis Nova 7 WoW Edition", parse_nova7_discrete),
    0x2232: ("Arctis Nova 5", parse_nova5),
    0x2253: ("Arctis Nova 5X", parse_nova5),
}


MOUSE_REQUEST = [0x00, 0xAA, 0x01]
MOUSE_ECHO = 0xAA
MOUSE_WRITE_ATTEMPTS = 3
MOUSE_READ_ATTEMPTS = 6
MOUSE_READ_TIMEOUT_MS = 100

# Aerox 3 Wireless: the receiver's flagged form of the wired battery query 0x92.
AEROX_REQUEST = [0x00, 0xD2]
AEROX_ECHO = 0xD2
AEROX_STEPS = 21          # 1..21, step 21 = full; above that the byte is a percentage
AEROX_CHARGING = 0x80     # bit in the level byte


def parse_rival3(r) -> Reading:
    """Rival 3 Wireless: aa <level> <?> <charging> ..., the Windows report id in front.

    The offsets follow the aa echo - see the module docstring - and are not confirmed
    on hardware yet, so anything implausible yields no reading at all.
    """
    if not r:
        return None, False, False
    m = 1 if r[0] == 0x00 and len(r) > 1 else 0
    if len(r) < m + 4 or r[m] != MOUSE_ECHO:
        return None, False, False
    level = r[m + 1]
    if not 0 <= level <= 100:
        return None, False, False
    return level, r[m + 3] != 0, True


def parse_aerox3(r) -> Reading:
    """Aerox 3 Wireless: d2 <level> ..., the Windows report id optionally in front.

    The reply echoes the query (alloyctl verified 0xD2 is acknowledged on 1038:1838 while
    the wired 0x92 stays silent), so a report without the echo yields no reading - the
    interface also carries the link's other traffic. The level byte is bit 7 charging flag
    plus a 1..21 step value, or a direct percentage above 21 (steel-mouse). A level byte of
    0 means the mouse is off or asleep, so it is not read as an empty battery.
    """
    if not r:
        return None, False, False
    m = 1 if r[0] == 0x00 and len(r) > 1 else 0
    if len(r) < m + 2 or r[m] != AEROX_ECHO:
        return None, False, False
    b = r[m + 1]
    v = b & ~AEROX_CHARGING
    if v == 0:
        return None, False, False
    level = min(v, 100) if v > AEROX_STEPS else (v - 1) * 5
    return level, bool(b & AEROX_CHARGING), True


# Rival 3 Wireless / Rival 650 exchange, as listed by steel-mouse. None of these has
# been on hardware here; the reply layout is the open question in issue #5.
MOUSE_MODELS = {
    0x1830: ("SteelSeries Rival 3 Wireless", parse_rival3),
    0x1872: ("SteelSeries Rival 3 Wireless Gen 2", parse_rival3),
    0x1838: ("SteelSeries Aerox 3 Wireless", parse_aerox3),
    0x1878: ("SteelSeries Aerox 3 Wireless CS2 Dragon Lore", parse_aerox3),
    # Aerox 5 Wireless and Aerox 9 Wireless (2.4 GHz mode): rivalcfg builds their wireless
    # profiles exactly like the Aerox 3 Wireless one - the wired battery command 0x92 with
    # the wireless flag 0x40 (so 0xD2), a 64-byte readback, charging in bit 7 and the level
    # as (value - 1) * 5 (rivalcfg devices/aerox{3,5,9}_wireless_wired.py / _wireless.py).
    0x1852: ("SteelSeries Aerox 5 Wireless", parse_aerox3),
    0x185C: ("SteelSeries Aerox 5 Wireless Destiny 2 Edition", parse_aerox3),
    0x1860: ("SteelSeries Aerox 5 Wireless Diablo IV Edition", parse_aerox3),
    0x1858: ("SteelSeries Aerox 9 Wireless", parse_aerox3),
    0x1874: ("SteelSeries Aerox 9 Wireless WOW Edition", parse_aerox3),
}

# Which exchange a mouse answers: the Rival 3 family takes 00 aa 01, the Aerox 3 family the
# receiver's 00 d2 battery query (Aerox 3 / 5 / 9 Wireless). Everything else keeps the Rival 3
# exchange.
MOUSE_EXCHANGE = {
    0x1838: (AEROX_REQUEST, AEROX_ECHO),
    0x1878: (AEROX_REQUEST, AEROX_ECHO),
    0x1852: (AEROX_REQUEST, AEROX_ECHO),
    0x185C: (AEROX_REQUEST, AEROX_ECHO),
    0x1860: (AEROX_REQUEST, AEROX_ECHO),
    0x1858: (AEROX_REQUEST, AEROX_ECHO),
    0x1874: (AEROX_REQUEST, AEROX_ECHO),
}


class SteelSeriesProvider(Provider):
    name = "steelseries"

    def __init__(self):
        self._diag: List[str] = []

    def _read(self, path: bytes) -> Optional[List[int]]:
        dev = hid.device()
        try:
            dev.open_path(path)
        except (OSError, IOError) as e:
            self._diag.append(f"  open: {e}")
            return None
        try:
            dev.write(REQUEST)
            first = None
            end = time.time() + TIMEOUT
            while time.time() < end:
                r = dev.read(64, 100)
                if not r:
                    continue
                if r[0] == 0xB0:
                    self._diag.append(f"  reply: {hexdump(r, 8)}")
                    return list(r)
                first = first or list(r)
            if first:                         # no b0 report: take what came, as HeadsetControl does
                self._diag.append(f"  reply (not b0): {hexdump(first, 8)}")
            else:
                self._diag.append("  no reply")
            return first
        except (OSError, IOError, ValueError) as e:
            self._diag.append(f"  error: {e}")
            return None
        finally:
            try:
                dev.close()
            except Exception:
                pass

    def _read_mouse(self, path: bytes, request: List[int],
                    echo: int) -> Optional[List[int]]:
        """The family's request out, a report echoing it back, up to three rounds.

        Reports on the interface that do not carry the echo end the round and the request
        is repeated, so the interface's other traffic (input reports, link events, the
        other families' replies) never reads as a level.
        """
        dev = hid.device()
        try:
            dev.open_path(path)
        except (OSError, IOError) as e:
            self._diag.append(f"  open: {e}")
            return None
        try:
            for _ in range(MOUSE_WRITE_ATTEMPTS):
                try:
                    dev.write(request + [0x00] * (64 - len(request)))   # 64 bytes
                except (OSError, IOError, ValueError) as e:
                    self._diag.append(f"  write: {e}")
                    continue
                for _ in range(MOUSE_READ_ATTEMPTS):
                    r = list(dev.read(64, MOUSE_READ_TIMEOUT_MS) or [])
                    if not r:
                        continue
                    if r[0] == echo or (r[0] == 0x00 and len(r) > 1 and r[1] == echo):
                        self._diag.append(f"  reply: {hexdump(r, 8)}")
                        return r
                    self._diag.append(f"  reply (no {echo:02x} echo): {hexdump(r, 8)}")
                    break
            self._diag.append(f"  no reply with the {echo:02x} echo")
            return None
        except (OSError, IOError, ValueError) as e:
            self._diag.append(f"  error: {e}")
            return None
        finally:
            try:
                dev.close()
            except Exception:
                pass

    def poll(self) -> List[DeviceStatus]:
        self._diag = []
        try:
            infos = hidlist.enumerate(STEELSERIES_VID)
        except Exception as e:  # pragma: no cover
            log.warning("hid.enumerate(steelseries): %s", e)
            return []
        out = []
        seen = set()
        for d in infos:
            pid = d["product_id"]
            if pid in seen or d.get("interface_number") != INTERFACE:
                continue
            if pid in MOUSE_MODELS:
                seen.add(pid)
                name, parse = MOUSE_MODELS[pid]
                request, echo = MOUSE_EXCHANGE.get(pid, (MOUSE_REQUEST, MOUSE_ECHO))
                self._diag.append(f"[SteelSeries] pid={pid:04x} '{name}' (mouse, "
                                  f"{echo:02x} exchange)")
                level, chg, online = parse(self._read_mouse(d["path"], request, echo) or [])
                if online and level is not None:
                    out.append(DeviceStatus(f"steelseries:{pid:04x}", name, level, chg, True,
                                            "steelseries", kind="mouse"))
                continue
            if pid not in MODELS:
                continue
            seen.add(pid)
            name, parse = MODELS[pid]
            self._diag.append(f"[SteelSeries] pid={pid:04x} '{name}'")
            level, chg, online = parse(self._read(d["path"]) or [])
            if online and level is not None:
                out.append(DeviceStatus(f"steelseries:{pid:04x}", name, level, chg, True,
                                        "steelseries", kind="headset"))
        return out

    def diagnostics(self) -> List[str]:
        return list(self._diag)
