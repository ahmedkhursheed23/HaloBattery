"""Tests for providers/ajazz_kb.py - the AK820 Max Ultra (#256).

The frames come from AJAZZ's online driver as documented by wsclx/ak820pro-modder:

    request   00 | AA 10 00 00 00 ...       0x10 = GET_DEVICE_INFO (report id 0)
    reply     [00 |] 55 10 .. .. .. .. .. .. <payload>
    payload   17 = level, 18 = charge status

Run from the repository root:

    python -m unittest discover -s tests
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from providers import ajazz_kb as A  # noqa: E402


def reply(level=96, charge=0x00, cmd=A.GET_DEVICE_INFO, magic=A.IN_MAGIC, report_id=None):
    r = [0x00] * A.FRAME_LEN
    r[0] = magic
    r[1] = cmd
    r[A.PAYLOAD_OFFSET + 17] = level
    r[A.PAYLOAD_OFFSET + 18] = charge
    return r if report_id is None else [report_id] + r


class FrameTest(unittest.TestCase):
    def test_the_request_is_report_id_zero_then_device_info(self):
        req = A.make_request()
        self.assertEqual([0x00, A.OUT_MAGIC, A.GET_DEVICE_INFO], req[:3])
        self.assertEqual(A.WIRE_LEN, len(req))

    def test_the_documented_reply_carries_the_level(self):
        self.assertEqual((96, False), A.parse_reply(reply(96)))

    def test_a_reply_that_keeps_the_report_id_in_front_is_read_too(self):
        self.assertEqual((96, False), A.parse_reply(reply(96, report_id=0x00)))
        self.assertEqual((80, True), A.parse_reply(reply(80, charge=0x01, report_id=0x00)))

    def test_charging_comes_from_payload_byte_18(self):
        self.assertEqual((80, True), A.parse_reply(reply(80, charge=0x01)))

    def test_another_magic_or_command_is_not_a_reply(self):
        self.assertIsNone(A.parse_reply(reply(96, magic=0xAA)))
        self.assertIsNone(A.parse_reply(reply(96, cmd=0x11)))

    def test_zero_means_no_reading(self):
        self.assertIsNone(A.parse_reply(reply(0)))

    def test_an_interrupt_frame_too_short_is_ignored(self):
        self.assertIsNone(A.parse_reply(reply(96)[:20]))


class FakeDevice:
    def __init__(self, frames):
        self.frames = list(frames)
        self.opened = []
        self.written = []

    def open_path(self, path):
        self.opened.append(path)

    def write(self, data):
        self.written.append(bytes(data))
        return len(data)

    def read(self, length, timeout_ms=0):
        return self.frames.pop(0) if self.frames else []

    def close(self):
        pass


class PollTest(unittest.TestCase):
    INFO = [
        {"path": b"if2", "interface_number": 2, "usage_page": 0xFF80, "usage": 1,
         "product_id": A.PID, "product_string": "AJAZZ AK820MAX"},
        {"path": b"if3", "interface_number": 3, "usage_page": 0xFF70, "usage": 0x71,
         "product_id": A.PID, "product_string": "AJAZZ AK820MAX"},
    ]

    def setUp(self):
        self._saved = (A.hid, A.hidlist)

    def tearDown(self):
        A.hid, A.hidlist = self._saved

    def poll(self, frames, infos=None):
        dev = FakeDevice(frames)
        A.hid = type("H", (), {"device": staticmethod(lambda: dev)})
        A.hidlist = type("L", (), {"enumerate": staticmethod(
            lambda vid=0: list(self.INFO if infos is None else infos))})
        out = A.AjazzKeyboardProvider().poll()
        return out, dev

    def test_the_interface_three_page_is_asked_first(self):
        out, dev = self.poll([reply(96)])
        self.assertEqual([(s.key, s.name, s.level, s.charging, s.online, s.kind) for s in out],
                         [("ajazz-kb:fefc", "AJAZZ AK820 Max Ultra", 96, False, True, "keyboard")])
        self.assertEqual([b"if3"], dev.opened)
        self.assertEqual([bytes(A.make_request())], dev.written)

    def test_the_charging_state_is_reported(self):
        out, _dev = self.poll([reply(70, charge=1)])
        self.assertTrue(out[0].charging)

    def test_no_answer_is_an_unknown_reading(self):
        out, _dev = self.poll([])
        self.assertIsNone(out[0].level)
        self.assertFalse(out[0].online)

    def test_no_receiver_reports_nothing(self):
        out, _dev = self.poll([], infos=[])
        self.assertEqual([], out)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
