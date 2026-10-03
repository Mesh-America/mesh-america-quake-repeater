"""Compile the actual watchdog runtime with isolated filesystem/USB boundaries."""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'test' / 'fixtures' / 'usb_logging_watchdog'


class UsbLoggingWatchdogRuntimeTest(unittest.TestCase):
    def test_production_runtime_and_persistence(self):
        compiler = os.environ.get('CXX') or shutil.which('g++') or shutil.which('clang++')
        if compiler is None:
            self.skipTest('a host C++17 compiler is required')
        sanitizer_flags = [] if os.name == 'nt' else [
            '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
            '-fno-pie', '-no-pie']
        with tempfile.TemporaryDirectory(prefix='usb-watchdog-runtime-') as directory:
            source = ROOT / 'src' / 'helpers' / 'UsbLoggingWatchdog.cpp'
            for ota in (False, True):
                with self.subTest(ota_enabled=ota):
                    binary = Path(directory) / ('ota' + str(ota) + '.exe')
                    compile_source = source
                    if ota:
                        # Copy this translation unit byte-for-byte. Its quoted
                        # OTA include can then use an isolated dependency fake,
                        # while every tested production statement is unchanged.
                        compile_source = Path(directory) / 'UsbLoggingWatchdog.cpp'
                        compile_source.write_bytes(source.read_bytes())
                    built = subprocess.run([
                        compiler, '-std=c++17', '-Wall', '-Wextra', '-Werror', '-pthread',
                        *sanitizer_flags, '-DARDUINO', '-DESP32', '-DESP32_PLATFORM',
                        '-DARDUINO_USB_MODE=0', '-DARDUINO_USB_CDC_ON_BOOT=1',
                        *(['-DENABLE_OTA'] if ota else []),
                        '-I' + str(FIXTURE / 'mocks'),
                        '-I' + str(ROOT / 'src' / 'helpers'), '-I' + str(ROOT / 'src'),
                        str(compile_source), str(FIXTURE / 'test_usb_logging_watchdog_runtime.cpp'),
                        '-o', str(binary)], capture_output=True, text=True, timeout=60)
                    self.assertEqual(built.returncode, 0, built.stderr)
                    tested = subprocess.run([str(binary)], capture_output=True, text=True, timeout=10)
                    self.assertEqual(tested.returncode, 0, tested.stderr)
                    self.assertIn('USB watchdog runtime and persistence passed', tested.stdout)

    def test_unsupported_transport_has_no_recovery_or_storage_work(self):
        compiler = os.environ.get('CXX') or shutil.which('g++') or shutil.which('clang++')
        if compiler is None:
            self.skipTest('a host C++17 compiler is required')
        with tempfile.TemporaryDirectory(prefix='usb-watchdog-unsupported-') as directory:
            harness = Path(directory) / 'unsupported.cpp'
            harness.write_text(r'''
#include <cassert>
#include <cstring>
#include <helpers/UsbLoggingWatchdog.h>
#include <helpers/UsbLoggingClientActivity.h>
namespace mesh { bool isUsbLoggingEnabled() { return true; } }
static bool safe(void*) { assert(false); return false; }
int main() {
  mesh::loadUsbLoggingWatchdog(nullptr, true);
  const auto status = mesh::usbLoggingStatus();
  assert(status.logging_enabled && !status.supported && !status.watchdog_auto);
  assert(!status.logger_active && !status.persistence_ready);
  assert(!mesh::serviceUsbLoggingWatchdog(safe));
  assert(!mesh::isUsbLoggingWatchdogArmed());
  assert(!mesh::isUsbLoggingWatchdogUpdateActive());
  mesh::noteUsbLoggingStatsCommand("stats-core");
  assert(!mesh::isUsbLoggingClientActive());
  mesh::clearUsbLoggingClientActivity();
  char reply[160] = {};
  for (const char* command : {"get usb.watchdog", "get usb.watchdog.last", "set usb.watchdog auto",
                             "set usb.watchdog on", "set usb.watchdog off"}) {
    assert(mesh::handleUsbLoggingWatchdogCommand(command, reply, sizeof(reply)));
    assert(strstr(reply, "unsupported"));
  }
  assert(!mesh::handleUsbLoggingWatchdogCommand("get usb.watchdogx", reply, sizeof(reply)));
  assert(!mesh::handleUsbLoggingWatchdogCommand("set usb.debug on", reply, sizeof(reply)));
  assert(!mesh::handleUsbLoggingWatchdogCommand(nullptr, reply, sizeof(reply)));
  assert(!mesh::handleUsbLoggingWatchdogCommand("get usb.watchdog", reply, 0));
}
''', encoding='ascii')
            binary = Path(directory) / 'unsupported.exe'
            built = subprocess.run([
                compiler, '-std=c++17', '-Wall', '-Wextra', '-Werror',
                '-DARDUINO', '-DESP32', '-DESP32_PLATFORM',
                '-I' + str(FIXTURE / 'mocks'),
                '-I' + str(ROOT / 'src' / 'helpers'), '-I' + str(ROOT / 'src'),
                str(ROOT / 'src' / 'helpers' / 'UsbLoggingWatchdog.cpp'),
                str(ROOT / 'src' / 'helpers' / 'UsbLoggingClientActivity.cpp'),
                str(harness), '-o', str(binary)], capture_output=True, text=True, timeout=60)
            self.assertEqual(built.returncode, 0, built.stderr)
            tested = subprocess.run([str(binary)], capture_output=True, text=True, timeout=10)
            self.assertEqual(tested.returncode, 0, tested.stderr)


if __name__ == '__main__':
    unittest.main()
