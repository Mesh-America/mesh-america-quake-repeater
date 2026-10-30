#!/usr/bin/env python3
"""Execute the full OLED driver and actual shared-rail reference counting."""

from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

from test_replay_reset_integration import extract_braced

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "test/fixtures/ssd1306_power"
DRIVER = ROOT / "src/helpers/ui/SSD1306Display.cpp"


class Ssd1306PowerTests(unittest.TestCase):
    def compile_run(self, reset_pin, source=None, expect_failure=False):
        compiler = os.environ.get("CXX") or shutil.which("g++") or shutil.which("clang++")
        if compiler is None:
            self.skipTest("a host C++17 compiler is required")
        with tempfile.TemporaryDirectory(prefix="meshcore-ssd1306-power-") as directory:
            work = Path(directory)
            driver = DRIVER
            if source is not None:
                driver = work / "SSD1306Display.cpp"
                driver.write_text(source, encoding="ascii")
            binary = work / "power"
            compiled = subprocess.run([
                compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
                "-Wno-unused-parameter", f"-DPIN_OLED_RESET={reset_pin}",
                *(["-fsanitize=address,undefined", "-fno-sanitize-recover=all",
                   "-fno-pie", "-no-pie"] if sys.platform.startswith("linux") else []),
                "-I", str(FIXTURE / "mocks"), "-I", str(ROOT / "src"),
                "-I", str(ROOT / "src/helpers/ui"),
                str(FIXTURE / "test.cpp"), str(driver),
                str(ROOT / "src/helpers/ui/DisplayDriver.cpp"), "-o", str(binary),
            ], text=True, capture_output=True, timeout=60)
            self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
            checked = subprocess.run([str(binary)], text=True, capture_output=True, timeout=10)
            if expect_failure:
                self.assertNotEqual(checked.returncode, 0, "negative control escaped the regression")
                self.assertIn("Assertion", checked.stderr)
            else:
                self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
                self.assertIn("PASS: actual SSD1306 power ownership (26 scenarios)", checked.stdout)

    def test_actual_failure_retry_wake_and_shared_owner_lifecycle(self):
        for reset_pin in (21, -1):
            with self.subTest(reset_pin=reset_pin):
                self.compile_run(reset_pin)

    def test_missing_rollback_and_failed_wake_negative_controls(self):
        source = DRIVER.read_text()
        begin = extract_braced(source, "bool SSD1306Display::begin(")
        old_begin = begin[:begin.index("  } else {\n    _panel_ready = false;")] + "  }\n  return started;\n}"
        self.compile_run(21, source.replace(begin, old_begin), expect_failure=True)
        stopped_wake = "if (!begin()) return;  // begin owns and rolls back its claim on failure"
        self.assertEqual(source.count(stopped_wake), 1)
        self.compile_run(21, source.replace(stopped_wake, "begin();"), expect_failure=True)


if __name__ == "__main__":
    unittest.main()
