#!/usr/bin/env python3
"""Bind native SolarXiao history admission to its actual startup allocation."""

from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import check_firmware_ram as ram


class SolarXiaoRoomMemoryTest(unittest.TestCase):
    def test_budget_matches_real_capped_history_allocation(self):
        compiler = shutil.which("g++")
        if compiler is None:
            self.skipTest("g++ is needed for the real history allocation check")
        fixture = r'''
#include <cassert>
#include <cstddef>
#include <cstdio>
#include <cstdlib>
#include <stdlib.h>
size_t allocation_bytes = 0;
unsigned allocation_count = 0;
void* history_malloc(size_t bytes) {
  allocation_bytes = bytes;
  ++allocation_count;
  return std::malloc(bytes);
}
#define malloc history_malloc
#include <helpers/ExternalVoltageHistory.h>
#undef malloc
int main() {
  using History = mesh::ExternalVoltageHistory;
  // Four native channels coexist with more optional monitors than fit.
  // Production must enforce one shared ceiling rather than add four to it.
  uint8_t channels[4 + History::MAX_CHANNELS];
  for (unsigned i = 0; i < 4; ++i) channels[i] = 2 + i;
  for (unsigned i = 0; i < History::MAX_CHANNELS; ++i) channels[4 + i] = 14 + i;
  History history;
  assert(history.configure(channels, sizeof(channels)));
  assert(allocation_count == 1);
  assert(history.channelCount() == History::MAX_CHANNELS);
  assert(history.storageBytes() == allocation_bytes);
  assert(allocation_bytes == History::MAX_CHANNELS * History::BYTES_PER_CHANNEL);
  std::printf("%zu\n", allocation_bytes);
}
'''
        with tempfile.TemporaryDirectory(prefix="solarxiao-room-memory-") as directory:
            directory = Path(directory)
            source, executable = directory / "history.cpp", directory / "history"
            source.write_text(fixture)
            result = subprocess.run([compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
                                     "-I" + str(ROOT / "src"), str(source), "-o", str(executable)],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            allocation = int(subprocess.check_output([str(executable)], text=True))
        for radio in ("30S", "33S"):
            for history_flag in ({}, {"MESH_ENABLE_TELEMETRY_HISTORY": 1}):
                with self.subTest(radio=radio, history=history_flag):
                    target = f"solarxiao_{radio}_room_server_lora_ota"
                    policy = ram.requirements("NRF52_PLATFORM", {
                        "MESH_SOLARXIAO_POWER": 1, **history_flag}, target)
                    parts = policy["components"]
                    self.assertEqual(parts["solarxiao_voltage_history"], allocation + 32)
                    self.assertEqual(parts["core_usb_filesystems_sensors"], 12288)
                    self.assertEqual(policy["required_heap_bytes"], sum(parts.values()))
                    self.assertGreaterEqual(policy["required_contiguous_bytes"], allocation + 32)

    def test_disabled_history_or_native_support_keeps_previous_budget(self):
        target = "solarxiao_33S_room_server_lora_ota"
        baseline = ram.requirements("NRF52_PLATFORM", {}, target)
        for flags in ({"MESH_SOLARXIAO_POWER": 0},
                      {"MESH_ENABLE_TELEMETRY_HISTORY": 0},
                      {"MESH_SOLARXIAO_POWER": 1, "MESH_ENABLE_TELEMETRY_HISTORY": 0}):
            with self.subTest(flags=flags):
                self.assertEqual(ram.requirements("NRF52_PLATFORM", flags, target), baseline)
        enabled = ram.requirements("NRF52_PLATFORM", {"MESH_SOLARXIAO_POWER": 1}, target)
        parts = dict(enabled["components"])
        reserve = parts.pop("solarxiao_voltage_history")
        self.assertEqual(parts, baseline["components"])
        self.assertEqual(enabled["required_heap_bytes"], baseline["required_heap_bytes"] + reserve)

    def test_non_solarxiao_and_other_platform_budgets_are_unchanged(self):
        for platform, target in (("NRF52_PLATFORM", "Xiao_nrf52_room_server_lora_ota"),
                                 ("ESP32_PLATFORM", "heltec_v4_room_server"),
                                 ("STM32_PLATFORM", "wio-e5_room_server"),
                                 ("RP2040_PLATFORM", "pico_room_server")):
            baseline = ram.requirements(platform, {}, target)
            if platform == "NRF52_PLATFORM":
                # Native ownership is opt-in, not inferred from a board name.
                self.assertNotIn("solarxiao_voltage_history", baseline["components"])
                continue
            with self.subTest(platform=platform):
                self.assertEqual(ram.requirements(platform, {
                    "MESH_SOLARXIAO_POWER": 1, "MESH_ENABLE_TELEMETRY_HISTORY": 1}, target), baseline)


if __name__ == "__main__":
    unittest.main()
