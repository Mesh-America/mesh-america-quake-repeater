#pragma once

#include <stddef.h>
#include <stdint.h>

namespace d7s {

// Transport implementations must return false on NACK, timeout or short reads.
// A failed EVENT read may already have cleared device flags; callers must report it.
class Transport {
public:
  virtual ~Transport() = default;
  virtual bool read(uint16_t reg, uint8_t* data, size_t size) = 0;
  virtual bool write(uint16_t reg, uint8_t value) = 0;
};

enum class State : uint8_t { Standby = 0, Earthquake = 1, Installing = 2, Offset = 3, SelfTest = 4 };
enum class Command : uint8_t { Install = 2, AcquireOffset = 3, SelfTest = 4 };
enum Interrupt : uint8_t { Int1 = 1, Int2 = 2 };
enum Event : uint8_t {
  SignificantShaking = 0x01, Tilt = 0x02, SelfTestError = 0x04, BaselineError = 0x08,
  // Not a device flag: a failed EVENT read may have cleared flags that were never seen.
  ReadUncertain = 0x80
};

struct Reading {
  uint16_t siRaw;
  uint16_t pgaRaw;
  Reading(uint16_t si = 0, uint16_t pga = 0) : siRaw(si), pgaRaw(pga) {}
};

struct Snapshot {
  State state = State::Standby;
  bool valid = false;
  bool liveValid = false;
  // A poll has succeeded at least once, i.e. the device answered like a D7S (valid state register).
  bool everValid = false;
  Reading live;
  // Latest stored record, fetched in standby. May predate this boot.
  Reading stored;
  bool storedValid = false;
  uint8_t events = 0;  // Latched software copy of read-to-clear EVENT bits 0..3.
  // How many EVENT reads have carried the significant-shaking flag since boot. Unlike `events` it is
  // never cleared, so a consumer that remembers the last value it handled sees each new report once.
  uint32_t shakingCount = 0;
  uint8_t interrupts = 0;  // Coalesced notifications, not edge counts.
  uint32_t updatedAt = 0;
  uint32_t failures = 0;
  // Sticky since boot, like events; cleared only by Sensor::takeEvents().
  bool eventReadUncertain = false;
  // Events plus the ReadUncertain marker, for consumers that must not hide possible loss.
  uint8_t eventReport() const { return events | (eventReadUncertain ? ReadUncertain : 0); }
};

class Sensor {
public:
  static constexpr uint8_t Address = 0x55;
  static constexpr uint32_t PollMs = 250, NotifyGapMs = 20, RetryMs = 5000;
  explicit Sensor(Transport& transport) : bus(transport) {}
  // Call only from the main loop, after atomically draining the ISR mailbox.
  void notify(uint8_t interrupts) { pending |= interrupts & (Int1 | Int2); }
  // Notifications read after at least 20 ms, otherwise every 250 ms. Failures retry at 5 s.
  bool service(uint32_t now);
  bool command(Command command);
  bool readStored(uint8_t index, bool ranked, Reading& reading);
  const Snapshot& snapshot() const { return data; }
  // Acknowledges only local copies (events and the uncertainty marker); never reads or
  // clears the sensor's memory. Returns eventReport() as it stood.
  uint8_t takeEvents();
  uint8_t takeInterrupts();
private:
  Transport& bus;
  Snapshot data;
  uint8_t pending = 0;
  bool attempted = false;
  bool failed = false;
  uint32_t lastAttempt = 0;
  bool storedPending = true;
};

}  // namespace d7s
