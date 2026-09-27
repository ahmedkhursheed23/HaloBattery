"""Tests for the Razer model table in providers/razer.py. No hardware is needed.

The table must agree with OpenRazer, the Linux driver that reads the battery of
these mice. OPENRAZER_CHARGE_LEVEL below is a copy of the PID -> transaction id
list in OpenRazer's razer_attr_read_charge_level() (driver/razermouse_driver.c,
commit 6820f9da16). The poll tests replace the HID layer with a fake mouse that
answers the 90-byte feature report the way the provider expects.

Run from the repository root:

    python -m unittest discover -s tests
"""
import os
import sys
import time
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from providers import razer as R  # noqa: E402

OPENRAZER_CHARGE_LEVEL = {
    0x001F: 0xFF,   # NAGA_EPIC
    0x0024: 0xFF,   # MAMBA_2012_WIRED
    0x0025: 0xFF,   # MAMBA_2012_WIRELESS
    0x0032: 0xFF,   # OUROBOROS
    0x003E: 0xFF,   # NAGA_EPIC_CHROMA
    0x003F: 0xFF,   # NAGA_EPIC_CHROMA_DOCK
    0x0044: 0xFF,   # MAMBA_WIRED
    0x0045: 0xFF,   # MAMBA_WIRELESS
    0x0059: 0x3F,   # LANCEHEAD_WIRED
    0x005A: 0x3F,   # LANCEHEAD_WIRELESS
    0x0062: 0x1F,   # ATHERIS_RECEIVER
    0x006F: 0x1F,   # LANCEHEAD_WIRELESS_RECEIVER
    0x0070: 0x1F,   # LANCEHEAD_WIRELESS_WIRED
    0x0072: 0x3F,   # MAMBA_WIRELESS_RECEIVER
    0x0073: 0x3F,   # MAMBA_WIRELESS_WIRED
    0x0077: 0x1F,   # PRO_CLICK_RECEIVER
    0x007A: 0xFF,   # VIPER_ULTIMATE_WIRED
    0x007B: 0xFF,   # VIPER_ULTIMATE_WIRELESS
    0x007C: 0x3F,   # DEATHADDER_V2_PRO_WIRED
    0x007D: 0x3F,   # DEATHADDER_V2_PRO_WIRELESS
    0x0080: 0x1F,   # PRO_CLICK_WIRED
    0x0083: 0xFF,   # BASILISK_X_HYPERSPEED
    0x0086: 0x1F,   # BASILISK_ULTIMATE_WIRED
    0x0088: 0x1F,   # BASILISK_ULTIMATE_RECEIVER
    0x008F: 0x1F,   # NAGA_PRO_WIRED
    0x0090: 0x1F,   # NAGA_PRO_WIRELESS
    0x0094: 0x1F,   # OROCHI_V2_RECEIVER
    0x0095: 0x1F,   # OROCHI_V2_BLUETOOTH
    0x009A: 0x1F,   # PRO_CLICK_MINI_RECEIVER
    0x009C: 0x1F,   # DEATHADDER_V2_X_HYPERSPEED
    0x009E: 0x1F,   # VIPER_MINI_SE_WIRED
    0x009F: 0x1F,   # VIPER_MINI_SE_WIRELESS
    0x00A5: 0x1F,   # VIPER_V2_PRO_WIRED
    0x00A6: 0x1F,   # VIPER_V2_PRO_WIRELESS
    0x00A7: 0x1F,   # NAGA_V2_PRO_WIRED
    0x00A8: 0x1F,   # NAGA_V2_PRO_WIRELESS
    0x00AA: 0x1F,   # BASILISK_V3_PRO_WIRED
    0x00AB: 0x1F,   # BASILISK_V3_PRO_WIRELESS
    0x00AF: 0x1F,   # COBRA_PRO_WIRED
    0x00B0: 0x1F,   # COBRA_PRO_WIRELESS
    0x00B3: 0x1F,   # HYPERPOLLING_WIRELESS_DONGLE
    0x00B4: 0x1F,   # NAGA_V2_HYPERSPEED_RECEIVER
    0x00B6: 0x1F,   # DEATHADDER_V3_PRO_WIRED
    0x00B7: 0x1F,   # DEATHADDER_V3_PRO_WIRELESS
    0x00B8: 0x1F,   # VIPER_V3_HYPERSPEED
    0x00B9: 0x1F,   # BASILISK_V3_X_HYPERSPEED
    0x00BE: 0x1F,   # DEATHADDER_V4_PRO_WIRED
    0x00BF: 0x1F,   # DEATHADDER_V4_PRO_WIRELESS
    0x00C0: 0x1F,   # VIPER_V3_PRO_WIRED
    0x00C1: 0x1F,   # VIPER_V3_PRO_WIRELESS
    0x00C2: 0x1F,   # DEATHADDER_V3_PRO_WIRED_ALT
    0x00C3: 0x1F,   # DEATHADDER_V3_PRO_WIRELESS_ALT
    0x00C4: 0x1F,   # DEATHADDER_V3_HYPERSPEED_WIRED
    0x00C5: 0x1F,   # DEATHADDER_V3_HYPERSPEED_WIRELESS
    0x00C7: 0x1F,   # PRO_CLICK_V2_VERTICAL_EDITION_WIRED
    0x00C8: 0x1F,   # PRO_CLICK_V2_VERTICAL_EDITION_WIRELESS
    0x00CB: 0x1F,   # BASILISK_V3_35K
    0x00CC: 0x1F,   # BASILISK_V3_PRO_35K_WIRED
    0x00CD: 0x1F,   # BASILISK_V3_PRO_35K_WIRELESS
    0x00D0: 0x1F,   # PRO_CLICK_V2_WIRED
    0x00D1: 0x1F,   # PRO_CLICK_V2_WIRELESS
    0x00D3: 0x1F,   # BASILISK_MOBILE_WIRED
    0x00D4: 0x1F,   # BASILISK_MOBILE_RECEIVER
    0x00D6: 0x1F,   # BASILISK_V3_PRO_35K_PHANTOM_GREEN_EDITION_WIRED
    0x00D7: 0x1F,   # BASILISK_V3_PRO_35K_PHANTOM_GREEN_EDITION_WIRELESS
}

# In OpenRazer's list, but not in the app's table on purpose (see providers/razer.py).
LEFT_OUT = {
    0x0095,   # Orochi V2 over Bluetooth: Windows' Bluetooth battery value covers it
    0x00CB,   # Basilisk V3 35K: a wired-only mouse
}


# ------------------------------------------------------------------ fake mouse
class FakeMouse:
    """One Razer HID interface. Answers the battery (07:80) and charging (07:84)
    requests with status 02 when the transaction id is `tid`, as the mice do."""

    def __init__(self, tid, raw_level=0xB5, charging=0):
        self.tid = tid
        self.values = {0x80: raw_level, 0x84: charging}
        self.tids = []          # transaction id of every request, in order
        self.request = None

    def reply(self):
        req = self.request
        out = bytearray(90)
        out[1:8] = req[1:8]
        if req[1] == self.tid:
            out[0] = R.STATUS_OK
            out[9] = self.values.get(req[7], 0)
        else:
            out[0] = R.STATUS_NOT_SUPPORTED
        return [0x00] + list(out)        # hidapi on Windows puts the report id first


class FakeBus:
    def __init__(self, mice):
        self.mice = mice                 # {path: FakeMouse}

    def device_class(self):
        bus = self

        class FakeDevice:
            def open_path(self, path):
                if path not in bus.mice:
                    raise OSError("cannot open")
                self.mouse = bus.mice[path]

            def send_feature_report(self, data):
                req = bytes(data[1:])
                self.mouse.request = req
                self.mouse.tids.append(req[1])
                return len(data)

            def get_feature_report(self, report_id, size):
                return self.mouse.reply()

            def close(self):
                pass

        return FakeDevice


def entry(pid, path, name, iface=0, page=0x0001):
    return {"product_id": pid, "interface_number": iface, "usage_page": page, "usage": 2,
            "path": path, "product_string": name, "serial_number": "000000000000"}


class PollTest(unittest.TestCase):
    def setUp(self):
        self._saved = (R.hid, R.hidlist, R.time)
        # no real waiting: the provider sleeps between a request and its reply
        R.time = types.SimpleNamespace(time=time.time, sleep=lambda s: None)

    def tearDown(self):
        R.hid, R.hidlist, R.time = self._saved

    def poll(self, entries, mice):
        bus = FakeBus(mice)
        R.hid = types.SimpleNamespace(device=bus.device_class())
        R.hidlist = types.SimpleNamespace(enumerate=lambda vid=0: list(entries))
        return R.RazerProvider().poll()


# ------------------------------------------------------------------ tests
class TableTest(unittest.TestCase):
    def test_every_openrazer_mouse_is_in_the_table(self):
        missing = sorted(f"{p:04X}" for p in OPENRAZER_CHARGE_LEVEL
                         if p not in R.KNOWN and p not in LEFT_OUT)
        self.assertEqual(missing, [])

    def test_transaction_ids_agree_with_openrazer(self):
        wrong = {f"{p:04X}": (f"{R.KNOWN[p][1]:02X}", f"{t:02X}")
                 for p, t in OPENRAZER_CHARGE_LEVEL.items()
                 if p in R.KNOWN and R.KNOWN[p][1] != t}
        self.assertEqual(wrong, {})

    def test_left_out_pids_stay_out(self):
        for pid in LEFT_OUT:
            self.assertNotIn(pid, R.KNOWN)

    def test_every_preferred_tid_is_also_tried_as_a_fallback(self):
        for pid, (name, tid) in R.KNOWN.items():
            self.assertIn(tid, R.TRANSACTION_IDS, f"{pid:04X} {name}")

    def test_naga_pro_and_naga_v2_pro_are_different_mice(self):
        # 008F / 0090 were called "Naga V2 Pro"; OpenRazer: NAGA_PRO_WIRED / _WIRELESS
        self.assertEqual(R.KNOWN[0x008F][0], "Razer Naga Pro")
        self.assertEqual(R.KNOWN[0x0090][0], "Razer Naga Pro")
        self.assertEqual(R.KNOWN[0x00A7][0], "Razer Naga V2 Pro")
        self.assertEqual(R.KNOWN[0x00A8][0], "Razer Naga V2 Pro")

    def test_wired_viper_is_not_in_the_table(self):
        # 0078 is OpenRazer's USB_DEVICE_ID_RAZER_VIPER, a wired mouse with no battery.
        # The Viper Ultimate is 007A / 007B.
        self.assertNotIn(0x0078, R.KNOWN)
        self.assertFalse(R.maybe_wireless(0x0078, "Razer Viper"))
        self.assertTrue(R.maybe_wireless(0x007B, "Razer Viper Ultimate"))


class PollRazerTest(PollTest):
    def test_pro_click_v2_vertical_issue_58(self):
        # The interfaces are the ones in the diagnostics report of issue #58.
        name = "Razer Pro Click V2 Vertical Edition"
        entries = [entry(0x00C8, b"if0", name, 0), entry(0x00C8, b"if1", name, 1),
                   entry(0x00C8, b"if2", name, 2)]
        mouse = FakeMouse(tid=0x1F, raw_level=0xB5)
        res = self.poll(entries, {b"if0": mouse})
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0].name, name)
        self.assertEqual(res[0].level, round(0xB5 / 255 * 100))     # 71 %
        self.assertEqual(mouse.tids[0], 0x1F)      # the first request is already right

    def test_pro_click_v2_vertical_is_not_skipped(self):
        # The name has no "wireless" word, so without a table entry the mouse was skipped.
        self.assertTrue(R.maybe_wireless(0x00C8, "Razer Pro Click V2 Vertical Edition"))
        self.assertFalse(any(w in "razer pro click v2 vertical edition" for w in R.WIRELESS_WORDS))

    def test_basilisk_x_hyperspeed_asks_with_ff_first(self):
        mouse = FakeMouse(tid=0xFF, raw_level=0xFF)
        res = self.poll([entry(0x0083, b"if0", "Razer Basilisk X HyperSpeed")], {b"if0": mouse})
        self.assertEqual([r.level for r in res], [100])
        self.assertEqual(mouse.tids[0], 0xFF)

    def test_naga_v2_pro_is_polled(self):
        mouse = FakeMouse(tid=0x1F, raw_level=0x80, charging=1)
        res = self.poll([entry(0x00A8, b"if0", "Razer Naga V2 Pro")], {b"if0": mouse})
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0].name, "Razer Naga V2 Pro")
        self.assertEqual(res[0].level, 50)
        self.assertTrue(res[0].charging)

    def test_wired_viper_gets_no_request(self):
        mouse = FakeMouse(tid=0xFF)
        res = self.poll([entry(0x0078, b"if0", "Razer Viper")], {b"if0": mouse})
        self.assertEqual(res, [])
        self.assertEqual(mouse.tids, [])


if __name__ == "__main__":
    unittest.main()
