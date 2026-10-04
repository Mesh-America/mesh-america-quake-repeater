"""Execute ESP ACL metadata decisions, errors and old/new probe admission."""
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "test/fixtures/client_acl_metadata"
MOCKS = ROOT / "test/fixtures/client_acl_spiffs/mocks"


class ClientAclMetadataTest(unittest.TestCase):
    def run_fixture(self, *, source_overrides=None, benchmark=False):
        compiler = shutil.which("g++") or shutil.which("clang++")
        if not compiler:
            self.skipTest("a C++17 compiler is required")
        with tempfile.TemporaryDirectory(prefix="meshcore-acl-metadata-") as directory:
            work = Path(directory)
            mocks = work / "mocks"
            shutil.copytree(MOCKS, mocks)
            shutil.copyfile(FIXTURE / "mocks/sys/stat.h", mocks / "sys/stat.h")
            # The existing functional mock models the namespace, not VFS's
            # extra fopen in exists(). Count calls from production separately
            # from mock open/rename internals, which consult namespace maps.
            arduino = (mocks / "Arduino.h").read_text()
            replacements = {
                "  bool metadata_error = false;": "  bool metadata_error = false;\n"
                    "  mutable unsigned exists_calls = 0;\n"
                    "  unsigned remove_calls = 0, rename_calls = 0;",
                "    return files.count(path) != 0 && unreadable.count(path) == 0;":
                    "    ++exists_calls;\n"
                    "    return files.count(path) != 0 && unreadable.count(path) == 0;",
                "      if (!exists(path)) {": "      if (!files.count(name)) {",
                "  bool remove(const char* path) {":
                    "  bool remove(const char* path) {\n    ++remove_calls;",
                "  bool rename(const char* from, const char* to) {":
                    "  bool rename(const char* from, const char* to) {\n    ++rename_calls;",
            }
            for old, new in replacements.items():
                self.assertEqual(arduino.count(old), 1)
                arduino = arduino.replace(old, new, 1)
            (mocks / "Arduino.h").write_text(arduino)
            helpers = work / "helpers"
            helpers.mkdir()
            for name, source in (source_overrides or {}).items():
                (helpers / name).write_text(source)
            binary = work / "acl-metadata"
            sanitizer = ["-fsanitize=address,undefined", "-fno-sanitize-recover=all",
                         "-fno-pie", "-no-pie"] if sys.platform.startswith("linux") else []
            compile_result = subprocess.run([
                compiler, "-std=c++17", "-Wall", "-Wextra", *sanitizer,
                "-DESP32=1", "-DESP32_PLATFORM=1",
                *( ["-DACL_METADATA_BENCHMARK_ONLY=1"] if benchmark else [] ),
                f"-I{mocks}", f"-I{helpers}", f"-I{ROOT / 'src/helpers'}",
                f"-I{ROOT / 'src'}", str(FIXTURE / "test.cpp"), "-o", str(binary),
            ], capture_output=True, text=True, timeout=60)
            self.assertEqual(compile_result.returncode, 0,
                             compile_result.stdout + compile_result.stderr)
            return subprocess.run([str(binary)], capture_output=True, text=True, timeout=10)

    def test_actual_acl_metadata_failures_and_publication(self):
        result = self.run_fixture()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("ACL metadata failure checks passed", result.stdout)

    def test_actual_save_reduces_source_exists_without_skipping_readback(self):
        # Recreate the former FS::exists admission only. Both runs retain the
        # current production serializer, readback, CRC and rename bodies. No
        # Git history is needed in a shallow CI checkout, and this measures
        # source admission calls, not SDK-internal fopen costs or wall time.
        old = {name: (ROOT / "src/helpers" / name).read_text()
               for name in ("ClientACL.cpp", "ClientACLFileTransaction.h")}
        header_anchor = "#if defined(ESP32_PLATFORM)\n  return filePresence(fs, path, present);"
        self.assertEqual(old["ClientACLFileTransaction.h"].count(header_anchor), 1)
        old["ClientACLFileTransaction.h"] = old["ClientACLFileTransaction.h"].replace(
            header_anchor, "#if 0\n  return filePresence(fs, path, present);", 1)
        reader_anchor = "bool* metadata_ok = nullptr) {\n#if defined(ESP32_PLATFORM)"
        self.assertEqual(old["ClientACL.cpp"].count(reader_anchor), 1)
        old["ClientACL.cpp"] = old["ClientACL.cpp"].replace(
            reader_anchor, "bool* metadata_ok = nullptr) {\n#if 0", 1)
        before = self.run_fixture(source_overrides=old, benchmark=True)
        after = self.run_fixture(benchmark=True)
        for result in (before, after):
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        pattern = r"BENCH exists=(\d+) reads=(\d+) bytes=(\d+)"
        first = tuple(map(int, re.search(pattern, before.stdout).groups()))
        second = tuple(map(int, re.search(pattern, after.stdout).groups()))
        self.assertGreater(first[0], 0)
        self.assertEqual(second[0], 0)
        self.assertEqual(first[1:], second[1:])
        self.assertEqual(second[2], 32 * 201 + 8)
        print(f"ACL save former-probe model {first[0]}->0 source exists calls; "
              f"actual read opens {second[1]}; "
              f"same {second[2]}-byte image. SDK-internal rename/remove opens excluded.")

    def test_exists_fallback_negative_control_is_detected(self):
        source = (ROOT / "src/helpers/ClientACLFileTransaction.h").read_text()
        anchor = "#if defined(ESP32_PLATFORM)\n  return filePresence(fs, path, present);"
        self.assertEqual(source.count(anchor), 1)
        result = self.run_fixture(source_overrides={
            "ClientACLFileTransaction.h": source.replace(anchor,
                "#if 0\n  return filePresence(fs, path, present);", 1),
            # Make the local quoted include resolve to the isolated header.
            "ClientACL.cpp": (ROOT / "src/helpers/ClientACL.cpp").read_text(),
        })
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("fs.exists_calls == 0", result.stderr)

    def test_stored_path_status_negative_control_is_detected(self):
        source = (ROOT / "src/helpers/ClientACL.cpp").read_text()
        anchors = {
            "success = success && metadata_ok": "success = success && true",
            "matches = metadata_ok && readMatches": "matches = true && readMatches",
        }
        for old, new in anchors.items():
            self.assertEqual(source.count(old), 1)
            source = source.replace(old, new, 1)
        result = self.run_fixture(source_overrides={"ClientACL.cpp": source})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("!acl.save(&fs)", result.stderr)

    def test_metadata_error_cannot_be_treated_as_corruption(self):
        source = (ROOT / "src/helpers/ClientACLFileTransaction.h").read_text()
        anchor = "if (result == ClientACLFileValidation::MetadataError) return false;"
        self.assertEqual(source.count(anchor), 2)
        source = source.replace(anchor, "// negative control: swallow metadata failure")
        result = self.run_fixture(source_overrides={
            "ClientACLFileTransaction.h": source,
            "ClientACL.cpp": (ROOT / "src/helpers/ClientACL.cpp").read_text(),
        })
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("recoverClientACLFilesVerified", result.stderr)


if __name__ == "__main__":
    unittest.main()
