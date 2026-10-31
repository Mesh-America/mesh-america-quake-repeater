#!/usr/bin/env python3
"""Unit tests for scripts/check_junit_suites.py."""
from pathlib import Path
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import check_junit_suites as cj  # noqa: E402

SUITES = ["test_d7s", "test_d7s_wire"]


def report(xml):
    with tempfile.NamedTemporaryFile("w", suffix=".xml", delete=False, encoding="utf-8") as f:
        f.write(xml)
    return f.name


class JunitSuiteCheck(unittest.TestCase):
    def run_main(self, xml, suites=SUITES):
        return cj.main(["x", report(xml), *suites])

    def test_all_suites_present_and_passing(self):
        xml = """<testsuites><testsuite name="native:test_d7s" tests="2">
        <testcase classname="test_d7s" name="a"/><testcase classname="test_d7s" name="b"/></testsuite>
        <testsuite name="native:test_d7s_wire" tests="1"><testcase classname="test_d7s_wire" name="c"/></testsuite>
        </testsuites>"""
        self.assertEqual(self.run_main(xml), 0)

    def test_missing_suite_fails_even_if_others_pass(self):
        xml = """<testsuites><testsuite name="native:test_d7s" tests="1">
        <testcase classname="test_d7s" name="a"/></testsuite></testsuites>"""
        self.assertEqual(self.run_main(xml), 1)

    def test_empty_report_fails(self):
        self.assertEqual(self.run_main("<testsuites/>"), 1)

    def test_failed_case_fails(self):
        xml = """<testsuites><testsuite name="s">
        <testcase classname="test_d7s" name="a"><failure message="boom"/></testcase>
        <testcase classname="test_d7s_wire" name="b"/></testsuite></testsuites>"""
        self.assertEqual(self.run_main(xml), 1)

    def test_skipped_case_fails(self):
        xml = """<testsuites><testsuite name="s">
        <testcase classname="test_d7s" name="a"><skipped/></testcase>
        <testcase classname="test_d7s_wire" name="b"/></testsuite></testsuites>"""
        self.assertEqual(self.run_main(xml), 1)

    def test_suite_level_totals_when_cases_are_not_named(self):
        xml = """<testsuites><testsuite name="test_d7s" tests="3" failures="0" errors="0" skipped="0"/>
        <testsuite name="test_d7s_wire" tests="2" failures="0" errors="0" skipped="0"/></testsuites>"""
        self.assertEqual(self.run_main(xml), 0)

    def test_suite_level_failure_counts(self):
        xml = """<testsuites><testsuite name="test_d7s" tests="3" failures="1" errors="0" skipped="0"/>
        <testsuite name="test_d7s_wire" tests="2" failures="0" errors="0" skipped="0"/></testsuites>"""
        self.assertEqual(self.run_main(xml), 1)


if __name__ == "__main__":
    unittest.main()
