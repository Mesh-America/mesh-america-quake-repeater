#!/usr/bin/env python3
"""Exercise saved guest enable state using production filesystem transactions."""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "test/fixtures/guest_login"


class GuestLoginSettingsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which("g++") or shutil.which("clang++")
        if compiler is None:
            raise unittest.SkipTest("host C++ compiler required")
        cls.work = tempfile.TemporaryDirectory(prefix="mesh-guest-settings-")
        cls.binaries = {}
        sanitizer = (["-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-no-pie"]
                     if os.name != "nt" else [])
        for backend in ("ESP32", "RP2040", "NRF52", "STM32"):
            binary = Path(cls.work.name) / (backend + (".exe" if os.name == "nt" else ""))
            sources = [str(FIXTURE / "test.cpp"), str(ROOT / "src/helpers/GuestLoginSettings.cpp")]
            if backend in ("NRF52", "STM32"):
                sources.append(str(ROOT / "src/helpers/AtomicFileWriter.cpp"))
            result = subprocess.run([
                compiler, "-std=c++17", "-O1", "-g", "-Wall", "-Wextra", "-Werror",
                "-Wno-misleading-indentation", "-Wno-sign-compare", *sanitizer,
                "-D" + backend + "_PLATFORM", *(["-DESP32"] if backend == "ESP32" else []),
                "-I", str(FIXTURE / "mocks"),
                "-I", str(ROOT / "src"), *sources, "-o", str(binary),
            ], capture_output=True, text=True, timeout=60)
            if result.returncode:
                cls.work.cleanup()
                raise AssertionError(backend + ":\n" + result.stdout + result.stderr)
            cls.binaries[backend] = binary

    @classmethod
    def tearDownClass(cls):
        cls.work.cleanup()

    def scenario(self, name):
        for backend, binary in self.binaries.items():
            with self.subTest(backend=backend):
                result = subprocess.run([str(binary), name], capture_output=True, text=True, timeout=15)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_default_and_saved_toggle(self):
        self.scenario("basics")

    def test_malformed_records_fail_closed(self):
        self.scenario("malformed")

    def test_failed_saves_preserve_previous_setting(self):
        self.scenario("failed_saves")

    def test_uncertain_save_blocks_enable_until_reload(self):
        self.scenario("uncertain")

    def test_restart_at_each_filesystem_operation(self):
        self.scenario("reboot")

    def test_load_io_failures_keep_guests_disabled(self):
        self.scenario("load_errors")


if __name__ == "__main__":
    unittest.main()
