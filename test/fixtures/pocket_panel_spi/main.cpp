#include <algorithm>
#include <array>
#include <cassert>
#include <cstdio>
#include <vector>
#include <helpers/ui/MeshPocketEinkPanel.h>
#include <GxEPD2_BW.h>

namespace {
constexpr int CS = 1, DC = 2, RST = 3, BUSY = 4;
using Bitmap = std::array<uint8_t, 4000>;
struct Command {
  uint8_t value;
  uint64_t time;
  std::vector<uint8_t> data;
};
std::vector<Command> commands;
std::vector<uint64_t> resets;
int pins[5] = {HIGH, HIGH, HIGH, HIGH, LOW};
uint64_t time_ms = 0, refresh_started = 0;
bool late_busy = false, updating = false;
unsigned busy_reads = 0;
uint8_t update_mode = 0;
Bitmap current{}, previous{}, expected{}, old_frame{};
uint64_t history_time = 0;

void checkCommandData() {
  if (commands.empty()) return;
  const auto& command = commands.back();
  if (command.value == 0x24 || command.value == 0x26) {
    assert(command.data.size() == 4000);
    // Any automatic all-white controller clear would fail for these patterns.
    assert(std::equal(command.data.begin(), command.data.end(), expected.begin()));
    auto& destination = command.value == 0x24 ? current : previous;
    std::copy(command.data.begin(), command.data.end(), destination.begin());
    if (updating) history_time = command.time;
  }
}

uint64_t busyEnd() {
  return refresh_started + (update_mode == 0xFF ? 1100 : 2900);
}

void recordCommand(uint8_t value) {
  checkCommandData();
  if (value == 0x20) {
    assert(!commands.empty());
    assert(commands.back().value == 0x22 && commands.back().data.size() == 1);
    update_mode = commands.back().data[0];
    assert(update_mode == 0xFF || update_mode == 0xF7);
    assert(current == expected);
    if (update_mode == 0xFF) assert(previous == old_frame);
    else assert(previous == expected);
    refresh_started = time_ms;
    updating = true;
  }
  if (value == 0x7F || value == 0x10) {
    assert(updating);
    const auto minimum = update_mode == 0xFF ? 800u : 2500u;
    assert(time_ms >= refresh_started + minimum);
    if (late_busy) assert(time_ms >= busyEnd());
    assert(current == expected && previous == expected);
    assert(history_time >= refresh_started + minimum);
  }
  commands.push_back({value, time_ms, {}});
}

using Display = GxEPD2_BW<MeshPocketEinkPanel, MeshPocketEinkPanel::HEIGHT>;

Bitmap drawPattern(Display& display, unsigned pattern) {
  display.fillScreen(GxEPD_WHITE);
  Bitmap bitmap;
  bitmap.fill(0xFF);
  // Exercise actual BW rotation and visible 122px versus 128px controller RAM.
  for (int y = 0; y < 122; ++y) {
    for (int x = 0; x < 250; ++x) {
      if (((x * 7 + y * 11 + pattern * 13) % 29) >= 7) continue;
      display.drawPixel(x, y, GxEPD_BLACK);
      const int controller_x = y;
      const int controller_y = 249 - x;
      bitmap[controller_y * 16 + controller_x / 8] &= ~(1u << (7 - controller_x % 8));
    }
  }
  return bitmap;
}

void frame(Display& display, unsigned pattern, bool partial, bool late) {
  old_frame = current;
  expected = drawPattern(display, pattern);
  late_busy = late;
  updating = false;
  commands.clear();
  resets.clear();
  busy_reads = 0;
  const auto frame_start = time_ms;
  display.epd2.prepareRefresh(partial);
  assert(commands.empty()); // prepare must never upload white or other image data
  assert(resets.size() == 1 && resets.front() >= frame_start);
  display.display(partial); // actual BW current upload / refresh / history sync
  display.epd2.finishRefresh();
  checkCommandData();
  assert(display.width() == 250 && display.height() == 122);
  assert(resets.size() == 1);
  assert(!commands.empty() && commands.front().value == 0x12);
  assert(resets.front() < commands.front().time);
  assert(commands.back().value == 0x10 && commands.back().data == std::vector<uint8_t>{1});
  assert(busy_reads > 0);

  std::vector<uint8_t> uploads;
  std::vector<uint8_t> modes;
  uint64_t refresh_time = 0, first_sync_time = 0;
  size_t final_border = 0, refresh_index = 0, sync_index = 0, nop_index = 0;
  for (size_t i = 0; i < commands.size(); ++i) {
    const auto& command = commands[i];
    if (command.value == 0x24 || command.value == 0x26) {
      uploads.push_back(command.value);
      assert(command.data.size() == expected.size());
      assert(std::equal(command.data.begin(), command.data.end(), expected.begin()));
      if (refresh_time && !first_sync_time) {
        first_sync_time = command.time;
        sync_index = i;
      }
    }
    if (command.value == 0x3C) final_border = i;
    if (command.value == 0x22) {
      assert(command.data.size() == 1);
      modes.push_back(command.data[0]);
    }
    if (command.value == 0x20) { refresh_time = command.time; refresh_index = i; }
    if (command.value == 0x7F) nop_index = i;
    if (command.value == 0x44) assert((command.data == std::vector<uint8_t>{0, 15}));
    if (command.value == 0x45) assert((command.data == std::vector<uint8_t>{0, 0, 249, 0}));
  }
  assert((uploads == (partial ? std::vector<uint8_t>{0x24, 0x26, 0x24}
                             : std::vector<uint8_t>{0x26, 0x24, 0x26, 0x24})));
  assert(modes == std::vector<uint8_t>{static_cast<uint8_t>(partial ? 0xFF : 0xF7)});
  assert(commands[final_border].data == std::vector<uint8_t>{static_cast<uint8_t>(partial ? 0x85 : 0x05)});
  assert(final_border < refresh_index && refresh_index < sync_index && sync_index < nop_index);
  assert(first_sync_time >= refresh_time + (partial ? 800 : 2500));
  if (late) assert(first_sync_time >= busyEnd());
  assert(current == expected && previous == expected);
}
} // namespace

void delay(unsigned long ms) { time_ms += ms; }
unsigned long micros() { return static_cast<unsigned long>(time_ms * 1000); }
unsigned long millis() { return static_cast<unsigned long>(time_ms); }
void pinMode(int, int) {}
void digitalWrite(int pin, int value) {
  assert(pin >= 0 && pin < 5);
  if (pin == RST && value == LOW && pins[RST] == HIGH) resets.push_back(time_ms);
  pins[pin] = value;
}
int digitalRead(int pin) {
  assert(pin == BUSY);
  ++busy_reads;
  // A LOW pin immediately after triggering refresh must not shorten safe delay;
  // a delayed BUSY assertion lasting beyond that delay must still be honored.
  if (updating && late_busy && time_ms >= refresh_started + 50 && time_ms < busyEnd()) return HIGH;
  return LOW;
}
uint8_t SPIClass::transfer(uint8_t value) {
  assert(pins[CS] == LOW);
  if (pins[DC] == LOW) recordCommand(value);
  else {
    assert(!commands.empty());
    commands.back().data.push_back(value);
  }
  return 0;
}

int main() {
  static_assert(MeshPocketEinkPanel::WIDTH == 128);
  static_assert(MeshPocketEinkPanel::WIDTH_VISIBLE == 122);
  static_assert(MeshPocketEinkPanel::HEIGHT == 250);
  Display display(MeshPocketEinkPanel(CS, DC, RST, BUSY));
  display.init();
  display.setRotation(3);
  current.fill(0xA5);
  previous.fill(0xA5);
  // Alternating patterns prove reset/deep sleep retained previous image RAM and
  // that differential refresh never sees a white or stale history buffer.
  frame(display, 1, false, false);
  frame(display, 2, true, false);
  frame(display, 3, true, true);
  frame(display, 4, false, true);
  std::puts("Pocket actual GxEPD2 SPI: full/partial/history/reset/sleep checks passed");
}
