"""Tests for providers/hyperx_cloud3s.py (HyperX Cloud III S Wireless). No hardware.

The fake dongle has the six collections of the #106 diagnostics. Only one of them
declares feature report 0x0C: the others refuse it, the way Windows refuses a feature
report whose id a collection does not have. It answers as HyperHeadset's
cloud_iii_s_wireless.rs describes. A fake clock replaces time.

Run from the repository root:

    python -m unittest discover -s tests
"""
import os
import sys
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from providers import hyperx_cloud3s as H  # noqa: E402


class Clock:
    def __init__(self):
        self.now = 1000.0

    def time(self):
        return self.now

    def sleep(self, s):
        self.now += s


def issue_106_entries(pid=0x02CC):
    shape = [(0x000C, 1), (0xFF13, 1), (0x000B, 5), (0xFFC0, 0x0202), (0x01C0, 1), (0x170F, 0x0202)]
    return [{"product_id": pid, "interface_number": 3, "usage_page": p, "usage": u,
             "path": b"%04x:%04x" % (p, u), "product_string": "HyperX Cloud III S Wireless"}
            for p, u in shape]


class Headset:
    """accepts: this collection declares report 0x0C. level None = switched off (0xFF)."""

    def __init__(self, clock, accepts=False, level=62, charge=0, noise=()):
        self.clock = clock
        self.accepts = accepts
        self.level, self.charge = level, charge
        self.queue = [list(r) for r in noise]
        self.sent = []
        self.opened = 0

    def feature(self, data):
        if not self.accepts:
            raise OSError("The parameter is incorrect.")
        data = list(data)
        self.sent.append(data)
        if self.accepts == "silent":
            return                        # takes the report, never answers
        cmd = data[5]
        value = {H.CMD_BATTERY: self.level, H.CMD_CHARGING: self.charge}.get(cmd)
        r = [0x0C, 0x02, 0x03, 0x01, 0x00, cmd, 0xFF if value is None else value] + [0] * 57
        self.queue.append(r)

    def read(self, timeout_ms):
        if self.queue:
            return self.queue.pop(0)
        self.clock.now += timeout_ms / 1000
        return []


class FakeBus:
    def __init__(self, cols):
        self.cols = cols

    def device_class(self):
        bus = self

        class FakeDevice:
            def open_path(self, path):
                self.c = bus.cols[path]
                self.c.opened += 1

            def send_feature_report(self, data):
                self.c.feature(data)
                return len(data)

            def read(self, n, timeout_ms=0):
                return self.c.read(timeout_ms)

            def close(self):
                pass

        return FakeDevice


class Cloud3STest(unittest.TestCase):
    def setUp(self):
        self._saved = (H.hid, H.hidlist, H.time)
        self.clock = Clock()
        H.time = types.SimpleNamespace(time=self.clock.time, sleep=self.clock.sleep)
        self.provider = H.HyperXCloud3SProvider()

    def tearDown(self):
        H.hid, H.hidlist, H.time = self._saved

    def cols(self, target=b"ff13:0001", **kw):
        return {e["path"]: Headset(self.clock, e["path"] == target, **kw) for e in issue_106_entries()}

    def poll(self, cols, entries=None):
        entries = issue_106_entries() if entries is None else entries
        H.hid = types.SimpleNamespace(device=FakeBus(cols).device_class())
        H.hidlist = types.SimpleNamespace(enumerate=lambda vid=0: list(entries))
        return self.provider.poll()

    def test_issue_106(self):
        cols = self.cols(level=62)
        res = self.poll(cols)
        self.assertEqual([(r.name, r.level, r.charging, r.online, r.kind, r.key) for r in res],
                         [("HyperX Cloud III S Wireless", 62, False, True, "headset", "hyperx:02cc")])
        sent = cols[b"ff13:0001"].sent
        self.assertEqual(sent[0], [0x0C, 0x02, 0x03, 0x01, 0x00, 0x06] + [0] * 58)
        self.assertEqual(sent[1][:6], [0x0C, 0x02, 0x03, 0x01, 0x00, 0x48])

    def test_only_get_requests_are_sent(self):
        cols = self.cols()
        self.poll(cols)
        self.poll(cols)
        for c in cols.values():
            for pkt in c.sent:
                self.assertEqual(pkt[3], 0x01)          # 01 = get; 00 would set a value
                self.assertIn(pkt[5], (H.CMD_BATTERY, H.CMD_CHARGING))

    def test_whichever_collection_declares_the_report_is_found(self):
        for target in (b"ffc0:0202", b"170f:0202", b"000c:0001"):
            self.provider = H.HyperXCloud3SProvider()
            res = self.poll(self.cols(target))
            self.assertEqual([r.level for r in res], [62], target)

    def test_vendor_pages_are_tried_first_and_the_collection_is_remembered(self):
        cols = self.cols(b"ffc0:0202")
        self.poll(cols)
        self.assertEqual(cols[b"000c:0001"].opened, 0)     # not reached: ff13, ffc0 first
        before = {p: c.opened for p, c in cols.items()}
        self.poll(cols)
        after = {p: c.opened - before[p] for p, c in cols.items()}
        self.assertEqual({p for p, n in after.items() if n}, {b"ffc0:0202"})

    def test_charging_and_fully_charged(self):
        for state, flag in ((0, False), (1, True), (2, True), (7, False)):
            self.provider = H.HyperXCloud3SProvider()
            res = self.poll(self.cols(charge=state))
            self.assertEqual([r.charging for r in res], [flag], state)

    def test_switched_off_headset_gives_no_icon(self):
        cols = self.cols(level=None)                          # the dongle answers 0xFF
        self.assertEqual(self.poll(cols), [])
        self.assertEqual(self.poll(cols), [])

    def test_a_level_above_100_is_refused(self):
        self.assertEqual(self.poll(self.cols(level=0xC8)), [])

    def test_other_reports_before_the_reply_are_skipped(self):
        noise = [[0x0F, 0x01] + [0] * 62, [0x05, 0x02] + [0] * 62,
                 [0x0C, 0, 0, 0, 0, 0x04, 1] + [0] * 57]       # a mute reply
        cols = self.cols()
        cols[b"ff13:0001"].queue += noise
        self.assertEqual([r.level for r in self.poll(cols)], [62])

    def test_a_collection_that_takes_the_report_but_never_answers_is_passed_over(self):
        cols = self.cols(b"ffc0:0202")
        cols[b"ff13:0001"].accepts = "silent"
        self.assertEqual([r.level for r in self.poll(cols)], [62])
        self.assertEqual(self.provider._path[0x02CC], b"ffc0:0202")

    def test_a_charging_reply_is_not_taken_for_the_battery(self):
        cols = self.cols(level=62, charge=1)
        cols[b"ff13:0001"].queue += [[0x0C, 0x02, 0x03, 0x01, 0x00, 0x48, 1] + [0] * 57,
                                     [0x0D, 0, 0, 0, 10, 1] + [0] * 58]
        self.assertEqual([(r.level, r.charging) for r in self.poll(cols)], [(62, True)])

    def test_battery_notification_is_a_reading(self):
        self.assertEqual(H.parse([0x0D, 0, 0, 0, 1, 55, 0]), ("battery", 55))
        self.assertEqual(H.parse([0x0D, 0, 0, 0, 10, 1, 0]), ("charging", 1))
        self.assertIsNone(H.parse([0x0D, 0, 0, 0, 3, 1, 0]))         # mute
        self.assertIsNone(H.parse([0x0C, 0, 0, 0, 0, 0x06, 0xFF]))

    def test_cloud_iii_ids_are_not_touched(self):
        entries = [dict(e, product_id=0x05B7) for e in issue_106_entries()]
        cols = self.cols()
        self.assertEqual(self.poll(cols, entries), [])
        self.assertTrue(all(c.opened == 0 for c in cols.values()))




if __name__ == "__main__":
    unittest.main()
