#pragma once
#include <Stream.h>
#include <algorithm>
#include <deque>
#include <functional>
#include <limits>
#include <vector>

// Only bytes accepted by the hardware are recorded/delivered. An ended UART
// cannot receive bytes and has no stale RX FIFO on the next begin().
class HardwareSerial : public Stream {
public:
  bool pins_ok = true, begin_ok = true, installed = false;
  unsigned begin_calls = 0, end_calls = 0, write_calls = 0;
  int tx_capacity = 4096;
  size_t write_limit = std::numeric_limits<size_t>::max();
  std::deque<uint8_t> rx;
  std::vector<uint8_t> tx;
  std::function<void(const uint8_t*, size_t)> delivered;

  bool setPins(int16_t, int16_t) { return pins_ok; }
  void begin(uint32_t) { ++begin_calls; installed = begin_ok; rx.clear(); }
  void end() { ++end_calls; installed = false; rx.clear(); }
  explicit operator bool() const { return installed; }
  int available() override { return installed ? static_cast<int>(rx.size()) : 0; }
  int read() override {
    if (!installed || rx.empty()) return -1;
    const auto value = rx.front(); rx.pop_front(); return value;
  }
  int availableForWrite() override {
    return installed ? static_cast<int>(std::min<size_t>(tx_capacity, write_limit)) : 0;
  }
  size_t write(const uint8_t* data, size_t size) override {
    ++write_calls;
    if (!installed) return 0;
    const size_t accepted = std::min(size, write_limit);
    tx.insert(tx.end(), data, data + accepted);
    if (accepted && delivered) delivered(data, accepted);
    return accepted;
  }
  void feed(const std::vector<uint8_t>& bytes) {
    if (installed) rx.insert(rx.end(), bytes.begin(), bytes.end());
  }
  void feed(const uint8_t* data, size_t size) {
    if (installed) rx.insert(rx.end(), data, data + size);
  }
};
