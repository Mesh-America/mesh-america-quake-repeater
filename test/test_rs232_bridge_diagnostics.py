#!/usr/bin/env python3
"""Sanitized production UART diagnostics, probes and legacy parser tests."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "test/fixtures/rs232_heartbeat"


class RS232BridgeDiagnosticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which("g++") or shutil.which("clang++")
        if not compiler:
            raise AssertionError("a host C++ compiler is required")
        cls.temporary = tempfile.TemporaryDirectory(prefix="rs232-diagnostics-")
        cls.binaries = []
        for platform, cooperative in (("ESP32", 0), ("ESP32", 1),
                                      ("NRF52_PLATFORM", 0),
                                      ("RP2040_PLATFORM", 0),
                                      ("STM32_PLATFORM", 0)):
            binary = Path(cls.temporary.name) / f"diagnostics-{platform}-{cooperative}"
            built = subprocess.run([
                compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
                "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
                "-fno-pie", "-no-pie", "-DARDUINO=1", f"-D{platform}=1",
                "-DWITH_RS232_BRIDGE=1",
                f"-DMESH_ESP32_USB_CONSOLE_COOPERATIVE={cooperative}",
                "-I" + str(FIXTURES), "-I" + str(ROOT / "src"),
                str(ROOT / "test/fixtures/rs232_bridge_diagnostics.cpp"),
                str(ROOT / "src/helpers/bridges/RS232Bridge.cpp"),
                "-o", str(binary),
            ], capture_output=True, text=True, timeout=60)
            if built.returncode:
                cls.temporary.cleanup()
                raise AssertionError(built.stdout + built.stderr)
            cls.binaries.append(binary)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def run_case(self, name):
        for binary in self.binaries:
            with self.subTest(console=binary.name):
                checked = subprocess.run([str(binary), name], capture_output=True,
                                         text=True, timeout=60)
                self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
                self.assertIn(name + " passed", checked.stdout)

    def test_probe_codec_strict_integrity_version_and_bounds(self):
        self.run_case("codec")

    def test_probe_never_allocates_echoes_forwards_or_refreshes_peer_power(self):
        self.run_case("isolation")

    def test_both_real_legacy_parsers_ignore_reserved_frames(self):
        self.run_case("legacy")

    def test_all_partial_tx_prefixes_are_bounded_and_never_retransmitted(self):
        self.run_case("backpressure")

    def test_stopped_busy_and_heartbeat_owned_transports_reject_probe(self):
        self.run_case("state")

    def test_data_errors_pool_wait_and_lifetime_reset_are_observed(self):
        self.run_case("counters")

    def test_saturating_counters_and_all_cli_page_bounds(self):
        self.run_case("bounds")

    def test_usb_debug_both_gates_change_rate_limit_and_console_backpressure(self):
        self.run_case("debug")


if __name__ == "__main__":
    unittest.main()
