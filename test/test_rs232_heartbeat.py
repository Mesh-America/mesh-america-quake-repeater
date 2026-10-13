#!/usr/bin/env python3
"""Sanitized tests of the actual UART driver, wire codec and standby policy.

No PlatformIO or connected hardware is used. The two-peer model ends/begins
physical mock UARTs, drops bytes arriving while either UART is stopped, and
never wakes a peer merely because another peer transmitted. The deterministic
phase sweep and long-window inequality exercise rendezvous without RNG luck.
"""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "test/fixtures/rs232_heartbeat"


class RS232HeartbeatTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.compiler = shutil.which("g++") or shutil.which("clang++")
        if not cls.compiler:
            raise AssertionError("a host C++ compiler is required")
        cls.temporary = tempfile.TemporaryDirectory(prefix="rs232-heartbeat-")
        cls.binary = Path(cls.temporary.name) / "heartbeat"
        built = subprocess.run([
            cls.compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
            "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
            "-fno-pie", "-no-pie", "-DWITH_RS232_BRIDGE=1", "-DESP32=1",
            "-I" + str(FIXTURES), "-I" + str(ROOT / "src"),
            str(FIXTURES / "main.cpp"),
            str(ROOT / "src/helpers/bridges/RS232Bridge.cpp"),
            "-o", str(cls.binary),
        ], capture_output=True, text=True, timeout=60)
        if built.returncode:
            cls.temporary.cleanup()
            raise AssertionError(built.stdout + built.stderr)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def run_case(self, name):
        checked = subprocess.run([str(self.binary), name], capture_output=True,
                                 text=True, timeout=60)
        self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
        self.assertIn(name + " passed", checked.stdout)

    def test_control_codec_rejects_invalid_bodies_and_keeps_old_framing(self):
        self.run_case("codec")

    def test_policy_idle_transitions_wake_deadlines_retry_and_clock_wrap(self):
        self.run_case("policy")

    def test_default_wire_and_old_new_data_compatibility(self):
        self.run_case("compatibility")

    def test_peer_proof_rejects_reflection_noise_replays_and_wrong_session(self):
        self.run_case("peer-proof")

    def test_partial_tx_backpressure_rx_pool_starvation_and_timeouts(self):
        self.run_case("bounded-io")

    def test_pair_recovers_from_both_sleeping_with_deterministic_phase_sweep(self):
        self.run_case("rendezvous")

    def test_pair_loss_boot_stagger_restart_and_failed_resume_recover(self):
        self.run_case("recovery")

    def test_expired_presence_does_not_resurrect_after_full_millis_counter_cycle(self):
        self.run_case("counter-cycle")


if __name__ == "__main__":
    unittest.main()
