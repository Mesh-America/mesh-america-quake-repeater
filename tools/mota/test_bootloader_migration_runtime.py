#!/usr/bin/env python3
"""Exercise the production migration arm/tick state machine with host stubs.

The ARM SVC adapter is replaced by a failing trap, and the EndF stub refuses
installation before hardware access. A controlled digest exercises the exact
candidate no-op. This tests scheduling and cancellation, not cryptography,
MBR copying or power-loss recovery; those require separate qualification.
"""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
STUBS = ROOT / 'tools/mota/tests/migration_stubs'


class MigrationRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix='migration-runtime-')
        cls.addClassCleanup(cls.directory.cleanup)
        cls.binary = cls.compile(Path(cls.directory.name), STUBS / 'runtime.cpp')

    @staticmethod
    def compile(directory, source):
        binary = directory / ('runtime.exe' if os.name == 'nt' else 'runtime')
        subprocess.run([
            os.environ.get('CXX', 'g++'), '-std=c++17', '-O2', '-Wall', '-Wextra',
            '-DOTA_BOOTLOADER_MIGRATION', '-DNRF52_PLATFORM', '-DENABLE_OTA',
            '-fsanitize=address,undefined', '-fno-sanitize-recover=all', '-fno-pie', '-no-pie',
            '-I', str(STUBS), '-I', str(ROOT / 'src'), '-I', str(ROOT / 'src/helpers/ota'),
            str(source), '-o', str(binary),
        ], check=True)
        return binary

    def run_scenario(self, scenario):
        subprocess.run([str(self.binary), scenario], check=True)

    def test_wrong_confirmation_cannot_arm(self):
        self.run_scenario('wrong-confirmation')

    def test_already_installed_preserves_running_application(self):
        self.run_scenario('already-installed')

    def test_negative_control_noop_must_not_arm_or_stop_softdevice(self):
        driver = (ROOT / 'src/helpers/ota/BootloaderMigration.cpp').read_text()
        changed = driver.replace('if (memcmp(digest, migration_candidate_sha256, sizeof(digest)) == 0) {',
                                 'if (false) {')
        self.assertNotEqual(driver, changed)
        harness = (STUBS / 'runtime.cpp').read_text().replace(
            '#include "helpers/ota/BootloaderMigration.cpp"', changed)
        with tempfile.TemporaryDirectory(prefix='migration-noop-negative-') as directory:
            directory = Path(directory)
            source = directory / 'runtime.cpp'
            source.write_text(harness)
            binary = self.compile(directory, source)
            result = subprocess.run([str(binary), 'already-installed'], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('!bootloader_migration_pending()', result.stderr)

    def test_grace_and_radio_drain_are_both_required(self):
        self.run_scenario('grace-and-drain')

    def test_duplicate_arm_does_not_extend_deadline(self):
        self.run_scenario('duplicate-arm')

    def test_timeout_wins_over_becoming_idle(self):
        self.run_scenario('timeout')

    def test_ota_activity_cancels_and_requires_fresh_arm(self):
        self.run_scenario('ota-cancel-rearm')

    def test_ota_activity_wins_at_install_boundary(self):
        self.run_scenario('ota-cancel-at-install')

    def test_millisecond_wrap_preserves_grace(self):
        self.run_scenario('clock-wrap')

    def test_current_results_override_stale_retained_marker(self):
        self.run_scenario('stale-retained-result')


if __name__ == '__main__':
    unittest.main()
