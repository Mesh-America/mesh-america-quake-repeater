"""Exercise real OLED controller persistence and command code on the host."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]

# Adapted from test_display_power.py, with per-operation failures and the nRF52
# File API so the same persistence behavior is exercised on both FS APIs.
FS_STUB = r'''
#pragma once
#include <map>
#include <string>
#include <vector>
#include <cstring>
#include <cstdint>
#define FILE_O_READ 1
#define FILE_O_WRITE 2
struct FakeFS;
struct File {
  FakeFS* fs = nullptr;
  std::string name;
  File() = default;
  explicit File(FakeFS& backing) : fs(&backing) {}
  File(FakeFS* backing, const char* path) : fs(backing), name(path) {}
  explicit operator bool() const { return fs != nullptr; }
  bool open(const char*, int);
  size_t size() const;
  size_t read(uint8_t*, size_t);
  size_t write(const uint8_t*, size_t);
  void flush() {}
  bool isDirectory() const { return false; }
  void close() {}
};
struct FakeFS {
  std::map<std::string, std::vector<uint8_t>> files;
  bool fail_write = false, corrupt_write = false, fail_temp_read = false;
  bool fail_open_write = false, fail_publish = false, fail_rollback = false;
  bool fail_backup = false, fail_remove_backup = false, fail_remove_temp = false;
  bool fail_remove_primary = false;
  bool false_publish = false, late_publish_error = false, fail_public_read = false;
  bool published = false;
  unsigned calls = 0, writes = 0;
  bool exists(const char* name) { ++calls; return files.count(name); }
  bool remove(const char* name) {
    ++calls;
    const std::string path(name);
    if ((fail_remove_backup && path == "/display_controller.bak")
        || (fail_remove_temp && path == "/display_controller.tmp")
        || (fail_remove_primary && path == "/display_controller")) return false;
    files.erase(name); return true;
  }
  bool rename(const char* from, const char* to) {
    ++calls;
    const std::string source(from);
    if ((fail_publish && source == "/display_controller.tmp")
        || (fail_rollback && source == "/display_controller.bak")
        || (fail_backup && source == "/display_controller")) return false;
    if (!exists(from)) return false;
#if !defined(NRF52_PLATFORM)
    if (exists(to)) return false;
#endif
    if (source == "/display_controller.tmp" && false_publish) return true;
    files[to] = files[from]; files.erase(from);
    if (source == "/display_controller.tmp") {
      published = true;
      if (late_publish_error) return false;
    }
    return true;
  }
  File open(const char* name, const char* mode, bool = false) {
    ++calls;
    if (*mode == 'w') {
      if (fail_open_write) return {};
      files[name].clear();
    }
    if (!exists(name)) return {};
    return File(this, name);
  }
};
inline bool File::open(const char* path, int flags) {
  *this = fs->open(path, flags == FILE_O_WRITE ? "w" : "r");
  return bool(*this);
}
inline size_t File::size() const { return fs->files[name].size(); }
inline size_t File::read(uint8_t* out, size_t count) {
  if (fs->fail_temp_read && name == "/display_controller.tmp") return 0;
  if (fs->fail_public_read && fs->published && name == "/display_controller") return 0;
  const auto& bytes = fs->files[name];
  count = count < bytes.size() ? count : bytes.size();
  memcpy(out, bytes.data(), count); return count;
}
inline size_t File::write(const uint8_t* in, size_t count) {
  ++fs->writes;
  if (fs->fail_write) {
    fs->files[name].assign(in, in + count / 2);
    return count / 2;
  }
  fs->files[name].assign(in, in + count);
  if (fs->corrupt_write && count) fs->files[name][0] ^= 1;
  return count;
}
#define FILESYSTEM FakeFS
'''

TEST = r'''
#include <cassert>
#include <helpers/ui/OLEDControllerSettings.h>
#if defined(NRF52_PLATFORM)
#define ATOMIC_FILE_WRITER_IMPLEMENTATION
#include <helpers/AtomicFileWriter.h>
#endif
using namespace mesh::ui;
const char* name(OLEDControllerMode mode) {
  return mode == OLEDControllerMode::Auto ? "auto"
      : mode == OLEDControllerMode::SSD1306 ? "ssd1306" : "sh1106";
}
void run(const char* command, const std::string& expected, bool supported = true) {
  char reply[160];
  assert(handleOLEDControllerCommand(command, reply, sizeof(reply), supported));
  assert(std::string(reply) == expected);
}
std::string getter(OLEDControllerMode saved, OLEDControllerMode active) {
  return std::string("display.controller ") + name(saved) + " (active " + name(active)
      + (saved != active ? "; restart required)" : ")");
}
void set(OLEDControllerMode mode, OLEDControllerMode active) {
  run((std::string("set display.controller ") + name(mode)).c_str(),
      std::string("OK - display controller ") + name(mode)
          + (mode != active ? "; restart required" : ""));
}
std::vector<uint8_t> record(OLEDControllerMode mode) {
  std::vector<uint8_t> data = {'O', 'C', 1, uint8_t(mode), 0, 0};
  for (unsigned i = 0; i < 5; ++i) data[5] ^= data[i];
  return data;
}
void commandsAndRestart() {
  FakeFS fs;
  const auto initial = defaultOLEDControllerMode();
  assert(!loadOLEDControllerSettings(&fs));
  assert(oledControllerMode() == initial);
  assert(fs.files.empty());
  run("get display.controller", getter(initial, initial));
  char reply[160];
  for (const char* text : {"get display.controllers", "set display.controllerx auto",
                           "get display.mode", "display.controller", ""}) {
    assert(!handleOLEDControllerCommand(text, reply, sizeof(reply), true));
  }
  for (const char* value : {"", "0", "1", "ssd1305", "ssD1306 extra", "sh1106x",
                            "auto sh1106", "sh1106 ", "auto\t", "auto\n", "+auto"}) {
    run((std::string("set display.controller ") + value).c_str(),
        "Error: use set display.controller <auto|ssd1306|sh1106>");
    assert(fs.files.empty() && fs.writes == 0);
  }
  run("get display.controller extra", "Error: unexpected argument");
  run("get display.controller ", "Error: unexpected argument");
  run("set display.controller sh1106", "Error: display controller unsupported", false);
  run("get display.controller", "Error: display controller unsupported", false);
  assert(fs.files.empty() && oledControllerMode() == initial);
  // Explicitly selecting the default must survive later build-default changes.
  set(initial, initial);
  assert(fs.files.at("/display_controller") == record(initial) && fs.writes == 1);
  const unsigned initial_calls = fs.calls;
  set(initial, initial);
  assert(fs.calls == initial_calls && fs.writes == 1);
  const auto next = initial == OLEDControllerMode::SH1106
      ? OLEDControllerMode::SSD1306 : OLEDControllerMode::SH1106;
  run(next == OLEDControllerMode::SH1106 ? "set display.controller SH1106"
                                        : "set display.controller SsD1306",
      std::string("OK - display controller ") + name(next) + "; restart required");
  assert(oledControllerMode() == initial);
  run("get display.controller", getter(next, initial));
  assert(fs.files.at("/display_controller") == record(next));
  const auto complete = fs.files;
  const auto calls = fs.calls;
  const auto writes = fs.writes;
  set(next, initial);
  assert(fs.files == complete && fs.calls == calls && fs.writes == writes);
  assert(loadOLEDControllerSettings(&fs));
  assert(oledControllerMode() == next);
  run("get display.controller", getter(next, next));
  run("set display.controller AuTo", "OK - display controller auto; restart required");
  assert(oledControllerMode() == next);
  assert(fs.files.at("/display_controller") == record(OLEDControllerMode::Auto));
  assert(loadOLEDControllerSettings(&fs));
  assert(oledControllerMode() == OLEDControllerMode::Auto);
  // A saved Auto is authoritative even in a build compiled to force a chip.
  run("get display.controller", getter(OLEDControllerMode::Auto, OLEDControllerMode::Auto));
  set(OLEDControllerMode::SH1106, OLEDControllerMode::Auto);
  set(OLEDControllerMode::Auto, OLEDControllerMode::Auto);
  run("get display.controller", getter(OLEDControllerMode::Auto, OLEDControllerMode::Auto));
  char short_reply[4] = {'?', '?', '?', '?'};
  assert(handleOLEDControllerCommand("get display.controller", short_reply,
                                     sizeof(short_reply), true));
  assert(short_reply[3] == '\0');
  assert(!loadOLEDControllerSettings(nullptr));
  assert(oledControllerMode() == initial);
  run((std::string("set display.controller ") + name(initial)).c_str(),
      "Error: display controller save failed");
  assert(oledControllerMode() == initial);
  run("get display.controller", getter(initial, initial));
}
void failedSaves() {
  for (unsigned failure = 0; failure < 9; ++failure) {
    FakeFS fs;
    fs.files["/display_controller"] = record(OLEDControllerMode::SSD1306);
    assert(loadOLEDControllerSettings(&fs));
    const auto saved = fs.files.at("/display_controller");
    switch (failure) {
      case 0: fs.fail_write = true; break;
      case 1: fs.corrupt_write = true; break;
      case 2: fs.fail_temp_read = true; break;
      case 3: fs.fail_open_write = true; break;
      case 4: fs.fail_publish = true; break;
      case 5: fs.fail_backup = true; break;
      case 6:
        fs.files["/display_controller.bak"] = saved;
        fs.fail_remove_backup = true;
        break;
      case 7:
        fs.files["/display_controller.tmp"] = {1, 2, 3};
        fs.fail_remove_temp = true;
        break;
      case 8: fs.fail_publish = fs.fail_rollback = true; break;
    }
    run("set display.controller sh1106", "Error: display controller save failed");
    assert(oledControllerMode() == OLEDControllerMode::SSD1306);
    run("get display.controller", getter(OLEDControllerMode::SSD1306, OLEDControllerMode::SSD1306));
    if (failure == 8) {
      assert(!fs.files.count("/display_controller"));
      assert(fs.files.at("/display_controller.bak") == saved);
      const auto files = fs.files;
      const auto calls = fs.calls;
      // A second command before reboot must not rotate away the sole backup.
      run("set display.controller auto", "Error: display controller save failed");
      assert(fs.files == files && fs.calls == calls);
      run("get display.controller", getter(OLEDControllerMode::SSD1306, OLEDControllerMode::SSD1306));
    } else assert(fs.files.at("/display_controller") == saved);
    fs.fail_publish = fs.fail_rollback = false;
    assert(loadOLEDControllerSettings(&fs));
    assert(oledControllerMode() == OLEDControllerMode::SSD1306);
    assert(fs.files.at("/display_controller") == saved);
  }
}
#if defined(NRF52_PLATFORM)
void atomicSaves() {
  for (unsigned failure = 0; failure < 7; ++failure) {
    FakeFS fs;
    fs.files["/display_controller"] = record(OLEDControllerMode::SSD1306);
    assert(loadOLEDControllerSettings(&fs));
    const auto saved = fs.files.at("/display_controller");
    switch (failure) {
      case 0: fs.fail_write = true; break;
      case 1: fs.corrupt_write = true; break;
      case 2: fs.fail_temp_read = true; break;
      case 3: fs.fail_open_write = true; break;
      case 4: fs.fail_publish = true; break;
      case 5: fs.false_publish = true; break;
      case 6: fs.fail_public_read = true; break;
    }
    run("set display.controller sh1106", "Error: display controller save failed");
    assert(oledControllerMode() == OLEDControllerMode::SSD1306);
    run("get display.controller", getter(OLEDControllerMode::SSD1306, OLEDControllerMode::SSD1306));
    if (failure < 6) assert(fs.files.at("/display_controller") == saved);
    else assert(fs.files.at("/display_controller") == record(OLEDControllerMode::SH1106));
    if (failure >= 4) {
      const auto files = fs.files;
      const auto calls = fs.calls;
      // Indeterminate publication must block any later write until reloaded.
      run("set display.controller auto", "Error: display controller save failed");
      assert(fs.files == files && fs.calls == calls);
    }
    fs.fail_public_read = false;
    assert(loadOLEDControllerSettings(&fs));
    assert(oledControllerMode() == (failure < 6 ? OLEDControllerMode::SSD1306
                                              : OLEDControllerMode::SH1106));
  }
  FakeFS fs;
  fs.files["/display_controller"] = record(OLEDControllerMode::SSD1306);
  fs.files["/display_controller.bak"] = record(OLEDControllerMode::Auto);
  assert(loadOLEDControllerSettings(&fs));
  fs.late_publish_error = true;
  // Public-byte validation, rather than rename's return code, decides success.
  set(OLEDControllerMode::SH1106, OLEDControllerMode::SSD1306);
  assert(!fs.files.count("/display_controller.bak"));
  assert(loadOLEDControllerSettings(&fs));
  assert(oledControllerMode() == OLEDControllerMode::SH1106);
}
#endif
void corruptionAndRecovery() {
  const auto desired = OLEDControllerMode::SH1106;
  const auto good = record(desired);
  for (unsigned corrupt = 0; corrupt < 9; ++corrupt) {
    FakeFS fs;
    auto bytes = good;
    if (corrupt < 6) bytes[corrupt] ^= 1;
    else if (corrupt == 6) bytes.pop_back();
    else if (corrupt == 7) bytes.push_back(0);
    else {
      bytes[3] = 3; bytes[5] = 0;
      for (unsigned i = 0; i < 5; ++i) bytes[5] ^= bytes[i];
    }
    fs.files["/display_controller"] = bytes;
    fs.files["/display_controller.tmp"] = good;
    assert(!loadOLEDControllerSettings(&fs));
    assert(oledControllerMode() == defaultOLEDControllerMode());
    assert(fs.writes == 0); // Unpublished temp data is never selected.
    fs.files["/display_controller.bak"] = good;
    assert(loadOLEDControllerSettings(&fs));
    assert(oledControllerMode() == desired);
    assert(fs.files.at("/display_controller") == good);
    assert(!fs.files.count("/display_controller.bak"));
  }
  FakeFS fs;
  fs.files["/display_controller.bak"] = good;
  assert(loadOLEDControllerSettings(&fs));
  assert(oledControllerMode() == desired);
  // A valid published primary wins over a stale backup.
  fs.files["/display_controller"] = record(OLEDControllerMode::Auto);
  fs.files["/display_controller.bak"] = good;
  assert(loadOLEDControllerSettings(&fs));
  assert(oledControllerMode() == OLEDControllerMode::Auto);
  fs.files.erase("/display_controller");
  fs.fail_rollback = true;
  assert(loadOLEDControllerSettings(&fs));
  assert(oledControllerMode() == desired); // Readable backup survives repair failure.
  assert(fs.files.at("/display_controller.bak") == good);
  const auto before = fs.files;
  const auto calls = fs.calls;
  set(desired, desired);
  assert(fs.files == before && fs.calls == calls);
  run("set display.controller auto", "Error: display controller save failed");
  assert(fs.files == before && oledControllerMode() == desired);
  fs.fail_rollback = false;
  assert(loadOLEDControllerSettings(&fs));
  assert(fs.files.at("/display_controller") == good);
  set(OLEDControllerMode::Auto, desired);
  assert(loadOLEDControllerSettings(&fs));
  assert(oledControllerMode() == OLEDControllerMode::Auto);
  // Failure to remove a corrupt primary must also protect the sole good backup.
  fs.files["/display_controller"] = {1, 2, 3};
  fs.files["/display_controller.bak"] = good;
  fs.fail_remove_primary = true;
  assert(loadOLEDControllerSettings(&fs));
  assert(oledControllerMode() == desired);
  const auto recovery_files = fs.files;
  run("set display.controller auto", "Error: display controller save failed");
  assert(fs.files == recovery_files);
  fs.fail_remove_primary = false;
  assert(loadOLEDControllerSettings(&fs));
  assert(fs.files.at("/display_controller") == good);
}
int main() {
  commandsAndRestart();
#if defined(NRF52_PLATFORM)
  atomicSaves();
#else
  failedSaves();
#endif
  corruptionAndRecovery();
}
'''


class OLEDControllerSettingsTests(unittest.TestCase):
    def compile_and_run(self, default_mode=0, platform=None):
        compiler = shutil.which("g++")
        if compiler is None:
            self.skipTest("g++ unavailable")
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            include = temporary / "helpers"
            include.mkdir()
            (include / "IdentityStore.h").write_text(FS_STUB, encoding="ascii")
            source = temporary / "main.cpp"
            source.write_text(TEST, encoding="ascii")
            executable = temporary / "test"
            command = [
                compiler, "-std=c++11", "-Wall", "-Wextra", "-Werror",
                "-DOLED_AUTO_DETECT=1", f"-DOLED_CONTROLLER_OVERRIDE={default_mode}",
                f"-I{temporary}", f"-I{ROOT / 'src'}", str(source),
                str(ROOT / "src/helpers/ui/OLEDControllerSettings.cpp"),
                "-o", str(executable),
            ]
            if platform:
                command.insert(1, f"-D{platform}")
            subprocess.run(command, check=True, capture_output=True, text=True)
            subprocess.run([str(executable)], check=True, capture_output=True, text=True)

    def test_saved_mode_and_atomic_failures_for_each_build_default(self):
        for mode in (0, 1, 2):
            with self.subTest(default_mode=mode):
                self.compile_and_run(default_mode=mode)

    def test_nrf52_filesystem_api(self):
        self.compile_and_run(platform="NRF52_PLATFORM")

    def test_rp2040_filesystem_api(self):
        self.compile_and_run(platform="RP2040_PLATFORM")


if __name__ == "__main__":
    unittest.main()
