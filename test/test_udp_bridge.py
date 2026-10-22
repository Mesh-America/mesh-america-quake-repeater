#!/usr/bin/env python3
"""Sanitized production UDP bridge protocol, sessions, queues and diagnostics."""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / 'test/fixtures/udp_bridge'


class UDPBridgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which('g++') or shutil.which('clang++')
        if not compiler:
            raise AssertionError('a host C++ compiler is required')
        cls.temporary = tempfile.TemporaryDirectory(prefix='udp-bridge-')
        cls.binaries = []
        for cooperative in (0, 1):
            binary = Path(cls.temporary.name) / f'bridge-{cooperative}'
            flags = [
                compiler, '-Wall', '-Wextra', '-Werror', '-O1',
                '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
                '-fno-pie', '-no-pie', '-DARDUINO=1', '-DESP32=1', '-DWITH_UDP_BRIDGE=1',
                f'-DMESH_ESP32_USB_CONSOLE_COOPERATIVE={cooperative}',
                '-I' + str(FIXTURES), '-I' + str(ROOT / 'test/mocks'), '-I' + str(ROOT / 'src'),
            ]
            core = Path(cls.temporary.name) / f'core-{cooperative}.o'
            # The pinned ESP32 GCC 8 firmware builds use C++11. Compile the
            # actual implementation with that language level, even though the
            # test driver uses C++17 aggregate initialization for test vectors.
            commands = [
                flags + ['-std=c++11', '-pedantic-errors', '-c',
                         str(ROOT / 'src/helpers/bridges/UDPBridge.cpp'), '-o', str(core)],
                flags + ['-std=c++17', str(ROOT / 'test/fixtures/udp_bridge_runtime.cpp'),
                         str(core), '-o', str(binary)],
            ]
            for command in commands:
                built = subprocess.run(command, capture_output=True, text=True, timeout=60)
                if built.returncode:
                    cls.temporary.cleanup()
                    raise AssertionError(built.stdout + built.stderr)
            cls.binaries.append(binary)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def check(self, name):
        for binary in self.binaries:
            with self.subTest(console=binary.name):
                result = subprocess.run([str(binary), name], capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn(name + ' passed', result.stdout)

    def test_strict_authenticated_codec_and_fresh_challenge_replay_guard(self):
        self.check('codec')

    def test_authenticated_probes_never_allocate_echo_or_reach_lora(self):
        self.check('isolation')

    def test_peer_and_receiver_restart_reject_retired_sessions_and_recordings(self):
        self.check('recovery')

    def test_owned_queues_pool_pressure_filter_and_no_retry(self):
        self.check('queues')

    def test_eight_peer_fanout_owned_bytes_and_targeted_probe(self):
        self.check('fanout')

    def test_secret_rotation_cancels_queued_work_refreshes_sessions_and_rejects_old_key(self):
        self.check('rotation')

    def test_network_gate_disconnect_secret_broadcast_and_socket_budget_failure(self):
        self.check('network')

    def test_bounded_status_pages_and_both_usb_debug_gates(self):
        self.check('bounds')


if __name__ == '__main__':
    unittest.main()
