#include "D7S.h"

namespace d7s {
namespace {
uint16_t word(const uint8_t* p) { return (uint16_t(p[0]) << 8) | p[1]; }
}

bool Sensor::service(uint32_t now) {
  if (attempted) {
    // Notifications only shorten the healthy poll to a floor, so a chattering line cannot
    // turn every main-loop pass into I2C traffic; failures always wait the full retry.
    const uint32_t interval = failed ? RetryMs : (pending ? NotifyGapMs : PollMs);
    if (uint32_t(now - lastAttempt) < interval) return false;
  }
  attempted = true;
  lastAttempt = now;
  data.interrupts |= pending;
  pending = 0;
  data.valid = false;
  data.liveValid = false;
  uint8_t state, events;
  if (!bus.read(0x1000, &state, 1) || (state & 7) > 4) {
    failed = true;
    storedPending = true;
    data.storedValid = false;
    ++data.failures;
    return false;
  }
  if (!bus.read(0x1002, &events, 1)) {
    // The device may have cleared EVENT before the transport reported failure.
    data.eventReadUncertain = true;
    failed = true;
    storedPending = true;
    data.storedValid = false;
    ++data.failures;
    return false;
  }
  data.events |= events & 0x0f;  // Preserve both INT1 causes in a single register read.
  if (events & SignificantShaking) ++data.shakingCount;
  if (events & (SignificantShaking | Tilt)) {
    // A shaking/tilt flag means a record may have been stored while we were not looking
    // (failure backoff, processing window shorter than the poll). Re-read it in standby.
    storedPending = true;
    data.storedValid = false;
  }
  data.state = static_cast<State>(state & 7);
  if (data.state != State::Standby) {
    storedPending = true;
    data.storedValid = false;
  }
  if (data.state == State::Earthquake) {
    uint8_t values[4];
    if (!bus.read(0x2000, values, sizeof(values))) {
      failed = true;
      storedPending = true;
      data.storedValid = false;
      ++data.failures;
      return false;
    }
    data.live = {word(values), word(values + 2)};
    data.liveValid = true;
  }
  if (data.state == State::Standby && storedPending) {
    Reading stored;
    if (!readStored(0, false, stored)) {
      failed = true;
      storedPending = true;
      data.storedValid = false;
      ++data.failures;
      return false;
    }
    data.stored = stored;
    data.storedValid = true;
    storedPending = false;
  }
  failed = false;
  data.valid = true;
  data.everValid = true;
  data.updatedAt = now;
  return true;
}

bool Sensor::command(Command command) {
  const auto value = static_cast<uint8_t>(command);
  if (value < 2 || value > 4) return false;
  // Read current state, rather than relying on a potentially stale snapshot.
  uint8_t state;
  if (!bus.read(0x1000, &state, 1) || (state & 7) != 0) return false;
  if (!bus.write(0x1003, value)) return false;
  data.valid = false;
  data.liveValid = false;
  return true;
}

bool Sensor::readStored(uint8_t index, bool ranked, Reading& reading) {
  if (index >= 5) return false;
  const uint16_t reg = 0x3008 + (uint16_t(index) + (ranked ? 5 : 0)) * 0x100;
  uint8_t values[4];
  if (!bus.read(reg, values, sizeof(values))) return false;
  reading = {word(values), word(values + 2)};
  return true;
}

uint8_t Sensor::takeEvents() {
  const uint8_t result = data.eventReport();
  data.events = 0;
  data.eventReadUncertain = false;
  return result;
}

uint8_t Sensor::takeInterrupts() {
  const uint8_t result = data.interrupts;
  data.interrupts = 0;
  return result;
}
}  // namespace d7s
