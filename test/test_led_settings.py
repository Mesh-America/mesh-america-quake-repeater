"""Exercise persisted LED commands on every filesystem backend."""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import unittest

from test_regulator_settings import FILESYSTEM
from test_serial_wifi_sessions import SANITIZER_FLAGS

ROOT = Path(__file__).resolve().parents[1]

BOARD = r'''
#pragma once
#include <cstdint>
namespace mesh {
namespace leds {
inline bool& state() { static bool value = true; return value; }
inline bool enabled() { return state(); }
inline void setEnabled(bool on) { state() = on; }
inline void applyStatusPolicy() {}
}
struct MainBoard {
  unsigned applies = 0;
  bool last_applied = true;
  void applyLedPolicy() { ++applies; last_applied = leds::enabled(); }
};
}
'''

HARNESS = r'''
#include <cassert>
#include <cstring>
#include <string>
#include <helpers/IdentityStore.h>
#include <MeshCore.h>
#if defined(NRF52_PLATFORM) || defined(STM32_PLATFORM)
#define ATOMIC_FILE_WRITER_IMPLEMENTATION
#include <helpers/AtomicFileWriter.h>
#undef ATOMIC_FILE_WRITER_IMPLEMENTATION
#endif
#include <helpers/LedSettings.cpp>

using namespace mesh::leds;
static const char* const target = "/leds_v1";
static const char* const rollback = "/leds_v1.bak";

std::string command(const char* text) {
  char reply[160] = {};
  assert(handleCommand(text, reply, sizeof(reply)));
  return reply;
}
void defaults() {
  mesh::MainBoard board;
  MockFS fs;
  setEnabled(false);
  beginSettings(board, &fs);
  assert(enabled() && board.last_applied && board.applies == 1);
  assert(command("get leds") == "> on");
  assert(fs.writes == 0);
  assert(command("set leds off") == "OK");
  assert(!enabled() && !board.last_applied && board.applies == 2);
  assert(command("get leds") == "> off");
  assert(fs.files[target].size() == 8);
  assert(!fs.exists("/leds_v1.tmp") && !fs.exists(rollback));
  setEnabled(true);
  beginSettings(board, &fs);
  assert(!enabled() && !board.last_applied);
  assert(command("set leds on") == "OK");
  beginSettings(board, &fs);
  assert(enabled() && board.last_applied);
  beginSettings(board, nullptr);
  const unsigned applies = board.applies;
  assert(command("set leds off").find("save unconfirmed") != std::string::npos);
  assert(enabled() && board.applies == applies);
}
void parsing() {
  mesh::MainBoard board;
  MockFS fs;
  beginSettings(board, &fs);
  const char* unrelated[] = {"", "g", "get", "get ", "get led", "get ledsX",
    "set ledsX off", "set led off", "get\tleds"};
  for (const char* text : unrelated) {
    char reply[80] = "untouched";
    assert(!handleCommand(text, reply, sizeof(reply)));
    assert(strcmp(reply, "untouched") == 0);
  }
  const char* invalid[] = {"set leds", "set leds ", "set leds 0",
    "set leds off extra", "set leds on ", "set leds ON", "get leds off", "get leds "};
  for (const char* text : invalid)
    assert(command(text).find("Error: usage") == 0);
  assert(fs.writes == 0 && board.applies == 1);
  assert(command("set leds\t off") == "OK" && !enabled());
  char bounded[3] = {'x', 'y', 'z'};
  assert(handleCommand("get leds", bounded, 1));
  assert(bounded[0] == 0 && bounded[1] == 'y' && bounded[2] == 'z');
  assert(!handleCommand(nullptr, bounded, sizeof(bounded)));
  assert(!handleCommand("get leds", nullptr, sizeof(bounded)));
  assert(!handleCommand("get leds", bounded, 0));
}
void failures() {
  for (unsigned failure = 0; failure < 5; ++failure) {
    mesh::MainBoard board;
    MockFS fs;
    beginSettings(board, &fs);
    assert(command("set leds on") == "OK");
    const auto original = fs.files[target];
    const unsigned applies = board.applies;
    if (failure == 0) fs.fail_open = true;
    if (failure == 1) fs.fail_write = true;
    if (failure == 2) fs.corrupt_write = true;
    if (failure == 3) fs.fail_rename_from = "/leds_v1.tmp";
    if (failure == 4) fs.fail_read_path = target;
    assert(command("set leds off").find("save unconfirmed") != std::string::npos);
    assert(enabled() && board.applies == applies);
    if (failure != 4) assert(fs.files[target] == original);
    fs.fail_open = fs.fail_write = fs.corrupt_write = false;
    fs.fail_rename_from.clear();
    fs.fail_read_path.clear();
    beginSettings(board, &fs);
    assert(enabled() == (failure != 4));
  }
}
void recovery() {
  mesh::MainBoard board;
  MockFS fs;
  beginSettings(board, &fs);
  assert(command("set leds off") == "OK");
  const auto saved = fs.files[target];
  fs.files[rollback] = saved;
  fs.files.erase(target);
  fs.files["/leds_v1.tmp"] = {'x'};
  beginSettings(board, &fs);
  assert(!enabled() && fs.files[target] == saved && !fs.exists(rollback));
  assert(command("set leds on") == "OK");
  assert(!fs.exists("/leds_v1.tmp"));
  fs.files[rollback] = saved;
  fs.files[target] = {'x'};
  beginSettings(board, &fs);
  assert(!enabled() && fs.files[target] == saved);
  fs.files[rollback] = saved;
  fs.files.erase(target);
  fs.fail_rename_from = rollback;
  beginSettings(board, &fs);
  assert(!enabled() && fs.files[rollback] == saved);
  const unsigned applies = board.applies;
  assert(command("set leds on").find("save unconfirmed") != std::string::npos);
  assert(!enabled() && board.applies == applies && fs.files[rollback] == saved);
}
void corrupt() {
  mesh::MainBoard board;
  MockFS fs;
  beginSettings(board, &fs);
  assert(command("set leds off") == "OK");
  const auto saved = fs.files[target];
  for (unsigned i = 0; i < saved.size(); ++i) {
    fs.files[target] = saved;
    fs.files[target][i] ^= 2;
    beginSettings(board, &fs);
    assert(enabled());
  }
  for (unsigned length = 0; length < saved.size(); ++length) {
    fs.files[target] = {saved.begin(), saved.begin() + length};
    beginSettings(board, &fs);
    assert(enabled());
  }
  fs.files[target] = saved;
  fs.files[target].push_back(0);
  beginSettings(board, &fs);
  assert(enabled());
}
int main() {
  defaults();
  parsing();
  failures();
  recovery();
  corrupt();
}
'''


class LedSettingsTests(unittest.TestCase):
    def test_commands_persistence_failures_and_recovery_across_platforms(self):
        compiler = os.environ.get("CXX") or shutil.which("g++") or shutil.which("clang++")
        if not compiler:
            self.skipTest("native C++ compiler unavailable")
        with tempfile.TemporaryDirectory(prefix="meshcore-led-settings-") as directory:
            folder = Path(directory)
            helpers = folder / "helpers"
            helpers.mkdir()
            filesystem = FILESYSTEM.replace(
                "  void flush() {}", "  void flush() {}\n  bool setBufferSize(size_t) { return true; }"
            ).replace(
                "#if !defined(NRF52_PLATFORM)",
                "#if !defined(NRF52_PLATFORM) && !defined(STM32_PLATFORM)",
            )
            (helpers / "IdentityStore.h").write_text(filesystem)
            (helpers / "ContactFileTransaction.h").write_text(
                (ROOT / "src/helpers/ContactFileTransaction.h").read_text()
            )
            (folder / "MeshCore.h").write_text(BOARD)
            source = folder / "test.cpp"
            source.write_text(HARNESS)
            for platform, flags in {
                "esp32": ["ESP32=1", "ESP32_PLATFORM=1"],
                "nrf52": ["NRF52_PLATFORM=1"],
                "stm32": ["STM32_PLATFORM=1"],
                "rp2040": ["RP2040_PLATFORM=1"],
            }.items():
                with self.subTest(platform=platform):
                    binary = folder / platform
                    built = subprocess.run(
                        [compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
                         *SANITIZER_FLAGS, *["-D" + flag for flag in flags],
                         "-I", str(folder), "-I", str(ROOT / "src"),
                         "-I", str(ROOT / "src/helpers"),
                         str(source), "-o", str(binary)],
                        capture_output=True, text=True, timeout=60,
                    )
                    self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
                    result = subprocess.run(
                        [str(binary)], capture_output=True, text=True, timeout=20
                    )
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
