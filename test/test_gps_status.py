"""Run the production GPS status branch against user and receiver states."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from test_replay_reset_integration import extract_braced

ROOT = Path(__file__).resolve().parents[1]


class GpsStatusTest(unittest.TestCase):
    def test_requested_state_is_distinct_from_sleeping_receiver(self):
        compiler = shutil.which("g++") or shutil.which("clang++")
        self.assertIsNotNone(compiler)
        source = (ROOT / "src/helpers/CommonCLI.cpp").read_text()
        branch = extract_braced(source, 'else if (memcmp(command, "gps", 3) == 0)')
        branch = branch[branch.index("{"):].replace("#endif", "")
        harness = r'''
#include <cassert>
#include <cstdio>
#include <cstring>
unsigned long now = 1000;
unsigned long millis() { return now; }
struct DateTime {
  explicit DateTime(unsigned long) {}
  int hour() { return 12; } int minute() { return 34; }
  int day() { return 30; } int month() { return 9; } int year() { return 2026; }
};
struct LocationProvider {
  bool powered = false, fix = false, saving = false;
  unsigned long off = 0, on = 0, sync = 0;
  bool isEnabled() { return powered; } bool isValid() { return fix; }
  int satellitesCount() { return 5; }
  bool getGPSPowerSaving() { return saving; }
  unsigned long getNextGPSOff() { return off; }
  unsigned long getNextGPSOn() { return on; }
  unsigned long getLastValidTimeSync() { return sync; }
};
struct Sensors {
  LocationProvider* provider;
  const char* user = "0";
  LocationProvider* getLocationProvider() { return provider; }
  const char* getSettingByKey(const char*) { return user; }
};
struct Prefs { bool powersaving_enabled = true; };
void status(Sensors* _sensors, Prefs* _prefs, char* reply) @BRANCH@
int main() {
  LocationProvider gps;
  Sensors sensors{&gps}; Prefs prefs;
  char reply[160];
  // Manual off must not be described as a periodic sleep, even with stale timers.
  gps.saving = true; gps.on = now + 1800000;
  status(&sensors, &prefs, reply);
  assert(!strcmp(reply, "off, unpowered"));
  // A shared power rail can keep the receiver powered after GPS is disabled.
  gps.powered = true;
  status(&sensors, &prefs, reply);
  assert(!strcmp(reply, "off, powered"));
  sensors.user = "1"; gps.powered = false;
  status(&sensors, &prefs, reply);
  assert(!strcmp(reply, "on, unpowered (powersaving, wake in 0h 30m), last sync: none"));
  // Sleep can leave a shared rail powered; the wake timer is still meaningful.
  gps.powered = true;
  status(&sensors, &prefs, reply);
  assert(!strcmp(reply, "on, powered (powersaving, wake in 0h 30m), last sync: none"));
  gps.off = now + 600000; gps.powered = true; gps.fix = true; gps.sync = 1;
  status(&sensors, &prefs, reply);
  assert(!strcmp(reply, "on, powered (powersaving, sleep in 0h 10m), fix, 5 sats, last sync: 12:34 - 30/9/2026 UTC"));
  // An overdue timer must not underflow into a huge remaining duration.
  gps.off = now - 1;
  status(&sensors, &prefs, reply);
  assert(strstr(reply, "sleep in 0h 0m"));
  prefs.powersaving_enabled = false; gps.powered = false;
  status(&sensors, &prefs, reply);
  assert(!strcmp(reply, "on, unpowered, fix, 5 sats"));
  // No GPS setting is a valid disabled state; avoid a null strcmp.
  sensors.user = nullptr;
  status(&sensors, &prefs, reply);
  assert(!strcmp(reply, "off, unpowered"));
  sensors.provider = nullptr;
  status(&sensors, &prefs, reply);
  assert(!strcmp(reply, "Can't find GPS"));
}
'''.replace("@BRANCH@", branch)
        with tempfile.TemporaryDirectory(prefix="meshcore-gps-status-") as directory:
            path = Path(directory)
            (path / "status.cpp").write_text(harness)
            subprocess.run([compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
                            str(path / "status.cpp"), "-o", str(path / "status")], check=True)
            subprocess.run([str(path / "status")], check=True)


if __name__ == "__main__":
    unittest.main()
