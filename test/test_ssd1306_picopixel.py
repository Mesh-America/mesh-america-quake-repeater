#!/usr/bin/env python3
"""Render the real SSD1306 driver with Adafruit GFX and a host panel double.

Build a V4 environment first to install Adafruit GFX, or point
MESHCORE_GFX_LIBRARY to that library's directory. Only the hardware panel,
Arduino strings and Print glue are replaced; the shared pixel renderer is compared with the original Adafruit font.
"""

import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "test/fixtures/ssd1306_picopixel"


class SSD1306PicopixelTest(unittest.TestCase):
    def test_actual_font_bounds_wrapping_and_default_font_restoration(self):
        configured = os.environ.get("MESHCORE_GFX_LIBRARY")
        candidates = [Path(configured)] if configured else sorted(
            (ROOT / ".pio/libdeps").glob("*/Adafruit GFX Library")
        )
        library = next((path for path in candidates
                        if (path / "Adafruit_GFX.cpp").is_file()), None)
        if library is None:
            self.skipTest("Build a V4 environment or set MESHCORE_GFX_LIBRARY")

        with tempfile.TemporaryDirectory(prefix="meshcore-picopixel-") as temp:
            for enabled in (0, 1):
                with self.subTest(picopixel=enabled):
                    binary = Path(temp) / f"render-{enabled}"
                    result = subprocess.run([
                        "c++", "-std=c++17", "-g",
                        "-fsanitize=address,undefined", "-DARDUINO=10819",
                        f"-DUI_SMALL_MESSAGE_FONT={enabled}",
                        "-I", str(FIXTURE / "mocks"),
                        "-I", str(ROOT / "src"), "-I", str(library),
                        str(ROOT / "src/helpers/ui/SSD1306Display.cpp"),
                        str(library / "Adafruit_GFX.cpp"),
                        str(FIXTURE / "render.cpp"), "-o", str(binary),
                    ], text=True, capture_output=True)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    result = subprocess.run(
                        [str(binary)], text=True, capture_output=True)
                    self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
