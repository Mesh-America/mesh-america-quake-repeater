#!/usr/bin/env python3
"""Exercise the real helper with frozen Adafruit UART lifecycle methods.

Only register completion and semaphore deletion are host boundaries. The
constructor, public started accessor, pin setter and stop logic preserve the
pinned framework's semantics without downloads, PlatformIO or hardware.
"""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "test/fixtures/nrf52_uart_lifecycle"


class RS232NrfUartLifecycleTests(unittest.TestCase):
    def compile_and_run(self, old_helper=False):
        compiler = shutil.which("g++") or shutil.which("clang++")
        self.assertIsNotNone(compiler, "a host C++ compiler is required")
        with tempfile.TemporaryDirectory(prefix="rs232-nrf-uart-") as directory:
            work = Path(directory)
            binary = work / "test"
            include = []
            if old_helper:
                source = (ROOT / "src/helpers/bridges/RS232UartUtils.h").read_text(encoding="ascii")
                self.assertEqual(source.count("if (uart) uart.end();"), 1)
                header = work / "helpers/bridges/RS232UartUtils.h"
                header.parent.mkdir(parents=True)
                header.write_text(source.replace("if (uart) uart.end();", "uart.end();"), encoding="ascii")
                include = ["-I" + str(work)]
            built = subprocess.run([
                compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
                "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
                "-fno-pie", "-no-pie", *include, "-I" + str(ROOT / "src"),
                str(FIXTURE / "main.cpp"), "-o", str(binary),
            ], capture_output=True, text=True, timeout=60)
            self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
            checked = subprocess.run([str(binary)], capture_output=True,
                                     text=True, timeout=10)
            return checked

    def test_fresh_stopped_running_and_repeated_remapping(self):
        checked = self.compile_and_run()
        self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
        self.assertIn("PASS: nRF UART lifecycle", checked.stdout)

    def test_unconditional_stop_negative_control_reaches_null_semaphore(self):
        checked = self.compile_and_run(old_helper=True)
        self.assertNotEqual(checked.returncode, 0, checked.stdout + checked.stderr)
        self.assertIn("FreeRTOS null semaphore assertion", checked.stderr)


if __name__ == "__main__":
    unittest.main()
