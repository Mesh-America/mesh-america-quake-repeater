"""Exercise the real RAM-only USB stats lease and bounded CDC input parser."""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
MOCKS = ROOT / 'test' / 'fixtures' / 'usb_logging_watchdog' / 'mocks'

HARNESS = r'''
#include <Arduino.h>
#include <helpers/UsbLoggingClientActivity.h>
#include <cassert>
#include <cstdio>
#include <initializer_list>
#include <string>

using Parser = mesh::UsbLoggingStatsLineParser;
constexpr uint32_t Lease = mesh::USB_LOGGING_CLIENT_LEASE_MS;

static unsigned consume(Parser& parser, const std::string& input) {
  unsigned matched = 0;
  for (const char byte : input) if (parser.consume(byte)) ++matched;
  return matched;
}

static void check_exact_stats_command_recognition() {
  assert(Lease == 15U * 60U * 1000U);
  assert(!mesh::isUsbLoggingStatsCommand(nullptr));
  for (const char* command : {"stats-core", "stats-radio", "stats-packets",
                             " \tstats-core\t ", "stats-radio\t", " stats-packets"}) {
    assert(mesh::isUsbLoggingStatsCommand(command));
  }
  for (const char* command : {"", " ", "stats", "stats-core2", "stats-radio-diag",
                             "stats-packets suffix", "STATS-CORE", "get name",
                             "get usb.watchdog", "usb.logger heartbeat", "stats-core\r",
                             "stats-core\n", "stats-core\b", "stats-cor", "stats-core;"}) {
    assert(!mesh::isUsbLoggingStatsCommand(command));
  }
}

static void check_default_expiry_and_renewal() {
  mock_watchdog_millis = 0;
  mesh::clearUsbLoggingClientActivity();
  assert(!mesh::isUsbLoggingClientActive());
  for (const char* command : {"stats-core", "stats-radio", "stats-packets"}) {
    mock_watchdog_millis = 100;
    mesh::noteUsbLoggingStatsCommand(command);
    assert(mesh::isUsbLoggingClientActive());
    mock_watchdog_millis = 100 + Lease - 1;
    assert(mesh::isUsbLoggingClientActive());
    mock_watchdog_millis = 100 + Lease;
    assert(!mesh::isUsbLoggingClientActive());
    assert(!mesh::isUsbLoggingClientActive());
  }
  mesh::clearUsbLoggingClientActivity();
  for (uint32_t cycle = 0; cycle != 100; ++cycle) {
    mock_watchdog_millis = cycle * 300000U;
    mesh::noteUsbLoggingStatsCommand("stats-core");
    assert(mesh::isUsbLoggingClientActive());
    mock_watchdog_millis += 300000U - 1;
    assert(mesh::isUsbLoggingClientActive());
  }
  const auto last = 99U * 300000U;
  mock_watchdog_millis = last + Lease - 1;
  assert(mesh::isUsbLoggingClientActive());
  mock_watchdog_millis = last + Lease;
  assert(!mesh::isUsbLoggingClientActive());
  // Expiration is latched. Multiple millis rollovers cannot revive an old poll.
  for (uint64_t day = 1; day <= 150; ++day) {
    mock_watchdog_millis = uint32_t(uint64_t(last) + day * 86400000ULL);
    assert(!mesh::isUsbLoggingClientActive());
  }
  mock_watchdog_millis = last; // Exactly the old uint32 clock value after wrap.
  assert(!mesh::isUsbLoggingClientActive());
}

static void check_invalid_input_never_extends_or_starts_a_lease() {
  for (const char* command : {"stats-core extra", "stats-radio-diag", "ver", "",
                             "usb.logger heartbeat", "stats-packets\n"}) {
    mock_watchdog_millis = 1000;
    mesh::clearUsbLoggingClientActivity();
    mesh::noteUsbLoggingStatsCommand(command);
    assert(!mesh::isUsbLoggingClientActive());
    mesh::noteUsbLoggingStatsCommand("stats-radio");
    mock_watchdog_millis = 1000 + Lease - 1;
    mesh::noteUsbLoggingStatsCommand(command);
    assert(mesh::isUsbLoggingClientActive());
    ++mock_watchdog_millis;
    assert(!mesh::isUsbLoggingClientActive());
  }
  mesh::noteUsbLoggingStatsCommand(nullptr);
  assert(!mesh::isUsbLoggingClientActive());
}

static void check_session_clear_and_clock_wrap() {
  mock_watchdog_millis = UINT32_MAX - 1000;
  mesh::clearUsbLoggingClientActivity();
  mesh::noteUsbLoggingStatsCommand(" \tstats-packets\t ");
  const uint32_t started = mock_watchdog_millis;
  mock_watchdog_millis = started + Lease - 1;
  assert(mesh::isUsbLoggingClientActive());
  mock_watchdog_millis = started + Lease;
  assert(!mesh::isUsbLoggingClientActive());
  mesh::noteUsbLoggingStatsCommand("stats-core");
  assert(mesh::isUsbLoggingClientActive());
  mesh::clearUsbLoggingClientActivity();
  assert(!mesh::isUsbLoggingClientActive());
  mesh::noteUsbLoggingStatsCommand("stats-radio");
  assert(mesh::isUsbLoggingClientActive());
  for (unsigned clear = 0; clear != 10000; ++clear) {
    mesh::clearUsbLoggingClientActivity();
    assert(!mesh::isUsbLoggingClientActive());
  }
  mesh::noteUsbLoggingStatsCommand("stats-core");
  assert(mesh::isUsbLoggingClientActive());
  // Deadline zero is reserved. This rare rollover expires only one ms early.
  mesh::clearUsbLoggingClientActivity();
  mock_watchdog_millis = uint32_t(0U - Lease);
  const uint32_t zero_deadline_start = mock_watchdog_millis;
  mesh::noteUsbLoggingStatsCommand("stats-core");
  mock_watchdog_millis = zero_deadline_start + Lease - 2;
  assert(mesh::isUsbLoggingClientActive());
  mock_watchdog_millis = zero_deadline_start + Lease - 1;
  assert(!mesh::isUsbLoggingClientActive());
  mock_watchdog_millis = 0;
  assert(!mesh::isUsbLoggingClientActive());
}

static void check_bounded_logging_endpoint_line_parser() {
  Parser parser;
  assert(consume(parser, "stats-core\r\n") == 1);
  assert(consume(parser, "stats-radio\n") == 1);
  assert(consume(parser, "stats-packets\r") == 1);
  assert(consume(parser, "stats-core") == 0);
  assert(consume(parser, "\n") == 1);
  assert(consume(parser, " \tstats-radio \t\r\n") == 1);
  assert(consume(parser, "stats-radio-diag\r\n") == 0);
  assert(consume(parser, "stats-packets suffix\r\n") == 0);
  assert(consume(parser, "\r\n\r\n") == 0);
  assert(consume(parser, "stats-core") == 0);
  parser.reset();
  assert(consume(parser, "\n") == 0);
  assert(consume(parser, std::string(21, ' ') + "stats-core\n") == 1); // 31 bytes.
  assert(consume(parser, std::string(22, ' ') + "stats-core\n") == 0); // 32 bytes.
  assert(consume(parser, std::string(1048576, 'x') + "stats-core\n") == 0);
  assert(consume(parser, "stats-core\n") == 1); // Recover after rejected line.
  assert(consume(parser, std::string("stats-core\0suffix\n", 18)) == 0);
  assert(consume(parser, "stats-core\n") == 1);
  assert(consume(parser, std::string(1, '\0') + "stats-core\n") == 0);
  assert(consume(parser, "stats-core\n") == 1);
  assert(consume(parser, "stats-core\b\n") == 0);
  assert(consume(parser, "stats-core\x7f\n") == 0);
}

int main() {
  check_exact_stats_command_recognition();
  check_default_expiry_and_renewal();
  check_invalid_input_never_extends_or_starts_a_lease();
  check_session_clear_and_clock_wrap();
  check_bounded_logging_endpoint_line_parser();
  puts("USB stats client activity lease passed");
}
'''


class UsbLoggingClientActivityTest(unittest.TestCase):
    def test_actual_client_activity_and_parser(self):
        compiler = os.environ.get('CXX') or shutil.which('g++') or shutil.which('clang++')
        if compiler is None:
            self.skipTest('a host C++17 compiler is required')
        sanitizer_flags = [] if os.name == 'nt' else [
            '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
            '-fno-pie', '-no-pie']
        with tempfile.TemporaryDirectory(prefix='usb-logging-client-') as directory:
            source = Path(directory) / 'test.cpp'
            binary = Path(directory) / 'test.exe'
            source.write_text(HARNESS, encoding='utf-8')
            built = subprocess.run([
                compiler, '-std=c++17', '-Wall', '-Wextra', '-Werror', '-DARDUINO',
                '-DESP32', '-DARDUINO_USB_MODE=0', '-DARDUINO_USB_CDC_ON_BOOT=1',
                *sanitizer_flags, '-I' + str(MOCKS), '-I' + str(ROOT / 'src'),
                str(source), str(ROOT / 'src' / 'helpers' / 'UsbLoggingClientActivity.cpp'),
                '-o', str(binary)], capture_output=True, text=True, timeout=60)
            self.assertEqual(built.returncode, 0, built.stderr)
            tested = subprocess.run([str(binary)], capture_output=True, text=True, timeout=10)
            self.assertEqual(tested.returncode, 0, tested.stderr)
            self.assertIn('USB stats client activity lease passed', tested.stdout)


if __name__ == '__main__':
    unittest.main()
