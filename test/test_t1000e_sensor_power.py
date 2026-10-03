#!/usr/bin/env python3
"""Verify the upstream sensor-rail correction without changing local GPS/OTA."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
VARIANT = ROOT / "variants/t1000-e"
FIXTURES = ROOT / "test/fixtures/t1000e_sensor_power"


class T1000eSensorPowerTests(unittest.TestCase):
    def test_obsolete_p0_04_control_is_removed_everywhere(self):
        for path in VARIANT.iterdir():
            if path.suffix in (".h", ".cpp", ".ini"):
                with self.subTest(path=path.name):
                    self.assertNotIn("SENSOR_EN", path.read_text())
        self.assertRegex((VARIANT / "variant.h").read_text(), r"PIN_3V3_EN\s+\(38\)")

    def test_real_rail_and_existing_shutdown_and_gps_are_preserved(self):
        board = (VARIANT / "T1000eBoard.h").read_text()
        self.assertIn("void shutdownPeripherals() override", board)
        self.assertIn("NRF52Board::shutdownPeripherals();", board)
        for pin in ("GPS_VRTC_EN", "GPS_RESET", "GPS_SLEEP_INT", "GPS_RTC_INT",
                    "GPS_EN", "PIN_3V3_EN", "PIN_3V3_ACC_EN", "BUZZER_EN"):
            self.assertIn(f"digitalWrite({pin}, LOW);", board)
        target = (VARIANT / "target.cpp").read_text()
        for method in ("armGpsPowerSavingCycle", "loopGpsTelemetry", "processGpsTelemetryFix"):
            self.assertIn(method, target)
        startup = (VARIANT / "variant.cpp").read_text()
        self.assertIn("digitalWrite(GPS_EN, HIGH);", startup)
        self.assertIn("digitalWrite(GPS_VRTC_EN, HIGH);", startup)
        self.assertIn("pinMode(PIN_3V3_EN, OUTPUT);", startup)

    def test_actual_sensor_functions_only_switch_p1_06_and_keep_bounds(self):
        with tempfile.TemporaryDirectory(prefix="t1000e-sensor-power-") as temp:
            binary = Path(temp) / "power"
            compiled = subprocess.run([
                "c++", "-std=c++11", "-Wall", "-Wextra", "-Wno-unused-variable",
                "-I", str(FIXTURES), "-I", str(VARIANT), str(FIXTURES / "power.cpp"),
                "-o", str(binary),
            ], text=True, capture_output=True)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            executed = subprocess.run([str(binary)], text=True, capture_output=True)
            self.assertEqual(executed.returncode, 0, executed.stderr)


if __name__ == "__main__":
    unittest.main()
