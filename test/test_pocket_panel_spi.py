#!/usr/bin/env python3
"""Run the Pocket panel profile through the pinned, real GxEPD2 SPI code.

Only Arduino/SPI and the GFX base geometry are simulated. The production
GxEPD2 canvas, bitmap upload, register setup, refresh and history writes run.
No PlatformIO or hardware is needed; missing pinned sources are downloaded.
"""

import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import urllib.request


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "test/fixtures/pocket_panel_spi"
PINNED = {
    "GxEPD2.h": "fd8f66f593ba9ec249249aa5d010f3e5fb951f8521635227e768218b2318b42d",
    "GxEPD2_BW.h": "4073c085d2d5ab2c6178570ac49f1b65b0a71125b1b164645d75f5e57922adfc",
    "GxEPD2_EPD.cpp": "0ce4a5030fdcd07b337fb1c932727e1cd11f8f6556b59cfd732e51e39fa4df03",
    "GxEPD2_EPD.h": "2b51ad2e47afdea65d8de424055a76d1a61fd097bffc2f485f3511e96a3b496d",
    "epd/GxEPD2_213_B74.cpp": "cbd162ac4d9d5abcc53eb3b0538366e6257cfafc911274f9b4e23bb5ec4eb94a",
    "epd/GxEPD2_213_B74.h": "f98af064e8ab2c51110b58ffbf97151756cf7a3290da2f279ec6409a490a434f",
}


class PocketPanelSpiTest(unittest.TestCase):
    def test_real_panel_preserves_bitmap_history_and_waits_before_sleep(self):
        compiler = shutil.which(os.environ.get("CXX", "g++"))
        if compiler is None:
            self.skipTest("host G++ required")
        cache = Path(os.environ.get("MESHCORE_GXEPD2_TEST_CACHE",
                                    str(Path(tempfile.gettempdir()) / "meshcore-gxepd2-1.6.2")))
        for name, expected in PINNED.items():
            target = cache / name
            if not target.is_file():
                url = "https://raw.githubusercontent.com/ZinggJM/GxEPD2/1.6.2/src/" + name
                try:
                    with urllib.request.urlopen(url, timeout=30) as response:
                        data = response.read()
                except OSError as error:
                    self.fail(f"Cannot fetch pinned GxEPD2 source {name}: {error}; "
                              "set MESHCORE_GXEPD2_TEST_CACHE to a verified offline cache")
                self.assertEqual(hashlib.sha256(data).hexdigest(), expected, name)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
            self.assertEqual(hashlib.sha256(target.read_bytes()).hexdigest(), expected, name)
        with tempfile.TemporaryDirectory(prefix="pocket-panel-spi-") as directory:
            binary = Path(directory) / "panel-test"
            overrides = Path(directory) / "include"
            flags = ["-std=c++17", "-Wall", "-Wextra", "-Werror", "-g"]
            if os.name != "nt":
                flags += ["-fsanitize=address,undefined", "-fno-omit-frame-pointer",
                          "-fno-pie", "-no-pie"]
            command = [compiler, *flags, "-DDISABLE_DIAGNOSTIC_OUTPUT=1",
                       "-I" + str(overrides), "-I" + str(FIXTURE),
                       "-I" + str(cache), "-I" + str(ROOT / "src"),
                       str(FIXTURE / "main.cpp"), str(cache / "GxEPD2_EPD.cpp"),
                       str(cache / "epd/GxEPD2_213_B74.cpp"), "-o", str(binary)]
            for args in (command, [str(binary)]):
                result = subprocess.run(args, capture_output=True, text=True,
                                        timeout=90 if args is command else 10)
                self.assertEqual(result.returncode, 0,
                                 " ".join(args) + "\n" + result.stdout + result.stderr)
            # The recorder must detect the old panel waveform, premature
            # completion on an initially LOW BUSY pin, and sleeping before BW
            # has synchronized the previous-image bank.
            header = (ROOT / "src/helpers/ui/MeshPocketEinkPanel.h").read_text()
            mutations = {
                "old B74 partial waveform": (
                    "_writeData(partial ? 0xFF : 0xF7);",
                    "_writeData(partial ? 0xFC : 0xF7);"),
                "missing minimum settling time": (
                    "delay(partial ? 800 : 2500);", "delay(0);"),
                "sleep before history sync": (
                    "_initial_refresh = false;", "finishRefresh();\n    _initial_refresh = false;"),
            }
            override = overrides / "helpers/ui/MeshPocketEinkPanel.h"
            override.parent.mkdir(parents=True)
            for label, (before, after) in mutations.items():
                with self.subTest(negative_control=label):
                    self.assertEqual(header.count(before), 1)
                    override.write_text(header.replace(before, after))
                    result = subprocess.run(command, capture_output=True, text=True, timeout=90)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=10)
                    self.assertNotEqual(result.returncode, 0, "recorder accepted " + label)
                    self.assertIn("Assertion", result.stderr, result.stderr)


if __name__ == "__main__":
    unittest.main()
