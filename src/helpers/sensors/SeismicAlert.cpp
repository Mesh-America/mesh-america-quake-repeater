#include "SeismicAlert.h"

#include <math.h>
#include <stdio.h>
#include <string.h>

namespace seismic {

bool locationIsSet(double lat, double lon) {
  if (!isfinite(lat) || !isfinite(lon)) return false;
  if (lat < -90.0 || lat > 90.0 || lon < -180.0 || lon > 180.0) return false;
  return !(fabs(lat) < 1e-6 && fabs(lon) < 1e-6);
}

Hashtag normalizeHashtag(const char* input, char* out, size_t cap) {
  if (input == nullptr || cap < 2) return Hashtag::Empty;
  while (*input == ' ') ++input;
  if (*input == '#') ++input;
  const size_t length = strlen(input);
  if (length == 0) return Hashtag::Empty;
  if (length + 2 > cap) return Hashtag::TooLong;  // '#' and the terminator
  out[0] = '#';
  for (size_t i = 0; i < length; ++i) {
    char c = input[i];
    if (c >= 'A' && c <= 'Z') c = char(c - 'A' + 'a');
    const bool ok = (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == '-';
    if (!ok) return Hashtag::BadCharacter;
    out[i + 1] = c;
  }
  out[length + 1] = '\0';
  return Hashtag::Ok;
}

namespace {
// "47.61" / "-122.33": two decimals (about a kilometre) without relying on floating-point printf.
void coordinate(char* out, size_t cap, double value) {
  long hundredths = lround(value * 100.0);
  const bool negative = hundredths < 0;
  if (negative) hundredths = -hundredths;
  snprintf(out, cap, "%s%ld.%02ld", negative ? "-" : "", hundredths / 100, hundredths % 100);
}
}  // namespace

size_t formatMessage(char* out, size_t outCap, size_t budget, double lat, double lon, bool haveValues,
                     uint16_t siRaw, uint16_t pgaRaw, bool test) {
  if (out == nullptr || outCap == 0) return 0;
  char la[16], lo[16];
  coordinate(la, sizeof(la), lat);
  coordinate(lo, sizeof(lo), lon);
  const char* mark = test ? "TEST: " : "";
  static const char* const disclaimer = "This does not necessarily indicate an earthquake.";
  const unsigned si = siRaw;
  const unsigned gal = (unsigned(pgaRaw) + 5u) / 10u;  // tenths of gal, rounded to whole gal

  // Longest to shortest. The disclaimer is in every form; detail goes first.
  char text[200];
  for (int form = 0; form < 3; ++form) {
    if (form < 2 && (!haveValues || test)) continue;  // no values, or a test: only the short form
    int n;
    if (form == 0) {
      n = snprintf(text, sizeof(text), "%sShaking detected near %s,%s. Strength %u.%u cm/s, peak acceleration %u gal. %s",
                   mark, la, lo, si / 10, si % 10, gal, disclaimer);
    } else if (form == 1) {
      n = snprintf(text, sizeof(text), "%sShaking detected near %s,%s. Strength %u.%u cm/s, peak %u gal. %s", mark,
                   la, lo, si / 10, si % 10, gal, disclaimer);
    } else {
      n = snprintf(text, sizeof(text), "%sShaking detected near %s,%s. %s", mark, la, lo, disclaimer);
    }
    if (n > 0 && size_t(n) <= budget && size_t(n) < outCap) {
      memcpy(out, text, size_t(n) + 1);
      return size_t(n);
    }
  }
  out[0] = '\0';
  return 0;
}

size_t formatFollowup(char* out, size_t outCap, size_t budget, uint16_t siRaw, uint16_t pgaRaw) {
  if (out == nullptr || outCap == 0) return 0;
  static const char* const disclaimer = "This does not necessarily indicate an earthquake.";
  const unsigned si = siRaw;
  const unsigned gal = (unsigned(pgaRaw) + 5u) / 10u;
  char text[200];
  for (int form = 0; form < 2; ++form) {
    int n;
    if (form == 0) {
      n = snprintf(text, sizeof(text), "Update: strength %u.%u cm/s, peak acceleration %u gal. %s", si / 10, si % 10, gal,
                   disclaimer);
    } else {
      n = snprintf(text, sizeof(text), "Update: strength %u.%u cm/s, peak %u gal. %s", si / 10, si % 10, gal, disclaimer);
    }
    if (n > 0 && size_t(n) <= budget && size_t(n) < outCap) {
      memcpy(out, text, size_t(n) + 1);
      return size_t(n);
    }
  }
  out[0] = '\0';
  return 0;
}

const char* blockText(Block block) {
  switch (block) {
    case Block::None: return "none";
    case Block::NoSensor: return "no earthquake sensor";
    case Block::SensorFault: return "sensor reported a fault";
    case Block::NoChannel: return "earthquake.channel is not set";
    case Block::NoLocation: return "location is not set (set lat and lon)";
  }
  return "";
}

uint32_t Policy::cooldownRemainingMs(uint32_t now) const {
  if (phase_ != Phase::Cooldown || reached(now, cooldownUntil_)) return 0;
  return cooldownUntil_ - now;
}

uint32_t Policy::waitRemainingMs(uint32_t now) const {
  uint32_t deadline;
  if (phase_ == Phase::Delaying) deadline = sendAt_;
  else if (followPending_) deadline = followDeadline();
  else return 0;
  return reached(now, deadline) ? 0 : deadline - now;
}

bool Policy::update(uint32_t now, const Input& in, const Gates& gates, uint32_t jitterMs, Send& out) {
  if (!in.sensorPresent) {
    // Nothing to watch. Start over when a sensor appears, so a report that was already waiting in
    // it is treated as history and not as a new event.
    baselineSet_ = false;
    followPending_ = false;
    if (phase_ != Phase::Cooldown) phase_ = Phase::Idle;
    return false;
  }
  if (!baselineSet_) {
    seen_ = in.shakingCount;
    baselineSet_ = true;
    return false;
  }
  if (phase_ == Phase::Cooldown && reached(now, cooldownUntil_)) phase_ = Phase::Idle;

  if (in.shakingCount != seen_) {
    seen_ = in.shakingCount;
    ++eventsSeen_;
    if (phase_ == Phase::Idle) {
      phase_ = Phase::Delaying;
      eventAt_ = now;
      sendAt_ = now + (jitterMs > jitterMaxMs_ ? jitterMaxMs_ : jitterMs);
      sawProcessing_ = in.processing;
      followPending_ = false;  // an earlier event's follow-up is not wanted any more
    } else if (phase_ == Phase::Cooldown) {
      ++ignored_;
    }
    // Reports during the delay belong to the same shaking and change nothing.
  }

  if (in.processing && (phase_ == Phase::Delaying || followPending_)) sawProcessing_ = true;

  if (phase_ == Phase::Delaying && reached(now, sendAt_)) {
    Block block = Block::None;
    if (in.sensorFaulted) block = Block::SensorFault;
    else if (!gates.channelSet) block = Block::NoChannel;
    else if (!gates.locationSet) block = Block::NoLocation;
    lastBlocked_ = block;
    if (block != Block::None) {
      ++suppressed_;
      phase_ = Phase::Idle;  // no cooldown: the next event may send once the setting is fixed
      return false;
    }
    out.kind = Kind::Alert;
    out.siRaw = out.pgaRaw = 0;
    ++sent_;
    phase_ = Phase::Cooldown;
    cooldownUntil_ = now + cooldownMs_;
    followPending_ = true;
    return true;
  }

  if (followPending_) {
    // A record read before the sensor finished is the previous event's, so numbers are only trusted
    // once measuring has been seen to end.
    if (!in.processing && in.recordValid && sawProcessing_) {
      followPending_ = false;
      ++followups_;
      out.kind = Kind::Followup;
      out.siRaw = in.siRaw;
      out.pgaRaw = in.pgaRaw;
      return true;
    }
    if (reached(now, followDeadline())) followPending_ = false;
  }
  return false;
}

}  // namespace seismic
