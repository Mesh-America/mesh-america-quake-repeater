"""Exercise the production calibration store and rollback across filesystems."""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]

HARNESS = r'''
#include <helpers/BatteryCalibrationStore.h>
#include <helpers/BatteryCalibration.h>
#include <cassert>
#include <cmath>
#include <cstring>
#include <string>
#include <vector>
#if defined(NRF52_PLATFORM) || defined(STM32_PLATFORM)
#define ATOMIC_FILE_WRITER_IMPLEMENTATION
#include <helpers/AtomicFileWriter.h>
#endif
#include "store_under_test.cpp"

struct Board : mesh::MainBoard {
  bool capable = true;
  uint16_t raw = 4000;
  bool supportsBatteryCalibration() const override { return capable; }
  uint16_t getBattMilliVolts() override { return calibrateBatteryMillivolts(raw); }
  const char* getManufacturerName() const override { return "fixture"; }
  uint8_t getStartupReason() const override { return 0; }
  void reboot() override {}
  void sleep(uint32_t) override {}
};
int main() {
  using namespace mesh::power;
  MemoryFS fs;
#if defined(NRF52_PLATFORM) || defined(STM32_PLATFORM)
  fs.rename_replaces = true;
#endif
  Board board;
  assert(beginBatteryCalibrationStore(board, &fs));
  assert(fs.files.empty() && board.getAdcMultiplier() == 1);
  char reply[160];
  auto run = [&](const char* command) {
    strcpy(reply, "untouched");
    return handleStoredBatteryCalibrationCommand(board, command, reply, sizeof(reply));
  };
  assert(run("get adc.multiplier") && !strcmp(reply, "> 1.000"));
  assert(!run("get adc.multiplierXYZ") && !strcmp(reply, "untouched"));
  assert(run("battery calibrate 4.18") && strstr(reply, "(saved)"));
  assert(fabs(board.getAdcMultiplier() - 1.045f) < 0.00001f);
  assert(board.getBattMilliVolts() == 4180);
  const auto good = fs.files.at("/battery_cal");
  assert(good.size() == 12);
  Board rebooted;
  assert(beginBatteryCalibrationStore(rebooted, &fs));
  assert(fabs(rebooted.getAdcMultiplier() - 1.045f) < 0.00001f);
  fs.fail_write = true;
  assert(run("set adc.multiplier 1.1") && strstr(reply, "save unconfirmed"));
  assert(fabs(board.getAdcMultiplier() - 1.045f) < 0.00001f);
  assert(fs.files.at("/battery_cal") == good);
  fs.fail_write = false;
  // Publication can succeed before verification fails. Report uncertainty
  // and restore runtime without claiming the old disk image survived.
  fs.fail_after_publication = true;
  assert(run("set adc.multiplier 1.1") && strstr(reply, "save unconfirmed"));
  assert(fabs(board.getAdcMultiplier() - 1.045f) < 0.00001f);
  assert(fs.files.at("/battery_cal") != good);
  fs.fail_after_publication = false;
  fs.fail_read_open = false;
  Board published;
  assert(beginBatteryCalibrationStore(published, &fs));
  assert(fabs(published.getAdcMultiplier() - 1.1f) < 0.00001f);
  fs.files["/battery_cal"] = good;
  for (const char* command : {"set adc.multiplier nan", "set adc.multiplier 1junk",
       "set adc.multiplier -1", "set adc.multiplier 1.6",
       "get adc.multiplier junk", "battery calibrate 0"}) {
    assert(run(command) && !strncmp(reply, "Error:", 6));
    assert(fs.files.at("/battery_cal") == good);
  }
  // Complete but corrupted records, truncations and invalid factors cannot
  // change the factory conversion on a new instance.
  for (size_t bit = 0; bit < good.size() * 8; ++bit) {
    fs.files["/battery_cal"] = good;
    fs.files["/battery_cal"][bit / 8] ^= uint8_t(1U << (bit % 8));
    Board fresh;
    assert(!beginBatteryCalibrationStore(fresh, &fs));
    assert(fresh.getAdcMultiplier() == 1);
  }
  fs.files["/battery_cal"] = good;
  fs.files["/battery_cal"].pop_back();
  Board truncated;
  assert(!beginBatteryCalibrationStore(truncated, &fs));
  assert(truncated.getAdcMultiplier() == 1);
  fs.files["/battery_cal"] = good;
  assert(run("battery calibrate reset") && strstr(reply, "(saved)"));
  assert(board.getAdcMultiplier() == 1);
  Board reset;
  assert(beginBatteryCalibrationStore(reset, &fs) && reset.getAdcMultiplier() == 1);
  board.capable = false;
  assert(run("get adc.multiplier") && strstr(reply, "unsupported"));
  assert(run("battery calibrate 4.18") && strstr(reply, "unsupported"));
  assert(run("set adc.multiplier 1.1") && strstr(reply, "unsupported"));
  board.capable = true;
#if defined(ESP32_PLATFORM) || defined(RP2040_PLATFORM)
  // Recover the old record if a reset interrupted the two-rename publication.
  fs.files["/battery_cal.bak"] = good;
  fs.files.erase("/battery_cal");
  Board recovered;
  assert(beginBatteryCalibrationStore(recovered, &fs));
  assert(recovered.getBattMilliVolts() == 4180);
#endif
  char bounded[4] = {'X', 'X', 'X', 'Z'};
  assert(handleStoredBatteryCalibrationCommand(board, "get adc.multiplier", bounded, 3));
  assert(bounded[2] == 0 && bounded[3] == 'Z');
  // A failed mount or volatile fallback must not claim reboot persistence.
  assert(!beginBatteryCalibrationStore(board, nullptr));
  const float before_missing_fs = board.getAdcMultiplier();
  assert(run("battery calibrate 4.18") && strstr(reply, "save unconfirmed"));
  assert(board.getAdcMultiplier() == before_missing_fs);
}
'''


class BatteryCalibrationStoreTests(unittest.TestCase):
    def test_roundtrip_corruption_write_failure_reset_and_backup_recovery(self):
        with tempfile.TemporaryDirectory(prefix="battery-calibration-store-") as temp:
            work = Path(temp)
            (work / "helpers").mkdir()
            mock = ROOT / "test/fixtures/radio_profiles/mocks/helpers/IdentityStore.h"
            mock_text = mock.read_text(encoding="ascii")
            mock_text = mock_text.replace("  bool fail_read_open = false;",
                                          "  bool fail_read_open = false;\n  bool fail_after_publication = false;")
            mock_text = mock_text.replace("    files[to] = files[from]; files.erase(from); return true;",
                "    files[to] = files[from]; files.erase(from);\n"
                "    if (fail_after_publication && !strcmp(to, \"/battery_cal\")) fail_read_open = true;\n"
                "    return true;")
            (work / "helpers/IdentityStore.h").write_text(mock_text, encoding="ascii")
            # Redirect only the hardware boundary include. The transaction and
            # calibration implementation bodies remain production code.
            transaction = (ROOT / "src/helpers/ContactFileTransaction.h").read_text(encoding="ascii")
            transaction = transaction.replace('#include "IdentityStore.h"', '#include <helpers/IdentityStore.h>')
            transaction = transaction.replace('#include "PersistentStoreFormat.h"', '#include <helpers/PersistentStoreFormat.h>')
            (work / "helpers/ContactFileTransaction.h").write_text(transaction, encoding="ascii")
            store = (ROOT / "src/helpers/BatteryCalibrationStore.cpp").read_text(encoding="ascii")
            for header in ("BatteryCalibrationStore.h", "BatteryCalibration.h", "CheckedSettingsFile.h",
                           "CLICommandUtils.h", "PersistentStoreFormat.h", "AtomicFileWriter.h",
                           "ContactFileTransaction.h", "NRF52VoltagePolicy.h"):
                store = store.replace(f'#include "{header}"', f'#include <helpers/{header}>')
            (work / "store_under_test.cpp").write_text(store, encoding="ascii")
            (work / "test.cpp").write_text(HARNESS, encoding="ascii")
            for platform in ("ESP32_PLATFORM", "RP2040_PLATFORM", "NRF52_PLATFORM", "STM32_PLATFORM"):
                with self.subTest(platform=platform):
                    binary = work / platform
                    built = subprocess.run([
                        os.environ.get("CXX", "g++"), "-std=c++17", "-O1", "-Wall", "-Wextra", "-Werror",
                        "-Wno-sign-compare", "-Wno-unused-parameter", "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
                        "-fno-pie", "-no-pie", "-D" + platform,
                        "-I" + str(work), "-I" + str(ROOT / "src"),
                        str(work / "test.cpp"), "-o", str(binary),
                    ], capture_output=True, text=True, timeout=60)
                    self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
                    result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=20)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
