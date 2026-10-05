#!/usr/bin/env python3
"""Execute the HWCDC facade and pinned SDK write against a stalled host."""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import unittest

from test_hwcdc_tx_backport import PATCHED, body


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'test/fixtures/hwcdc_write_capacity.cpp'


class HwcdcWriteCapacityTest(unittest.TestCase):
    def harness(self, uncapped=False):
        source = (ROOT / 'src/helpers/UsbLogging.cpp').read_text()
        facade = body(source, 'class Esp32HwcdcSessionStream') + ';'
        if uncapped:
            start = facade.index('    // The shared producer guard')
            end = facade.index('    noteUsbLoggingTxAttempt();', start)
            facade = facade[:start] + facade[end:]
            facade = facade.replace('Serial.write(data, attempt)', 'Serial.write(data, size)')
        sdk_write = body(PATCHED, 'size_t HWCDC::write(const uint8_t *buffer, size_t size)')
        sdk_write = sdk_write.replace('HWCDC::write(', 'HWCDC::driverWrite(', 1)
        sdk_available = body(PATCHED, 'int HWCDC::availableForWrite(void)')
        return (FIXTURE.read_text()
                .replace('@SDK_WRITE@', sdk_write)
                .replace('@SDK_AVAILABLE@', sdk_available)
                .replace('@FACADE@', facade))

    def compile(self, directory, uncapped=False, zero_timeout=False):
        compiler = os.environ.get('CXX') or shutil.which('g++') or shutil.which('clang++')
        if compiler is None:
            self.skipTest('a host C++17 compiler is required')
        source = Path(directory) / 'test.cpp'
        source.write_text(self.harness(uncapped), encoding='ascii')
        flags = ['-fsanitize=address,undefined', '-fno-sanitize-recover=all',
                 '-fno-pie', '-no-pie'] if os.name != 'nt' else []
        includes = ['-I' + str(ROOT / 'test/mocks'), '-I' + str(ROOT / 'src')]
        if zero_timeout:
            copied = Path(directory) / 'helpers'
            copied.mkdir()
            packet_log = (ROOT / 'src/helpers/SerialPacketLog.h').read_text()
            self.assertIn('Serial.setTxTimeoutMs(5);', packet_log)
            (copied / 'SerialPacketLog.h').write_text(
                packet_log.replace('Serial.setTxTimeoutMs(5);',
                                   'Serial.setTxTimeoutMs(0);'), encoding='ascii')
            includes.insert(0, '-I' + str(directory))
        binary = Path(directory) / 'test.exe'
        built = subprocess.run([
            compiler, '-std=c++17', '-Wall', '-Wextra', '-Wno-unused-parameter',
            '-pthread', *flags, '-DESP32_PLATFORM', '-DARDUINO_USB_MODE=1',
            '-DARDUINO_USB_CDC_ON_BOOT=1', *includes, str(source), '-o', str(binary)
        ], capture_output=True, text=True, timeout=60)
        self.assertEqual(built.returncode, 0, built.stderr)
        return binary

    def test_actual_facade_sdk_stall_capacity_and_record_boundaries(self):
        with tempfile.TemporaryDirectory(prefix='hwcdc-capacity-') as directory:
            binary = self.compile(directory)
            for case in ('full', 'oversize', 'stale', 'contention', 'mutex',
                         'isr_drain', 'short', 'mota', 'timeout', 'sdk_fallback'):
                with self.subTest(case=case):
                    result = subprocess.run([str(binary), case], capture_output=True,
                                            text=True, timeout=10)
                    self.assertEqual(result.returncode, 0, result.stderr)

    def test_uncapped_negative_control_reenters_sdk_wait_loop(self):
        with tempfile.TemporaryDirectory(prefix='hwcdc-no-cap-') as directory:
            binary = self.compile(directory, uncapped=True)
            result = subprocess.run([str(binary), 'oversize'], capture_output=True,
                                    text=True, timeout=10)
            self.assertNotEqual(result.returncode, 0)

    def test_zero_timeout_negative_control(self):
        with tempfile.TemporaryDirectory(prefix='hwcdc-no-timeout-') as directory:
            binary = self.compile(directory, zero_timeout=True)
            result = subprocess.run([str(binary), 'timeout'], capture_output=True,
                                    text=True, timeout=10)
            self.assertNotEqual(result.returncode, 0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
