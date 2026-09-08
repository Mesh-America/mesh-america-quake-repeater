#!/usr/bin/env python3
"""Exercise the real ESP32 Companion adapter against the NimBLE 2.5 API."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class NimbleCompanionTests(unittest.TestCase):
    def test_identity_security_and_data_path_under_sanitizers(self):
        with tempfile.TemporaryDirectory(prefix="meshcore-nimble-") as temp:
            binary = Path(temp) / "nimble-companion"
            result = subprocess.run([
                "c++", "-std=c++17", "-g", "-fsanitize=address,undefined",
                "-DMESH_USE_NIMBLE_ARDUINO=1",
                "-I", str(ROOT / "test/fixtures/nimble_companion/mocks"),
                "-I", str(ROOT / "src"),
                str(ROOT / "src/helpers/esp32/SerialBLEInterface.cpp"),
                str(ROOT / "test/fixtures/nimble_companion/test_nimble_companion.cpp"),
                "-o", str(binary),
            ], text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            result = subprocess.run([str(binary)], text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
