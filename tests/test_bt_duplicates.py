"""Tests for drop_bluetooth_duplicates() in halo_battery.pyw: one icon per device,
not one per transport. No tray, no hardware.

Run from the repository root:

    python -m unittest discover -s tests
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_hide_rename import hb  # noqa: E402
from providers.base import DeviceStatus  # noqa: E402


def bt(name="Razer Barracuda Pro", level=80):
    return DeviceStatus("bt:" + name, name, level, False, True, "bluetooth", kind="headset")


def dongle(level=None, online=False):
    # what BarracudaProvider returns when the receiver is plugged in but the headset
    # does not answer on it (level None, online False)
    return DeviceStatus("barracuda:053a", "Razer Barracuda Pro (2.4 GHz)", level,
                        False, online, "barracuda", kind="headset")


def keys(results):
    return [st.key for st in results]


class BluetoothDuplicateTests(unittest.TestCase):
    def test_live_hid_reading_drops_the_bluetooth_copy(self):
        out = hb.drop_bluetooth_duplicates([dongle(75, True), bt()], set())
        self.assertEqual(keys(out), ["barracuda:053a"])

    def test_dongle_without_link_keeps_the_bluetooth_reading(self):
        # headset connected to the PC over Bluetooth, its 2.4 GHz receiver still plugged in
        out = hb.drop_bluetooth_duplicates([dongle(None, False), bt()], set())
        self.assertIn("bt:Razer Barracuda Pro", keys(out))

    def test_greyed_hid_entry_keeps_the_bluetooth_reading(self):
        # a mouse switched to its Bluetooth channel: the receiver entry keeps its last
        # value greyed out (online False) for a while
        mouse = DeviceStatus("razer:00b6:1", "Razer DeathAdder V3 Pro", 60, False, False,
                             "razer", kind="mouse")
        out = hb.drop_bluetooth_duplicates([mouse, bt("Razer DeathAdder V3 Pro", 61)], set())
        self.assertIn("bt:Razer DeathAdder V3 Pro", keys(out))

    def test_online_hid_entry_without_level_keeps_the_bluetooth_reading(self):
        out = hb.drop_bluetooth_duplicates([dongle(None, True), bt()], set())
        self.assertIn("bt:Razer Barracuda Pro", keys(out))


if __name__ == "__main__":
    unittest.main()
