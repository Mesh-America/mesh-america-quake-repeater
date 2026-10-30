"""Exercise the production per-image bootloader lock with filesystem faults."""

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
FILESYSTEM = r'''
#pragma once
#include <algorithm>
#include <cstdint>
#include <cstring>
#include <limits>
#include <map>
#include <set>
#include <string>
#include <vector>
struct lfs_info {};
static const int LFS_ERR_NOENT = -2;
static const uint8_t FILE_O_READ = 0, FILE_O_WRITE = 1;
class FakeFilesystem;
class File {
  FakeFilesystem* fs;
  std::string path;
  size_t position = 0;
  bool opened = false, writing = false;
public:
  explicit File(FakeFilesystem& filesystem) : fs(&filesystem) {}
  bool open(const char*, uint8_t);
  size_t write(const uint8_t*, size_t);
  int read(void*, uint16_t);
  uint32_t size() const;
  bool isDirectory() const;
  void flush() {}
  void close() { opened = false; }
  explicit operator bool() const { return opened; }
};
class FakeFilesystem {
public:
  std::map<std::string, std::vector<uint8_t>> files;
  std::set<std::string> directories;
  std::string stat_error;
  bool fail_read = false, fail_write_open = false, fail_rename = false;
  bool false_success_rename = false, error_after_publish = false;
  bool corrupt_after_publish = false, fail_reads_after_publish = false;
  size_t max_write = std::numeric_limits<size_t>::max();
  size_t max_read = std::numeric_limits<size_t>::max();
  unsigned writes = 0, renames = 0;
  bool exists(const char* path) const {
    return files.count(path) || directories.count(path);
  }
  bool remove(const char* path) { return files.erase(path) != 0; }
  bool rename(const char* from, const char* to) {
    ++renames;
    if (fail_rename) return false;
    if (false_success_rename) return true;
    auto found = files.find(from);
    if (found == files.end() || directories.count(to)) return false;
    files[to] = found->second;
    files.erase(found);
    if (corrupt_after_publish && !files[to].empty()) files[to][0] ^= 1;
    if (fail_reads_after_publish) fail_read = true;
    return !error_after_publish;
  }
  void _lockFS() {}
  void _unlockFS() {}
  FakeFilesystem* _getFS() { return this; }
};
inline int lfs_stat(FakeFilesystem* fs, const char* path, lfs_info*) {
  if (fs->stat_error == path) return -5;
  return fs->exists(path) ? 0 : LFS_ERR_NOENT;
}
inline bool File::open(const char* filename, uint8_t mode) {
  path = filename;
  writing = mode == FILE_O_WRITE;
  if (fs->directories.count(path)) return false;
  if (writing) {
    if (fs->fail_write_open) return false;
    position = fs->files[path].size();
  } else {
    if (fs->fail_read || !fs->files.count(path)) return false;
    position = 0;
  }
  opened = true;
  return true;
}
inline size_t File::write(const uint8_t* data, size_t size) {
  if (!opened || !writing) return 0;
  ++fs->writes;
  const size_t count = std::min(size, fs->max_write);
  auto& contents = fs->files[path];
  contents.insert(contents.end(), data, data + count);
  position += count;
  return count;
}
inline int File::read(void* data, uint16_t size) {
  if (!opened || writing || fs->fail_read) return -1;
  const auto& contents = fs->files[path];
  const size_t count = std::min<size_t>(
      std::min<size_t>(size, fs->max_read),
      contents.size() - std::min(position, contents.size()));
  if (count) memcpy(data, contents.data() + position, count);
  position += count;
  return static_cast<int>(count);
}
inline uint32_t File::size() const {
  auto found = fs->files.find(path);
  return found == fs->files.end() ? 0 : found->second.size();
}
inline bool File::isDirectory() const { return fs->directories.count(path); }
#define FILESYSTEM FakeFilesystem
'''

SOURCE = r'''
#include <cassert>
#include <helpers/IdentityStore.h>
#define ATOMIC_FILE_WRITER_IMPLEMENTATION
#include <helpers/AtomicFileWriter.h>
#include <helpers/ota/BootloaderMigrationStore.h>
#include <helpers/PersistentStoreFormat.h>
using namespace mesh::ota;
static const char* Path = "/bl_auto";
static const char* Temp = "/bl_auto.tmp";
int main(int argc, char** argv) {
  assert(argc == 2);
  const std::string scenario = argv[1];
  uint8_t a[32], b[32];
  memset(a, 0x31, sizeof(a));
  memcpy(b, a, sizeof(b));
  b[31] ^= 1;  // Deliberately preserve the 8-byte EndF hash prefix.
  FakeFilesystem fs;
  if (scenario == "fresh") {
    assert(bootloader_migration_auto_lock(&fs, a) == MigrationAutoLock::Eligible);
    assert(bootloader_migration_auto_lock(nullptr, a) == MigrationAutoLock::Unavailable);
    assert(bootloader_migration_auto_lock(&fs, nullptr) == MigrationAutoLock::Unavailable);
    assert(!bootloader_migration_lock_auto(nullptr, a));
    assert(!bootloader_migration_lock_auto(&fs, nullptr));
  } else if (scenario == "persist") {
    assert(bootloader_migration_lock_auto(&fs, a));
    assert(fs.files.at(Path).size() == 40 && !fs.exists(Temp));
    FakeFilesystem rebooted;
    rebooted.files = fs.files;
    assert(bootloader_migration_auto_lock(&rebooted, a) == MigrationAutoLock::Locked);
    assert(bootloader_migration_auto_lock(&rebooted, b) == MigrationAutoLock::PreviousImage);
    assert(bootloader_migration_lock_auto(&rebooted, b));
    assert(bootloader_migration_auto_lock(&rebooted, b) == MigrationAutoLock::Locked);
    assert(bootloader_migration_auto_lock(&rebooted, a) == MigrationAutoLock::PreviousImage);
  } else if (scenario == "locked") {
    assert(bootloader_migration_lock_auto(&fs, a));
    const auto original = fs.files;
    const unsigned writes = fs.writes, renames = fs.renames;
    fs.max_write = 0;
    fs.fail_rename = true;
    assert(bootloader_migration_lock_auto(&fs, a));
    assert(fs.files == original && fs.writes == writes && fs.renames == renames);
  } else if (scenario == "malformed") {
    assert(bootloader_migration_lock_auto(&fs, a));
    const auto good = fs.files.at(Path);
    for (unsigned kind = 0; kind < 4; ++kind) {
      fs.files[Path] = good;
      if (kind == 0) fs.files[Path].clear();
      if (kind == 1) fs.files[Path].push_back(0);
      if (kind == 2) {
        fs.files[Path][0] ^= 1;
        mesh::storage::writeLE32(fs.files[Path].data() + 36,
            mesh::storage::updateCRC32(0xffffffffU, fs.files[Path].data(), 36));
      }
      if (kind == 3) fs.files[Path][39] ^= 1;
      const auto before = fs.files;
      assert(bootloader_migration_auto_lock(&fs, a) == MigrationAutoLock::Unavailable);
      assert(!bootloader_migration_lock_auto(&fs, b));
      assert(fs.files == before);
    }
  } else if (scenario == "directory") {
    fs.directories.insert(Path);
    assert(bootloader_migration_auto_lock(&fs, a) == MigrationAutoLock::Unavailable);
    assert(!bootloader_migration_lock_auto(&fs, a));
  } else if (scenario == "stat") {
    for (const auto path : {Path, Temp}) {
      fs.stat_error = path;
      assert(bootloader_migration_auto_lock(&fs, a) == MigrationAutoLock::Unavailable);
      assert(!bootloader_migration_lock_auto(&fs, a));
      assert(fs.writes == 0 && fs.renames == 0);
    }
  } else if (scenario == "read") {
    assert(bootloader_migration_lock_auto(&fs, a));
    const auto before = fs.files;
    fs.fail_read = true;
    assert(bootloader_migration_auto_lock(&fs, a) == MigrationAutoLock::Unavailable);
    assert(!bootloader_migration_lock_auto(&fs, b));
    fs.fail_read = false;
    fs.max_read = 7;
    assert(bootloader_migration_auto_lock(&fs, a) == MigrationAutoLock::Unavailable);
    assert(!bootloader_migration_lock_auto(&fs, b));
    assert(fs.files == before);
  } else if (scenario == "temporary") {
    assert(bootloader_migration_lock_auto(&fs, a));
    const auto complete = fs.files.at(Path);
    for (bool primary : {false, true}) {
      fs = FakeFilesystem();
      if (primary) assert(bootloader_migration_lock_auto(&fs, a));
      for (size_t size : {size_t(0), size_t(7), size_t(40)}) {
        fs.files[Temp] = std::vector<uint8_t>(size, 0x31);
        const auto before = fs.files;
        assert(bootloader_migration_auto_lock(&fs, a) == MigrationAutoLock::Unavailable);
        assert(!bootloader_migration_lock_auto(&fs, b));
        assert(fs.files == before);
      }
      fs.files[Temp] = complete;
      const auto before = fs.files;
      assert(bootloader_migration_auto_lock(&fs, a) == MigrationAutoLock::Unavailable);
      assert(bootloader_migration_auto_lock(&fs, b) == MigrationAutoLock::Unavailable);
      assert(!bootloader_migration_lock_auto(&fs, b));
      assert(fs.files == before);
    }
  } else if (scenario == "short_write" || scenario == "write_open") {
    assert(bootloader_migration_lock_auto(&fs, a));
    const auto before = fs.files;
    if (scenario == "short_write") fs.max_write = 7;
    else fs.fail_write_open = true;
    assert(!bootloader_migration_lock_auto(&fs, b));
    assert(fs.files == before);
    assert(bootloader_migration_auto_lock(&fs, a) == MigrationAutoLock::Locked);
  } else if (scenario == "rename_fail" || scenario == "rename_false_success") {
    assert(bootloader_migration_lock_auto(&fs, a));
    const auto before = fs.files;
    fs.fail_rename = scenario == "rename_fail";
    fs.false_success_rename = scenario == "rename_false_success";
    assert(!bootloader_migration_lock_auto(&fs, b));
    assert(fs.files == before);
    assert(bootloader_migration_auto_lock(&fs, a) == MigrationAutoLock::Locked);
  } else if (scenario == "rename_late_error") {
    fs.error_after_publish = true;
    assert(bootloader_migration_lock_auto(&fs, a));
    assert(bootloader_migration_auto_lock(&fs, a) == MigrationAutoLock::Locked);
  } else if (scenario == "publish_corrupt") {
    fs.corrupt_after_publish = true;
    assert(!bootloader_migration_lock_auto(&fs, a));
    assert(bootloader_migration_auto_lock(&fs, a) == MigrationAutoLock::Unavailable);
  } else if (scenario == "publish_unreadable") {
    fs.fail_reads_after_publish = true;
    assert(!bootloader_migration_lock_auto(&fs, a));
    assert(bootloader_migration_auto_lock(&fs, a) == MigrationAutoLock::Unavailable);
    fs.fail_read = false;
    assert(bootloader_migration_auto_lock(&fs, a) == MigrationAutoLock::Locked);
  } else if (scenario == "settings") {
    fs.files["/node_prefs"] = {1, 2, 3, 4};
    fs.files["/_main"] = {9, 8, 7};
    const auto before = fs.files;
    assert(bootloader_migration_lock_auto(&fs, a));
    for (const auto& file : before) assert(fs.files.at(file.first) == file.second);
    assert(fs.files.size() == before.size() + 1);
  } else assert(false);
}
'''


class BootloaderMigrationStoreTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which("g++") or shutil.which("clang++")
        if compiler is None:
            raise unittest.SkipTest("a host C++17 compiler is required")
        cls.temporary = tempfile.TemporaryDirectory(prefix="bootloader-lock-store-")
        cls.addClassCleanup(cls.temporary.cleanup)
        directory = Path(cls.temporary.name)
        headers = directory / "helpers"
        headers.mkdir()
        (headers / "IdentityStore.h").write_text(FILESYSTEM, encoding="ascii")
        source = directory / "test.cpp"
        source.write_text(SOURCE, encoding="ascii")
        cls.binary = directory / ("test.exe" if os.name == "nt" else "test")
        sanitize = [] if os.name == "nt" else [
            "-fsanitize=address,undefined", "-fno-sanitize-recover=all", "-fno-pie", "-no-pie"]
        built = subprocess.run([
            compiler, "-std=c++17", "-O1", "-g", "-Wall", "-Wextra", "-Werror",
            "-DNRF52_PLATFORM=1", "-DOTA_BOOTLOADER_MIGRATION=1", *sanitize,
            "-I", str(directory), "-I", str(ROOT / "src"), str(source),
            str(ROOT / "src/helpers/ota/BootloaderMigrationStore.cpp"),
            "-o", str(cls.binary),
        ], capture_output=True, text=True, timeout=60)
        if built.returncode:
            raise AssertionError(built.stdout + built.stderr)

    def scenario(self, name):
        tested = subprocess.run([str(self.binary), name], capture_output=True, text=True, timeout=30)
        self.assertEqual(tested.returncode, 0, tested.stdout + tested.stderr)

    def test_missing_store_and_volatile_storage(self):
        self.scenario("fresh")

    def test_power_cycle_and_new_firmware_compare_all_32_hash_bytes(self):
        self.scenario("persist")

    def test_matching_image_never_rewrites_its_lock(self):
        self.scenario("locked")

    def test_malformed_records_are_preserved_and_block_install(self):
        self.scenario("malformed")

    def test_directory_cannot_authorize_install(self):
        self.scenario("directory")

    def test_metadata_errors_are_not_treated_as_absence(self):
        self.scenario("stat")

    def test_unreadable_and_partial_records_are_preserved(self):
        self.scenario("read")

    def test_interrupted_transaction_never_authorizes_another_attempt(self):
        self.scenario("temporary")

    def test_partial_write_cannot_authorize_install(self):
        self.scenario("short_write")

    def test_write_open_failure_cannot_authorize_install(self):
        self.scenario("write_open")

    def test_failed_rename_preserves_previous_firmware_lock(self):
        self.scenario("rename_fail")

    def test_false_success_rename_cannot_authorize_install(self):
        self.scenario("rename_false_success")

    def test_verified_public_record_survives_late_rename_error(self):
        self.scenario("rename_late_error")

    def test_corruption_after_publication_fails_closed(self):
        self.scenario("publish_corrupt")

    def test_unreadable_publication_fails_closed_and_later_remains_locked(self):
        self.scenario("publish_unreadable")

    def test_settings_and_identity_are_untouched(self):
        self.scenario("settings")


if __name__ == "__main__":
    unittest.main()
