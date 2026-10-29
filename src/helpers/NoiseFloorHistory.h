#pragma once

#include <math.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

namespace mesh {

// Boot-local, UTC-aligned noise history. Only completed quarter-hours are
// published; each needs a fresh estimate in all three five-minute subslots.
class NoiseFloorHistory {
public:
  static constexpr uint8_t PROFILE_COUNT = 2;
  static constexpr uint8_t SAMPLE_BITS = 5;
  static constexpr uint8_t MISSING = 31;
  static constexpr uint8_t MAX = 30;
  static constexpr uint32_t SAMPLE_INTERVAL_SECONDS = 900;
  static constexpr uint32_t READ_INTERVAL_SECONDS = 300;
  static constexpr uint16_t SAMPLES_PER_DAY = 96;
  static constexpr uint8_t RETENTION_DAYS = 8;
  static constexpr uint16_t RETENTION_SAMPLES = SAMPLES_PER_DAY * RETENTION_DAYS;
  static constexpr size_t BYTES_PER_PROFILE = RETENTION_SAMPLES * SAMPLE_BITS / 8U;
  static constexpr uint8_t CLI_PAGE_SAMPLES = 176;
  static constexpr uint8_t PAGE_COUNT = 5;
  static constexpr size_t PAGE_HEADER_SIZE = 7;
  static constexpr uint8_t PAGE_PAYLOAD_TYPE_V1 = 0x15;
  static constexpr uint8_t RADIO2_PAGE_PAYLOAD_TYPE_V1 = 0x16;
  static constexpr size_t BINARY_HEADER_SIZE = 19;
  static constexpr size_t BINARY_SOURCE_ID_SIZE = 8;
  static constexpr uint8_t BINARY_MAX_SAMPLES = 255;
  static constexpr size_t BINARY_PAYLOAD_SIZE = 184;

  NoiseFloorHistory() { clear(); }

  void clear() {
    memset(_samples, 0xFF, sizeof(_samples));
    memset(_pending, 0, sizeof(_pending));
    _next = _count = 0;
    _bucket = 0;
    _has_bucket = false;
  }

  // Call with current RTC time before handing over newly published estimates.
  // A clock reset discards ambiguous timestamps. Forward gaps are bounded by
  // retention, so an RTC correction cannot cause an unbounded catch-up loop.
  void advance(uint32_t epoch_seconds) {
    const uint32_t bucket = epoch_seconds / SAMPLE_INTERVAL_SECONDS;
    if (!_has_bucket) {
      _bucket = bucket;
      _has_bucket = true;
      return;
    }
    if (bucket == _bucket) return;
    if (bucket < _bucket || bucket - _bucket > RETENTION_SAMPLES) {
      clear();
      _bucket = bucket;
      _has_bucket = true;
      return;
    }
    const uint32_t elapsed = bucket - _bucket;
    append(aggregate(_pending[0]), aggregate(_pending[1]));
    for (uint32_t i = 1; i < elapsed; ++i) append(MISSING, MISSING);
    for (uint8_t profile = 0; profile < PROFILE_COUNT; ++profile) {
      _pending[profile].mask = 0;
    }
    _bucket = bucket;
  }

  // Publication IDs are the radio's millis() timestamp, not the polling time.
  // Repeated reads of one calibration must never fill multiple subslots.
  bool observe(uint8_t profile, uint32_t measured_epoch, float dbm,
               uint32_t publication_id) {
    if (profile >= PROFILE_COUNT || !isfinite(dbm) || dbm < -200.0f
        || dbm > 0.0f || !_has_bucket
        || measured_epoch / SAMPLE_INTERVAL_SECONDS != _bucket) return false;
    Pending& pending = _pending[profile];
    if (pending.has_publication) {
      if (publication_id == pending.publication_id
          || measured_epoch < pending.measured_epoch) return false;
      // Within one RTC second, preserve publication ordering across millis wrap.
      if (measured_epoch == pending.measured_epoch
          && (uint32_t)(publication_id - pending.publication_id) >= 0x80000000UL) {
        return false;
      }
    }
    pending.has_publication = true;
    pending.publication_id = publication_id;
    pending.measured_epoch = measured_epoch;
    const uint8_t slot = (uint8_t)((measured_epoch % SAMPLE_INTERVAL_SECONDS)
                                 / READ_INTERVAL_SECONDS);
    pending.values[slot] = dbm;
    pending.mask |= (uint8_t)(1U << slot);
    return true;
  }

  // Retuning/disabling a profile cannot combine estimates from two channels.
  // Keep the publication watermark and completed history for deduplication.
  void invalidateProfile(uint8_t profile) {
    if (profile < PROFILE_COUNT) _pending[profile].mask = 0;
  }

  uint16_t sampleCount(uint8_t profile) const {
    return profile < PROFILE_COUNT ? _count : 0;
  }

  bool hasValidSamples(uint8_t profile) const {
    if (profile >= PROFILE_COUNT) return false;
    for (uint16_t offset = 0; offset < _count; ++offset) {
      if (sampleCodeAtOffset(profile, offset) != MISSING) return true;
    }
    return false;
  }

  static constexpr size_t storageBytes() { return PROFILE_COUNT * BYTES_PER_PROFILE; }

  uint8_t sampleCodeAtOffset(uint8_t profile, uint16_t offset) const {
    if (profile >= PROFILE_COUNT || offset >= _count) return MISSING;
    const uint16_t index = (uint16_t)((_next + RETENTION_SAMPLES - 1U - offset)
                                    % RETENTION_SAMPLES);
    const size_t first_bit = (size_t)index * SAMPLE_BITS;
    uint8_t code = 0;
    for (uint8_t bit = 0; bit < SAMPLE_BITS; ++bit) {
      const size_t absolute = first_bit + bit;
      code = (uint8_t)((code << 1U)
          | ((_samples[profile][absolute / 8U] >> (7U - absolute % 8U)) & 1U));
    }
    return code;
  }

  // Page 1 contains the newest 176 completed positions, oldest first. The
  // oldest page is shortened to actual retained history, never padded preboot.
  // Correlated CLI replies already have a prompt prefix and use bare Base64.
  bool formatPageReply(uint8_t profile, const char* args, char* reply,
                       size_t reply_size = 160, bool include_prompt = true) const {
    if (reply == NULL || reply_size == 0) return false;
    reply[0] = 0;
    if (profile >= PROFILE_COUNT) return error(reply, reply_size, "Err - invalid radio profile");
    unsigned page = 1;
    const char* cursor = args == NULL ? "" : args;
    while (*cursor == ' ') ++cursor;
    if (*cursor != 0) {
      page = 0;
      while (*cursor >= '0' && *cursor <= '9' && page <= PAGE_COUNT) {
        page = page * 10U + (unsigned)(*cursor++ - '0');
      }
      while (*cursor == ' ') ++cursor;
      if (*cursor != 0 || page < 1 || page > PAGE_COUNT) {
        return error(reply, reply_size, "Err - noise history page must be 1-5");
      }
    }
    const uint16_t newest_offset = (uint16_t)((page - 1U) * CLI_PAGE_SAMPLES);
    if (_count == 0 || newest_offset >= _count) {
      return error(reply, reply_size, "Err - noise history page is empty");
    }
    uint16_t count = (uint16_t)(_count - newest_offset);
    if (count > CLI_PAGE_SAMPLES) count = CLI_PAGE_SAMPLES;
    const uint16_t oldest_offset = (uint16_t)(newest_offset + count - 1U);
    uint8_t payload[PAGE_HEADER_SIZE + (CLI_PAGE_SAMPLES * SAMPLE_BITS + 7U) / 8U];
    const size_t length = PAGE_HEADER_SIZE + (count * SAMPLE_BITS + 7U) / 8U;
    memset(payload, 0, length);
    payload[0] = profile == 0 ? PAGE_PAYLOAD_TYPE_V1 : RADIO2_PAGE_PAYLOAD_TYPE_V1;
    putUint32LE(payload + 1, startEpoch(oldest_offset));
    payload[5] = (uint8_t)(SAMPLE_INTERVAL_SECONDS / 60U);
    payload[6] = (uint8_t)count;
    pack(profile, oldest_offset, count, payload + PAGE_HEADER_SIZE);
    return base64Reply(payload, length, reply, reply_size, include_prompt);
  }

  // Reuses the telemetry RAW_CUSTOM envelope: magic, source ID, epoch,
  // uint16 interval in minutes, uint8 count; five-bit samples follow it.
  size_t formatBinarySnapshot(uint8_t profile,
      const uint8_t source_id[BINARY_SOURCE_ID_SIZE], uint8_t* dest,
      size_t dest_size) const {
    if (profile >= PROFILE_COUNT || source_id == NULL || dest == NULL
        || dest_size <= BINARY_HEADER_SIZE || _count == 0) return 0;
    size_t available = dest_size - BINARY_HEADER_SIZE;
    if (available > BINARY_PAYLOAD_SIZE - BINARY_HEADER_SIZE) {
      available = BINARY_PAYLOAD_SIZE - BINARY_HEADER_SIZE;
    }
    uint16_t count = (uint16_t)(available * 8U / SAMPLE_BITS);
    if (count > BINARY_MAX_SAMPLES) count = BINARY_MAX_SAMPLES;
    if (count > _count) count = _count;
    if (count == 0) return 0;
    const size_t length = BINARY_HEADER_SIZE + (count * SAMPLE_BITS + 7U) / 8U;
    memset(dest, 0, length);
    memcpy(dest, profile == 0 ? "N1B1" : "N2B1", 4);
    memcpy(dest + 4, source_id, BINARY_SOURCE_ID_SIZE);
    putUint32LE(dest + 12, startEpoch((uint16_t)(count - 1U)));
    dest[16] = (uint8_t)(SAMPLE_INTERVAL_SECONDS / 60U);
    dest[17] = 0;
    dest[18] = (uint8_t)count;
    pack(profile, (uint16_t)(count - 1U), count, dest + BINARY_HEADER_SIZE);
    return length;
  }

private:
  struct Pending {
    float values[3];
    uint32_t publication_id;
    uint32_t measured_epoch;
    uint8_t mask;
    bool has_publication;
  };
  uint8_t _samples[PROFILE_COUNT][BYTES_PER_PROFILE];
  Pending _pending[PROFILE_COUNT];
  uint16_t _next;
  uint16_t _count;
  uint32_t _bucket;
  bool _has_bucket;

  static float decode(uint8_t code) {
    return code == 0 ? -120.0f : code == 1 ? -119.0f : -122.0f + 2.0f * code;
  }

  // direction=-1 rounds minima down, +1 rounds maxima up, 0 is nearest.
  static uint8_t encode(float value, int direction) {
    if (value <= -120.0f) return 0;
    if (value > -64.0f) return MAX;
    uint8_t lower = 0;
    for (uint8_t upper = 1; upper <= 29; ++upper) {
      const float high = decode(upper);
      if (value > high) { lower = upper; continue; }
      if (value == high || direction > 0) return upper;
      if (direction < 0) return lower;
      return value - decode(lower) < high - value ? lower : upper;
    }
    return 29;
  }

  static uint8_t aggregate(const Pending& pending) {
    if (pending.mask != 7) return MISSING;
    float low = pending.values[0], high = low;
    float sum = 0;
    for (uint8_t i = 0; i < 3; ++i) {
      const float value = pending.values[i];
      if (value < low) low = value;
      if (value > high) high = value;
      sum += value;
    }
    if (low <= -100.0f) return encode(low, -1);
    if (high >= -80.0f) return encode(high, 1);
    return encode(sum / 3.0f, 0);
  }

  void append(uint8_t first, uint8_t second) {
    const uint8_t codes[PROFILE_COUNT] = {first, second};
    for (uint8_t profile = 0; profile < PROFILE_COUNT; ++profile) {
      const size_t first_bit = (size_t)_next * SAMPLE_BITS;
      for (uint8_t bit = 0; bit < SAMPLE_BITS; ++bit) {
        const size_t absolute = first_bit + bit;
        const uint8_t mask = (uint8_t)(1U << (7U - absolute % 8U));
        if (codes[profile] & (1U << (SAMPLE_BITS - 1U - bit))) {
          _samples[profile][absolute / 8U] |= mask;
        } else {
          _samples[profile][absolute / 8U] &= (uint8_t)~mask;
        }
      }
    }
    _next = (uint16_t)((_next + 1U) % RETENTION_SAMPLES);
    if (_count < RETENTION_SAMPLES) ++_count;
  }

  uint32_t startEpoch(uint16_t offset) const {
    return (_bucket - 1U - offset) * SAMPLE_INTERVAL_SECONDS;
  }

  void pack(uint8_t profile, uint16_t oldest_offset, uint16_t count,
            uint8_t* dest) const {
    for (uint16_t index = 0; index < count; ++index) {
      const uint8_t code = sampleCodeAtOffset(profile, (uint16_t)(oldest_offset - index));
      for (uint8_t bit = 0; bit < SAMPLE_BITS; ++bit) {
        const size_t absolute = (size_t)index * SAMPLE_BITS + bit;
        if (code & (1U << (SAMPLE_BITS - 1U - bit))) {
          dest[absolute / 8U] |= (uint8_t)(1U << (7U - absolute % 8U));
        }
      }
    }
  }

  static void putUint32LE(uint8_t* dest, uint32_t value) {
    for (uint8_t i = 0; i < 4; ++i) dest[i] = (uint8_t)(value >> (8U * i));
  }

  static bool error(char* reply, size_t size, const char* text) {
    if (reply != NULL && size != 0) snprintf(reply, size, "%s", text);
    return false;
  }

  static bool base64Reply(const uint8_t* payload, size_t length, char* reply,
                          size_t size, bool include_prompt) {
    static const char alphabet[] =
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    const size_t encoded = ((length + 2U) / 3U) * 4U;
    const size_t prefix = include_prompt ? 2U : 0U;
    if (size < encoded + prefix + 1U) {
      return error(reply, size, "Err - telemetry reply buffer too small");
    }
    if (include_prompt) {
      reply[0] = '>';
      reply[1] = ' ';
    }
    size_t output = prefix;
    for (size_t i = 0; i < length; i += 3U) {
      const size_t remaining = length - i;
      const uint32_t value = ((uint32_t)payload[i] << 16U)
          | (remaining > 1 ? (uint32_t)payload[i + 1] << 8U : 0)
          | (remaining > 2 ? payload[i + 2] : 0);
      reply[output++] = alphabet[(value >> 18U) & 63U];
      reply[output++] = alphabet[(value >> 12U) & 63U];
      reply[output++] = remaining > 1 ? alphabet[(value >> 6U) & 63U] : '=';
      reply[output++] = remaining > 2 ? alphabet[value & 63U] : '=';
    }
    reply[output] = 0;
    return true;
  }
};

}  // namespace mesh
