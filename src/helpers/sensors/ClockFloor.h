#pragma once

#include <stddef.h>
#include <stdint.h>

// Keeps a repeater's clock from going backwards across a restart.
//
// A repeater with no clock module or GPS loses the time when power is lost or an update is installed,
// and falls back to a built-in date. Peers that already saw a later timestamp from it reject its
// lower ones as replays, so it cannot be logged in to until the clock catches up or is set by hand.
//
// The fix is to remember, in flash, the last time the clock was known to have reached ("renewed at"),
// renewing it every `interval`. The clock can never have run more than one interval past that, so after
// a restart that left the clock behind it, the clock is set to renewed-at plus one interval (plus a
// little slack). That is never behind anything sent before, and at most one interval ahead of real time
// after a quick restart. Renewing rarely keeps flash wear low (the filesystem is small).
//
// Everything here is plain logic with no hardware dependency, so it can be tested on a PC. See
// docs/clock-floor.md.
namespace clockfloor {

// Nothing earlier than the firmware's own starting date (1 March 2026) is a real time.
constexpr uint32_t kMinTime = 1772323200UL;
constexpr uint32_t kMaxTime = kMinTime + 10UL * 365 * 86400;  // ten years on: anything later is garbage

constexpr uint16_t kDefaultIntervalMin = 360;  // 6 hours: 4 writes a day
constexpr uint16_t kMinIntervalMin = 10;
constexpr uint16_t kMaxIntervalMin = 1440;

constexpr uint32_t kToleranceSec = 600;  // a clock this close to the renewed-at time is not "behind" it
constexpr uint32_t kSlackSec = 1200;     // covers a renewal that was late (retry after a failed write)
constexpr uint32_t kMinGapSec = 600;     // between ordinary writes, and the wait before retrying a failed one
constexpr uint32_t kForcedGapSec = 60;   // between forced writes (before a planned restart)

uint16_t clampInterval(unsigned minutes);

// ---- The saved record --------------------------------------------------------------------------

struct Record {
  bool enabled = true;
  uint16_t intervalMin = kDefaultIntervalMin;
  uint32_t renewedAt = 0;  // 0 = nothing saved
};

constexpr size_t kRecordSize = 16;
void encode(const Record& record, uint8_t out[kRecordSize]);
// False for the wrong size, magic, version or checksum, so a damaged file is ignored and never trusted.
bool decode(const uint8_t* data, size_t length, Record& out);

// ---- At boot -----------------------------------------------------------------------------------

// The time the clock should be set to, or 0 to leave it alone. Acts only when the clock is clearly
// behind the saved renewed-at time: a clock that survived the restart (retained RAM after a soft
// reset, a real RTC chip, GPS) is already right and is never touched. A saved time that is not
// plausible is ignored.
uint32_t restoreTime(uint32_t clockNow, const Record& saved);

// ---- While running -----------------------------------------------------------------------------

class Keeper {
public:
  void begin(const Record& saved) { record_ = saved; }
  const Record& record() const { return record_; }

  void setEnabled(bool enabled) { record_.enabled = enabled; }
  void setIntervalMin(unsigned minutes) { record_.intervalMin = clampInterval(minutes); }

  // Ask for a write at the next update, ahead of a planned restart or update. Ignored when the saved
  // time is already less than kMinGapSec old.
  void requestSave() { forced_ = true; }

  // Call regularly. `now` is the clock; `uptimeSec` is a steady count (the clock itself can jump). True
  // when `toWrite` should be saved: report the outcome with saved() or failed().
  bool update(uint32_t now, uint32_t uptimeSec, Record& toWrite);
  void saved(const Record& written);
  void failed() { ++failures_; }

  // For the status line.
  uint32_t writes() const { return writes_; }
  uint32_t failures() const { return failures_; }

private:
  Record record_;
  bool forced_ = false;
  bool attempted_ = false;
  uint32_t lastAttemptUptime_ = 0;
  uint32_t writes_ = 0, failures_ = 0;
};

// "2026-10-04 18:00" (UTC). `capacity` must be at least 17.
void formatUtc(char* out, size_t capacity, uint32_t epochSeconds);

}  // namespace clockfloor
