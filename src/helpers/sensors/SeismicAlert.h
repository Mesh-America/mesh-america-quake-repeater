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

// Writes the alert and returns its length, or 0 if even the shortest form does not fit `budget`
// characters. The disclaimer is never cut: when the full text is too long for the room left after
// the repeater's name, detail is dropped instead (see the three forms in SeismicAlert.cpp).
//   "Shaking detected near 47.61,-122.33. Strength 43.3 cm/s, peak acceleration 148 gal. This does
//    not necessarily indicate an earthquake."
// SI is stored in tenths of cm/s and PGA in tenths of gal. `test` marks a test message.
size_t formatMessage(char* out, size_t outCap, size_t budget, double lat, double lon, bool haveValues,
                     uint16_t siRaw, uint16_t pgaRaw, bool test = false);

// The follow-up with the sensor's final numbers, same units as above:
//   "Update: strength 43.3 cm/s, peak acceleration 148 gal. This does not necessarily indicate an earthquake."
// Returns 0 if it does not fit `budget`.
size_t formatFollowup(char* out, size_t outCap, size_t budget, uint16_t siRaw, uint16_t pgaRaw);

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

enum class Kind : uint8_t { Alert, Followup };

// What to send. An Alert goes out at once and carries no numbers; a Followup carries the sensor's
// final numbers once it has finished measuring.
struct Send {
  Kind kind = Kind::Alert;
  uint16_t siRaw = 0;
  uint16_t pgaRaw = 0;
};

// One alert per shaking event, then a quiet period. The flow:
//   1. A new significant-shaking report arrives (reports from before this started watching are
//      history and ignored).
//   2. After a very short random delay (so neighbouring repeaters which all felt the same shaking
//      do not transmit in the same instant), check every gate: a sensor that is not faulted, a
//      channel and a location. If any is missing nothing is sent and the reason is kept (a missing
//      setting never queues an old alert for later).
//   3. Send the alert immediately, then ignore further reports until the cooldown has passed.
//   4. The sensor needs about two minutes to finish measuring. When it has, send one follow-up with
//      its final numbers. If it never does, or the numbers cannot be trusted, no follow-up is sent.
class Policy {
public:
  enum class Phase : uint8_t { Idle, Delaying, Cooldown };
  // How long the sensor may take to finish measuring (it works for about two minutes), and how
  // long to wait for a measuring state that never shows before giving up on the follow-up.
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
  bool followupPending() const { return followPending_; }
  Block lastBlocked() const { return lastBlocked_; }
  uint32_t eventsSeen() const { return eventsSeen_; }
  uint32_t sent() const { return sent_; }
  uint32_t followupsSent() const { return followups_; }
  uint32_t suppressed() const { return suppressed_; }
  uint32_t ignoredInCooldown() const { return ignored_; }
  uint32_t cooldownRemainingMs(uint32_t now) const;
  // Time left before the alert goes out, or before the follow-up is given up on; 0 when neither.
  uint32_t waitRemainingMs(uint32_t now) const;

private:
  static bool reached(uint32_t now, uint32_t t) { return int32_t(now - t) >= 0; }
  uint32_t followDeadline() const { return eventAt_ + (sawProcessing_ ? RecordWaitMs : NoProcessingWaitMs); }

  uint32_t cooldownMs_ = 10UL * 60 * 1000;
  uint32_t jitterMaxMs_ = 2UL * 1000;
  Phase phase_ = Phase::Idle;
  Block lastBlocked_ = Block::None;
  bool baselineSet_ = false;
  bool sawProcessing_ = false;
  bool followPending_ = false;
  uint32_t seen_ = 0;
  uint32_t eventAt_ = 0, sendAt_ = 0, cooldownUntil_ = 0;
  uint32_t eventsSeen_ = 0, sent_ = 0, followups_ = 0, suppressed_ = 0, ignored_ = 0;
};

}  // namespace seismic
