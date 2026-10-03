#pragma once

#include <stddef.h>
#include <stdint.h>

// Earthquake channel alerts for the Mesh America Quake Repeater.
//
// Everything here is plain logic with no hardware, radio or filesystem dependency, so it can be
// tested on a PC. The repeater supplies the facts (what the sensor saw, whether a channel, a
// and a location are set) and sends the message when this says to. See
// docs/earthquake-alerts.md for what it does and why.
namespace seismic {

// ---- Gates -----------------------------------------------------------------------------------

// A position counts as set when it is finite, in range, and not exactly 0,0 (the default every
// repeater starts with, in the ocean off Africa, which nobody means).
bool locationIsSet(double lat, double lon);

// ---- Channel name ----------------------------------------------------------------------------

enum class Hashtag : uint8_t { Ok, Empty, TooLong, BadCharacter };
// Accepts "quake-alerts" or "#Quake-Alerts" and writes the canonical "#quake-alerts" (lower case
// letters, digits and dashes) into `out`. `cap` is the size of `out` including its terminator.
Hashtag normalizeHashtag(const char* input, char* out, size_t cap);

// ---- The message -----------------------------------------------------------------------------

// Writes the message and returns its length, or 0 if even the shortest form does not fit `budget`
// characters. The disclaimer is never cut: when the full text is too long for the room left after
// the repeater's name, detail is dropped instead (see the three forms in SeismicAlert.cpp).
//   "Shaking detected near 47.61,-122.33. Strength 43.3 cm/s, peak acceleration 148 gal. This does
//    not necessarily indicate an earthquake."
// SI is stored in tenths of cm/s and PGA in tenths of gal. `test` marks a test message.
size_t formatMessage(char* out, size_t outCap, size_t budget, double lat, double lon, bool haveValues,
                     uint16_t siRaw, uint16_t pgaRaw, bool test = false);

// ---- Deciding when to send -------------------------------------------------------------------

struct Input {
  bool sensorPresent = false;  // A D7S has answered like one.
  bool sensorFaulted = false;  // It has reported a self-test or baseline error since boot.
  bool processing = false;     // It is working on a shaking event right now.
  bool recordValid = false;    // `siRaw`/`pgaRaw` are the sensor's latest stored record.
  uint32_t shakingCount = 0;   // Monotonic count of significant-shaking reports since boot.
  uint16_t siRaw = 0;
  uint16_t pgaRaw = 0;
};

struct Gates {
  bool channelSet = false;
  bool locationSet = false;
};

enum class Block : uint8_t { None, NoSensor, SensorFault, NoChannel, NoLocation };
const char* blockText(Block block);

struct Send {
  bool haveValues = false;
  uint16_t siRaw = 0;
  uint16_t pgaRaw = 0;
};

// One alert per shaking event, then a quiet period. The flow:
//   1. A new significant-shaking report arrives (reports from before this started watching are
//      history and ignored).
//   2. Wait for the sensor to finish its processing window so the message can carry the final
//      values. If they do not arrive in time, send without values.
//   3. Wait a random delay, so that neighbouring repeaters which all felt the same shaking do not
//      transmit at the same moment.
//   4. Check every gate: a sensor that is not faulted, a channel and a location. If any
//      is missing nothing is sent and the reason is kept (a missing setting never queues an old
//      alert for later).
//   5. Send, then ignore further reports until the cooldown has passed.
class Policy {
public:
  enum class Phase : uint8_t { Idle, WaitingForRecord, Delaying, Cooldown };
  // How long the sensor may take to finish processing (it works for about two minutes), and how
  // long to wait for a processing state that never shows before giving up on values.
  static constexpr uint32_t RecordWaitMs = 4UL * 60 * 1000;
  static constexpr uint32_t NoProcessingWaitMs = 5UL * 1000;

  void configure(uint32_t cooldownMs, uint32_t jitterMaxMs) {
    cooldownMs_ = cooldownMs;
    jitterMaxMs_ = jitterMaxMs;
  }
  uint32_t jitterMaxMs() const { return jitterMaxMs_; }

  // Call often. `jitterMs` is a fresh random value in [0, jitterMaxMs()]; it is only used when a
  // new event starts. Returns true when a message should be sent now, filling `out`.
  bool update(uint32_t now, const Input& in, const Gates& gates, uint32_t jitterMs, Send& out);

  Phase phase() const { return phase_; }
  Block lastBlocked() const { return lastBlocked_; }
  uint32_t eventsSeen() const { return eventsSeen_; }
  uint32_t sent() const { return sent_; }
  uint32_t suppressed() const { return suppressed_; }
  uint32_t ignoredInCooldown() const { return ignored_; }
  uint32_t cooldownRemainingMs(uint32_t now) const;

private:
  static bool reached(uint32_t now, uint32_t t) { return int32_t(now - t) >= 0; }

  uint32_t cooldownMs_ = 10UL * 60 * 1000;
  uint32_t jitterMaxMs_ = 30UL * 1000;
  Phase phase_ = Phase::Idle;
  Block lastBlocked_ = Block::None;
  bool baselineSet_ = false;
  bool sawProcessing_ = false;
  bool haveValues_ = false;
  uint16_t si_ = 0, pga_ = 0;
  uint32_t seen_ = 0;
  uint32_t eventAt_ = 0, sendAt_ = 0, cooldownUntil_ = 0;
  uint32_t eventsSeen_ = 0, sent_ = 0, suppressed_ = 0, ignored_ = 0;
};

}  // namespace seismic
