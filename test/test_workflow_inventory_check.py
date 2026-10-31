#!/usr/bin/env python3
"""Unit tests for scripts/check_workflow_inventory.py (no GitHub access)."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import check_workflow_inventory as cwi  # noqa: E402

W = ".github/workflows/"
INV = {W + "a.yml": "active", W + "b.yml": "disabled_manually", "dynamic/x/codeql": "active"}
LIVE = {W + "a.yml": "active", W + "b.yml": "disabled_manually", "dynamic/x/codeql": "active"}
DISK = {W + "a.yml", W + "b.yml"}


class InventoryCompare(unittest.TestCase):
    def test_clean(self):
        self.assertEqual(cwi.compare(INV, LIVE, DISK), ([], []))

    def test_new_upstream_workflow_is_flagged(self):
        errors, _ = cwi.compare(INV, {**LIVE, W + "new.yml": "active"}, DISK | {W + "new.yml"})
        self.assertEqual(len(errors), 2)  # listed live and present on disk, but not in the inventory

    def test_disabled_workflow_that_came_back_is_flagged(self):
        errors, _ = cwi.compare(INV, {**LIVE, W + "b.yml": "active"}, DISK)
        self.assertEqual(errors, [f"{W}b.yml: state is active, inventory expects disabled_manually"])

    def test_window_allows_the_named_workflow_only(self):
        live = {**LIVE, W + "b.yml": "active"}
        self.assertEqual(cwi.compare(INV, live, DISK, window=["b.yml"]), ([], []))
        self.assertTrue(cwi.compare(INV, {**live, W + "a.yml": "disabled_manually"}, DISK, window=["b.yml"])[0])

    def test_file_on_disk_not_yet_live_is_only_a_warning(self):
        inv = {**INV, W + "quake-ci.yml": "active"}
        errors, warnings = cwi.compare(inv, LIVE, DISK | {W + "quake-ci.yml"})
        self.assertEqual(errors, [])
        self.assertEqual(len(warnings), 1)

    def test_missing_file_for_inventory_row(self):
        errors, _ = cwi.compare(INV, LIVE, {W + "a.yml"})
        self.assertEqual(errors, [f"{W}b.yml is in the inventory but not on disk"])

    def test_dynamic_row_must_be_live(self):
        live = {k: v for k, v in LIVE.items() if not k.startswith("dynamic/")}
        self.assertEqual(len(cwi.compare(INV, live, DISK)[0]), 1)


class RealInventory(unittest.TestCase):
    def test_every_workflow_file_on_disk_has_a_row(self):
        inv = cwi.parse_inventory((ROOT / ".github/WORKFLOWS.md").read_text(encoding="utf-8"))
        disk = {p.relative_to(ROOT).as_posix() for p in (ROOT / ".github/workflows").glob("*.y*ml")}
        self.assertEqual(sorted(disk - set(inv)), [], "a workflow file has no row in .github/WORKFLOWS.md")
        self.assertEqual(sorted(p for p in inv if not p.startswith("dynamic/") and p not in disk), [])

    def test_states_are_known(self):
        inv = cwi.parse_inventory((ROOT / ".github/WORKFLOWS.md").read_text(encoding="utf-8"))
        self.assertTrue(inv)
        self.assertLessEqual(set(inv.values()), {"active", "disabled_manually"})


if __name__ == "__main__":
    unittest.main()
