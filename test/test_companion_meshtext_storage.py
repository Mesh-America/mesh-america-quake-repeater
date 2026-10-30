"""Exercise actual nRF52 Meshtext store methods and atomic writes without hardware."""

from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import unittest

from cpp_source import body

ROOT = Path(__file__).resolve().parents[1]

HARNESS = r'''
#include <algorithm>
#include <cassert>
#include <cstdint>
#include <cstring>
#include <initializer_list>
#include <limits>
#include <string>
#include <unordered_map>
#include <vector>
class FakeFilesystem;
class File {
  FakeFilesystem* fs;
  std::string path;
  size_t position = 0;
  bool opened = false;
  bool writing = false;
public:
  explicit File(FakeFilesystem& owner): fs(&owner) {}
  bool open(const char*, uint8_t);
  explicit operator bool() const { return opened; }
  size_t write(const uint8_t*, size_t);
  int read(void*, uint16_t);
  uint32_t size() const;
  bool isDirectory() const;
  void close() { opened = false; }
  void flush() {}
};
class FakeFilesystem {
public:
  std::unordered_map<std::string, std::vector<uint8_t>> files;
  unsigned read_failures = 0;
  bool stat_failure = false, rename_failure = false, false_rename = false;
  bool remove_failure = false, short_read = false, directory = false;
  size_t max_write = std::numeric_limits<size_t>::max();
  unsigned operations = 0;
  bool exists(const char* path) const { return files.count(path); }
  bool remove(const char* path) { ++operations; return !remove_failure && files.erase(path); }
  bool rename(const char* source, const char* target) {
    ++operations;
    if (rename_failure || !exists(source)) return false;
    if (!false_rename) { files[target] = files[source]; files.erase(source); }
    return true;
  }
};
enum { FILE_O_READ = 0, FILE_O_WRITE = 1 };
bool File::open(const char* value, uint8_t mode) {
  ++fs->operations; path = value; writing = mode == FILE_O_WRITE;
  if (!writing && fs->read_failures) { --fs->read_failures; return false; }
  if (!writing && !fs->exists(value)) return false;
  position = writing ? fs->files[path].size() : 0; opened = true; return true;
}
size_t File::write(const uint8_t* data, size_t size) {
  if (!opened || !writing) return 0;
  size = std::min(size, fs->max_write);
  auto& bytes = fs->files[path]; bytes.insert(bytes.end(), data, data + size);
  position += size; return size;
}
int File::read(void* data, uint16_t size) {
  if (!opened || writing) return -1;
  const auto& bytes = fs->files[path];
  size_t count = std::min<size_t>(size, bytes.size() - std::min(bytes.size(), position));
  if (fs->short_read && count) --count;
  memcpy(data, bytes.data() + position, count); position += count; return count;
}
uint32_t File::size() const { return fs->exists(path.c_str()) ? fs->files[path].size() : 0; }
bool File::isDirectory() const { return fs->directory; }
#define NRF52_PLATFORM 1
#define FILESYSTEM FakeFilesystem
#define ATOMIC_FILE_WRITER_IMPLEMENTATION
#include <helpers/AtomicFileWriter.h>
class DataStore {
public:
  FILESYSTEM* _fs;
  bool _primary_storage_unavailable = false, _volatile_primary_fs = false;
  explicit DataStore(FILESYSTEM& fs): _fs(&fs) {}
  bool loadMeshtextSettings(uint8_t[40], size_t&);
  bool saveMeshtextSettings(const uint8_t[40]);
  bool eraseMeshtextSettings();
  File openRead(FILESYSTEM* fs, const char* path) {
    File file(*fs); file.open(path, FILE_O_READ); return file;
  }
};
// Fault-injected metadata boundary; the methods themselves are production code.
static bool contactPathPresence(FILESYSTEM* fs, const char* path, bool& present,
                                uint32_t* size = nullptr) {
  ++fs->operations;
  if (fs->stat_failure) return false;
  present = fs->exists(path);
  if (present && size) *size = fs->files[path].size();
  return true;
}
__METHODS__
static std::vector<uint8_t> image(unsigned value) { return std::vector<uint8_t>(40, value); }
int main(int argc, char** argv) {
  assert(argc == 2); const std::string test = argv[1];
  FakeFilesystem fs; DataStore store(fs); uint8_t out[40]; memset(out, 77, sizeof(out));
  size_t size = 99; const auto old = image(11), replacement = image(22);
  if (test == "roundtrip") {
    assert(store.loadMeshtextSettings(out, size) && size == 0);
    assert(store.saveMeshtextSettings(old.data()));
    DataStore reboot(fs); assert(reboot.loadMeshtextSettings(out, size) && size == 40);
    assert(!memcmp(out, old.data(), 40));
    assert(store.saveMeshtextSettings(replacement.data()));
    assert(reboot.loadMeshtextSettings(out, size) && !memcmp(out, replacement.data(), 40));
    assert(fs.files.count("/mesh_mt") && !fs.files.count("/mesh_mt.tmp"));
  } else if (test == "sizes") {
    for (unsigned length : {0, 16, 39, 41, 400}) {
      fs.files["/mesh_mt"] = std::vector<uint8_t>(length, 33);
      assert(!store.loadMeshtextSettings(out, size) && size == 0 && out[0] == 77);
    }
    fs.files["/mesh_mt"] = old; fs.directory = true;
    assert(!store.loadMeshtextSettings(out, size) && out[0] == 77);
  } else if (test == "reads") {
    fs.files["/mesh_mt"] = old; fs.read_failures = 2;
    assert(store.loadMeshtextSettings(out, size) && size == 40 && !memcmp(out, old.data(), 40));
    memset(out, 77, sizeof(out)); fs.read_failures = 3;
    assert(!store.loadMeshtextSettings(out, size) && size == 0 && out[0] == 77);
    fs.short_read = true;
    assert(!store.loadMeshtextSettings(out, size) && size == 0 && out[0] == 77);
  } else if (test == "writes") {
    fs.files["/mesh_mt"] = old; fs.max_write = 10;
    assert(!store.saveMeshtextSettings(replacement.data()) && fs.files["/mesh_mt"] == old);
    fs.max_write = 40; fs.rename_failure = true;
    assert(!store.saveMeshtextSettings(replacement.data()) && fs.files["/mesh_mt"] == old);
    fs.rename_failure = false; fs.false_rename = true;
    assert(!store.saveMeshtextSettings(replacement.data()) && fs.files["/mesh_mt"] == old);
    assert(!fs.files.count("/mesh_mt.tmp"));
    fs.false_rename = false; fs.read_failures = 3;
    assert(!store.saveMeshtextSettings(replacement.data()) && fs.files["/mesh_mt"] == old);
  } else if (test == "quarantine") {
    for (unsigned reason = 0; reason != 3; ++reason) {
      store._primary_storage_unavailable = reason == 0;
      store._volatile_primary_fs = reason == 1; fs.stat_failure = reason == 2;
      assert(!store.loadMeshtextSettings(out, size) && size == 0);
      assert(!store.saveMeshtextSettings(replacement.data()));
      assert(!store.eraseMeshtextSettings());
    }
    assert(fs.files.empty());
  } else if (test == "staging_erase") {
    fs.files["/mesh_mt.tmp"] = replacement;
    assert(store.loadMeshtextSettings(out, size) && size == 0 && out[0] == 77);
    fs.files["/mesh_mt"] = old;
    assert(store.loadMeshtextSettings(out, size) && !memcmp(out, old.data(), 40));
    fs.remove_failure = true;
    assert(!store.eraseMeshtextSettings() && fs.files["/mesh_mt"] == old);
    assert(!store.saveMeshtextSettings(replacement.data()) && fs.files["/mesh_mt"] == old);
    fs.remove_failure = false; assert(store.eraseMeshtextSettings() && fs.files.empty());
    assert(store.eraseMeshtextSettings());
    assert(store.loadMeshtextSettings(out, size) && size == 0);
  } else return 2;
}
'''


class CompanionMeshtextStorageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = os.environ.get("CXX") or shutil.which("g++") or shutil.which("clang++")
        if not compiler:
            raise unittest.SkipTest("a host C++ compiler is required")
        cls.temp = tempfile.TemporaryDirectory(prefix="meshtext-storage-")
        cls.addClassCleanup(cls.temp.cleanup)
        source = (ROOT / "examples/companion_radio/DataStore.cpp").read_text(encoding="utf-8")
        methods = "\n".join(body(source, "bool DataStore::" + operation + "(") for operation in (
            "loadMeshtextSettings", "saveMeshtextSettings", "eraseMeshtextSettings"))
        directory = Path(cls.temp.name)
        harness = directory / "storage.cpp"
        harness.write_text(HARNESS.replace("__METHODS__", methods), encoding="ascii")
        cls.binary = directory / "storage"
        result = subprocess.run([compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
                                 "-I", str(ROOT / "src"), str(harness), "-o", str(cls.binary)],
                                capture_output=True, text=True, timeout=60)
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)

    def run_case(self, case):
        subprocess.run([str(self.binary), case], check=True, timeout=10)

    def test_primary_record_survives_reboot_and_verified_replacement(self):
        self.run_case("roundtrip")

    def test_truncated_oversized_and_directory_records_fail_closed(self):
        self.run_case("sizes")

    def test_bounded_read_recovery_preserves_output_on_failure(self):
        self.run_case("reads")

    def test_partial_write_and_failed_publish_preserve_committed_settings(self):
        self.run_case("writes")

    def test_metadata_errors_and_volatile_fallback_cannot_claim_durability(self):
        self.run_case("quarantine")

    def test_uncommitted_staging_is_ignored_and_explicit_erase_removes_both(self):
        self.run_case("staging_erase")


if __name__ == "__main__":
    unittest.main()
