#include "ClockFloor.h"

#include <stdio.h>
#include <string.h>

namespace clockfloor {

namespace {

constexpr uint8_t kMagic0 = 'C', kMagic1 = 'F', kVersion = 1;

uint32_t crc32(const uint8_t* data, size_t length) {
  uint32_t crc = 0xFFFFFFFFUL;
  for (size_t i = 0; i < length; ++i) {
    crc ^= data[i];
    for (int bit = 0; bit < 8; ++bit) crc = (crc >> 1) ^ ((crc & 1) ? 0xEDB88320UL : 0);
  }
  return ~crc;
}

void put32(uint8_t* p, uint32_t v) {
  p[0] = uint8_t(v);
  p[1] = uint8_t(v >> 8);
  p[2] = uint8_t(v >> 16);
  p[3] = uint8_t(v >> 24);
}
uint32_t get32(const uint8_t* p) {
  return uint32_t(p[0]) | (uint32_t(p[1]) << 8) | (uint32_t(p[2]) << 16) | (uint32_t(p[3]) << 24);
}

}  // namespace

uint16_t clampInterval(unsigned minutes) {
  if (minutes < kMinIntervalMin) return kMinIntervalMin;
  if (minutes > kMaxIntervalMin) return kMaxIntervalMin;
  return uint16_t(minutes);
}

void encode(const Record& record, uint8_t out[kRecordSize]) {
  memset(out, 0, kRecordSize);
  out[0] = kMagic0;
  out[1] = kMagic1;
  out[2] = kVersion;
  out[3] = record.enabled ? 1 : 0;
  out[4] = uint8_t(record.intervalMin);
  out[5] = uint8_t(record.intervalMin >> 8);
  put32(&out[6], record.renewedAt);
  put32(&out[12], crc32(out, 12));
}

bool decode(const uint8_t* data, size_t length, Record& out) {
  if (data == nullptr || length != kRecordSize) return false;
  if (data[0] != kMagic0 || data[1] != kMagic1 || data[2] != kVersion) return false;
  if (get32(&data[12]) != crc32(data, 12)) return false;
  const unsigned interval = unsigned(data[4]) | (unsigned(data[5]) << 8);
  if (interval < kMinIntervalMin || interval > kMaxIntervalMin) return false;
  out.enabled = (data[3] & 1) != 0;
  out.intervalMin = uint16_t(interval);
  out.renewedAt = get32(&data[6]);
  return true;
}

uint32_t restoreTime(uint32_t clockNow, const Record& saved) {
  if (!saved.enabled) return 0;
  const uint32_t renewed = saved.renewedAt;
  if (renewed < kMinTime || renewed > kMaxTime) return 0;
  // Already at or past the saved time, give or take: the clock survived. Leave it.
  if (uint64_t(clockNow) + kToleranceSec >= renewed) return 0;
  return renewed + uint32_t(saved.intervalMin) * 60UL + kSlackSec;
}

bool Keeper::update(uint32_t now, uint32_t uptimeSec, Record& toWrite) {
  if (!record_.enabled) return false;
  if (now < kMinTime || now > kMaxTime) return false;  // not a time worth saving

  const uint32_t interval = uint32_t(record_.intervalMin) * 60UL;
  const uint32_t gap = forced_ ? kForcedGapSec : kMinGapSec;
  // Never write more often than the gap, whether the last attempt worked or not.
  if (attempted_ && uint32_t(uptimeSec - lastAttemptUptime_) < gap) return false;

  const uint32_t renewed = record_.renewedAt;
  const bool never = renewed == 0;
  // A forced save only helps when the saved time is stale. If it was renewed in the last few minutes
  // the restart is already as accurate as it will get, and repeating the request (an admin sending
  // `reboot` again and again) must not turn into repeated flash writes.
  if (forced_ && !never && renewed <= now && uint32_t(now - renewed) < kMinGapSec) forced_ = false;
  const bool renewalDue = !never && uint64_t(now) >= uint64_t(renewed) + interval;  // also true right after a restore
  const bool movedBack = !never && renewed > uint64_t(now) + interval;              // the clock was set earlier
  if (!(never || renewalDue || movedBack || forced_)) return false;

  toWrite = record_;
  toWrite.renewedAt = now;
  forced_ = false;
  attempted_ = true;
  lastAttemptUptime_ = uptimeSec;
  return true;
}

void Keeper::saved(const Record& written) {
  record_ = written;
  ++writes_;
}

void formatUtc(char* out, size_t capacity, uint32_t epochSeconds) {
  if (out == nullptr || capacity == 0) return;
  // Civil date from days since 1970-01-01 (Howard Hinnant's algorithm).
  const int64_t days = int64_t(epochSeconds / 86400UL);
  const uint32_t secondsOfDay = epochSeconds % 86400UL;
  const int64_t z = days + 719468;
  const int64_t era = (z >= 0 ? z : z - 146096) / 146097;
  const unsigned doe = unsigned(z - era * 146097);
  const unsigned yoe = (doe - doe / 1460 + doe / 36524 - doe / 146096) / 365;
  const int64_t y = int64_t(yoe) + era * 400;
  const unsigned doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
  const unsigned mp = (5 * doy + 2) / 153;
  const unsigned d = doy - (153 * mp + 2) / 5 + 1;
  const unsigned m = mp < 10 ? mp + 3 : mp - 9;
  const int64_t year = y + (m <= 2 ? 1 : 0);
  snprintf(out, capacity, "%04d-%02u-%02u %02u:%02u", int(year), m, d, secondsOfDay / 3600, (secondsOfDay % 3600) / 60);
}

}  // namespace clockfloor
