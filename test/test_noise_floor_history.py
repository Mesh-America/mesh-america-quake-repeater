#!/usr/bin/env python3
"""Exercise the production five-bit noise history and its CLI/raw encoders."""

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class NoiseFloorHistoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = os.environ.get("CXX") or shutil.which("g++") or shutil.which("clang++")
        if not compiler:
            raise RuntimeError("noise history tests require a host C++ compiler")
        cls.work = tempfile.TemporaryDirectory(prefix="meshcore-noise-history-")
        cls.binary = Path(cls.work.name) / ("history.exe" if os.name == "nt" else "history")
        flags = ["-std=c++11", "-O1", "-g", "-Wall", "-Wextra", "-Werror"]
        if os.name != "nt":
            flags += ["-fsanitize=address,undefined", "-fno-sanitize-recover=all",
                      "-fno-omit-frame-pointer", "-fno-pie", "-no-pie"]
        result = subprocess.run([
            compiler, *flags, "-I" + str(ROOT / "src"),
            str(ROOT / "test/fixtures/noise_floor_history/main.cpp"), "-o", str(cls.binary),
        ], capture_output=True, text=True, timeout=60)
        if result.returncode:
            cls.work.cleanup()
            raise AssertionError(result.stdout + result.stderr)

    @classmethod
    def tearDownClass(cls):
        cls.work.cleanup()

    def run_case(self, scenario):
        result = subprocess.run([str(self.binary), scenario], capture_output=True,
                                text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_selection_thresholds_directional_rounding_and_sentinels(self):
        self.run_case("selection")

    def test_three_fresh_subslots_duplicate_rejection_and_millis_wrap(self):
        self.run_case("freshness")

    def test_retunes_clear_pending_samples_and_keep_profile_histories_separate(self):
        self.run_case("invalidation")

    def test_eight_day_packed_ring_rollover_and_oldest_partial_page(self):
        self.run_case("rollover")

    def test_missing_buckets_and_rtc_corrections_are_bounded(self):
        self.run_case("clock")

    def test_base64_160_byte_bounds_raw_header_255_samples_and_padding(self):
        self.run_case("wire")


if __name__ == "__main__":
    unittest.main()
