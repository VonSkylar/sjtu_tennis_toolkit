"""Guards for the shared JavaScript probe fragments.

The probes are JavaScript strings, so a typo inside one cannot fail a Python
import -- it only shows up as a probe that quietly stops matching on the live
booking page. Two cheap guards catch most of that:

* every fragment is handed to ``node`` for a syntax check (skipped when node is
  missing), and
* the duplicated helpers are asserted to have exactly one definition, so a
  future edit cannot quietly grow a private copy again.

Neither guard can prove the selectors still match the real page. Only the page
can, which is why the numbers live in ``constants`` where a redesign has one
place to change.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import queue
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from sjtu_tennis_toolkit.browser import js_snippets
from sjtu_tennis_toolkit.browser.monitor import VenueMonitor
from sjtu_tennis_toolkit.browser.rusher import RushBooker
from sjtu_tennis_toolkit.constants import BOOKING_GRID_GEOMETRY
from sjtu_tennis_toolkit.models import (
    MonitorConfig,
    RushTimeSlot,
    Slot,
    VENUES_BY_KEY,
)

TARGET_DATE = dt.date(2026, 9, 20)

PACKAGE_ROOT = Path(__file__).resolve().parent.parent / "sjtu_tennis_toolkit"
PROBE_MODULES = ("booking_actions.py", "monitor.py", "rusher.py")

#: Text that used to be copy-pasted into every probe. It may only exist in the
#: shared fragment module now.
DUPLICATED_MARKERS = (
    "const visible = (el) => {",
    "const norm = (text) =>",
    "const norm = (value) =>",
    "Array.from(document.querySelectorAll('body *')).filter(visible)",
    "const gridLeft = Math.min",
    "b >= 185",
    "g >= 130",
    "Math.abs(r - g) <= 18",
    "item.rect.width >= 25",
    "Math.abs(item.centerX - targetX) <= 60",
    "court <= 8",
    "candidates.length >= 8",
)

NODE_CHECK_SCRIPT = """
const fs = require('fs');
const fragments = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
let failed = 0;
fragments.forEach((fragment, index) => {
  try {
    new Function('return (' + fragment + ');');
  } catch (error) {
    failed += 1;
    console.log('fragment ' + index + ': ' + error.message);
  }
});
process.exit(failed === 0 ? 0 : 1);
"""


def find_node() -> str | None:
    """Locate a node binary, or None when the machine has none."""
    candidates = [os.environ.get("SJTU_TENNIS_NODE"), shutil.which("node")]
    home = Path.home()
    for pattern in (".workbuddy/binaries/node/versions/*/node.exe", ".workbuddy/binaries/node/versions/*/bin/node"):
        candidates.extend(
            str(path) for path in sorted(home.glob(pattern), reverse=True)
        )
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    return None


class FakePage:
    """Answers each probe with the shape it expects to read back."""

    def __init__(self) -> None:
        self.fragments: list[str] = []
        self.arguments: list[object] = []
        self.mouse = self

    def click(self, *_args) -> None:
        return None

    def wait_for_timeout(self, _milliseconds: int) -> None:
        return None

    def evaluate(self, expression, arg=None):
        self.fragments.append(expression)
        self.arguments.append(arg)
        if "innerWidth" in expression:
            return {"width": 1400, "height": 950}
        if "classify" in expression:
            return {"state": "unknown", "reason": "fake", "x": 1.0, "y": 1.0}
        if "candidateCount" in expression:
            return {"slots": [], "candidateCount": 0}
        if "readyCount" in expression:
            return {"ready": True, "targetFound": True, "dateCount": 9}
        if "courtSet" in expression:
            return {"ready": True, "reason": "fake"}
        if "预订须知" in expression:
            return {"ok": True, "reason": "fake"}
        if "el-message" in expression and "node.remove" not in expression:
            return ""
        if "button" in expression:
            return {"x": 1.0, "y": 1.0}
        if "scrollIntoView" in expression:
            return {"ok": True}
        return {}


def collect_fragments() -> FakePage:
    """Send every probe through a :class:`FakePage` and return what it saw."""
    venue = VENUES_BY_KEY["east"]
    config = MonitorConfig(
        venues=(venue,),
        dates=(TARGET_DATE,),
        start_hour=7,
        end_hour=11,
        check_interval_seconds=20,
        auto_order_enabled=True,
        huxiaoming_court_scope="all",
    )
    page = FakePage()
    monitor = VenueMonitor(lambda: config, queue.Queue())
    booker = RushBooker(lambda: config, queue.Queue())
    slot = Slot("east", venue.name, TARGET_DATE, "场地2", "08:00")

    monitor._extract_available_slots(page, config, TARGET_DATE, venue)
    monitor._slot_cell_state(page, slot)
    monitor._scroll_slot_into_view(page, slot)
    monitor._click_visible_text_button(page, "立即下单", timeout=10)
    monitor._accept_booking_notice_fast(page)
    monitor._notice_text(page)
    monitor._is_click_point_in_viewport(page, 1.0, 1.0)
    monitor._selected_order_matches_slot(page, slot)
    booker._date_tab_state(page, TARGET_DATE)
    booker._target_grid_state(page, RushTimeSlot(8, 9))
    return page


class SharedFragmentTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.page = collect_fragments()

    def test_grid_probe_always_appends_the_geometry_argument(self) -> None:
        self.assertTrue(js_snippets.grid_probe("text", "\n}").startswith("({ text, geom }) => {"))
        self.assertTrue(js_snippets.grid_probe("", "\n}").startswith("({ geom }) => {"))
        self.assertIn(js_snippets.GEOMETRY_ARGUMENT, js_snippets.grid_arguments())

    def test_grid_arguments_carries_the_shared_geometry(self) -> None:
        arguments = js_snippets.grid_arguments(text="立即下单")
        self.assertEqual(arguments["text"], "立即下单")
        self.assertIs(arguments[js_snippets.GEOMETRY_ARGUMENT], BOOKING_GRID_GEOMETRY)

    def test_probes_using_helpers_receive_the_geometry(self) -> None:
        self.assertTrue(self.page.fragments)
        for fragment, argument in zip(self.page.fragments, self.page.arguments):
            if "geom." not in fragment:
                continue
            self.assertIsInstance(argument, dict)
            self.assertIn(js_snippets.GEOMETRY_ARGUMENT, argument)

    def test_helpers_are_included_in_every_wrapped_probe(self) -> None:
        wrapped = [fragment for fragment in self.page.fragments if "geom." in fragment]
        self.assertGreaterEqual(len(wrapped), 8)
        for fragment in wrapped:
            self.assertIn("const visible = (el) => {", fragment)

    def test_geometry_keys_used_by_js_are_declared(self) -> None:
        used = set(re.findall(r"geom\.([A-Za-z][A-Za-z0-9]*)", "".join(self.page.fragments)))
        self.assertTrue(used)
        self.assertEqual(used - set(BOOKING_GRID_GEOMETRY), set())

    def test_every_declared_geometry_key_is_used(self) -> None:
        used = set(re.findall(r"geom\.([A-Za-z][A-Za-z0-9]*)", "".join(self.page.fragments)))
        self.assertEqual(set(BOOKING_GRID_GEOMETRY) - used, set())

    def test_fragments_parse_as_javascript(self) -> None:
        node = find_node()
        if not node:
            self.skipTest("node is not available; JS fragments only guard syntax with it")
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / "check.js"
            script.write_text(NODE_CHECK_SCRIPT, encoding="utf-8")
            payload = Path(directory) / "fragments.json"
            payload.write_text(json.dumps(self.page.fragments), encoding="utf-8")
            completed = subprocess.run(
                [node, str(script), str(payload)],
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
        self.assertEqual(
            completed.returncode,
            0,
            f"node rejected a fragment:\n{completed.stdout}{completed.stderr}",
        )


class DuplicationTest(unittest.TestCase):
    def test_probe_modules_no_longer_carry_private_copies(self) -> None:
        for name in PROBE_MODULES:
            source = (PACKAGE_ROOT / "browser" / name).read_text(encoding="utf-8")
            for marker in DUPLICATED_MARKERS:
                self.assertNotIn(
                    marker,
                    source,
                    f"{name} still carries a private copy of {marker!r}",
                )

    def test_shared_module_defines_the_helpers_once(self) -> None:
        helpers = js_snippets.GRID_HELPERS
        self.assertEqual(helpers.count("const visible = (el) => {"), 1)
        self.assertEqual(helpers.count("const norm = (text) =>"), 1)
        self.assertEqual(
            helpers.count("Array.from(document.querySelectorAll('body *')).filter(visible)"),
            1,
        )


if __name__ == "__main__":
    unittest.main()
