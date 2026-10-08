"""Exercise the production Dispatcher's startup and non-RX recovery timing."""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class DispatcherStartupWatchdogTest(unittest.TestCase):
    def run_scenarios(self, soft_only):
        compiler = shutil.which('g++') or shutil.which('clang++')
        self.assertIsNotNone(compiler)
        flags = ['-std=c++17', '-Wall', '-Wextra']
        if os.name != 'nt':
            flags += ['-fsanitize=address,undefined', '-fno-omit-frame-pointer',
                      '-fno-pie', '-no-pie']
        if soft_only:
            flags += ['-DRADIO_LIVENESS_SOFT_ONLY']
        with tempfile.TemporaryDirectory() as work:
            exe = Path(work) / 'dispatcher_watchdog.exe'
            result = subprocess.run([compiler, *flags,
                '-I', str(ROOT / 'test/mocks'), '-I', str(ROOT / 'src'),
                str(ROOT / 'src/Dispatcher.cpp'), str(ROOT / 'src/Packet.cpp'),
                str(ROOT / 'src/helpers/StaticPoolPacketManager.cpp'),
                str(ROOT / 'test/fixtures/dispatcher/startup_watchdog_test.cpp'),
                '-o', str(exe)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr[-14000:])
            env = os.environ.copy()
            # Production pools live for the whole firmware boot and have no
            # destructor. Keep bounds/UAF/UB checks without teardown leak checks.
            if os.name != 'nt':
                env['ASAN_OPTIONS'] = env.get('ASAN_OPTIONS', '') + ':detect_leaks=0'
            for scenario in ('delayed_setup', 'failed_initial_receive',
                             'later_receive_loss', 'delayed_reactivation',
                             'repeated_begin', 'startup_without_radio',
                             'startup_with_carrier'):
                with self.subTest(scenario=scenario, soft_only=soft_only):
                    run = subprocess.run([str(exe), scenario], capture_output=True,
                                         text=True, env=env)
                    self.assertEqual(run.returncode, 0, run.stdout + run.stderr)

    def test_soft_and_hard_recovery(self):
        self.run_scenarios(soft_only=False)

    def test_soft_only_recovery(self):
        self.run_scenarios(soft_only=True)


if __name__ == '__main__':
    unittest.main()
