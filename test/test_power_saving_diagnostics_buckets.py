#!/usr/bin/env python3
"""Exercise real SDK-entry time buckets, protocol bounds and legacy layout."""
from pathlib import Path
import os
import shlex
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = r'''
#include <helpers/PowerSavingDiagnostics.h>
#include <assert.h>
#include <stddef.h>
#include <string.h>
using namespace mesh::powerdiag;

struct LegacySnapshot {
  uint32_t blocked_ms[ReasonCount] = {};
  uint16_t transitions[ReasonCount] = {};
  Mask current = 0, seen = 0;
  uint32_t union_blocked_ms = 0, eligible_ms = 0, last_ms = 0, decision_at_ms = 0;
  uint32_t calls = 0, returns = 0, short_returns = 0, board_vetoes = 0, errors = 0;
  uint32_t call_us = 0, max_call_us = 0, last_call_us = 0, call_begin_us = 0;
  int32_t detail = 0;
  bool enabled = false, observed = false, pending = false;
};

#if defined(ESP32_PLATFORM)
static void call(uint32_t elapsed_ms) {
  sleepBegin(123, state().bucket_start_ms + elapsed_ms);
  sleepEnd(1123);
}
static uint32_t sum() {
  uint32_t total = state().bucket_outside_calls;
  for (size_t i = 0; i < SdkBucketCount; ++i) total += state().sdk_call_bins[i];
  return total;
}
#endif

int main(int argc, char** argv) {
  assert(argc == 2);
  const char* test = argv[1];
#if defined(ESP32_PLATFORM)
  static_assert(sizeof(Snapshot) <= 256, "ESP32 diagnostics RAM budget");
  static_assert(sizeof(Snapshot) - sizeof(LegacySnapshot) <= 40, "Bucket storage grew");
  if (!strcmp(test, "boundaries")) {
    setEnabled(true, 1000);
    call(0); call(15999); call(16000); call(255999); call(256000);
    assert(state().sdk_call_bins[0] == 2 && state().sdk_call_bins[1] == 1);
    assert(state().sdk_call_bins[15] == 1 && state().bucket_outside_calls == 1);
    assert(state().bucket_flags == SdkBucketOutside && state().calls == 5);
    assert(sum() == state().calls && state().returns == state().calls);
    // An earlier timestamp becomes explicitly outside; it is never clamped.
    sleepBegin(200, 999); sleepEnd(1200);
    assert(state().bucket_outside_calls == 2 && state().sdk_call_bins[0] == 2);
  } else if (!strcmp(test, "reset_freeze")) {
    sleepBegin(12, 12); assert(state().calls == 0 && state().bucket_flags == 0);
    setEnabled(true, 1000); call(1);
    setEnabled(true, 3000); assert(state().bucket_start_ms == 1000);
    setEnabled(false, 4000);
    sleepBegin(5000, 9000); sleepEnd(6000);
    assert(state().calls == 1 && state().sdk_call_bins[0] == 1);
    char text[160]; formatPage(9, text, sizeof(text), 1000000);
    assert(state().calls == 1 && state().bucket_start_ms == 1000);
    setEnabled(true, 10000);
    assert(state().calls == 0 && sum() == 0 && state().bucket_start_ms == 10000);
    call(17000); reset(40000);
    assert(enabled() && state().calls == 0 && sum() == 0 && state().bucket_start_ms == 40000);
    setEnabled(false, 41000); reset(50000);
    assert(!enabled() && state().bucket_start_ms == 50000 && sum() == 0);
  } else if (!strcmp(test, "clock_wrap")) {
    const uint32_t start = UINT32_MAX - 1000;
    setEnabled(true, start);
    sleepBegin(UINT32_MAX - 31, uint32_t(start + 16000));
    sleepEnd(50);
    assert(state().sdk_call_bins[1] == 1 && state().last_call_us == 82);
    sleepBegin(0, 500); sleepEnd(1000);
    assert(state().sdk_call_bins[0] == 1 && state().bucket_flags == 0);
    assert(state().bucket_start_ms == start && sum() == state().calls);
  } else if (!strcmp(test, "saturation_missing")) {
    setEnabled(true, 0);
    state().calls = UINT16_MAX - 1; state().sdk_call_bins[0] = UINT16_MAX - 1;
    call(1); assert(state().sdk_call_bins[0] == UINT16_MAX && state().bucket_flags == 0);
    call(2); assert(state().sdk_call_bins[0] == UINT16_MAX && state().calls == 65536);
    assert(state().bucket_flags == SdkBucketSaturated);
    reset(1000); state().calls = UINT32_MAX; state().bucket_outside_calls = UINT32_MAX;
    call(256000);
    assert(state().bucket_outside_calls == UINT32_MAX && state().calls == UINT32_MAX);
    assert(state().bucket_flags == (SdkBucketOutside | SdkBucketSaturated));
    reset(2000); sleepBegin(30); sleepEnd(1030);
    assert(state().calls == 1 && sum() == 0 && state().bucket_flags == SdkBucketMissingClock);
  } else if (!strcmp(test, "format_capacity")) {
    setEnabled(true, UINT32_MAX);
    state().bucket_outside_calls = UINT32_MAX; state().bucket_flags = 255;
    for (size_t i = 0; i < SdkBucketCount; ++i) state().sdk_call_bins[i] = UINT16_MAX;
    for (unsigned page = 9; page <= 10; ++page) {
      char full[160]; memset(full, 'x', sizeof(full));
      formatPage(page, full, 157, UINT32_MAX);
      assert(strlen(full) < 157 && strstr(full, page == 9 ? "bins0=" : "bins8="));
      assert(strstr(full, "outside=4294967295 flags=255"));
      for (size_t capacity = 0; capacity <= 157; ++capacity) {
        char guarded[162]; memset(guarded, 'q', sizeof(guarded));
        formatPage(page, guarded + 1, capacity, UINT32_MAX);
        assert(guarded[0] == 'q' && guarded[capacity + 1] == 'q');
        if (capacity) assert(memchr(guarded + 1, 0, capacity));
      }
      char command[40]; snprintf(command, sizeof(command), "get powersaving.diag %u", page);
      char reply[160]; assert(handleCommand(command, reply, 157, UINT32_MAX));
      assert(!strncmp(reply, "> bucket_ms=16000 start_ms=4294967295", 34));
    }
    char reply[160];
    assert(handleCommand("get powersaving.diag 09", reply, sizeof(reply), 0));
    assert(!strncmp(reply, "Error:", 6));
    assert(handleCommand("get powersaving.diag 10junk", reply, sizeof(reply), 0));
    assert(!strncmp(reply, "Error:", 6));
  } else return 2;
#else
  static_assert(sizeof(Snapshot) == sizeof(LegacySnapshot), "Legacy diagnostics layout changed");
  static_assert(offsetof(Snapshot, enabled) == offsetof(LegacySnapshot, enabled), "Legacy field offset changed");
  static_assert(offsetof(Snapshot, pending) == offsetof(LegacySnapshot, pending), "Legacy field offset changed");
  if (strcmp(test, "legacy")) return 2;
  setEnabled(true, UINT32_MAX - 10); decision(0, UINT32_MAX - 5);
  sleepBegin(UINT32_MAX - 31); sleepEnd(50);
  assert(state().calls == 1 && state().returns == 1 && state().last_call_us == 82);
  char reply[160];
  for (unsigned page = 9; page <= 10; ++page) {
    char command[40]; snprintf(command, sizeof(command), "get powersaving.diag %u", page);
    assert(handleCommand(command, reply, sizeof(reply), 1));
    assert(!strcmp(reply, "Error: get powersaving.diag [0-8|state|calls|time|reason]; reason pages 3-8"));
  }
#endif
  return 0;
}
'''


class SdkBucketTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='meshcore-sdk-buckets-')
        cls.addClassCleanup(cls.temp.cleanup)
        source = Path(cls.temp.name) / 'buckets.cpp'
        source.write_text(SOURCE, encoding='ascii')
        cls.binaries = {}
        for platform in ('ESP32_PLATFORM', 'NRF52_PLATFORM'):
            binary = Path(cls.temp.name) / platform
            result = subprocess.run(shlex.split(os.environ.get('CXX', 'g++')) +
                ['-std=c++11', '-Wall', '-Wextra', '-Werror', '-pedantic', '-D' + platform,
                 '-I', str(ROOT / 'src'), str(source), '-o', str(binary)],
                capture_output=True, text=True)
            if result.returncode:
                raise RuntimeError(result.stderr)
            cls.binaries[platform] = binary

    def run_case(self, name, platform='ESP32_PLATFORM'):
        result = subprocess.run([str(self.binaries[platform]), name], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_bin_boundaries_and_outside_calls_are_not_clamped(self):
        self.run_case('boundaries')

    def test_on_reset_disabled_and_off_freeze(self):
        self.run_case('reset_freeze')

    def test_millis_wrap_is_independent_of_micros_wrap(self):
        self.run_case('clock_wrap')

    def test_saturation_and_missing_clock_are_explicit(self):
        self.run_case('saturation_missing')

    def test_real_pages_fit_protocol_and_every_small_buffer(self):
        self.run_case('format_capacity')

    def test_nrf52_retains_legacy_layout_counters_and_cli(self):
        self.run_case('legacy', 'NRF52_PLATFORM')


if __name__ == '__main__':
    unittest.main()
