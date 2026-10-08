#!/usr/bin/env python3
"""Execute the production ESP32 UART begin/end and bridge state checks."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from test_replay_reset_integration import extract_braced

ROOT = Path(__file__).resolve().parents[1]

FIXTURE = r'''
#include <cassert>
#include <cstdint>
#define ESP32 1
#define BRIDGE_DEBUG_PRINTLN(...) ((void)0)
struct NodePrefs { uint32_t bridge_baud = 57600; };
struct Stream { virtual ~Stream() = default; };
struct HardwareSerial : Stream {
  bool pins_ok = true, begin_ok = true, installed = false;
  unsigned pin_calls = 0, begin_calls = 0, end_calls = 0;
  int16_t rx = -1, tx = -1;
  uint32_t baud = 0;
  bool setPins(int16_t selected_rx, int16_t selected_tx) {
    ++pin_calls; rx = selected_rx; tx = selected_tx; return pins_ok;
  }
  void begin(uint32_t selected_baud) { ++begin_calls; baud = selected_baud; installed = begin_ok; }
  explicit operator bool() const { return installed; }
  void end() { ++end_calls; installed = false; }
};
struct BridgeBase {
  bool _initialized = false;
  @RUNNING@
};
struct RS232Bridge : BridgeBase {
  NodePrefs* _prefs;
  Stream* _serial;
  int16_t _rx_pin, _tx_pin;
  RS232Bridge(NodePrefs& prefs, HardwareSerial& serial)
      : _prefs(&prefs), _serial(&serial), _rx_pin(5), _tx_pin(6) {}
  void begin();
  void end();
};
@BEGIN@
@END@
int main() {
  NodePrefs prefs;
  HardwareSerial serial;
  RS232Bridge bridge(prefs, serial);
  assert(!bridge.isRunning());
  serial.pins_ok = false;
  bridge.begin();
  assert(!bridge.isRunning() && serial.pin_calls == 1 && serial.begin_calls == 0);
  serial.pins_ok = true; serial.begin_ok = false;
  bridge.begin();
  assert(!bridge.isRunning() && !serial.installed && serial.begin_calls == 1);
  serial.begin_ok = true;
  bridge.begin();
  assert(bridge.isRunning() && serial.installed && serial.begin_calls == 2);
  assert(serial.rx == 5 && serial.tx == 6 && serial.baud == 57600);
  bridge.end();
  assert(!bridge.isRunning() && !serial.installed && serial.end_calls == 1);
  // A failed restart must clear its former state, and a later retry can recover.
  bridge.begin(); assert(bridge.isRunning());
  serial.pins_ok = false;
  bridge.begin(); assert(!bridge.isRunning());
  bridge.end(); serial.pins_ok = true; prefs.bridge_baud = 19200;
  bridge.begin(); assert(bridge.isRunning() && serial.baud == 19200);
  for (unsigned cycle = 0; cycle < 100; ++cycle) {
    bridge.end(); assert(!bridge.isRunning());
    bridge.begin(); assert(bridge.isRunning());
  }
  bridge.end(); assert(!bridge.isRunning());
}
'''


class RS232DriverLifecycleTests(unittest.TestCase):
    def test_failed_pins_or_driver_start_never_report_running_and_retry_recovers(self):
        compiler = shutil.which("g++") or shutil.which("clang++")
        self.assertIsNotNone(compiler, "a host C++ compiler is required")
        driver = (ROOT / "src/helpers/bridges/RS232Bridge.cpp").read_text(encoding="ascii")
        base = (ROOT / "src/helpers/bridges/BridgeBase.cpp").read_text(encoding="ascii")
        code = FIXTURE.replace("@RUNNING@", extract_braced(base, "bool BridgeBase::isRunning() const")
                               .replace("BridgeBase::", "").replace(" override", ""))
        code = code.replace("@BEGIN@", extract_braced(driver, "void RS232Bridge::begin()"))
        code = code.replace("@END@", extract_braced(driver, "void RS232Bridge::end()"))
        with tempfile.TemporaryDirectory(prefix="rs232-driver-lifecycle-") as directory:
            work = Path(directory)
            source, binary = work / "main.cpp", work / "test"
            source.write_text(code, encoding="ascii")
            built = subprocess.run([compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
                "-fsanitize=address,undefined", "-fno-sanitize-recover=all", "-fno-pie", "-no-pie",
                str(source), "-o", str(binary)], capture_output=True, text=True, timeout=60)
            self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
            checked = subprocess.run([str(binary)], capture_output=True, text=True, timeout=10)
            self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)


if __name__ == "__main__":
    unittest.main()
