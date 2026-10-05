#!/usr/bin/env python3
"""Execute the production profile-image reader with ESP SPIFFS missing files.

The metadata helper and reader/checksum compile from production. Only stat and
File are peripheral doubles; the ESP double reproduces the pinned wrapper's
truthy-directory result for a missing read-open. This is a host regression,
not a qualification of physical flash faults.
"""
from pathlib import Path
import binascii
import os
import shutil
import subprocess
import tempfile
import unittest

from test_replay_reset_integration import extract_braced


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src/helpers/RadioProfileCLI.cpp"

STAT_HEADER = r'''
#pragma once
struct stat { unsigned st_mode = 0; };
int stat(const char*, struct stat*);
'''

HARNESS = r'''
#include <cassert>
#include <cerrno>
#include <cstdint>
#include <cstring>
#include <string>
#include <vector>
#include <sys/stat.h>
#include <helpers/FilePresence.h>

struct State {
  bool present = false, directory = false, metadata_error = false;
  bool open_error = false, short_read = false;
  unsigned stats = 0, opens = 0, exists = 0, reads = 0, closes = 0;
  unsigned missing_directory_opens = 0;
  std::vector<uint8_t> bytes;
} state;

int stat(const char* path, struct stat* info) {
  ++state.stats;
  assert(std::string(path) == "/spiffs/radio_profiles");
  if (state.metadata_error) { errno = EIO; return -1; }
  if (!state.present) { errno = ENOENT; return -1; }
  info->st_mode = state.directory ? 0040000 : 0100000;
  return 0;
}

struct File {
  bool valid = false, directory = false;
  explicit operator bool() const { return valid; }
  size_t size() const { return directory ? 0 : state.bytes.size(); }
  int read(uint8_t* dest, size_t count) {
    ++state.reads;
    assert(valid && !directory && count == state.bytes.size());
    const size_t actual = state.short_read ? count - 1 : count;
    memcpy(dest, state.bytes.data(), actual);
    return static_cast<int>(actual);
  }
  void close() { ++state.closes; valid = false; }
};
struct FILESYSTEM {
  File open(const char* path, const char* mode) {
    ++state.opens;
    assert(std::string(path) == "/radio_profiles" && std::string(mode) == "r");
    if (state.open_error) return {};
#if defined(ESP32_PLATFORM)
    // Arduino2.0.17: failed stat -> opendir -> truthy Directory, even when
    // this prefix contains no files. A pre-probe must avoid this operation.
    if (!state.present) {
      ++state.missing_directory_opens;
      return {true, true};
    }
#else
    if (!state.present) return {};
#endif
    return {true, state.directory};
  }
  bool exists(const char* path) {
    ++state.exists;
    assert(std::string(path) == "/radio_profiles");
    return state.present && !state.directory;
  }
};

namespace mesh {
@CHECKSUM@
struct RadioProfileCLI {
  enum class ImageReadResult { Missing, Valid, Invalid, Unreadable };
  FILESYSTEM* fs_;
  ImageReadResult readImage(const char*, uint8_t*, size_t);
};
@READER@
}

int main(int argc, char** argv) {
  assert(argc == 2);
  const std::string which = argv[1];
  FILESYSTEM fs;
  mesh::RadioProfileCLI cli{&fs};
  using Result = mesh::RadioProfileCLI::ImageReadResult;
  uint8_t output[24] = {};
  const uint8_t valid_image[24] = {@IMAGE@};
  state.bytes.assign(valid_image, valid_image + sizeof(valid_image));

  if (which == "missing") {
    const Result result = cli.readImage("/radio_profiles", output, sizeof(output));
    assert(result == Result::Missing);
#if defined(ESP32_PLATFORM)
    assert(state.stats == 1 && state.opens == 0 && state.exists == 0);
#else
    assert(state.stats == 0 && state.opens == 1 && state.exists == 1);
#endif
    assert(state.reads == 0 && state.missing_directory_opens == 0);
  } else if (which == "metadata_error") {
    state.metadata_error = true;
    assert(cli.readImage("/radio_profiles", output, sizeof(output)) == Result::Unreadable);
    assert(state.stats == 1 && state.opens == 0 && state.exists == 0 && state.reads == 0);
  } else if (which == "null_fs") {
    cli.fs_ = nullptr;
    assert(cli.readImage("/radio_profiles", output, sizeof(output)) == Result::Unreadable);
    assert(state.stats == 0 && state.opens == 0 && state.reads == 0);
  } else {
    state.present = true;
    Result expected = Result::Valid;
    if (which == "directory") { state.directory = true; expected = Result::Invalid; }
    else if (which == "short_read") { state.short_read = true; expected = Result::Unreadable; }
    else if (which == "open_error") { state.open_error = true; expected = Result::Unreadable; }
    else if (which == "wrong_size") { state.bytes.pop_back(); expected = Result::Invalid; }
    else if (which == "corrupt_crc") { state.bytes[7] ^= 1; expected = Result::Invalid; }
    else if (which == "future_version") {
      state.bytes[2] = 2;
      const uint32_t crc = mesh::checksum(state.bytes.data(), state.bytes.size() - 4);
      memcpy(state.bytes.data() + state.bytes.size() - 4, &crc, 4);
      expected = Result::Invalid;
    } else assert(which == "valid");
    assert(cli.readImage("/radio_profiles", output, sizeof(output)) == expected);
    assert(state.opens == 1);
#if defined(ESP32_PLATFORM)
    assert(state.stats == 1 && state.exists == 0);
#else
    assert(state.stats == 0 && state.exists == unsigned(state.open_error));
#endif
    const bool opened_readable = !state.directory && !state.open_error && which != "wrong_size";
    assert(state.reads == unsigned(opened_readable));
    assert(state.closes == unsigned(!state.open_error));
    if (which == "valid") assert(memcmp(output, valid_image, sizeof(output)) == 0);
  }
}
'''


class RadioProfileSpiffsMissingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = os.environ.get("CXX") or shutil.which("g++") or shutil.which("clang++")
        if compiler is None:
            raise unittest.SkipTest("a host C++17 compiler is required")
        cls.work_dir = tempfile.TemporaryDirectory(prefix="radio-profile-spiffs-")
        cls.addClassCleanup(cls.work_dir.cleanup)
        cls.work = Path(cls.work_dir.name)
        (cls.work / "sys").mkdir()
        (cls.work / "sys/stat.h").write_text(STAT_HEADER, encoding="utf-8")
        source = SOURCE.read_text(encoding="utf-8")
        reader = extract_braced(source, "RadioProfileCLI::ImageReadResult RadioProfileCLI::readImage(")
        checksum = extract_braced(source, "uint32_t checksum(")
        # Encode the fixture independently: production CRC keeps the final XOR.
        image = bytearray(b"R2\x01" + bytes(range(3, 20)))
        image += (binascii.crc32(image) ^ 0xffffffff).to_bytes(4, "little")
        harness = HARNESS.replace("@CHECKSUM@", checksum).replace(
            "@IMAGE@", ", ".join(str(value) for value in image))
        # Remove only the initial ESP metadata probe. The old directory quirk
        # must compile successfully, then fail the same missing-file assertion.
        start = reader.index("#if defined(ESP32_PLATFORM)")
        end = reader.index("#endif", start) + len("#endif")
        unguarded = reader[:start] + reader[end:]
        cls.binaries = {}
        for name, defines, implementation in (
                ("esp", ["-DESP32_PLATFORM=1"], reader),
                ("other", [], reader),
                ("unguarded", ["-DESP32_PLATFORM=1"], unguarded)):
            cpp = cls.work / f"{name}.cpp"
            binary = cls.work / name
            cpp.write_text(harness.replace("@READER@", implementation), encoding="utf-8")
            compiled = subprocess.run([
                compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
                *defines, f"-I{cls.work}", f"-I{ROOT / 'src'}", str(cpp), "-o", str(binary),
            ], capture_output=True, text=True, timeout=60)
            if compiled.returncode != 0:
                raise AssertionError(compiled.stdout + compiled.stderr)
            cls.binaries[name] = binary

    def run_case(self, case, target="esp"):
        result = subprocess.run([str(self.binaries[target]), case], cwd=self.work,
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_absent_image_is_missing_without_read_open(self):
        self.run_case("missing")

    def test_present_images_keep_decode_and_fault_classification(self):
        for case in ("valid", "directory", "short_read", "open_error", "wrong_size",
                     "corrupt_crc", "future_version", "null_fs"):
            with self.subTest(case=case):
                self.run_case(case)

    def test_metadata_error_is_unreadable_without_read_open(self):
        self.run_case("metadata_error")

    def test_other_platform_keeps_original_open_and_exists_path(self):
        for case in ("missing", "valid", "short_read", "open_error", "corrupt_crc", "null_fs"):
            with self.subTest(case=case):
                self.run_case(case, "other")

    def test_removing_metadata_guard_exposes_missing_directory_regression(self):
        result = subprocess.run([str(self.binaries["unguarded"]), "missing"], cwd=self.work,
                                capture_output=True, text=True, timeout=10)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("result == Result::Missing", result.stderr)


if __name__ == "__main__":
    unittest.main()
