"""Razer Barracuda X (2.4 GHz dongle) tests; no hardware is opened.

Request, reply prefix and layout: github.com/GigaVibeSlopper67/Barracuda_X_Helpers
@ 0f2038b50e6ec1a0f898b398c567e3b6060aceb8 (barracuda_battery.py). Its author
validated discharge, charge and full states on 1532:0536. The frames below are built
from that layout (status byte [9], millivolts [12:14], percent [14]); they are not
captures.

Run: python -m unittest discover -s tests
"""
import os
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from providers import blackshark2020
from providers.razer import RazerProvider, maybe_wireless


def frame(hex_data):
    return bytes.fromhex(hex_data).ljust(64, b"\x00")


DISCHARGING = frame("ff 0f 05 fe 12 04 1f 08 05 03 05 01 10 20 50")   # 4128 mV, 80
CHARGING = frame("ff 0f 05 fe 12 04 1f 08 05 05 03 09 10 20 50")
FULL = frame("ff 0f 05 fe 12 04 1f 08 05 06 05 06 10 88 64")
EMPTY_CACHE = frame("ff 01 00")

PIDS = (0x0536, 0x0552, 0x0574)


def iface(pid, path=b"vendor", usage_page=0xFF00, usage=1, n=3):
    return dict(product_id=pid, serial_number="", path=path, usage_page=usage_page,
                usage=usage, interface_number=n, product_string="Hid Interface")


class ReadTests(unittest.TestCase):
    def read(self, replies):
        dev = Mock()
        dev.send_feature_report.return_value = 64
        dev.get_feature_report.side_effect = replies
        with patch.object(blackshark2020.hid, "device", return_value=dev), \
                patch.object(blackshark2020.time, "sleep"):
            result = blackshark2020.read_battery_barracuda_x(b"dongle", [])
        # byte for byte the request the helper sends (and the 2020 headset uses)
        dev.send_feature_report.assert_called_once_with(
            bytes([0xFF, 0x0A, 0x00, 0xFD, 0x04, 0x12, 0xF1, 0x02, 0x05] + [0] * 55))
        dev.get_feature_report.assert_called_with(0xFF, 64)
        dev.close.assert_called_once()
        return result

    def test_status_map(self):
        self.assertEqual(self.read([DISCHARGING]), ("ok", 80, False))
        self.assertEqual(self.read([CHARGING]), ("ok", 80, True))
        self.assertEqual(self.read([FULL]), ("ok", 100, False))

    def test_unknown_status_keeps_level(self):
        for state in range(256):
            if state in (0x03, 0x05, 0x06):
                continue
            with self.subTest(state=state):
                data = bytearray(DISCHARGING)
                data[9] = state
                self.assertEqual(self.read([data]), ("ok", 80, None))

    def test_status_is_byte_9_not_byte_11(self):
        data = bytearray(CHARGING)
        data[11] = 0x01   # the 2020 headset would read this as "not charging"
        self.assertEqual(self.read([data]), ("ok", 80, True))

    def test_implausible_level_is_dropped(self):
        data = bytearray(DISCHARGING)
        data[14] = 101
        self.assertEqual(self.read([data]), ("ok", None, False))

    def test_empty_cache_is_not_zero_percent(self):
        with patch.object(blackshark2020.time, "monotonic", side_effect=[0, 1]):
            self.assertEqual(self.read([EMPTY_CACHE]), ("fail", None, False))

    def test_short_write_fails(self):
        dev = Mock()
        dev.send_feature_report.return_value = -1
        with patch.object(blackshark2020.hid, "device", return_value=dev):
            self.assertEqual(blackshark2020.read_battery_barracuda_x(b"dongle", []),
                             ("fail", None, False))
        dev.get_feature_report.assert_not_called()
        dev.close.assert_called_once()

    def test_2020_headset_status_map_unchanged(self):
        data = bytearray(CHARGING)    # byte 11 = 0x09 -> charging, level hidden
        dev = Mock()
        dev.send_feature_report.return_value = 64
        dev.get_feature_report.side_effect = [bytes(data)]
        with patch.object(blackshark2020.hid, "device", return_value=dev), \
                patch.object(blackshark2020.time, "sleep"):
            self.assertEqual(blackshark2020.read_battery(b"x", []), ("ok", None, True))


class RoutingTests(unittest.TestCase):
    def poll(self, ifaces, reply=None):
        p = RazerProvider()
        with patch("providers.razer.hidlist.enumerate", return_value=ifaces), \
                patch.object(blackshark2020, "read_battery_barracuda_x",
                             return_value=reply or ("ok", 80, False)) as read, \
                patch.object(p, "_poll_group") as generic, patch.object(p, "_poll_pa") as pa:
            out = p.poll()
        return out, read, generic, pa

    def test_barracuda_x_ids_use_the_feature_read_only(self):
        for pid in PIDS:
            with self.subTest(pid=pid):
                ifaces = [iface(pid, b"consumer", 0x0C), iface(pid, b"cfg", 0xFFC0),
                          iface(pid, b"vendor")]
                out, read, generic, pa = self.poll(ifaces)
                self.assertEqual(len(out), 1)
                self.assertEqual((out[0].level, out[0].charging, out[0].online), (80, False, True))
                self.assertEqual(out[0].name, blackshark2020.BARRACUDA_X_NAMES[pid])
                self.assertEqual(read.call_args.args[0], b"vendor")
                read.assert_called_once()
                generic.assert_not_called()   # no mouse request
                pa.assert_not_called()        # no PA probe

    def test_ids_are_wireless_even_with_a_generic_product_string(self):
        for pid in PIDS:
            self.assertTrue(maybe_wireless(pid, "Hid Interface"))

    def test_0550_is_not_routed_here(self):
        # 1532:0550 is not in the source's list; it keeps the old path until tested.
        self.assertNotIn(0x0550, blackshark2020.BARRACUDA_X_NAMES)
        p = RazerProvider()
        with patch("providers.razer.hidlist.enumerate",
                   return_value=[dict(iface(0x0550), product_string="Razer Barracuda X 2.4")]), \
                patch.object(blackshark2020, "read_battery_barracuda_x") as read, \
                patch.object(p, "_poll_group", return_value=None) as generic:
            p.poll()
        read.assert_not_called()
        generic.assert_called_once()

    def test_offline_dongle_shows_nothing(self):
        out, *_ = self.poll([iface(0x0536)], ("offline", None, False))
        self.assertEqual(out, [])

    def test_barracuda_pro_and_2020_keep_their_paths(self):
        p = RazerProvider()
        with patch("providers.razer.hidlist.enumerate", return_value=[iface(0x053A)]), \
                patch.object(blackshark2020, "read_battery_barracuda_x") as read:
            self.assertEqual(p.poll(), [])
        read.assert_not_called()


if __name__ == "__main__":
    unittest.main()
