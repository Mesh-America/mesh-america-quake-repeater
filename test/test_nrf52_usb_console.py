"""Compile the complete native nRF52 USB facade with stalled endpoint mocks."""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'test/fixtures/nrf52_usb_console'


class Nrf52UsbConsoleTest(unittest.TestCase):
    def test_actual_console_and_session_callbacks(self):
        compiler = shutil.which('g++') or shutil.which('clang++')
        if not compiler:
            self.skipTest('a host C++17 compiler is required')
        sanitizer = [] if os.name == 'nt' else [
            '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
            '-fno-pie', '-no-pie']
        with tempfile.TemporaryDirectory(prefix='nrf52-usb-console-') as directory:
            for companion in (False, True):
                with self.subTest(companion=companion):
                    binary = Path(directory) / ('console-' + str(companion))
                    built = subprocess.run([
                        compiler, '-std=c++17', '-Wall', '-Wextra', '-Werror',
                        *sanitizer, '-DARDUINO', '-DNRF52_PLATFORM', '-DUSE_TINYUSB',
                        '-DMESH_DEBUG=1', *(['-DENABLE_USB_INTERFACE'] if companion else []),
                        '-I' + str(FIXTURE / 'mocks'), '-I' + str(ROOT / 'src'),
                        str(FIXTURE / 'test_console.cpp'),
                        *[str(ROOT / 'src/helpers' / file) for file in (
                            'UsbLogging.cpp', 'UsbLoggingClientActivity.cpp',
                            'UsbLoggingLineStateOverride.cpp')],
                        '-o', str(binary)], capture_output=True, text=True, timeout=60)
                    self.assertEqual(built.returncode, 0, built.stderr)
                    tested = subprocess.run([str(binary)], capture_output=True, text=True, timeout=10)
                    self.assertEqual(tested.returncode, 0, tested.stderr)
                    self.assertIn('native nRF52 console transport passed', tested.stdout)


if __name__ == '__main__':
    unittest.main()
