"""Run the nRF52 idle hint with the real watchdog and role sleep guards."""

from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import unittest

from test_replay_reset_integration import extract_braced


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "test/fixtures/usb_logging_watchdog"


class Nrf52UsbWatchdogSleepTest(unittest.TestCase):
    def test_idle_roles_keep_watchdog_deadlines_and_pending_usb_quarantine(self):
        source = (ROOT / "src/helpers/UsbLoggingWatchdog.cpp").read_text(encoding="ascii")
        # The persistence boundary uses the existing ESP host fake. Compile
        # the exact nRF52 hint separately in the same TU, with the real policy,
        # publication, staged recovery and persistent state beneath it.
        hint = extract_braced(source, "bool isUsbLoggingWatchdogArmed()")
        hint = hint.replace("isUsbLoggingWatchdogArmed()", "nrf52UsbNeedsService()", 1)
        guards = []
        for role in ("simple_repeater", "simple_room_server", "simple_sensor"):
            main = (ROOT / f"examples/{role}/main.cpp").read_text(encoding="ascii")
            start = main.index("  const auto sleep_guard =")
            guard = main[start:main.index("  if (can_power_save)", start)]
            guards.append("static bool " + role + "() {\n" + guard
                          + "\nreturn can_power_save;\n}\n")
        main = (ROOT / "examples/companion_radio/main.cpp").read_text(encoding="ascii")
        start = main.index("  using mesh::powerdiag::Reason;", main.index("void loop()"))
        guard = main[start:main.index("  uint32_t noise_floor_delay_ms = 0;", start)]
        guards.append("static bool companion() {\n" + guard + "\nreturn sleep_reason == 0;\n}\n")
        guards = "\n".join(guards).replace("mesh::isUsbLoggingWatchdogArmed()", "mesh::nrf52UsbNeedsService()")
        harness = r'''
#include <Arduino.h>
#include <FS.h>
#include <helpers/UsbLoggingWatchdog.cpp>
#include <helpers/PowerSavingDiagnostics.h>
#include <cassert>
#include <cstring>
#include <vector>
static mesh::UsbLoggingObservation observation{true, false, false, false, 0};
static bool logging = true, pending = false, client = false, safe = true;
static std::vector<unsigned> recoveries;
namespace mesh {
bool isUsbLoggingEnabled() { return logging; }
bool isUsbLoggingClientActive() { return client; }
void clearUsbLoggingClientActivity() { client = false; }
bool isUsbLoggingTransportRecoveryPending() { return pending; }
UsbLoggingObservation observeUsbLoggingTransport() { return observation; }
UsbLoggingRecoveryResult recoverUsbLoggingTransport(uint8_t stage) {
  recoveries.push_back(stage); return UsbLoggingRecoveryResult::Attempted;
}
void probeUsbLoggingTransport() {}
}
#define NRF52_PLATFORM 1
#undef ESP32_PLATFORM
namespace mesh {
@HINT@
namespace wireless {
struct Control { bool busy = false; bool pending() const { return busy; } };
Control& control() { static Control value; return value; }
}
}
static bool morse_timing = false;
struct Prefs { bool powersaving_enabled = true; };
struct Mesh {
  Prefs prefs; bool work = false;
  Prefs* getNodePrefs() { return &prefs; }
  bool isTrackerModeEnabled() const { return false; }
  mesh::powerdiag::Mask pendingWorkReason() const {
    return work ? mesh::powerdiag::mask(mesh::powerdiag::Reason::Ota) : 0;
  }
} the_mesh;
struct Board {
  bool connected = false;
  bool isUsbDataConnected() const { return connected; }
  bool isUsbHostConnected() const { return connected; }
} board;
@GUARDS@
static bool recovery_safe(void*) { return safe; }
static bool service(uint32_t now) {
  mock_watchdog_millis = now;
  return mesh::serviceUsbLoggingWatchdog(recovery_safe);
}
static void mode(const char* command) {
  char reply[160];
  assert(mesh::handleUsbLoggingWatchdogCommand(command, reply, sizeof(reply)));
  assert(std::strstr(reply, "(saved)"));
  recoveries.clear();
}
static void all_idle() {
  assert(!mesh::nrf52UsbNeedsService() && "armed watchdog must not spin idle nRF52");
  assert(simple_repeater() && simple_room_server() && simple_sensor() && companion());
}
static void all_busy() {
  assert(!simple_repeater() && !simple_room_server() && !simple_sensor() && !companion());
}
int main() {
  fs::FS fs; fs::stat_filesystem = &fs;
  mesh::loadUsbLoggingWatchdog(&fs);
  mode("set usb.watchdog on");
  assert(!service(0)); all_idle();
  // CPU waits can leave long gaps between loop calls. They must not restart
  // or pause the five-minute repair and original one-hour reset deadlines.
  assert(!service(299999)); all_idle(); assert(recoveries.empty());
  assert(!service(300000)); all_idle(); assert((recoveries == std::vector<unsigned>{1}));
  assert(!service(360000)); all_idle(); assert((recoveries == std::vector<unsigned>{1, 2}));
  assert(!service(3599999)); all_idle();
  assert(service(3600000));
  assert(mesh::usbLoggingStatus().reboot_count == 1);
  // Mounted USB with its handle closed has the same idle behavior. A real
  // open session, OTA owner, or pending detach still keeps its existing veto.
  mode("set usb.watchdog on");
  observation = {true, true, false, false, 1};
  assert(!service(3600001)); all_idle();
  board.connected = true; all_busy(); board.connected = false;
  the_mesh.work = true; assert(!companion()); the_mesh.work = false;
  // Auto has confirmed this boot's stats client, matching the field failure.
  mode("set usb.watchdog auto");
  observation = {true, true, true, false, 2}; client = true;
  assert(!service(3600002));
  assert(mesh::usbLoggingStatus().watchdog_auto && mesh::usbLoggingStatus().logger_active);
  observation.reader_connected = false;
  assert(!service(3600003)); all_idle();
  assert(!service(3900003)); all_idle(); assert((recoveries == std::vector<unsigned>{1}));
  assert(!service(3960003)); all_idle(); assert((recoveries == std::vector<unsigned>{1, 2}));
  assert(!service(7200003)); all_idle();
  assert(mesh::usbLoggingStatus().reboot_count == 1); // Auto never adds a reboot.
  // A real in-flight USB cleanup must finish even with the logger/watchdog off.
  mode("set usb.watchdog off"); logging = false; pending = true;
  assert(mesh::nrf52UsbNeedsService()); all_busy();
  pending = false; all_idle();
}
'''.replace("@HINT@", hint).replace("@GUARDS@", guards)
        compiler = os.environ.get("CXX") or shutil.which("g++") or shutil.which("clang++")
        if compiler is None:
            self.skipTest("a host C++17 compiler is required")
        with tempfile.TemporaryDirectory(prefix="nrf52-watchdog-sleep-") as directory:
            cpp, binary = Path(directory) / "sleep.cpp", Path(directory) / "sleep"
            cpp.write_text(harness, encoding="ascii")
            built = subprocess.run([
                compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror", "-pthread",
                "-fsanitize=address,undefined", "-fno-sanitize-recover=all", "-fno-pie", "-no-pie",
                "-DARDUINO", "-DESP32", "-DESP32_PLATFORM", "-DARDUINO_USB_MODE=0",
                "-DARDUINO_USB_CDC_ON_BOOT=1", "-I" + str(FIXTURE / "mocks"),
                "-I" + str(ROOT / "src"), str(cpp), "-o", str(binary),
            ], capture_output=True, text=True, timeout=60)
            self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
            result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
