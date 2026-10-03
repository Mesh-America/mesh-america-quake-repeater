"""Compile the production USB watchdog event codec without Arduino or PIO."""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]

HARNESS = r'''
#include <helpers/UsbLoggingWatchdogEvent.h>
#include <array>
#include <cassert>
#include <cstdio>
#include <cstring>

using Event = mesh::UsbLoggingWatchdogEvent;
constexpr size_t Size = mesh::USB_WATCHDOG_EVENT_SIZE;
static_assert(Size == 13, "The management extension is exactly thirteen bytes");

static bool same(const Event& lhs, const Event& rhs) {
  return lhs.reasons == rhs.reasons && lhs.action == rhs.action
      && lhs.epoch == rhs.epoch && lhs.uptime_seconds == rhs.uptime_seconds
      && lhs.sequence == rhs.sequence && lhs.persisted == rhs.persisted;
}

static Event populated() {
  Event event;
  event.reasons = Event::HOST_ABSENT | Event::TX_STALLED | Event::CLIENT_INACTIVE;
  event.action = Event::REBOOT_REQUESTED;
  event.epoch = 0x12345678;
  event.uptime_seconds = 0x90abcdef;
  event.sequence = 0x10203040;
  event.persisted = true;
  return event;
}

static void exact_little_endian_and_bounds() {
  const auto event = populated();
  std::array<uint8_t, Size + 2> output;
  output.fill(0x5a);
  mesh::encodeUsbWatchdogEvent(output.data() + 1, event);
  const uint8_t expected[Size] = {
      0xbd, 0x78, 0x56, 0x34, 0x12, 0xef, 0xcd, 0xab, 0x90,
      0x40, 0x30, 0x20, 0x10};
  assert(output.front() == 0x5a && output.back() == 0x5a);
  assert(!std::memcmp(output.data() + 1, expected, Size));
  Event decoded;
  assert(mesh::validUsbWatchdogEvent(expected));
  assert(mesh::decodeUsbWatchdogEvent(expected, decoded));
  assert(same(event, decoded));
}

static void zero_sequence_has_one_canonical_encoding() {
  auto event = populated();
  event.sequence = 0;
  uint8_t output[Size];
  std::memset(output, 0x5a, Size);
  mesh::encodeUsbWatchdogEvent(output, event);
  for (const auto byte : output) assert(byte == 0);
  auto decoded = populated();
  assert(mesh::validUsbWatchdogEvent(output));
  assert(mesh::decodeUsbWatchdogEvent(output, decoded));
  assert(same(decoded, Event()));
  mesh::encodeUsbWatchdogEvent(output, Event());
  for (const auto byte : output) assert(byte == 0);
}

static void roundtrip_every_reason_action_and_persistence_bit() {
  unsigned count = 0;
  for (uint8_t reasons = 1; reasons <= 15; ++reasons) {
    for (uint8_t action = Event::SOFT_RECOVERY; action <= Event::REBOOT_CANCELLED; ++action) {
      for (unsigned persisted = 0; persisted != 2; ++persisted) {
        auto event = populated();
        event.reasons = reasons;
        event.action = action;
        event.persisted = persisted;
        uint8_t output[Size];
        mesh::encodeUsbWatchdogEvent(output, event);
        assert(output[0] == (reasons | (action << 4) | (persisted << 7)));
        auto decoded = Event();
        assert(mesh::validUsbWatchdogEvent(output));
        assert(mesh::decodeUsbWatchdogEvent(output, decoded));
        assert(same(event, decoded));
        ++count;
      }
    }
  }
  assert(count == 120);
}

static void assert_invalid_preserves_destination(const uint8_t* bytes) {
  auto destination = populated();
  const auto before = destination;
  assert(!mesh::validUsbWatchdogEvent(bytes));
  assert(!mesh::decodeUsbWatchdogEvent(bytes, destination));
  assert(same(before, destination));
}

static void invalid_zero_sequence_mixed_data_and_invalid_actions() {
  // With sequence zero, every other wire bit must be zero too. This covers
  // reasons, action, persistence, timestamp and uptime independently.
  for (size_t index = 0; index != 9; ++index) {
    for (unsigned bit = 0; bit != 8; ++bit) {
      uint8_t bytes[Size] = {};
      bytes[index] = uint8_t(1U << bit);
      assert_invalid_preserves_destination(bytes);
    }
  }
  uint8_t bytes[Size];
  mesh::encodeUsbWatchdogEvent(bytes, populated());
  bytes[0] = Event::HOST_ABSENT; // A nonempty record cannot use NONE.
  assert_invalid_preserves_destination(bytes);
  bytes[0] = Event::SOFT_RECOVERY << 4; // Nor can it have no reason.
  assert_invalid_preserves_destination(bytes);
  for (unsigned action = 5; action <= 7; ++action) {
    for (unsigned persisted = 0; persisted != 2; ++persisted) {
      bytes[0] = uint8_t(Event::HOST_ABSENT | (action << 4) | (persisted << 7));
      assert_invalid_preserves_destination(bytes);
    }
  }
}

static void epoch_zero_and_uint32_boundaries_are_valid() {
  for (unsigned maximum = 0; maximum != 2; ++maximum) {
    auto event = populated();
    event.epoch = maximum ? UINT32_MAX : 0;
    event.uptime_seconds = maximum ? UINT32_MAX : 0;
    event.sequence = maximum ? UINT32_MAX : 1;
    event.persisted = maximum;
    uint8_t bytes[Size];
    mesh::encodeUsbWatchdogEvent(bytes, event);
    Event decoded;
    assert(mesh::validUsbWatchdogEvent(bytes));
    assert(mesh::decodeUsbWatchdogEvent(bytes, decoded));
    assert(same(event, decoded));
    for (size_t index = 1; index != 9; ++index) {
      assert(bytes[index] == (maximum ? 0xff : 0));
    }
  }
}

static void wire_validation_matches_decode_for_every_flag_and_sequence_byte() {
  for (unsigned code = 0; code <= 255; ++code) {
    for (size_t sequence_byte = 9; sequence_byte < Size; ++sequence_byte) {
      uint8_t bytes[Size] = {};
      bytes[0] = uint8_t(code);
      bytes[1] = 0x5a; // Arbitrary advisory clock and uptime are allowed.
      bytes[8] = 0xa5;
      bytes[sequence_byte] = 0x80;
      const unsigned reasons = code & 15;
      const unsigned action = (code >> 4) & 7;
      const bool expected = reasons != 0 && action >= 1 && action <= 4;
      assert(mesh::validUsbWatchdogEvent(bytes) == expected);
      Event decoded;
      assert(mesh::decodeUsbWatchdogEvent(bytes, decoded) == expected);
    }
  }
}

static void action_names_are_stable_and_unknown_is_none() {
  const char* expected[] = {"none", "soft-recovery", "reenumerate",
                            "reboot-requested", "reboot-cancelled"};
  for (unsigned action = 0; action <= 255; ++action) {
    assert(!std::strcmp(mesh::usbWatchdogActionName(uint8_t(action)),
                        action < 5 ? expected[action] : "none"));
  }
}

int main(int argc, char** argv) {
  assert(argc == 2);
  if (!std::strcmp(argv[1], "bytes")) exact_little_endian_and_bounds();
  else if (!std::strcmp(argv[1], "empty")) zero_sequence_has_one_canonical_encoding();
  else if (!std::strcmp(argv[1], "roundtrip")) roundtrip_every_reason_action_and_persistence_bit();
  else if (!std::strcmp(argv[1], "invalid")) invalid_zero_sequence_mixed_data_and_invalid_actions();
  else if (!std::strcmp(argv[1], "limits")) epoch_zero_and_uint32_boundaries_are_valid();
  else if (!std::strcmp(argv[1], "validation")) wire_validation_matches_decode_for_every_flag_and_sequence_byte();
  else if (!std::strcmp(argv[1], "names")) action_names_are_stable_and_unknown_is_none();
  else return 2;
  std::puts("USB watchdog event codec passed");
}
'''


class UsbWatchdogEventTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = os.environ.get('CXX') or shutil.which('g++') or shutil.which('clang++')
        if not compiler:
            raise unittest.SkipTest('a host C++ compiler is required')
        cls.directory = tempfile.TemporaryDirectory(prefix='mesh-usb-watchdog-event-')
        cls.addClassCleanup(cls.directory.cleanup)
        source = Path(cls.directory.name) / 'event.cpp'
        source.write_text(HARNESS, encoding='ascii')
        cls.executable = Path(cls.directory.name) / 'event'
        command = [compiler, '-std=c++17', '-Wall', '-Wextra', '-Werror', '-pedantic',
                   '-O2', '-I', str(ROOT / 'src'), str(source), '-o', str(cls.executable)]
        result = subprocess.run(command, capture_output=True, text=True, timeout=60)
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)

    def run_case(self, name):
        result = subprocess.run([str(self.executable), name], capture_output=True,
                                text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('USB watchdog event codec passed', result.stdout)

    def test_exact_thirteen_byte_little_endian_layout_and_output_bounds(self):
        self.run_case('bytes')

    def test_empty_event_canonical_encoding_resets_decoded_destination(self):
        self.run_case('empty')

    def test_all_reason_masks_actions_and_persistence_bits_roundtrip(self):
        self.run_case('roundtrip')

    def test_malformed_records_fail_without_mutating_destination(self):
        self.run_case('invalid')

    def test_zero_epoch_and_maximum_uint32_fields_are_valid(self):
        self.run_case('limits')

    def test_action_names(self):
        self.run_case('names')

    def test_wire_only_validation_matches_decode_for_all_flags_and_sequence_bytes(self):
        self.run_case('validation')


if __name__ == '__main__':
    unittest.main()
