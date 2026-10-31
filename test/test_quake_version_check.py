#!/usr/bin/env python3
"""Unit tests for scripts/check_quake_version.py (no network, no git, no compiler)."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import check_quake_version as cqv  # noqa: E402

TAGS = ["quake-v1.17.1.8", "quake-v1.18.0.1", "quake-v1.18.0.2", "companion-v9", "quake-vnonsense"]


class VersionParsing(unittest.TestCase):
    def test_compares_numerically_not_as_strings(self):
        self.assertGreater(cqv.parse_version("1.18.0.10"), cqv.parse_version("1.18.0.9"))
        self.assertGreater(cqv.parse_version("2.0.0.0"), cqv.parse_version("1.18.0.2"))
        self.assertEqual(cqv.parse_version("v1.18"), (1, 18, 0, 0))

    def test_rejects_unpackable_versions(self):
        for bad in ("1.2.3.4.5", "256.0.0.0", "a.b", ""):
            with self.assertRaises(ValueError):
                cqv.parse_version(bad)

    def test_highest_tag_ignores_foreign_tags(self):
        self.assertEqual(cqv.highest_tag(TAGS), (1, 18, 0, 2))
        self.assertIsNone(cqv.highest_tag(["companion-v9"]))

    def test_ini_versions_reads_every_define(self):
        text = """-D FIRMWARE_VERSION='"v1.18.0.2"'      ; one
        -D FIRMWARE_VERSION='"v1.18.0.3"'  ; two"""
        self.assertEqual(cqv.ini_versions(text), [(1, 18, 0, 2), (1, 18, 0, 3)])


class Rules(unittest.TestCase):
    def run_check(self, versions, event="pull_request", base=(1, 18, 0, 2), **kw):
        return cqv.check(versions, TAGS, base, event, **kw)

    def test_unchanged_version_passes(self):
        self.assertEqual(self.run_check(["1.18.0.2", "1.18.0.2"]), [])

    def test_real_bump_passes(self):
        self.assertEqual(self.run_check(["2.0.0.0", "2.0.0.0"]), [])

    def test_images_with_different_versions_fail(self):
        self.assertTrue(self.run_check(["1.18.0.2", "1.18.0.3"]))

    def test_a_single_manifest_fails(self):
        self.assertTrue(self.run_check(["1.18.0.2"]))

    def test_lower_than_existing_tag_fails(self):
        self.assertTrue(self.run_check(["1.18.0.1", "1.18.0.1"], base=(1, 18, 0, 1)))

    def test_pull_request_bump_to_an_existing_tag_fails(self):
        # base is ahead of the tag, the PR sets the version back to the tag's value
        errors = self.run_check(["1.18.0.2", "1.18.0.2"], base=(1, 18, 0, 3))
        self.assertTrue(errors)

    def test_merge_back_is_exempt_from_the_strict_rule(self):
        self.assertEqual(self.run_check(["1.18.0.2", "1.18.0.2"], base=(1, 18, 0, 1), merge_back=True), [])

    def test_push_event_allows_the_version_to_equal_the_newest_tag(self):
        self.assertEqual(self.run_check(["1.18.0.2", "1.18.0.2"], event="push", base=None), [])

    def test_push_event_still_rejects_a_lower_version(self):
        self.assertTrue(self.run_check(["1.18.0.1", "1.18.0.1"], event="push", base=None))

    def test_no_tags_yet(self):
        self.assertEqual(cqv.check(["1.0.0.0", "1.0.0.0"], [], None, "pull_request"), [])


if __name__ == "__main__":
    unittest.main()
