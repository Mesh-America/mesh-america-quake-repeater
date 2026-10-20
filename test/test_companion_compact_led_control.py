"""Exercise the compact Companion LED CLI and its existing preference store."""

from pathlib import Path
import os
import re
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


def method(source, name):
    match = re.search(rf"\bbool\s+MyMesh::{name}\([^)]*\)\s*\{{", source)
    if not match:
        raise AssertionError(f"production {name} is missing")
    end, depth = match.end(), 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[match.start():end]


def startup_loader():
    source = (ROOT / "examples/companion_radio/MyMesh.cpp").read_text()
    setup = source.split("void MyMesh::configureRadioFromPrefs() {", 1)[1]
    match = re.search(
        r"#if defined\(WIO_E5_MINI_HEADLESS_COMPANION_UI\)\n(.*?)#endif", setup, re.S)
    if not match:
        raise AssertionError("compact LED startup restore is missing")
    return "void MyMesh::loadCompactLedSetting() {\n" + match.group(1) + "}\n"


STUBS = r"""
#include <helpers/LedPolicy.h>
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <initializer_list>
#include <string>
#include <vector>
std::vector<std::string> events;
struct Prefs {
  uint8_t leds_quiet = 0;
  uint32_t unrelated = 0x12345678;
};
struct Board {
  unsigned applies = 0;
  bool level = true;
  void applyLedPolicy() {
    events.push_back("board");
    ++applies;
    level = mesh::leds::enabled();
  }
} board;
unsigned status_applies = 0;
bool status_level = true;
namespace mesh { namespace leds {
void applyStatusPolicy() {
  events.push_back("status");
  ++status_applies;
  status_level = enabled();
}
}}
class MyMesh {
public:
  Prefs _prefs;
  Prefs saved;
  bool save_ok = true;
  unsigned saves = 0;
  bool savePrefs() {
    events.push_back("save");
    ++saves;
    if (!save_ok) return false;
    saved = _prefs;
    return true;
  }
  bool handleCompactLedCommand(const char*, char*, size_t);
  void loadCompactLedSetting();
};
void reset() {
  mesh::leds::setEnabled(true);
  board.applies = status_applies = 0;
  board.level = status_level = true;
  events.clear();
}
"""


SCENARIOS = r"""
std::string run(MyMesh& mesh, const char* command) {
  char reply[160] = {};
  assert(mesh.handleCompactLedCommand(command, reply, sizeof(reply)));
  return reply;
}
int main() {
  reset();
  MyMesh mesh;
  assert(run(mesh, "get leds") == "> on");
  assert(mesh.saves == 0 && board.applies == 0 && status_applies == 0);
  for (const char* command : {"set leds", "set leds ",
       "set leds 1", "set leds 0", "set leds ON", "set leds OFF", "set leds true",
       "set leds off extra", "set leds on extra"}) {
    assert(run(mesh, command).find("Error") == 0);
    assert(mesh.saves == 0 && board.applies == 0 && status_applies == 0);
    assert(mesh::leds::enabled());
  }
  for (const char* command : {"get leds on", "get leds ", "get led", "get leds.extra", "get ledsx", "set ledsx on",
       "set led on", "get buzzer", "get radio", "get", "set", ""}) {
    char reply[16] = "unchanged";
    assert(!mesh.handleCompactLedCommand(command, reply, sizeof(reply)));
    assert(strcmp(reply, "unchanged") == 0);
  }
  assert(run(mesh, "set leds on") == "OK");
  assert(mesh.saves == 0);
  assert(mesh._prefs.leds_quiet == 0);

  // An unchanged stored preference can repair stale live policy without flash.
  mesh::leds::setEnabled(false);
  assert(run(mesh, "set leds on") == "OK");
  assert(mesh.saves == 0 && mesh::leds::enabled() && board.level && status_level);
  events.clear();
  const unsigned applied = board.applies, status = status_applies;

  // A failed preference transaction restores the byte and leaves live output.
  mesh.save_ok = false;
  assert(run(mesh, "set leds off").find("Error") == 0);
  assert(mesh.saves == 1 && mesh._prefs.leds_quiet == 0);
  assert(mesh::leds::enabled() && mesh.saved.leds_quiet == 0);
  assert(board.applies == applied && status_applies == status);
  assert(events == std::vector<std::string>{"save"});

  mesh.save_ok = true;
  events.clear();
  assert(run(mesh, "set leds off") == "OK");
  assert(mesh.saves == 2 && !mesh::leds::enabled());
  assert(mesh._prefs.leds_quiet == 1 && mesh.saved.leds_quiet == 1);
  assert(mesh._prefs.unrelated == 0x12345678 && mesh.saved.unrelated == 0x12345678);
  assert(board.applies == applied + 1 && !board.level);
  assert(status_applies == status + 1 && !status_level);
  assert((events == std::vector<std::string>{"save", "board", "status"}));
  assert(run(mesh, "get leds") == "> off");
  assert(run(mesh, "set leds off") == "OK" && mesh.saves == 2);

  // Reload durable preference bytes through the actual compact startup block.
  MyMesh reboot;
  reboot._prefs = mesh.saved;
  reset();
  reboot.loadCompactLedSetting();
  assert(!mesh::leds::enabled());
  assert(board.applies == 1 && !board.level && status_applies == 1 && !status_level);
  assert(run(reboot, "get leds") == "> off");
  assert(run(reboot, "set leds off") == "OK" && reboot.saves == 0);
  reboot.save_ok = false;
  const unsigned before_failed_apply = board.applies, before_failed_status = status_applies;
  assert(run(reboot, "set leds on").find("Error") == 0 && reboot.saves == 1);
  assert(reboot._prefs.leds_quiet == 1 && !mesh::leds::enabled());
  assert(board.applies == before_failed_apply && status_applies == before_failed_status);
  reboot.save_ok = true;
  assert(run(reboot, "set leds on") == "OK" && reboot.saves == 2);
  assert(reboot.saved.leds_quiet == 0 && reboot.saved.unrelated == 0x12345678);
  assert(mesh::leds::enabled() && board.level && status_level);
  MyMesh restored_on;
  restored_on._prefs = reboot.saved;
  mesh::leds::setEnabled(false);
  restored_on.loadCompactLedSetting();
  assert(mesh::leds::enabled() && board.level && status_level);

  // Historic reserved zero means on; only exactly one requests quiet LEDs.
  for (unsigned value = 0; value < 256; ++value) {
    MyMesh fresh;
    fresh._prefs.leds_quiet = value;
    reset();
    mesh::leds::setEnabled(false);
    fresh.loadCompactLedSetting();
    const bool on = value != 1;
    assert(mesh::leds::enabled() == on && fresh._prefs.leds_quiet == !on);
    assert(board.applies == 1 && board.level == on);
    assert(status_applies == 1 && status_level == on);
    assert(fresh.saves == 0);
  }
  for (const char* command : {"get leds", "set leds invalid", "set leds off", "set leds on"}) {
    for (size_t capacity = 1; capacity <= 160; ++capacity) {
      char reply[164]; memset(reply, '#', sizeof(reply));
      memcpy(reply, "ab|", 3);
      assert(mesh.handleCompactLedCommand(command, reply + 3, capacity));
      assert(memcmp(reply, "ab|", 3) == 0 && reply[3 + capacity] == '#');
      assert(memchr(reply + 3, 0, capacity));
    }
  }
  char reply[16];
  assert(!mesh.handleCompactLedCommand(nullptr, reply, sizeof(reply)));
  assert(!mesh.handleCompactLedCommand("get leds", nullptr, sizeof(reply)));
  assert(!mesh.handleCompactLedCommand("get leds", reply, 0));
}
"""


class CompanionCompactLedControlTests(unittest.TestCase):
    def test_preference_byte_storage_and_policy(self):
        compiler = os.environ.get("CXX") or shutil.which("g++") or shutil.which("clang++")
        if not compiler:
            self.skipTest("C++ compiler unavailable")
        source = (ROOT / "examples/companion_radio/Notifications.cpp").read_text()
        source = STUBS + method(source, "handleCompactLedCommand") + startup_loader() + SCENARIOS
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            cpp = directory / "compact_led_cli.cpp"
            exe = directory / ("compact_led_cli.exe" if os.name == "nt" else "compact_led_cli")
            cpp.write_text(source, encoding="ascii")
            flags = [] if os.name == "nt" else [
                "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
                "-fno-omit-frame-pointer", "-fno-pie", "-no-pie"]
            result = subprocess.run(
                [compiler, "-std=c++11", "-Wall", "-Wextra", *flags,
                 "-DWIO_E5_MINI_HEADLESS_COMPANION_UI=1", "-I", str(ROOT / "src"),
                 str(cpp), "-o", str(exe)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            result = subprocess.run([str(exe)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
