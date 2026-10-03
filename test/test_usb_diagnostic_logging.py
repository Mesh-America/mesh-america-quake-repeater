#!/usr/bin/env python3
"""Exercise Ethernet diagnostics and the production NetworkLink logging macro."""

from pathlib import Path
import os
import re
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "test/fixtures/usb_diagnostic_logging"


class UsbDiagnosticLoggingTests(unittest.TestCase):
    def test_runtime_gate_backpressure_and_functional_ethernet_output(self):
        compiler = os.environ.get("CXX") or shutil.which("g++") or shutil.which("clang++")
        if compiler is None:
            self.skipTest("a host C++17 compiler is required")
        network = (ROOT / "src/helpers/NetworkLink.cpp").read_text(encoding="utf-8")
        start = network.index("// Same \"MQTT: \" prefix")
        macro = network[start:network.index("namespace {", start)]
        with tempfile.TemporaryDirectory(prefix="meshcore-usb-diagnostics-") as directory:
            temporary = Path(directory)
            (temporary / "NetworkLoggingMacro.h").write_text(macro, encoding="utf-8")
            for debug, touch_debug in ((None, False), (0, False), (1, False), (1, True)):
                with self.subTest(mqtt_debug=debug, touch_debug=touch_debug):
                    binary = temporary / "usb-diagnostics.exe"
                    defines = [] if debug is None else [f"-DMQTT_DEBUG={debug}"]
                    if touch_debug:
                        defines += ["-DDISPLAY_TOUCH_DEBUG=1", "-DPIN_TOUCH_INT=7"]
                    compiled = subprocess.run(
                        [compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
                         "-DARDUINO=1", "-DETHERNET_ENABLED=1", *defines,
                         f"-I{FIXTURE / 'mocks'}", f"-I{ROOT / 'src'}",
                         f"-I{temporary}", str(FIXTURE / "test.cpp"),
                         "-o", str(binary)],
                        capture_output=True, text=True, timeout=60,
                    )
                    self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
                    checked = subprocess.run(
                        [str(binary)], capture_output=True, text=True, timeout=10,
                    )
                    self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
                    self.assertIn("PASS: gated USB diagnostics", checked.stdout)

    def test_no_raw_serial_diagnostic_writes(self):
        for relative in ("src/helpers/nrf52/EthernetCLI.h", "src/helpers/NetworkLink.cpp",
                         "src/helpers/ui/CHSC6XTouch.h", "src/helpers/ethernet/ch390/CH390Config.h"):
            with self.subTest(source=relative):
                source = (ROOT / relative).read_text(encoding="utf-8")
                self.assertIn("UsbLogging.h", source)
                self.assertIn("mesh::isUsbLoggingEnabled()", source)
                self.assertIn("mesh::usbLoggingPort()", source)
                self.assertIsNone(re.search(r"\bSerial\.(?:print|println|printf|write)\s*\(", source))


if __name__ == "__main__":
    unittest.main()
