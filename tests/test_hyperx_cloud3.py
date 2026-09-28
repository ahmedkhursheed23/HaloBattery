"""Tests for providers/hyperx_cloud3.py. No hardware is needed.

The fake dongle answers as LennardKittner/HyperHeadset's cloud_iii_wireless code
describes: report 0x66, the command echo, then the battery percent at byte 4. The
tests cover how the request reaches the dongle: cython-hidapi's write() and
send_feature_report() return -1 on failure instead of raising, and hid.device.error()
then gives the Windows error text.

Run from the repository root:

    python -m unittest discover -s tests
"""
import os
import sys
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from providers import hyperx_cloud3 as H  # noqa: E402

PATH = b"\\\\?\\hid#vid_03f0&pid_05b7&mi_03&col01#8&1234abcd&0&0000#{4d1e55b2-f16f-11cf-88cb-001111000030}"

# hidapi 0.14's Windows text for ERROR_INVALID_FUNCTION.
INCORRECT_FUNCTION = "WriteFile: (0x00000001) Incorrect function."


class FakeDongle:
    """write / feature: how that call answers.
    "ok"     accepted (returns the length, as hidapi does)
    "-1"     returns -1, as cython-hidapi does on failure
    "raise"  raises OSError with `error_text`
    """

    def __init__(self, write="ok", feature="ok", error_text=INCORRECT_FUNCTION,
                 level=80, charging=1):
        self.write_mode = write
        self.feature_mode = feature
        self.error_text = error_text
        self.level = level
        self.charging = charging
        self.writes = []
        self.features = []
        self.pending = []

    # hid.device API
    def open_path(self, path):
        pass

    def close(self):
        pass

    def error(self):
        return self.error_text

    def _answer(self, packet):
        cmd = packet[1]
        r = [H.REPORT_ID, cmd] + [0] * 60
        if cmd == H.CMD_BATTERY:
            r[2], r[4] = 1, self.level
        elif cmd == H.CMD_CHARGING:
            r[2] = self.charging
        self.pending.append(r)

    def _do(self, mode, packet):
        if mode == "raise":
            raise OSError(self.error_text)
        if mode == "-1":
            return -1
        self._answer(packet)
        return len(packet)

    def write(self, packet):
        self.writes.append(list(packet))
        return self._do(self.write_mode, packet)

    def send_feature_report(self, packet):
        self.features.append(list(packet))
        return self._do(self.feature_mode, packet)

    def read(self, n, timeout_ms=0):
        return self.pending.pop(0) if self.pending else []


class Base(unittest.TestCase):
    def setUp(self):
        self._saved = (H.hid, H.hidlist, H.time)
        H.time = types.SimpleNamespace(sleep=lambda s: None)

    def tearDown(self):
        H.hid, H.hidlist, H.time = self._saved

    def poll(self, dongle):
        H.hid = types.SimpleNamespace(device=lambda: dongle)
        entry = {"product_id": 0x05B7, "path": PATH, "interface_number": 3,
                 "usage_page": H.USAGE_PAGE, "usage": H.USAGE}
        H.hidlist = types.SimpleNamespace(enumerate=lambda vid=0: [entry])
        p = H.HyperXCloud3Provider()
        out = p.poll()
        return out, p.diagnostics()


class WritePath(Base):
    def test_write_accepted(self):
        d = FakeDongle(write="ok")
        out, diag = self.poll(d)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].level, 80)
        self.assertTrue(out[0].charging)
        self.assertEqual(d.features, [])

    def test_write_minus_one_then_feature_report_accepted(self):
        d = FakeDongle(write="-1", feature="ok")
        out, diag = self.poll(d)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].level, 80)
        self.assertTrue(out[0].charging)
        # The same packet goes out as a feature report, for both commands.
        self.assertEqual(d.features, d.writes)
        self.assertEqual([f[1] for f in d.features], [H.CMD_BATTERY, H.CMD_CHARGING])
        self.assertTrue(any("retrying as a feature report" in line for line in diag), diag)
        self.assertTrue(any("feature report accepted" in line for line in diag), diag)

    def test_write_minus_one_and_feature_minus_one(self):
        d = FakeDongle(write="-1", feature="-1")
        out, diag = self.poll(d)
        self.assertEqual(out, [])
        self.assertEqual(len(d.features), 1)
        self.assertFalse(any("feature report accepted" in line for line in diag), diag)
        self.assertTrue(any(line.strip().startswith("feature report ->") for line in diag), diag)

    def test_write_minus_one_other_error_no_fallback(self):
        # Only "Incorrect function" means the dongle wants a feature report.
        d = FakeDongle(write="-1", error_text="WriteFile: (0x0000001F) A device attached "
                                             "to the system is not functioning.")
        out, diag = self.poll(d)
        self.assertEqual(out, [])
        self.assertEqual(d.features, [])
        self.assertTrue(any("not functioning" in line for line in diag), diag)

    def test_write_raises_incorrect_function_then_feature_report(self):
        d = FakeDongle(write="raise", feature="ok")
        out, diag = self.poll(d)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].level, 80)
        self.assertEqual(len(d.features), 2)

    def test_write_raises_other_error_no_fallback(self):
        d = FakeDongle(write="raise", error_text="device disconnected")
        out, diag = self.poll(d)
        self.assertEqual(out, [])
        self.assertEqual(d.features, [])


if __name__ == "__main__":
    unittest.main()
