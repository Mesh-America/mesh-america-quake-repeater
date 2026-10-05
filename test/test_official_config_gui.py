#!/usr/bin/env python3
"""Run stock config GUI bootstrap against production startup and CR CLI code.

Node executes the actual pinned SerialCLI class and GUI connect/disconnect
functions. Host clocks and USB peripherals are simulated; GPS discovery, the
boot absence inventory, command framing and the time handler come from
production C++. Inventory scan latency is an explicit cost model, not a host
benchmark or predicted hardware timing. No browser, physical device or secret
configuration reads are required by this CI test.
"""
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import urllib.request

import test_esp32_gps_discovery as gps
import test_official_web_console as console
from test_hwcdc_tx_backport import body
from test_replay_reset_integration import extract_braced

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "test/fixtures/official_config_gui"
COMMIT = "aff42ad8ef2b332f24d644ff6a783f8272a88ff2"
SOURCES = {
    "src/gui.js": (44387, "919034806e903fbc41e29a367a7d854837f6520f47aa34e5d0618f5dd3d29800"),
    "lib/serial-cli.js": (36909, "fbfbdcfa8bf1a372a0396d342e018ba8ee83d33b7b98c3a546fd37cd7e8ce870"),
}


def official_sources():
    explicit = os.environ.get("MESHCORE_OFFICIAL_CONFIG_GUI")
    base = Path(explicit) if explicit else Path.home() / ".cache/meshcore-tests/config-gui" / COMMIT
    result = {}
    for relative, (size, digest) in SOURCES.items():
        path = base / relative
        if not path.exists():
            if explicit:
                raise AssertionError("Missing explicit config GUI source: " + str(path))
            url = f"https://raw.githubusercontent.com/meshcore-dev/config.meshcore.io/{COMMIT}/{relative}"
            with urllib.request.urlopen(url, timeout=45) as response:
                data = response.read(size + 1)
            if len(data) != size or hashlib.sha256(data).hexdigest() != digest:
                raise AssertionError("Pinned config GUI download failed its source gate")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        data = path.read_bytes()
        if len(data) != size or hashlib.sha256(data).hexdigest() != digest:
            raise AssertionError("Config GUI source SHA/size mismatch: " + str(path))
        result[relative] = path.resolve()
    return result


def gps_boot_source(*, blocking=False):
    source = gps.harness(negative="blocking" if blocking else None).split("int main(", 1)[0]
    return source + r'''
int main() {
  fresh(); TestLocation location; EnvironmentSensorManager sensors(location);
  const uint32_t started = millis();
  sensors.initBasicGPS();
  std::printf("%u\n", unsigned(millis() - started));
}
'''


def cli_source(*, lf_reply=False, reject_cr=False):
    source = console.firmware_harness(lose_crlf=lf_reply)
    common = (ROOT / "src/helpers/CommonCLI.cpp").read_text()
    time_handler = body(common, 'if (memcmp(command, "time ", 5) == 0)')
    support = r'''
struct RTC { uint32_t utc=1715770351; uint32_t getCurrentTime(){return utc;}
  void setCurrentTime(uint32_t value){utc=value;} } rtc;
struct ClockCallbacks { void onManualClockSet(){} } clock_callbacks;
struct DateTime { explicit DateTime(uint32_t){} int hour(){return 20;}
  int minute(){return 50;} int day(){return 5;} int month(){return 10;}
  int year(){return 2026;} };
static uint32_t _atoi(const char* value){return std::strtoul(value,nullptr,10);}
'''
    source = source.replace("struct MyMesh {", support + "\nstruct MyMesh {\n"
                            "  RTC* getRTCClock(){return &rtc;}\n"
                            "  ClockCallbacks* _callbacks=&clock_callbacks;\n")
    old = extract_braced(source, "  void handleUsbCommand(")
    source = source.replace(old, "  void handleUsbCommand(const char* command, char* reply) {\n"
                            + time_handler + '\nelse strcpy(reply, "Unknown");\n}')
    if reject_cr:
        # Regress firmware framing, not the pinned client's actual CR write.
        pump = body(source, "static void __attribute__((noinline)) serviceCommandInterfaces()")
        changed = pump.replace("if (c == '\\r')", "if (c == '\\n')")
        assert changed != pump
        source = source.replace(pump, changed)
    return source


class OfficialConfigGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.node = shutil.which("node")
        cls.compiler = os.environ.get("CXX") or shutil.which("g++") or shutil.which("clang++")
        if not cls.node or not cls.compiler:
            raise unittest.SkipTest("Node 18+ and a host C++17 compiler are required")
        cls.sources = official_sources()

    def run_contract(self, *, blocking=False, lf_reply=False, reject_cr=False,
                     extra_boot_ms=0):
        with tempfile.TemporaryDirectory(prefix="official-config-gui-") as directory:
            work = Path(directory)
            gui = self.sources["src/gui.js"].read_text()
            bootstrap = "\n".join(extract_braced(gui, signature) + ";" for signature in
                                  ("const connect = async() =>", "const disconnect = async() =>"))
            witness = (FIXTURE / "bootstrap-witness.js").read_text()
            self.assertEqual(bootstrap, witness.rstrip("\n"), "Pinned GUI bootstrap witness changed")
            (work / "bootstrap.js").write_text(bootstrap, encoding="ascii")
            for name, text in {"Arduino.h": gps.ARDUINO, "Mesh.h": gps.MESH,
                               "CayenneLPP.h": gps.CAYENNE,
                               "Wire.h": "#pragma once\nclass TwoWire {};\n"}.items():
                (work / name).write_text(text, encoding="ascii")
            sanitize = (["-fsanitize=address,undefined", "-fno-sanitize-recover=all",
                         "-fno-pie", "-no-pie"] if sys.platform.startswith("linux") else [])
            boot_cpp, boot = work / "gps.cpp", work / "gps"
            boot_cpp.write_text(gps_boot_source(blocking=blocking), encoding="ascii")
            command = [self.compiler, "-std=c++17", "-Wall", "-Wextra", "-Wno-unused-parameter",
                       "-Wno-unused-function", "-DENV_INCLUDE_GPS=1", "-DESP32_PLATFORM=1",
                       *sanitize, "-I" + str(work), "-I" + str(ROOT / "src"), str(boot_cpp),
                       str(ROOT / "src/helpers/SensorManager.cpp"), "-o", str(boot)]
            built = subprocess.run(command, text=True, capture_output=True, timeout=60)
            self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
            measured = subprocess.run([str(boot)], text=True, capture_output=True, timeout=10)
            self.assertEqual(measured.returncode, 0, measured.stdout + measured.stderr)
            self.assertGreaterEqual(extra_boot_ms, 0)
            boot_ms = int(measured.stdout.strip()) + extra_boot_ms
            cli_cpp, cli = work / "cli.cpp", work / "cli"
            cli_cpp.write_text(cli_source(lf_reply=lf_reply, reject_cr=reject_cr), encoding="ascii")
            command = [self.compiler, "-std=c++17", "-Wall", "-Wextra",
                       "-DARDUINO_USB_MODE=1", "-DARDUINO_USB_CDC_ON_BOOT=1",
                       "-DESP32_PLATFORM=1", "-DMESH_ESP32_USB_CONSOLE_COOPERATIVE=1",
                       "-DMESH_USB_CONSOLE_COOPERATIVE=1", "-DMESH_USB_LOGGING_AVAILABLE=1",
                       "-DCONFIG_TINYUSB_ENABLED=0", *sanitize, "-I", str(ROOT / "src"),
                       str(cli_cpp), "-o", str(cli)]
            built = subprocess.run(command, text=True, capture_output=True, timeout=60)
            self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
            result = subprocess.run([self.node, str(FIXTURE / "contract.mjs"),
                                     str(self.sources["lib/serial-cli.js"]), str(work / "bootstrap.js"),
                                     str(cli), str(boot_ms)], text=True, capture_output=True, timeout=20)
            return result

    def test_stock_gui_time_handshake_with_cooperative_gps_and_cr_only(self):
        result = self.run_contract()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_reverted_blocking_gps_breaks_stock_gui_deadline(self):
        result = self.run_contract(blocking=True)
        self.assertNotEqual(result.returncode, 0, "Negative control did not fail")
        self.assertIn("initial time missed the stock 5000 ms deadline", result.stderr)

    def test_lf_only_firmware_reply_breaks_actual_gui_parser(self):
        result = self.run_contract(lf_reply=True)
        self.assertNotEqual(result.returncode, 0, "Negative control did not fail")
        self.assertIn("initial time missed the stock 5000 ms deadline", result.stderr)

    def test_firmware_rejecting_cr_breaks_actual_gui_bootstrap(self):
        result = self.run_contract(reject_cr=True)
        self.assertNotEqual(result.returncode, 0, "Negative control did not fail")
        self.assertIn("initial time missed the stock 5000 ms deadline", result.stderr)

    def test_boot_inventory_keeps_stock_gui_initial_time_within_deadline(self):
        from test_esp32_boot_file_inventory import run_boot_inventory_timing
        # The real inventory/recovery/probe code supplies operation counts.
        # Peripheral timing charges 129 ms per absent native name scan plus
        # 1000 ms setup settle; it does not imitate the full physical boot.
        timing = run_boot_inventory_timing()
        self.assertGreater(timing["snapshot_reads"], 0)
        self.assertGreaterEqual(timing["elapsed_ms"], 1000)
        self.assertLess(timing["elapsed_ms"], 5000)
        result = self.run_contract(extra_boot_ms=timing["elapsed_ms"])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_removing_boot_inventory_breaks_stock_gui_deadline(self):
        from test_esp32_boot_file_inventory import run_boot_inventory_timing
        # Same actual startup probes and native backend, with beginInventory
        # omitted. The client still receives one CR command with no retry.
        timing = run_boot_inventory_timing(disable_inventory=True)
        self.assertEqual(timing["snapshot_reads"], 0)
        self.assertGreaterEqual(timing["elapsed_ms"], 5000)
        result = self.run_contract(extra_boot_ms=timing["elapsed_ms"])
        self.assertNotEqual(result.returncode, 0, "Negative control did not fail")
        self.assertIn("initial time missed the stock 5000 ms deadline", result.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
