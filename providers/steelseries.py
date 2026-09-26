"""SteelSeries wireless headsets (Arctis Nova 7 and Nova 5 families), directly
over USB/HID, without SteelSeries GG. Works alongside GG.

Protocol (model list and reply layouts as documented by Sapd/HeadsetControl):
  * output report 00 b0 on interface 3 (usage page 0xFFC0) of the dongle
  * Nova 7 reply:  b0 <link> <battery> <status> ...
      link 03 = headset connected, 02 = not connected (Linux driver; seen on a 22A1:
      while the headset is off or still switching on, the dongle repeats the last
      battery value, and only the link byte shows it)
      battery 0..100, or 0..4 on the original firmware
      status 00 = headset off / out of range, 01 / 02 = charging, 03 = on battery
  * Nova 5 / Nova 3P reply:  b0 <status> <?> <battery 0..100> <charging> ...
      status 02 = headset off / out of range, charging 01 = charging
  * Arctis 7+ reply:  b0 <status> <battery 0..4> <charging> ...
      status 01 = headset off, charging 01 = charging
  * GameBuds reply:  b0 <?> <?> <left status> <right status> <left %> <right %> ...
      status 03 = bud out of the case; a bud in the case reports 0 %, so it is ignored
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

Nova Pro Wireless (base station 0x12E0, X base station 0x12E5), from the same
HeadsetControl source:
  * the same b0 exchange, but asked for with report id 06 (06 b0) instead of 00, and
    HeadsetControl reads it on interface 4 rather than 3
  * reply: level code in byte 6 on a 0..8 scale (0, 12, 25, 37, 50, 62, 75, 87, 100),
    state in byte 15: 01 = headset off / out of range, 02 = cable charging, 08 = on
    battery. Any other state byte, a level code above 8 or a reply shorter than 16
    bytes is refused rather than shown
  * nine steps are not a percentage, so the tray shows "about NN%" for these

Older Arctis headsets (Arctis 1, 7, 9, Pro Wireless) use other requests on other
interfaces: see CLASSIC_MODELS further down.

New models go into MODELS (headsets on the b0 exchange), NOVA_PRO_MODELS,
MOUSE_MODELS (mice) or CLASSIC_MODELS (older headsets): product id -> (name, parser ...).
"""
from __future__ import annotations

import time
from typing import Callable, Dict, List, Optional, Tuple

import hid

from . import hidlist
from .base import DeviceStatus, Provider, hexdump, log

STEELSERIES_VID = 0x1038
INTERFACE = 3
REQUEST = [0x00, 0xB0]
TIMEOUT = 1.0

Reading = Tuple[Optional[int], bool, bool]   # level, charging, online


def parse_nova7(r) -> Reading:
    # the link byte must say "connected": the battery byte keeps its old value while
    # the headset is off, so without this check an old level shows as a live one
    if len(r) < 4 or r[0] != 0xB0 or r[1] != 0x03 or r[3] == 0x00:
        return None, False, False
    return min(r[2], 100), r[3] in (0x01, 0x02), True


def parse_nova7_discrete(r) -> Reading:
    level, chg, online = parse_nova7(r)
    return (None if level is None else min(level, 4) * 25), chg, online


def parse_nova5(r) -> Reading:
    if len(r) < 5 or r[0] != 0xB0 or r[1] == 0x02:
        return None, False, False
    return min(r[3], 100), r[4] == 0x01, True


def parse_arctis7_plus(r) -> Reading:
    """Arctis 7+: b0 <status> <level 0..4> <charging>. Status 01 = headset off."""
    if len(r) < 4 or r[0] != 0xB0 or r[1] == 0x01:
        return None, False, False
    return min(r[2], 4) * 25, r[3] == 0x01, True


def parse_gamebuds(r) -> Reading:
    """Arctis GameBuds: the lower level of the buds that are out of the case."""
    if len(r) < 7 or r[0] != 0xB0:
        return None, False, False
    levels = [r[5 + i] for i in (0, 1) if r[3 + i] == 0x03]
    if not levels:                        # both buds are in the case (or off)
        return None, False, False
    return min(min(levels), 100), False, True


def parse_nova_pro(r) -> Reading:
    """Nova Pro Wireless base station: level code 0..8 in byte 6, state in byte 15.

    The state byte is the gate - a reply carrying anything else is not the battery
    answer - and 0x01 is the headset reporting itself off, which is no reading at all
    rather than 0%.
    """
    if len(r) < 16 or r[15] not in (0x01, 0x02, 0x08):
        return None, False, False
    if r[15] == 0x01 or not 0 <= r[6] <= 8:
        return None, False, False
    return r[6] * 100 // 8, r[15] == 0x02, True


# Nova Pro Wireless base stations. Different report id, and HeadsetControl asks on
# interface 4 for these two while the Nova 7 / Nova 5 dongles answer on interface 3.
NOVA_PRO_REQUEST = [0x06, 0xB0]
NOVA_PRO_INTERFACES = (3, 4)
NOVA_PRO_MODELS = {
    0x12E0: ("Arctis Nova Pro Wireless", parse_nova_pro),
    0x12E5: ("Arctis Nova Pro Wireless X", parse_nova_pro),
}
# the level is a nine-step scale, so the tray says "about NN%" instead of "NN%"
COARSE_PIDS = set(NOVA_PRO_MODELS)


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
    0x220A: ("Arctis Nova 7P", parse_nova7_discrete),
    0x22A7: ("Arctis Nova 7P", parse_nova7),
    0x2298: ("Arctis Nova 7P", parse_nova7),
    0x2269: ("Arctis Nova 3P Wireless", parse_nova5),
    0x226D: ("Arctis Nova 3X Wireless", parse_nova5),
    0x220E: ("Arctis 7+", parse_arctis7_plus),
    0x2212: ("Arctis 7+ PS5", parse_arctis7_plus),
    0x2216: ("Arctis 7+ Xbox", parse_arctis7_plus),
    0x2236: ("Arctis 7+ Destiny", parse_arctis7_plus),
    0x230A: ("Arctis GameBuds", parse_gamebuds),
}


MOUSE_REQUEST = [0x00, 0xAA, 0x01]
MOUSE_ECHO = 0xAA
MOUSE_WRITE_ATTEMPTS = 3
MOUSE_READ_ATTEMPTS = 6
MOUSE_READ_TIMEOUT_MS = 100


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


# Rival 3 Wireless / Rival 650 exchange, as listed by steel-mouse. None of these has
# been on hardware here; the reply layout is the open question in issue #5.
MOUSE_MODELS = {
    0x1830: ("SteelSeries Rival 3 Wireless", parse_rival3),
    0x1872: ("SteelSeries Rival 3 Wireless Gen 2", parse_rival3),
}


# ---------------------------------------------------------------- older Arctis headsets
# These headsets use other requests on other interfaces. Model list, requests and
# layouts come from HeadsetControl. The echo checks and the Arctis 7 connection query
# come from the Linux driver (drivers/hid/hid-steelseries-arctis.c).
#
# An exchange gets a function `ask(request, accept)`. ask() writes the request and
# returns the first reply for which accept(reply) is true, or None. So a report that
# is not the answer is never read as a level.

Ask = Callable[[List[int], Callable[[List[int]], bool]], Optional[List[int]]]


def _echo(a: int, b: int) -> Callable[[List[int]], bool]:
    """Accept a reply that starts with the two request bytes."""
    return lambda r: len(r) >= 4 and r[0] == a and r[1] == b


def exchange_arctis1(ask: Ask) -> Reading:
    """06 12 -> 06 12 <status> <level>. Status 01 = headset off. No charging flag."""
    r = ask([0x06, 0x12], _echo(0x06, 0x12))
    if r is None or r[2] == 0x01:
        return None, False, False
    return min(r[3], 100), False, True


def exchange_arctis7_2018(ask: Ask) -> Reading:
    """06 14 -> 06 14 <link>, link 03 = connected; then 06 18 -> 06 18 <level>."""
    r = ask([0x06, 0x14], _echo(0x06, 0x14))
    if r is None or r[2] != 0x03:
        return None, False, False
    r = ask([0x06, 0x18], _echo(0x06, 0x18))
    if r is None:
        return None, False, False
    return min(r[2], 100), False, True       # "sometimes overreports": capped (Linux)


def exchange_arctis7(ask: Ask) -> Reading:
    """06 18 -> 06 18 <level>. No connection query is documented for these models;
    the level reads 0 while the headset is off (Linux), so 0 means no reading."""
    r = ask([0x06, 0x18], _echo(0x06, 0x18))
    if r is None or r[2] == 0:
        return None, False, False
    return min(r[2], 100), False, True


def exchange_arctis9(ask: Ask) -> Reading:
    """00 20 -> aa 01 <?> <raw level> <charging>. Any other reply = headset off
    (Linux: 55 = no status, 03 = old status). Raw level 0x64..0x9A -> 0..100 %."""
    r = ask([0x00, 0x20], lambda r: len(r) >= 5 and r[0] in (0xAA, 0x55))
    if r is None or r[0] != 0xAA or r[1] != 0x01:
        return None, False, False
    raw = min(max(r[3], 0x64), 0x9A)
    return (raw - 0x64) * 100 // (0x9A - 0x64), r[4] == 0x01, True


def exchange_pro_wireless(ask: Ask) -> Reading:
    """41 aa -> <state>, state 02 = headset off, 04 = on; then 40 aa -> <level 0..4>.
    The replies do not echo the request, so only the documented values are accepted."""
    r = ask([0x41, 0xAA] + [0x00] * 29, lambda r: len(r) >= 1 and r[0] in (0x02, 0x04))
    if r is None or r[0] == 0x02:
        return None, False, False
    r = ask([0x40, 0xAA] + [0x00] * 29, lambda r: len(r) >= 1 and r[0] <= 4)
    if r is None:
        return None, False, False
    return r[0] * 25, False, True


# product id -> (name, interface, usage page or None, exchange). Only the vendor
# collections (usage page 0xFF00 and above) of that interface ever get a request.
# The Arctis Pro GameDAC (1280) is left out: it is a wired headset with no battery.
CLASSIC_MODELS: Dict[int, Tuple[str, int, Optional[int], Callable[[Ask], Reading]]] = {
    0x12B3: ("Arctis 1 Wireless", 3, 0xFF43, exchange_arctis1),
    0x12B6: ("Arctis 1 Wireless Xbox", 3, 0xFF43, exchange_arctis1),
    0x12D7: ("Arctis 7X", 3, 0xFF43, exchange_arctis1),
    0x12D5: ("Arctis 7P", 3, 0xFF43, exchange_arctis1),
    0x12AD: ("Arctis 7", 5, None, exchange_arctis7_2018),
    0x1260: ("Arctis 7", 5, None, exchange_arctis7),
    0x1252: ("Arctis Pro Wireless 2019", 5, None, exchange_arctis7),
    0x12C2: ("Arctis 9", 0, None, exchange_arctis9),
    0x1290: ("Arctis Pro Wireless", 0, None, exchange_pro_wireless),
}


class SteelSeriesProvider(Provider):
    name = "steelseries"

    def __init__(self):
        self._diag: List[str] = []
        self._classic_path: Dict[int, bytes] = {}   # pid -> the collection that answered

    def _read(self, path: bytes, request: Optional[List[int]] = None) -> Optional[List[int]]:
        dev = hid.device()
        try:
            dev.open_path(path)
        except (OSError, IOError) as e:
            self._diag.append(f"  open: {e}")
            return None
        try:
            dev.write(request or REQUEST)
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

    def _read_mouse(self, path: bytes) -> Optional[List[int]]:
        """00 aa 01 out, an aa reply back, up to three rounds as steel-mouse does.

        Reports on the interface that do not carry the aa echo end the round and the
        request is repeated, so a stray report never reads as a level.
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
                    dev.write(MOUSE_REQUEST + [0x00] * 61)   # 64 bytes, as steel-mouse sends
                except (OSError, IOError, ValueError) as e:
                    self._diag.append(f"  write: {e}")
                    continue
                for _ in range(MOUSE_READ_ATTEMPTS):
                    r = list(dev.read(64, MOUSE_READ_TIMEOUT_MS) or [])
                    if not r:
                        continue
                    if r[0] == MOUSE_ECHO or (r[0] == 0x00 and len(r) > 1 and r[1] == MOUSE_ECHO):
                        self._diag.append(f"  reply: {hexdump(r, 8)}")
                        return r
                    self._diag.append(f"  reply (no aa echo): {hexdump(r, 8)}")
                    break
            self._diag.append("  no reply with the aa echo")
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
            iface = d.get("interface_number")
            nova_pro = pid in NOVA_PRO_MODELS
            if pid in seen or iface not in (NOVA_PRO_INTERFACES if nova_pro else (INTERFACE,)):
                continue
            if nova_pro:
                seen.add(pid)
                name, parse = NOVA_PRO_MODELS[pid]
                self._diag.append(f"[SteelSeries] pid={pid:04x} '{name}'")
                reply = self._read(d["path"], NOVA_PRO_REQUEST) or []
                level, chg, online = parse(reply)
                if not online and reply:
                    self._diag.append("  the base station says the headset is off or out of range")
                if online and level is not None:
                    out.append(DeviceStatus(f"steelseries:{pid:04x}", name, level, chg, True,
                                            "steelseries", f"about {level}%", kind="headset"))
                continue
            if pid in MOUSE_MODELS:
                seen.add(pid)
                name, parse = MOUSE_MODELS[pid]
                self._diag.append(f"[SteelSeries] pid={pid:04x} '{name}' (mouse)")
                level, chg, online = parse(self._read_mouse(d["path"]) or [])
                if online and level is not None:
                    out.append(DeviceStatus(f"steelseries:{pid:04x}", name, level, chg, True,
                                            "steelseries", kind="mouse"))
                continue
            if pid not in MODELS or d.get("usage_page") != 0xFFC0:
                continue
            seen.add(pid)
            name, parse = MODELS[pid]
            self._diag.append(f"[SteelSeries] pid={pid:04x} '{name}'")
            level, chg, online = parse(self._read(d["path"]) or [])
            if online and level is not None:
                out.append(DeviceStatus(f"steelseries:{pid:04x}", name, level, chg, True,
                                        "steelseries", kind="headset"))
        out += self._poll_classic(infos)
        return out

    def _run_exchange(self, path: bytes, exchange: Callable[[Ask], Reading]):
        """Open one collection and run an exchange on it.
        -> (reading, answered): answered is True if any request got an accepted reply."""
        dev = hid.device()
        try:
            dev.open_path(path)
        except (OSError, IOError) as e:
            self._diag.append(f"  open: {e}")
            return (None, False, False), False
        answered = []

        def ask(request, accept):
            dev.write(request)
            end = time.time() + TIMEOUT
            while time.time() < end:
                r = list(dev.read(64, 100) or [])
                if r and accept(r):
                    self._diag.append(f"  {hexdump(request, 2)} -> {hexdump(r, 8)}")
                    answered.append(True)
                    return r
            self._diag.append(f"  {hexdump(request, 2)} -> no reply")
            return None

        try:
            return exchange(ask), bool(answered)
        except (OSError, IOError, ValueError) as e:
            self._diag.append(f"  error: {e}")
            return (None, False, False), bool(answered)
        finally:
            try:
                dev.close()
            except Exception:
                pass

    def _poll_classic(self, infos: List[dict]) -> List[DeviceStatus]:
        out = []
        for pid, (name, iface, page, exchange) in CLASSIC_MODELS.items():
            paths = [d["path"] for d in infos
                     if d["product_id"] == pid and d.get("interface_number") == iface
                     and (d.get("usage_page") == page if page
                          else (d.get("usage_page") or 0) >= 0xFF00)]
            if not paths:
                continue
            self._diag.append(f"[SteelSeries] pid={pid:04x} '{name}'")
            # once a collection has answered, ask only that one
            known = self._classic_path.get(pid)
            for path in ([known] if known in paths else paths):
                (level, chg, online), answered = self._run_exchange(path, exchange)
                if answered:
                    self._classic_path[pid] = path
                    if online and level is not None:
                        out.append(DeviceStatus(f"steelseries:{pid:04x}", name, level, chg, True,
                                                "steelseries", kind="headset"))
                    else:
                        self._diag.append("  the headset is off or out of range")
                    break
        return out

    def diagnostics(self) -> List[str]:
        return list(self._diag)
