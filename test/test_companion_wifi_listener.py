#!/usr/bin/env python3
"""Fault-inject the production Companion TCP listener, without a radio or PC probe."""

from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

from test_replay_reset_integration import extract_braced


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "test/fixtures/companion_wifi_listener/test.cpp"
MOCKS = ROOT / "test/fixtures/serial_wifi_sessions/mocks"
SANITIZERS = (
    ["-fsanitize=address,undefined", "-fno-sanitize-recover=all", "-fno-pie", "-no-pie"]
    if sys.platform.startswith("linux") else []
)
SCENARIOS = (
    "no listener attempt before station association and a real IP",
    "healthy listener is not restarted by loop or repeated begin",
    "failed socket creation is counted and retried without leaking",
    "failed bind closes the retained SDK descriptor before retry",
    "failed listen closes the retained SDK descriptor before retry",
    "retry delay grows and caps at 30 seconds without a tight loop",
    "retry deadline is correct across millis rollover",
    "disable cancels automatic repair even after enable",
    "end and background suspension cannot resurrect the listener",
    "lost listener recovers without dropping a healthy client or its replies",
    "station reconnect preserves requested listener and restarts service",
    "station association alone with zero address is not ready",
    "a ready setup AP supports TCP without station association",
    "AP mode without an AP IP is not ready",
    "single-client takeover retains existing session ownership guarantees",
    "accepted sockets and valid command frames have separate diagnostics",
    "invalid protocol frame records a rejection and never dispatches its tail",
    "incomplete frame records timeout only at its bounded deadline",
    "diagnostic reads cannot start listeners or consume client commands",
    "begin without enable is bounded and cannot auto-retry while disabled",
    "transmit diagnostics count only completely written framed packets",
    "invalid port requests never start or automatically retry",
    "short header read is distinguished from invalid protocol and timeout",
    "short payload read is distinguished from invalid protocol and timeout",
    "healthy address changes never restart a listener or displace its client",
    "MultiSerial services unavailable transport so it can recover before dispatch",
    "failed listener repair retains an accepted client and queued data",
    "stale AP address never starts a listener while AP mode is disabled",
)


class CompanionWiFiListenerTests(unittest.TestCase):
    def test_production_listener_faults(self):
        compiler = os.environ.get("CXX") or shutil.which("g++") or shutil.which("clang++")
        if compiler is None:
            self.skipTest("a host C++17 compiler is required")
        with tempfile.TemporaryDirectory(prefix="meshcore-wifi-listener-") as directory:
            binary = Path(directory) / "wifi-listener.exe"
            compiled = subprocess.run(
                [compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
                 *SANITIZERS, "-DESP32=1", f"-I{MOCKS}", f"-I{ROOT / 'src'}",
                 str(FIXTURE), str(ROOT / "src/helpers/wifi/SerialWifiInterface.cpp"),
                 "-o", str(binary)],
                capture_output=True, text=True, timeout=60,
            )
            self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
            for scenario, description in enumerate(SCENARIOS):
                with self.subTest(scenario=description):
                    checked = subprocess.run(
                        [str(binary), str(scenario)], capture_output=True,
                        text=True, timeout=10,
                    )
                    self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
                    self.assertIn(f"PASS: Wi-Fi listener scenario {scenario}", checked.stdout)

    def test_production_cli_and_display_formatter_are_bounded_and_observable(self):
        compiler = os.environ.get("CXX") or shutil.which("g++") or shutil.which("clang++")
        if compiler is None:
            self.skipTest("a host C++17 compiler is required")
        main = (ROOT / "examples/companion_radio/main.cpp").read_text(encoding="utf-8")
        methods = extract_braced(main, "void formatCompanionWiFiTcpStatus(")
        methods += "\n" + extract_braced(main, "void formatCompanionWiFiDisplayStatus(")
        fixture = (ROOT / "test/fixtures/companion_wifi_listener/diagnostics.cpp").read_text()
        with tempfile.TemporaryDirectory(prefix="meshcore-wifi-diagnostics-") as directory:
            work = Path(directory)
            source = work / "diagnostics.cpp"
            source.write_text(fixture.replace("@METHODS@", methods), encoding="utf-8")
            binary = work / "diagnostics.exe"
            compiled = subprocess.run(
                [compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
                 *SANITIZERS, "-DESP32=1", f"-I{MOCKS}", f"-I{ROOT / 'src'}",
                 str(source), str(ROOT / "src/helpers/wifi/SerialWifiInterface.cpp"),
                 "-o", str(binary)], capture_output=True, text=True, timeout=60,
            )
            self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
            checked = subprocess.run([str(binary)], capture_output=True, text=True, timeout=10)
            self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
            self.assertIn("PASS: production Wi-Fi diagnostic formatters", checked.stdout)

    def test_cli_routes_and_registration_gate_use_real_listener(self):
        main = (ROOT / "examples/companion_radio/main.cpp").read_text(encoding="utf-8")
        mesh = (ROOT / "examples/companion_radio/MyMesh.cpp").read_text(encoding="utf-8")
        command = extract_braced(mesh, 'if (strcmp(command, "get wifi.tcp") == 0)')
        self.assertIn("formatCompanionWiFiTcpStatus(reply, reply_size);", command)
        self.assertIn("return true;", command)
        self.assertRegex(main, r"companion_wifi_interface_registered\s*=\s*"
                              r"interface_manager\.addInterface\(InterfaceType::WiFi")
        for signature in ("static void startCompanionWiFi(",
                          "static void serviceCompanionWiFiBackgroundPower("):
            method = extract_braced(main, signature)
            gate = extract_braced(method, "if (companion_wifi_interface_registered)")
            self.assertIn("wifi_interface.begin(TCP_PORT)", gate)
            self.assertIn("wifi_interface.enable()", gate)
        diagnostic = extract_braced(main, "void formatCompanionWiFiTcpStatus(")
        self.assertNotRegex(diagnostic, r"(?:\.connect\(|WiFiClient\s+|server\.available)")
        display = extract_braced(main, "void formatCompanionWiFiDisplayStatus(")
        self.assertIn("wifi_interface.getStatus().listening", display)


if __name__ == "__main__":
    unittest.main()
