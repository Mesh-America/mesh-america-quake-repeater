#!/usr/bin/env python3
"""Run real native mOTA serial tests with actual production code and sanitizers."""

from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class MotaSerialDeadlineTests(unittest.TestCase):
    def test_actual_native_serial_cases(self):
        native = (ROOT / "test/test_ota/test_ota_core.cpp").read_text()
        start = native.index("class FakeMotaSeederStream")
        end = native.index("class FakeFolderMotaSeederStream", start)
        source = r'''
#include <gtest/gtest.h>
#include <algorithm>
#include <array>
#include <vector>
#include <cstring>
#include <type_traits>
#include <utility>
#include "helpers/ota/MotaSourceSerial.h"
#include "helpers/BleMotaStream.h"
#include "helpers/ota/MotaSeederProto.h"
#include "helpers/ota/OtaByteIO.h"
#include "helpers/ota/FolderMotaStore.h"
using namespace mesh::ota;
'''
        source += native[start:end]
        source += r'''
int main(int argc, char** argv) {
  ::testing::InitGoogleTest(&argc, argv);
  return RUN_ALL_TESTS();
}
'''
        googletest = ROOT / ".pio/libdeps/native/googletest/googletest"
        self.assertTrue(googletest.is_dir(), "Native googletest dependency must be present")
        with tempfile.TemporaryDirectory() as directory:
            cpp = Path(directory) / "serial-deadline.cpp"
            cpp.write_text(source)
            for sanitizer in (False, True):
                with self.subTest(sanitizer=sanitizer):
                    binary = Path(directory) / ("serial-deadline-" + str(sanitizer))
                    flags = (["-fsanitize=address,undefined", "-fno-sanitize-recover=all",
                              "-fno-pie", "-no-pie"] if sanitizer else [])
                    build = subprocess.run([
                        "g++", "-std=c++17", "-pthread", *flags,
                        "-I", str(ROOT / "test/mocks"), "-I", str(ROOT / "src"),
                        "-I", str(googletest / "include"), "-I", str(googletest),
                        str(cpp), str(ROOT / "src/helpers/ota/MotaSourceSerial.cpp"),
                        str(ROOT / "src/helpers/ota/FolderMotaStore.cpp"),
                        str(googletest / "src/gtest-all.cc"), "-o", str(binary)],
                        capture_output=True, text=True)
                    self.assertEqual(build.returncode, 0, build.stdout + build.stderr)
                    run = subprocess.run([str(binary), "--gtest_brief=1"],
                                         capture_output=True, text=True, timeout=30)
                    self.assertEqual(run.returncode, 0, run.stdout + run.stderr)


if __name__ == "__main__":
    unittest.main()
