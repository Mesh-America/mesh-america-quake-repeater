#!/usr/bin/env python3
"""Exercise the production radio-to-history sampler with controlled publications."""

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class NoiseFloorSamplerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = os.environ.get("CXX") or shutil.which("g++") or shutil.which("clang++")
        if not compiler:
            raise RuntimeError("noise sampler tests require a host C++ compiler")
        cls.work = tempfile.TemporaryDirectory(prefix="meshcore-noise-sampler-")
        cls.binary = Path(cls.work.name) / ("sampler.exe" if os.name == "nt" else "sampler")
        flags = ["-std=c++11", "-O1", "-g", "-Wall", "-Wextra", "-Werror"]
        if os.name != "nt":
            flags += ["-fsanitize=address,undefined", "-fno-sanitize-recover=all",
                      "-fno-omit-frame-pointer", "-fno-pie", "-no-pie"]
        result = subprocess.run([
            compiler, *flags, "-I" + str(ROOT / "src"),
            str(ROOT / "test/fixtures/noise_floor_sampler/main.cpp"), "-o", str(cls.binary),
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

    def test_three_fresh_publications_complete_a_bucket_without_extra_requests(self):
        self.run_case("successful")

    def test_cached_estimates_do_not_fill_multiple_subslots(self):
        self.run_case("cached")

    def test_millis_wrap_and_a_zero_publication_timestamp_are_valid(self):
        self.run_case("rollover")

    def test_retunes_and_validity_changes_discard_only_pending_profile_readings(self):
        self.run_case("generations")

    def test_radio2_disable_reenable_keeps_history_and_restarts_pending_aggregation(self):
        self.run_case("enable_disable")

    def test_rtc_jumps_start_new_buckets_and_do_not_loop_unbounded(self):
        self.run_case("clock")

    def test_unsupported_radios_and_fresh_dual_profiles_need_no_hardware_actions(self):
        self.run_case("unsupported_fresh")

    def test_invalid_rssi_never_suppresses_measurements_or_survives_as_pending_data(self):
        self.run_case("invalid")


if __name__ == "__main__":
    unittest.main()
