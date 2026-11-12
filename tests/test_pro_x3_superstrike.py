"""PRO X3 SUPERSTRIKE HID++ collection regression tests (no hardware required).

Run at the repository root:
    python -m unittest discover -s tests
"""
from test_logitech import LogitechTestCase, FakeHidpp, entry, L


class ProX3SuperstrikeTests(LogitechTestCase):
    def device(self):
        return FakeHidpp(
            {L.F_UNIFIED: (6, {1: [73, 0, 0]}), L.F_NAME: (3, {2: [3]})},
            name="PRO X3 SUPERSTRIKE",
        )

    def test_c54f_lightspeed_receiver(self):
        entries = [
            entry(0xC54F, 0xFF43, 0x0301, b"short", "LIGHTSPEED"),
            entry(0xC54F, 0xFF43, 0x0302, b"long", "LIGHTSPEED"),
        ]
        bus = self.use(entries, {b"long": ({1: self.device()}, b"short")})
        results = L.LogitechProvider().poll()
        self.assertEqual(len(results), 1)
        self.assertEqual((results[0].name, results[0].level),
                         ("PRO X3 SUPERSTRIKE", 73))
        self.assertTrue(any(path == b"long" and packet[1] == 1
                            for path, packet in bus.writes))

    def test_c54d_receiver(self):
        entries = [entry(0xC54D, 0xFF43, 0x0302, b"long", "LIGHTSPEED")]
        self.use(entries, {b"long": ({1: self.device()}, None)})
        results = L.LogitechProvider().poll()
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].level, 73)

    def test_c0a9_wired_mouse(self):
        entries = [entry(0xC0A9, 0xFF43, 0x0302, b"long", "PRO X3")]
        self.use(entries, {b"long": ({0xFF: self.device()}, None)})
        results = L.LogitechProvider().poll()
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].level, 73)

    def test_unknown_pid_must_not_claim_ff43(self):
        entries = [entry(0xC539, 0xFF43, 0x0302, b"long", "LIGHTSPEED")]
        self.use(entries, {b"long": ({1: self.device()}, None)})
        self.assertEqual(L.LogitechProvider().poll(), [])

    def test_existing_ff00_collection_takes_priority(self):
        entries = [
            entry(0xC54F, 0xFF00, 2, b"ordinary", "LIGHTSPEED"),
            entry(0xC54F, 0xFF43, 0x0302, b"pro-x3", "LIGHTSPEED"),
        ]
        groups = L.LogitechProvider._collections(entries)
        self.assertEqual(next(iter(groups.values()))[2], b"ordinary")
