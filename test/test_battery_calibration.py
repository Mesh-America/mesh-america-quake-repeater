"""Exercise production battery calibration parsing, scaling and command behavior."""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest
from test_replay_reset_integration import extract_braced

ROOT = Path(__file__).resolve().parents[1]

HARNESS = r'''
#include <helpers/BatteryCalibration.h>
#include <cassert>
#include <cmath>
#include <cstring>
#include <limits>
#include <initializer_list>

using namespace mesh::power;
struct Board {
  float multiplier = 1.0f;
  uint16_t millivolts = 4000;
  unsigned reads = 0;
  float getAdcMultiplier() const { return multiplier; }
  uint16_t getBattMilliVolts() { ++reads; return millivolts; }
};

int main() {
  assert(validRelativeBatteryMultiplier(0));
  assert(validRelativeBatteryMultiplier(0.5f));
  assert(validRelativeBatteryMultiplier(1.5f));
  assert(!validRelativeBatteryMultiplier(0.499f));
  assert(!validRelativeBatteryMultiplier(1.501f));
  assert(!validRelativeBatteryMultiplier(NAN));
  assert(!validRelativeBatteryMultiplier(INFINITY));
  assert(scaleBatteryMillivolts(4000, 1.05f) == 4200);
  assert(scaleBatteryMillivolts(1001, 0.5f) == 501);
  assert(scaleBatteryMillivolts(0, 1.5f) == 0);
  assert(scaleBatteryMillivolts(60000, 1.5f) == UINT16_MAX);
  assert(scaleBatteryMillivolts(4000, NAN) == 4000);
  assert(scaleBatteryMillivolts(4000, 0) == 4000);

  uint16_t parsed = 123;
  assert(parseBatteryReferenceMillivolts("4.18", parsed) && parsed == 4180);
  assert(parseBatteryReferenceMillivolts("13.200", parsed) && parsed == 13200);
  assert(parseBatteryReferenceMillivolts("65.535\t ", parsed) && parsed == 65535);
  assert(parseBatteryReferenceMillivolts("0.001", parsed) && parsed == 1);
  for (const char* bad : {"", "0", "0.000", "-4.2", "+4.2", "nan", "inf",
       "4e0", "4.2V", "4.2 extra", "4.", "4.2000", "65.536", "999999999999"}) {
    parsed = 123;
    assert(!parseBatteryReferenceMillivolts(bad, parsed) && parsed == 123);
  }

  Board board;
  char reply[160] = {};
  bool save_ok = true;
  unsigned saves = 0;
  float saved = -1;
  auto setter = [&](float value, char* error, size_t capacity) {
    ++saves;
    if (!save_ok) {
      snprintf(error, capacity, "Error: simulated save failure");
      return false;
    }
    saved = value;
    board.multiplier = value == 0 ? 1 : value;
    return true;
  };
  auto run = [&](const char* command) {
    strcpy(reply, "untouched");
    return handleBatteryCalibrationCommand(board, command, reply, sizeof(reply), setter);
  };
  assert(!run("battery calibrateX 4.18") && saves == 0);
  assert(strcmp(reply, "untouched") == 0);
  assert(run("battery calibrate 4.18") && saves == 1);
  assert(fabs(saved - 1.045f) < 0.00001f);
  assert(strstr(reply, "4.180 V") && strstr(reply, "(saved)"));
  // Repeat calibration composes with the effective existing multiplier.
  board.millivolts = 4180;
  assert(run("battery calibrate 4.18") && saves == 2);
  assert(fabs(saved - 1.045f) < 0.00001f);
  // Works with an existing absolute board coefficient too.
  board.multiplier = 5.42f;
  board.millivolts = 4000;
  assert(run("battery calibrate 4.18") && saves == 3);
  assert(fabs(saved - 5.6639f) < 0.0001f);
  // Pack voltages are not limited to single-cell lithium values.
  board.multiplier = 1;
  board.millivolts = 13000;
  assert(run("battery calibrate 13.2") && saves == 4);
  assert(fabs(saved - 13200.0f / 13000.0f) < 0.00001f);
  const unsigned before = saves;
  for (const char* command : {"battery calibrate", "battery calibrate 0",
       "battery calibrate 4.2junk", "battery calibrate resetjunk",
       "battery calibrate nan", "battery calibrate 4.2", "battery calibrate 65"}) {
    assert(run(command) && strncmp(reply, "Error:", 6) == 0 && saves == before);
  }
  board.millivolts = 0;
  assert(run("battery calibrate 13.2") && saves == before);
  board.millivolts = UINT16_MAX;
  assert(run("battery calibrate 13.2") && saves == before);
  // Reset is allowed even while the voltage is unavailable.
  assert(run("battery calibrate reset") && saves == before + 1 && saved == 0);
  board.millivolts = 4000;
  save_ok = false;
  const float previous = board.multiplier;
  assert(run("battery calibrate 4.18"));
  assert(strcmp(reply, "Error: simulated save failure") == 0);
  assert(board.multiplier == previous);
  board.multiplier = 0;
  const unsigned unsupported_saves = saves, unsupported_reads = board.reads;
  assert(run("battery calibrate 4.18") && strstr(reply, "unsupported"));
  assert(run("battery calibrate reset") && strstr(reply, "unsupported"));
  assert(saves == unsupported_saves && board.reads == unsupported_reads);
  board.multiplier = NAN;
  assert(run("battery calibrate 4.18") && saves == unsupported_saves);
  // Replies obey a prefixed Companion console's smaller buffer.
  board.multiplier = 1;
  char tiny[12];
  memset(tiny, 'x', sizeof(tiny));
  assert(handleBatteryCalibrationCommand(board, "battery calibrate", tiny, 8, setter));
  assert(tiny[7] == 0 && tiny[8] == 'x');
}
'''

BOARD_HARNESS = r'''
#include <MeshCore.h>
#include <cassert>
#include <cmath>
struct ADCBoard : mesh::MainBoard {
  uint16_t raw = 4000;
  bool supportsBatteryCalibration() const override { return true; }
  uint16_t getBattMilliVolts() override { return calibrateBatteryMillivolts(raw); }
  const char* getManufacturerName() const override { return "test ADC"; }
  void reboot() override {}
  uint8_t getStartupReason() const override { return 0; }
};
struct UnsupportedBoard : ADCBoard {
  bool supportsBatteryCalibration() const override { return false; }
};
int main() {
  ADCBoard board;
  assert(board.getAdcMultiplier() == 1 && board.getBattMilliVolts() == 4000);
  assert(board.setAdcMultiplier(1.05f) && board.getBattMilliVolts() == 4200);
  for (float invalid : {NAN, INFINITY, -INFINITY, -1.0f, 0.49f, 1.51f}) {
    assert(!board.setAdcMultiplier(invalid));
    assert(board.getBattMilliVolts() == 4200);
  }
  assert(board.setAdcMultiplier(0) && board.getBattMilliVolts() == 4000);
  assert(board.setAdcMultiplier(1.5f));
  board.raw = 60000;
  assert(board.getBattMilliVolts() == UINT16_MAX);
  board.raw = 0;
  assert(board.getBattMilliVolts() == 0);
  UnsupportedBoard unsupported;
  assert(unsupported.getAdcMultiplier() == 0);
  assert(!unsupported.setAdcMultiplier(1.05f));
}
'''


class BatteryCalibrationTests(unittest.TestCase):
    def exercise(self, harness):
        with tempfile.TemporaryDirectory(prefix="battery-calibration-") as folder:
            source, binary = Path(folder) / "main.cpp", Path(folder) / "check"
            source.write_text("#include <initializer_list>\n" + harness)
            build = subprocess.run([
                os.environ.get("CXX", "g++"), "-std=c++17", "-O1", "-g",
                "-Wall", "-Wextra", "-Werror", "-Wno-unused-parameter",
                "-fsanitize=address,undefined",
                "-fno-sanitize-recover=all", "-fno-pie", "-no-pie", "-I",
                str(ROOT / "src"), str(source), "-o", str(binary)
            ], capture_output=True, text=True, timeout=60)
            self.assertEqual(build.returncode, 0, build.stdout + build.stderr)
            result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_production_calibration_commands(self):
        self.exercise(HARNESS)

    def test_actual_board_calibration(self):
        self.exercise(BOARD_HARNESS)

    def test_nrf52_boot_policy_takes_priority_without_double_scaling(self):
        source = (ROOT / "src/helpers/NRF52Board.cpp").read_text()
        methods = "\n".join(extract_braced(source, signature) for signature in (
            "uint16_t NRF52Board::calibrateBatteryMillivolts(",
            "float NRF52Board::getAdcMultiplier("))
        self.exercise(r'''
#define NRF52_POWER_MANAGEMENT 1
#include <MeshCore.h>
#include <helpers/NRF52VoltageRules.h>
#include <cassert>
#include <cmath>
namespace mesh { namespace power {
bool policy_ready = false;
bool voltagePolicySupported() { return policy_ready; }
uint16_t configuredAdcPermille() { return 1050; }
}}
class NRF52Board : public mesh::MainBoard {
public:
  bool supportsBatteryCalibration() const override { return true; }
  uint16_t calibrateBatteryMillivolts(uint16_t) const;
  float getAdcMultiplier() const override;
  uint16_t getBattMilliVolts() override { return calibrateBatteryMillivolts(4000); }
  const char* getManufacturerName() const override { return "fixture"; }
  uint8_t getStartupReason() const override { return 0; }
  void reboot() override {}
};
''' + methods + r'''
int main() {
  NRF52Board board;
  // Early startup has not loaded the boot policy yet.
  assert(board.getBattMilliVolts() == 4000 && board.getAdcMultiplier() == 1);
  // A board without boot policy uses the common calibration normally.
  assert(board.setAdcMultiplier(1.2f) && board.getBattMilliVolts() == 4800);
  mesh::power::policy_ready = true;
  // A loaded policy is authoritative, rather than stacking two corrections.
  assert(board.getBattMilliVolts() == 4200);
  assert(fabs(board.getAdcMultiplier() - 1.05f) < 0.00001f);
  assert(board.calibrateBatteryMillivolts(0) == 0);
  assert(board.calibrateBatteryMillivolts(65000) == UINT16_MAX);
}
''')


if __name__ == "__main__":
    unittest.main()
