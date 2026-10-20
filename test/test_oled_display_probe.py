#!/usr/bin/env python3
"""Run the real SSD1306/SH1106 status probe against scripted I2C replies."""

from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]

HARNESS = r'''
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <initializer_list>
#include <limits>
#include <vector>
#include <helpers/ui/OLEDDisplayProbe.h>

struct Sample {
  uint8_t status;
  uint8_t count = 1;
  bool available = true;
  int read = -2; // -2 supplies the status byte, -1 simulates a failed read.
};

struct ScriptedWire {
  uint8_t expected_address = 0x3C;
  uint8_t probe_error = 0;
  std::vector<Sample> samples;
  std::vector<uint8_t> status_errors;
  std::vector<std::vector<uint8_t>> writes;
  unsigned requests = 0, reads = 0, ends = 0, write_calls = 0;
  unsigned failed_write = std::numeric_limits<unsigned>::max();
  Sample current{};

  void beginTransmission(uint8_t address) {
    assert(address == expected_address);
    writes.push_back({});
  }
  size_t write(uint8_t byte) {
    assert(!writes.empty());
    writes.back().push_back(byte);
    return write_calls++ == failed_write ? 0 : 1;
  }
  uint8_t endTransmission(bool = true) {
    const unsigned transaction = ends++;
    if (transaction == 0) return probe_error;
    const unsigned sample = transaction - 1;
    return sample < status_errors.size() ? status_errors[sample] : 0;
  }
  uint8_t requestFrom(uint8_t address, uint8_t count) {
    assert(address == expected_address);
    assert(count == 1);
    assert(requests < 4);
    current = requests < samples.size() ? samples[requests] : Sample{0};
    ++requests;
    return current.count;
  }
  int available() { return current.available ? current.count : 0; }
  int read() {
    ++reads;
    return current.read == -2 ? current.status : current.read;
  }

  void checkBus() const {
    assert(ends <= 5);
    assert(requests <= 4);
    assert(reads <= requests);
    assert(!writes.empty());
    assert(writes.front().empty()); // Address probe does not alter the panel.
    for (size_t i = 1; i < writes.size(); ++i) {
      assert(writes[i] == std::vector<uint8_t>{0x00});
    }
  }
};

using mesh::ui::OLEDController;

static OLEDController detect(ScriptedWire& wire) {
  const auto controller = mesh::ui::detectOLEDController(wire, wire.expected_address);
  wire.checkBus();
  return controller;
}

static ScriptedWire status(std::initializer_list<uint8_t> values) {
  ScriptedWire wire;
  for (uint8_t value : values) wire.samples.push_back({value});
  return wire;
}

int main() {
  for (uint8_t address : {0x3C, 0x3D}) {
    for (uint8_t error : {1, 2, 3, 4, 5}) {
      ScriptedWire wire;
      wire.expected_address = address;
      wire.probe_error = error;
      assert(detect(wire) == OLEDController::Absent);
      assert(wire.requests == 0 && wire.reads == 0 && wire.ends == 1);
    }
    auto wire = status({0x08, 0x08});
    wire.expected_address = address;
    assert(detect(wire) == OLEDController::SH1106);
    assert(wire.requests == 2);
  }

  // Only the status low nibble identifies the controller. Busy bit 0x80
  // alone is also seen on SSD1306 hardware and must not select SH1106.
  for (unsigned value = 0; value <= 255; ++value) {
    auto wire = status({uint8_t(value), uint8_t(value),
                        uint8_t(value), uint8_t(value)});
    const auto expected = (value & 0x0F) == 0x08
        ? OLEDController::SH1106 : OLEDController::SSD1306;
    assert(detect(wire) == expected);
    assert(wire.requests == 2);
  }
  for (auto values : {
      std::initializer_list<uint8_t>{8, 0, 8, 0},
      {0, 8, 0, 8}, {8, 0x80, 8, 0x80}, {0xFF, 8, 0xFF, 8}}) {
    auto wire = status(values);
    assert(detect(wire) == OLEDController::SSD1306);
    assert(wire.requests == 4);
  }
  for (auto values : {
      std::initializer_list<uint8_t>{0, 8, 0x88},
      {0, 1, 8, 8}, {8, 0, 8, 8}}) {
    auto wire = status(values);
    assert(detect(wire) == OLEDController::SH1106);
    assert(wire.requests >= 3 && wire.requests <= 4);
  }
  // Two ordinary stable statuses identify SSD1306 without wasting all four
  // reads, and must not be overturned by later unrelated reply bytes.
  auto stable_ssd = status({0x00, 0x80, 8, 8});
  assert(detect(stable_ssd) == OLEDController::SSD1306);
  assert(stable_ssd.requests == 2);

  // Incomplete and failed samples may never complete a matching pair.
  for (unsigned failure = 0; failure < 4; ++failure) {
    auto wire = status({8, 8, 0, 0});
    if (failure == 0) wire.samples[1].count = 0;
    if (failure == 1) wire.samples[1].available = false;
    if (failure == 2) wire.samples[1].read = -1;
    if (failure == 3) wire.samples[1].count = 2;
    assert(detect(wire) == OLEDController::SSD1306);
    assert(wire.requests == 2);
  }
  for (unsigned failed_sample = 0; failed_sample < 4; ++failed_sample) {
    auto wire = status({0, 1, 2, 3});
    wire.status_errors.resize(4, 0);
    wire.status_errors[failed_sample] = 2;
    assert(detect(wire) == OLEDController::SSD1306);
    assert(wire.requests == failed_sample);
    assert(wire.ends == failed_sample + 2);
  }
  for (unsigned failed_sample = 0; failed_sample < 4; ++failed_sample) {
    auto wire = status({0, 1, 2, 3});
    wire.failed_write = failed_sample;
    assert(detect(wire) == OLEDController::SSD1306);
    assert(wire.requests == failed_sample);
  }

  // No detection state carries between boots, addresses, or missing panels.
  auto sh = status({8, 8});
  auto ssd = status({0x80, 0x80, 0x80, 0x80});
  ScriptedWire missing;
  missing.probe_error = 2;
  assert(detect(sh) == OLEDController::SH1106);
  assert(detect(ssd) == OLEDController::SSD1306);
  assert(detect(missing) == OLEDController::Absent);
  std::puts("PASS: OLED controller status detection, errors and sample bounds");
}
'''

ARDUINO = r'''
#pragma once
#include <cstdint>
#include <utility>
#include <vector>
#define OUTPUT 1
#define HIGH 1
#define LOW 0
inline std::vector<std::pair<int, int>> pin_modes, pin_levels;
inline std::vector<unsigned> delays;
inline void pinMode(int pin, int mode) { pin_modes.push_back({pin, mode}); }
inline void digitalWrite(int pin, int level) { pin_levels.push_back({pin, level}); }
inline void delay(unsigned ms) { delays.push_back(ms); }
'''

WIRE = r'''
#pragma once
#include <cassert>
#include <cstddef>
#include <cstdint>
#include <limits>
#include <map>
#include <vector>
struct TwoWire {
  struct Transaction { uint8_t address; std::vector<uint8_t> data; };
  std::vector<Transaction> transactions;
  std::vector<uint32_t> clocks;
  std::map<uint8_t, bool> present{{0x3C, true}, {0x3D, false}};
  std::map<uint8_t, std::vector<int>> status{{0x3C, {8, 8, 8, 8}}};
  std::map<uint8_t, unsigned> requests;
  unsigned begun = 0, byte_writes = 0, block_writes = 0;
  unsigned failed_tx = std::numeric_limits<unsigned>::max();
  unsigned failed_byte = std::numeric_limits<unsigned>::max();
  unsigned failed_block = std::numeric_limits<unsigned>::max();
  int current_read = 0;
  void begin() { ++begun; }
  void setClock(uint32_t value) { clocks.push_back(value); }
  void beginTransmission(uint8_t address) { transactions.push_back({address, {}}); }
  size_t write(uint8_t byte) {
    assert(!transactions.empty());
    transactions.back().data.push_back(byte);
    return byte_writes++ == failed_byte ? 0 : 1;
  }
  size_t write(const uint8_t* bytes, size_t count) {
    assert(!transactions.empty());
    transactions.back().data.insert(transactions.back().data.end(), bytes, bytes + count);
    assert(transactions.back().data.size() <= 32);
    return block_writes++ == failed_block ? count - 1 : count;
  }
  uint8_t endTransmission(bool = true) {
    const auto& tx = transactions.back();
    return !present[tx.address] || transactions.size() - 1 == failed_tx ? 2 : 0;
  }
  uint8_t requestFrom(uint8_t address, uint8_t count) {
    assert(count == 1);
    const unsigned index = requests[address]++;
    current_read = index < status[address].size() ? status[address][index] : 0;
    return present[address] ? 1 : 0;
  }
  int available() { return 1; }
  int read() { return current_read; }
};
inline TwoWire Wire;
'''

VENDOR = r'''
#pragma once
#include <Arduino.h>
#include <Wire.h>
#include <cstdlib>
#include <cstring>
#define SSD1306_SWITCHCAPVCC 2
void* test_malloc(size_t count);
void test_free(void* pointer);
class Adafruit_SSD1306 {
protected:
  const uint16_t WIDTH, HEIGHT;
  TwoWire* wire;
  uint8_t* buffer = nullptr;
  int8_t rstPin, i2caddr = 0, vccstate = 0;
  uint32_t wireClk, restoreClk;
public:
  unsigned base_begin_calls = 0, base_display_calls = 0;
  bool fail_begin = false, last_reset = true, last_periph_begin = true;
  Adafruit_SSD1306(uint8_t width, uint8_t height, TwoWire* bus = &Wire,
                   int8_t reset = -1, uint32_t during = 400000, uint32_t after = 100000)
      : WIDTH(width), HEIGHT(height), wire(bus), rstPin(reset),
        wireClk(during), restoreClk(after) {}
  ~Adafruit_SSD1306() { test_free(buffer); }
  bool begin(uint8_t vcc, uint8_t address, bool reset, bool periph_begin) {
    ++base_begin_calls;
    last_reset = reset;
    last_periph_begin = periph_begin;
    if (fail_begin) return false;
    if (!buffer) buffer = static_cast<uint8_t*>(test_malloc(WIDTH * ((HEIGHT + 7) / 8)));
    if (!buffer) return false;
    i2caddr = address;
    vccstate = vcc;
    clearDisplay();
    return true;
  }
  void clearDisplay() { std::memset(buffer, 0, WIDTH * ((HEIGHT + 7) / 8)); }
  uint8_t* getBuffer() { return buffer; }
  void display() { ++base_display_calls; }
  void ssd1306_command(uint8_t command) {
    wire->beginTransmission(uint8_t(i2caddr));
    wire->write(uint8_t(0));
    wire->write(command);
    wire->endTransmission();
  }
};
'''

BACKEND_HARNESS = r'''
#include <cassert>
#include <cstdlib>
#include <stdlib.h>
#include <cstdio>
#include <algorithm>
#include <Adafruit_SSD1306.h>
static unsigned active_allocations = 0, total_allocations = 0;
static bool allocation_fails = false;
void* test_malloc(size_t count) {
  assert(count == 1024);
  if (allocation_fails) return nullptr;
  void* result = std::malloc(count);
  assert(result);
  ++active_allocations;
  ++total_allocations;
  return result;
}
void test_free(void* pointer) {
  if (!pointer) return;
  assert(active_allocations == 1);
  --active_allocations;
  std::free(pointer);
}
#define malloc test_malloc
#include <helpers/ui/AutoOLEDBackend.h>
#undef malloc
using mesh::ui::OLEDController;

static void resetPins() { pin_modes.clear(); pin_levels.clear(); delays.clear(); }
static unsigned totalRequests(const TwoWire& wire) {
  unsigned count = 0;
  for (const auto& entry : wire.requests) count += entry.second;
  return count;
}
[[maybe_unused]] static void beginSH(AutoOLEDBackend& display, TwoWire& wire) {
  assert(display.begin(SSD1306_SWITCHCAPVCC, 0x3C, true, false));
  assert(display.controller() == OLEDController::SH1106);
  assert(display.base_begin_calls == 0);
  assert(display.getBuffer() != nullptr);
  assert(active_allocations == 1);
  assert(wire.begun == 0);
  assert(wire.clocks.back() == 100000);
}
[[maybe_unused]] static void verifyFrame(AutoOLEDBackend& display, TwoWire& wire) {
  uint8_t* buffer = display.getBuffer();
  for (unsigned i = 0; i < 1024; ++i) buffer[i] = uint8_t((i * 37 + i / 128) & 255);
  const size_t first = wire.transactions.size();
  display.display();
  assert(display.base_display_calls == 0);
  size_t index = first;
  for (unsigned page = 0; page < 8; ++page) {
    const auto& command = wire.transactions.at(index++);
    assert(command.address == 0x3C);
    assert(command.data == (std::vector<uint8_t>{0x00, uint8_t(0xB0 | page), 0x02, 0x10}));
    unsigned column = 0;
    while (column < 128) {
      const auto& data = wire.transactions.at(index++);
      assert(data.address == 0x3C);
      const unsigned count = std::min(31u, 128u - column);
      assert(data.data.size() == count + 1);
      assert(data.data[0] == 0x40);
      for (unsigned i = 0; i < count; ++i)
        assert(data.data[i + 1] == buffer[page * 128 + column + i]);
      column += count;
    }
  }
  assert(index == wire.transactions.size());
  assert(wire.clocks.back() == 100000);
}

int main() {
  resetPins();
#if defined(OLED_CONTROLLER_OVERRIDE) && OLED_CONTROLLER_OVERRIDE == 1
  {
    TwoWire wire;
    AutoOLEDBackend display(128, 64, &wire, -1);
    assert(display.begin(2, 0x3C, true, true));
    assert(display.controller() == OLEDController::SSD1306);
    assert(display.base_begin_calls == 1);
    assert(!display.last_reset && !display.last_periph_begin);
    assert(wire.begun == 1 && totalRequests(wire) == 0);
    display.display();
    assert(display.base_display_calls == 1);
  }
#else
  {
    TwoWire wire;
#if defined(OLED_CONTROLLER_OVERRIDE) && OLED_CONTROLLER_OVERRIDE == 2
    wire.status[0x3C] = {0, 0};
#endif
    AutoOLEDBackend display(128, 64, &wire, 9);
    beginSH(display, wire);
    assert(pin_modes == (std::vector<std::pair<int, int>>{{9, OUTPUT}}));
    assert(pin_levels == (std::vector<std::pair<int, int>>{{9, HIGH}, {9, LOW}, {9, HIGH}}));
    assert(delays == (std::vector<unsigned>{1, 10, 100}));
    assert(totalRequests(wire) ==
#if defined(OLED_CONTROLLER_OVERRIDE) && OLED_CONTROLLER_OVERRIDE == 2
           0
#else
           2
#endif
    );
    const std::vector<uint8_t> init = {
      0x00, 0xAE, 0xD5, 0x80, 0xA8, 0x3F, 0xD3, 0x00, 0x40,
      0xAD, 0x8B, 0xA1, 0xC8, 0xDA, 0x12, 0x81, 0xFF,
      0xD9, 0x1F, 0xDB, 0x40, 0x33, 0xA6, 0x20, 0x10, 0xA4
    };
    assert(wire.transactions[wire.transactions.size() - 2].data == init);
    assert(wire.transactions.back().data == (std::vector<uint8_t>{0, 0xAF}));
    verifyFrame(display, wire);
    const auto* original = display.getBuffer();
    const auto allocations = total_allocations;
    resetPins();
    assert(display.begin(2, 0x3C, false, false));
    assert(display.getBuffer() == original && total_allocations == allocations);
    assert(pin_modes.empty() && pin_levels.empty());
    verifyFrame(display, wire);
  }
  assert(active_allocations == 0);

  // Initialization and frame errors stop further writes, restore the bus
  // clock, and leave a bounded framebuffer available for a later retry.
  for (unsigned failure = 0; failure < 8; ++failure) {
    TwoWire wire;
    AutoOLEDBackend display(128, 64, &wire, -1);
    const unsigned init =
#if defined(OLED_CONTROLLER_OVERRIDE) && OLED_CONTROLLER_OVERRIDE == 2
        1;
#else
        3;
#endif
    if (failure < 2) wire.failed_tx = init + failure;
    if (failure == 2) wire.failed_byte = init - 1;
    if (failure == 3) wire.failed_block = 0;
    if (failure < 4) {
      assert(!display.begin(2, 0x3C, false, false));
      assert(wire.clocks.back() == 100000);
      const auto transfers = wire.transactions.size();
      display.display();
      display.ssd1306_command(0xAF);
      assert(wire.transactions.size() == transfers);
    } else {
      beginSH(display, wire);
      const auto transfers = wire.transactions.size();
      if (failure == 4) wire.failed_tx = transfers;
      if (failure == 5) wire.failed_block = wire.block_writes + 1;
      if (failure == 6) wire.failed_tx = transfers + 1;
      if (failure == 7) wire.failed_byte = wire.byte_writes + 1;
      display.display();
      assert(wire.transactions.size() == transfers + (failure == 4 ? 1 : 2));
      assert(wire.clocks.back() == 100000);
    }
    wire.failed_tx = wire.failed_byte = wire.failed_block = ~0u;
    wire.requests.clear();
    const auto* original = display.getBuffer();
    const auto allocations = total_allocations;
    assert(display.begin(2, 0x3C, false, false));
    assert(display.getBuffer() == original && total_allocations == allocations);
    verifyFrame(display, wire);
  }
  assert(active_allocations == 0);
  {
    TwoWire wire;
    AutoOLEDBackend display(128, 64, &wire, -1);
    allocation_fails = true;
    assert(!display.begin(2, 0x3C, false, false));
    assert(display.getBuffer() == nullptr && active_allocations == 0);
    const auto transfers = wire.transactions.size();
    display.display();
    display.ssd1306_command(0xAF);
    assert(wire.transactions.size() == transfers);
    allocation_fails = false;
    wire.requests.clear();
    beginSH(display, wire);
  }
#endif
  assert(active_allocations == 0);

#if !defined(OLED_CONTROLLER_OVERRIDE) || OLED_CONTROLLER_OVERRIDE == 0
  {
    TwoWire wire;
    wire.status[0x3C] = {0, 0};
    AutoOLEDBackend display(128, 64, &wire, -1);
    assert(display.begin(2, 0x3C, false, false));
    const auto* original = display.getBuffer();
    const auto allocations = total_allocations;
    wire = TwoWire{};
    assert(display.begin(2, 0x3C, false, false));
    assert(display.controller() == OLEDController::SH1106);
    assert(display.getBuffer() == original && total_allocations == allocations);
    verifyFrame(display, wire);
    wire = TwoWire{};
    wire.present[0x3C] = false;
    assert(!display.begin(2, 0x3C, false, false));
    assert(display.controller() == OLEDController::Absent);
    const auto transfers = wire.transactions.size();
    display.display();
    assert(wire.transactions.size() == transfers);
    wire = TwoWire{};
    wire.status[0x3C] = {0x80, 0x80};
    assert(display.begin(2, 0x3C, false, false));
    assert(display.controller() == OLEDController::SSD1306);
    assert(display.getBuffer() == original && total_allocations == allocations);
    display.display();
    assert(display.base_display_calls == 1 && display.base_begin_calls == 2);
  }
  assert(active_allocations == 0);
  for (bool fail : {false, true}) {
    TwoWire wire;
    wire.status[0x3C] = {0x00, 0x80};
    AutoOLEDBackend display(128, 64, &wire, -1);
    display.fail_begin = fail;
    assert(display.begin(2, 0x3C, true, true) == !fail);
    assert(display.controller() == OLEDController::SSD1306);
    assert(display.base_begin_calls == 1);
    assert(!display.last_reset && !display.last_periph_begin);
    assert(wire.begun == 1);
    display.display();
    assert(display.base_display_calls == unsigned(!fail));
  }
#endif
  {
    TwoWire wire;
    wire.present[0x3C] = false;
    AutoOLEDBackend display(128, 64, &wire, -1);
    display.ssd1306_command(0xAE);
    assert(wire.transactions.empty());
    assert(!display.begin(2, 0x3C, true, false));
    assert(display.controller() == OLEDController::Absent);
    assert(display.getBuffer() == nullptr);
    assert(totalRequests(wire) == 0);
    const auto transfers = wire.transactions.size();
    display.display();
    display.ssd1306_command(0xAE);
    assert(wire.transactions.size() == transfers);
  }
  assert(active_allocations == 0);
  std::puts("PASS: OLED backend selection, single buffer, page writes and retry");
}
'''


class OledDisplayProbeTests(unittest.TestCase):
    def compile_run(self, source_text, definitions=(), mocks=None):
        compiler = os.environ.get("CXX") or shutil.which("g++") or shutil.which("clang++")
        if compiler is None:
            self.skipTest("a host C++17 compiler is required")
        with tempfile.TemporaryDirectory(prefix="meshcore-oled-probe-") as directory:
            work = Path(directory)
            source = work / "probe.cpp"
            source.write_text(source_text, encoding="ascii")
            for name, contents in (mocks or {}).items():
                (work / name).write_text(contents, encoding="ascii")
            binary = work / "probe"
            sanitizer = (["-fsanitize=address,undefined", "-fno-sanitize-recover=all",
                          "-fno-pie", "-no-pie"] if sys.platform.startswith("linux") else [])
            built = subprocess.run([
                compiler, "-std=c++17", "-O1", "-Wall", "-Wextra", "-Werror",
                *sanitizer, *definitions, "-I", str(work),
                "-I", str(ROOT / "src"), str(source), "-o", str(binary),
            ], text=True, capture_output=True, timeout=60)
            self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
            checked = subprocess.run([str(binary)], text=True, capture_output=True, timeout=15)
            self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
            return checked.stdout

    def test_real_detector_selects_only_repeated_sh1106_status(self):
        self.assertIn("PASS: OLED controller status detection", self.compile_run(HARNESS))

    def test_real_backend_transfers_and_failure_recovery(self):
        mocks = {"Arduino.h": ARDUINO, "Wire.h": WIRE, "Adafruit_SSD1306.h": VENDOR}
        for definitions in ((), ("-DOLED_CONTROLLER_OVERRIDE=1",),
                            ("-DOLED_CONTROLLER_OVERRIDE=2",)):
            with self.subTest(definitions=definitions):
                output = self.compile_run(BACKEND_HARNESS, definitions, mocks)
                self.assertIn("PASS: OLED backend selection", output)


if __name__ == "__main__":
    unittest.main()
