"""Tests for the tray menu in flyout.py: colours, where the menu and its submenus
open, the - / + counter items and the size of a menu. No window is opened.

Run from the repository root:

    python -m unittest discover -s tests
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import flyout  # noqa: E402
from pystray import Menu, MenuItem as Item  # noqa: E402

WORK = (0, 0, 1920, 1032)         # a 1080p screen above a 48 px taskbar


class ColourTests(unittest.TestCase):
    def test_argb(self):
        self.assertEqual(flyout.parse_argb("#99202020"), (0x99, 0x20, 0x20, 0x20))
        self.assertEqual(flyout.parse_argb("#F2F2F2"), (0xFF, 0xF2, 0xF2, 0xF2))

    def test_gradient_colour_is_abgr(self):
        self.assertEqual(flyout.abgr("#99112233"), 0x99332211)

    def test_translucent_colours_are_laid_over_the_tint(self):
        dark = flyout.colours(False)
        self.assertEqual(dark["text"], "#f2f2f2")
        self.assertEqual(dark["muted"], "#9e9e9e")        # 60 % of #F2F2F2 over #202020
        light = flyout.colours(True)
        self.assertEqual(light["text"], "#1a1a1a")

    def test_transparent_key_is_next_to_the_tint_and_not_a_used_colour(self):
        for light in (False, True):
            c = flyout.colours(light)
            self.assertNotIn(c["key"], (c["text"], c["muted"], c["separator"], c["border"]))
            tint = flyout.parse_argb(flyout.PALETTE[light]["tint"])[1:]
            key = flyout.parse_argb(c["key"])[1:]
            self.assertLessEqual(max(abs(a - b) for a, b in zip(tint, key)), 1)

    def test_hover_keeps_its_opacity(self):
        self.assertAlmostEqual(flyout.colours(False)["hover_alpha"], 0x1A / 255)
        self.assertEqual(flyout.colours(False)["hover"], "#ffffff")
        self.assertEqual(flyout.colours(True)["hover"], "#000000")


class PlacementTests(unittest.TestCase):
    # taskbars on a 1920x1080 screen, 48 px thick
    BOTTOM = (0, 1032, 1920, 1080)

    def test_bottom_taskbar_centred_on_the_click_with_a_gap(self):
        self.assertEqual(flyout.place_menu(1500, 1050, 250, 300, WORK, self.BOTTOM), (1375, 724))

    def test_top_taskbar(self):
        work = (0, 48, 1920, 1080)
        self.assertEqual(flyout.place_menu(1500, 20, 250, 300, work, (0, 0, 1920, 48)), (1375, 56))

    def test_right_taskbar_centred_vertically(self):
        work = (0, 0, 1872, 1080)
        self.assertEqual(flyout.place_menu(1890, 500, 250, 300, work, (1872, 0, 1920, 1080)),
                         (1614, 350))

    def test_left_taskbar(self):
        work = (48, 0, 1920, 1080)
        self.assertEqual(flyout.place_menu(20, 500, 250, 300, work, (0, 0, 48, 1080)), (56, 350))

    def test_kept_off_the_screen_edges(self):
        # a click at the far right: the menu stops 8 px from the edge
        self.assertEqual(flyout.place_menu(1910, 1050, 250, 300, WORK, self.BOTTOM), (1662, 724))
        # a vertical taskbar and a click near the bottom
        work = (0, 0, 1872, 1080)
        self.assertEqual(flyout.place_menu(1890, 1070, 250, 300, work, (1872, 0, 1920, 1080)),
                         (1614, 780))

    def test_gap_scales(self):
        self.assertEqual(flyout.place_menu(1500, 1050, 250, 300, WORK, self.BOTTOM, 1.5), (1375, 720))

    def test_without_a_taskbar_centred_above_the_cursor(self):
        self.assertEqual(flyout.place_menu(1000, 800, 250, 300, WORK), (875, 492))

    def test_submenu_to_the_right_with_overlap_and_raised(self):
        self.assertEqual(flyout.place_submenu(1000, 1250, 800, 200, 150, WORK), (1248, 795))

    def test_submenu_to_the_left_without_room(self):
        self.assertEqual(flyout.place_submenu(1600, 1850, 800, 200, 150, WORK), (1402, 795))

    def test_submenu_scaled(self):
        # 150 %: overlap 3 px, 8 px higher (5 * 1.5 rounded)
        self.assertEqual(flyout.place_submenu(1000, 1250, 800, 200, 150, WORK, 1.5), (1247, 792))

    def test_submenu_stays_on_the_screen(self):
        x, y = flyout.place_submenu(1000, 1250, 1000, 200, 150, WORK)
        self.assertEqual(y, WORK[3] - 150)


class TaskbarAreaTests(unittest.TestCase):
    """The menu and its submenus stay off the taskbar even when the work area includes
    it: an auto-hide taskbar, or the taskbar over a full screen game (reported with
    Dota 2: the bottom rows of the menu were behind the taskbar)."""
    SCREEN = (0, 0, 1920, 1080)

    def test_bottom_taskbar_is_cut_off(self):
        self.assertEqual(flyout.usable_area(self.SCREEN, (0, 1032, 1920, 1080)), (0, 0, 1920, 1032))

    def test_top_left_and_right_taskbars(self):
        self.assertEqual(flyout.usable_area(self.SCREEN, (0, 0, 1920, 48)), (0, 48, 1920, 1080))
        self.assertEqual(flyout.usable_area(self.SCREEN, (0, 0, 48, 1080)), (48, 0, 1920, 1080))
        self.assertEqual(flyout.usable_area(self.SCREEN, (1872, 0, 1920, 1080)), (0, 0, 1872, 1080))

    def test_a_work_area_without_the_taskbar_is_unchanged(self):
        # the usual case: Windows already left the taskbar out
        self.assertEqual(flyout.usable_area(WORK, (0, 1032, 1920, 1080)), WORK)
        self.assertEqual(flyout.usable_area(WORK, None), WORK)

    def test_a_hidden_auto_hide_taskbar_leaves_its_visible_edge_out(self):
        # hidden, it keeps a 2 px edge on the screen
        self.assertEqual(flyout.usable_area(self.SCREEN, (0, 1078, 1920, 1126)), (0, 0, 1920, 1078))

    def test_a_taskbar_on_another_monitor_is_ignored(self):
        self.assertEqual(flyout.usable_area(self.SCREEN, (1920, 1032, 3840, 1080)), self.SCREEN)

    def test_a_long_submenu_opens_above_the_taskbar(self):
        # Preferences near the bottom of a full screen game: 500 px tall
        area = flyout.usable_area(self.SCREEN, (0, 1032, 1920, 1080))
        x, y = flyout.place_submenu(1000, 1250, 900, 250, 500, area)
        self.assertLessEqual(y + 500, 1032)

    def test_the_menu_passes_the_area_without_the_taskbar_to_its_submenus(self):
        import types
        seen = {}

        class FakeWin32:
            def monitor(self, x, y):
                return (0, 0, 1920, 1080), 1.0          # the work area includes the taskbar

            def taskbar(self, x, y):
                return (0, 1032, 1920, 1080)

            def buttons_down(self):
                return False

            def activate(self, hwnd):
                pass

        class FakePanel:
            def __init__(self, host, menu, style, parent, row):
                self.rows, self.w, self.h, self.hwnd = [1], 250, 300, 1
                self.win = types.SimpleNamespace(focus_force=lambda: None)

            def open(self, x, y):
                seen["y"] = y

            def destroy(self):
                pass

        host = flyout.FlyoutHost(FakeWin32())
        host._root = types.SimpleNamespace(after=lambda *a: None, after_cancel=lambda *a: None)
        host.style = lambda scale, light: types.SimpleNamespace(scale=scale)
        saved = flyout._Panel
        flyout._Panel = FakePanel
        try:
            host._show(None, None, (1500, 1050))
        finally:
            flyout._Panel = saved
        self.assertEqual(host.panels[0].work, (0, 0, 1920, 1032))
        self.assertLessEqual(seen["y"] + 300, 1032)


class CounterTests(unittest.TestCase):
    def make(self, value=20):
        cfg = {"low": value}
        item = flyout.CounterItem("Low battery alert", [(0, "Off"), (10, "10%"), (20, "20%"), (30, "30%")],
                                  lambda: cfg["low"], lambda v: cfg.__setitem__("low", v))
        return item, cfg

    def test_steps_through_the_choices(self):
        item, cfg = self.make(20)
        self.assertEqual(item.label(), "20%")
        self.assertTrue(item.step(+1))
        self.assertEqual(cfg["low"], 30)
        self.assertFalse(item.step(+1))              # at the end
        self.assertEqual(cfg["low"], 30)
        item.step(-1), item.step(-1), item.step(-1)
        self.assertEqual(item.label(), "Off")
        self.assertFalse(item.can_step(-1))

    def test_a_value_between_the_choices_counts_as_the_nearest(self):
        item, _cfg = self.make(12)
        self.assertEqual(item.label(), "10%")

    def test_classic_menu_sees_a_radio_submenu(self):
        item, cfg = self.make(10)
        sub = item.submenu
        self.assertEqual([i.text for i in sub.items], ["Off", "10%", "20%", "30%"])
        self.assertEqual([i.checked for i in sub.items], [False, True, False, False])
        sub.items[3](None)
        self.assertEqual(cfg["low"], 30)


class FakeStyle:
    """_Style without tkinter: 7 px per character, 17 px line."""

    def __init__(self, scale=1.0):
        self.scale = scale
        self.px = lambda v: max(1, round(v * scale))
        self.line = round(17 * scale)
        self.icon_family = "Segoe Fluent Icons"

    def glyph(self, g):
        return g


def measure(text):
    return 7 * len(text)


class LayoutTests(unittest.TestCase):
    def menu(self):
        cfg = {"low": 20}
        return Menu(
            Item("Header", None, enabled=False),
            Menu.SEPARATOR,
            Item("Refresh now", lambda: None),
            Item("Hidden", lambda: None, visible=False),
            Item("Preferences", Menu(Item("A", lambda: None))),
            flyout.CounterItem("Low battery alert", [(0, "Off"), (20, "20%")],
                               lambda: cfg["low"], lambda v: None),
            Item("Checked", lambda: None, checked=lambda i: True),
        )

    def test_rows_follow_the_visible_items(self):
        rows = flyout.build_rows(self.menu())
        self.assertEqual([r.kind for r in rows], ["item", "sep", "item", "item", "counter", "item"])
        self.assertFalse(rows[0].selectable)
        self.assertFalse(rows[1].selectable)
        self.assertIsNotNone(rows[3].submenu)
        self.assertTrue(rows[5].checked)

    def test_sizes_at_100_percent(self):
        rows = flyout.build_rows(self.menu())
        w, h = flyout.layout(rows, FakeStyle(), measure, lambda g: 10)
        # the widest row is the counter: text, 16 px gap, - (28) value (34) + (28)
        self.assertEqual(w, 4 + 8 + 24 + 7 * 17 + 16 + 28 + 34 + 28 + 10 + 4)
        item_h = 1 + 6 + 17 + 6 + 1
        sep_h = 4 + 1 + 4
        self.assertEqual(rows[0].y, 4)
        self.assertEqual(rows[0].h, item_h)
        self.assertEqual(rows[1].h, sep_h)
        self.assertEqual(rows[4].h, item_h)                        # the 26 px buttons fit
        self.assertEqual(h, 4 + 5 * item_h + sep_h + 4)

    def test_everything_scales(self):
        rows = flyout.build_rows(self.menu())
        w1, h1 = flyout.layout(rows, FakeStyle(1.0), measure, lambda g: 10)
        rows = flyout.build_rows(self.menu())
        w2, h2 = flyout.layout(rows, FakeStyle(1.5), lambda t: round(measure(t) * 1.5), lambda g: 15)
        self.assertAlmostEqual(w2 / w1, 1.5, delta=0.01)
        self.assertAlmostEqual(h2 / h1, 1.5, delta=0.05)

    def test_minimum_width(self):
        rows = flyout.build_rows(Menu(Item("Exit", lambda: None)))
        self.assertEqual(flyout.layout(rows, FakeStyle(), measure, lambda g: 10)[0], 230)
        rows = flyout.build_rows(Menu(Item("Exit", lambda: None)))
        self.assertEqual(flyout.layout(rows, FakeStyle(1.25), measure, lambda g: 10)[0], 288)

    def test_a_long_text_widens_the_menu(self):
        rows = flyout.build_rows(Menu(Item("x" * 40, lambda: None)))
        w, _h = flyout.layout(rows, FakeStyle(), measure, lambda g: 10)
        self.assertEqual(w, 4 + 8 + 24 + 280 + 10 + 4)


if __name__ == "__main__":
    unittest.main()
