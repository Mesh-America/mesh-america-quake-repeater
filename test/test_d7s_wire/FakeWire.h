#pragma once

#include <cstddef>
#include <cstdint>
#include <deque>
#include <vector>

// Scriptable stand-in for Arduino's TwoWire, recording every transaction. Test-local so it never
// shadows the shared test/mocks/Wire.h stub.
class FakeWire {
public:
  struct Txn {
    uint8_t address;
    std::vector<uint8_t> bytes;
    bool stop;
    bool isRead;
    size_t requested;
  };
  std::vector<Txn> log;
  std::deque<uint8_t> rx;       // Bytes returned by the next requestFrom().
  uint8_t endTransmissionResult = 0;  // 0 = ACK, 2 = address NACK.
  int shortReadBy = 0;          // Deliver this many fewer bytes than requested.

  void beginTransmission(uint8_t address) { cur = {address, {}, true, false, 0}; }
  size_t write(uint8_t b) { cur.bytes.push_back(b); return 1; }
  uint8_t endTransmission(bool stop = true) {
    cur.stop = stop;
    log.push_back(cur);
    return endTransmissionResult;
  }
  size_t requestFrom(uint8_t address, size_t quantity) {
    log.push_back({address, {}, true, true, quantity});
    const size_t n = quantity > size_t(shortReadBy) ? quantity - shortReadBy : 0;
    avail = n < rx.size() ? n : rx.size();
    return avail;
  }
  int available() { return int(avail); }
  int read() {
    if (rx.empty() || avail == 0) return -1;
    const uint8_t b = rx.front();
    rx.pop_front();
    --avail;
    return b;
  }

private:
  Txn cur{};
  size_t avail = 0;
};
