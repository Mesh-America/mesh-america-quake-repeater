#pragma once

#include "MorseTx.h"
#include <string.h>

#ifndef MESH_ENABLE_MORSE_RX
// Current integrated STM32WL targets have 256 KiB flash. Keep their complete
// existing feature set and Morse TX; timed capture is an explicit larger-build
// opt-in rather than moving the deployed filesystem boundary.
#if defined(STM32_PLATFORM)
#define MESH_ENABLE_MORSE_RX 0
#else
#define MESH_ENABLE_MORSE_RX 1
#endif
#endif

#if defined(MESH_MORSE_HIL) && MESH_MORSE_HIL \
    && defined(MESH_MORSE_HIL_FAST_OFF_DEBOUNCE) \
    && MESH_MORSE_HIL_FAST_OFF_DEBOUNCE != 0 \
    && MESH_MORSE_HIL_FAST_OFF_DEBOUNCE != 1
#error "HIL Morse fast OFF debounce flag must be 0 or 1"
#endif

namespace mesh {

enum class MorseRxResult : uint8_t {
  Started, Stopped, Busy, Unsupported, InvalidFrequency, Overlap,
  InvalidSpeed, InvalidDuration, Failed
};

struct MorseRxDiagnostics {
  float noise_dbm = NAN, last_dbm = NAN, minimum_dbm = NAN, maximum_dbm = NAN;
  uint32_t samples = 0;
  uint32_t max_sample_gap_ms = 0;
  uint16_t unit_ms = 0;
  uint8_t read_errors = 0;
};

#if defined(MESH_MORSE_HIL) && MESH_MORSE_HIL
struct MorseRssiTraceEntry {
  uint32_t millis;
  int8_t rssi_dbm;
  uint8_t flags; // raw key=1, committed key=2, candidate=4, learning=8
};

// Lab-only sparse envelope diagnostics. Stored independently on admitted heap,
// never as an extra idle BSS buffer. Preserve the latest bounded window.
class MorseRssiTrace {
public:
  static constexpr size_t Capacity = 512;
  void clear() { _length = _next = 0; _total = _last_elapsed = 0; _triggered = _dropped = false; }
  size_t length() const { return _length; }
  uint32_t total() const { return _total; }
  bool truncated() const { return _dropped || _total > Capacity; }
  bool read(size_t offset, MorseRssiTraceEntry& out) const {
    if (offset >= _length) return false;
    size_t index = (_next + Capacity - 1) % Capacity;
    uint32_t elapsed = _last_elapsed;
    for (size_t position = _length - 1; position > offset; --position) {
      elapsed -= _entries[index].delta_ms;
      index = (index + Capacity - 1) % Capacity;
    }
    out = {elapsed, _entries[index].rssi_dbm, _entries[index].flags};
    return true;
  }
  void sample(float rssi, uint32_t elapsed, uint8_t flags) {
    if (flags & 8) return;
    // Debounced key edges retain the actual decoder transitions. Suppress
    // intermediate debounce samples so a full message fits, but retain large
    // quiet-floor/power changes for AGC/envelope diagnosis.
    if (!_triggered) {
      if (!(flags & 2)) return;
      _triggered = true;
    }
    if (flags & 4) return;
    int16_t value = static_cast<int16_t>(rssi >= 0 ? rssi + 0.5f : rssi - 0.5f);
    if (value < -128) value = -128;
    if (value > 127) value = 127;
    if (_length) {
      const auto& previous = _entries[(_next + Capacity - 1) % Capacity];
      const int16_t delta = value - previous.rssi_dbm;
      if (((flags ^ previous.flags) & 2) == 0 && delta > -6 && delta < 6
          && elapsed - _last_elapsed < 60000U) return;
    }
    // Quiet anchors at sixty seconds bound the stored deltas even in a full
    // five-minute capture. Public reads reconstruct exact 32-bit timestamps.
    uint32_t delta_ms = _length ? elapsed - _last_elapsed : 0;
    if (delta_ms > UINT16_MAX) {
      // A long stalled sampler supplies no measurements for the missing span.
      // Restart the retained window, explicitly marked incomplete, rather
      // than wrapping the delta or inventing intermediate RF measurements.
      _length = _next = 0;
      _dropped = true;
      delta_ms = 0;
    }
    _entries[_next] = {static_cast<uint16_t>(delta_ms), static_cast<int8_t>(value), flags};
    _next = (_next + 1) % Capacity;
    if (_length < Capacity) ++_length;
    ++_total;
    _last_elapsed = elapsed;
  }
private:
  struct StoredEntry { uint16_t delta_ms; int8_t rssi_dbm; uint8_t flags; };
  static_assert(sizeof(StoredEntry) == 4, "HIL stored entries must remain four bytes");
  StoredEntry _entries[Capacity];
  uint16_t _length = 0, _next = 0;
  uint32_t _last_elapsed = 0, _total = 0;
  bool _triggered = false, _dropped = false;
};
#endif

// RSSI envelope decoding, not an RF demodulator or an artificial narrow
// filter. The real receiver supplies its instantaneous power measurements.
// Quiet arming samples establish the noise floor before the sender keys up.
class MorseRx {
public:
#if defined(MESH_MORSE_HIL) && MESH_MORSE_HIL && defined(MESH_MORSE_HIL_SAMPLE_INTERVAL_MS)
  static constexpr uint32_t SampleIntervalMillis = MESH_MORSE_HIL_SAMPLE_INTERVAL_MS;
  static_assert(MESH_MORSE_HIL_SAMPLE_INTERVAL_MS >= 1
      && MESH_MORSE_HIL_SAMPLE_INTERVAL_MS <= 10,
      "HIL Morse RSSI sample interval must be 1..10 milliseconds");
#else
  static constexpr uint32_t SampleIntervalMillis = 2;
#endif
#if defined(MESH_MORSE_HIL) && MESH_MORSE_HIL && defined(MESH_MORSE_HIL_RX_BITRATE_KBPS)
  static constexpr float ReceiverBitRateKbps = MESH_MORSE_HIL_RX_BITRATE_KBPS;
#else
  static constexpr float ReceiverBitRateKbps = 1.2f;
#endif
  static_assert(ReceiverBitRateKbps >= 0.6f && ReceiverBitRateKbps <= 300.0f,
                "HIL GFSK receiver clock must remain in the supported range");
  static constexpr uint32_t MinDurationMillis = 1000UL;
  static constexpr uint32_t MaxDurationMillis = 300000UL;
  static constexpr uint32_t NoiseLearningMillis = 500UL;
  static constexpr size_t CaptureCapacity = 4096;
  // A startup estimator heuristic, not a guaranteed radio/AGC floor shift.
  static constexpr float StartupFloorUncertaintyDb = 30.0f;
#if defined(MESH_MORSE_HIL) && MESH_MORSE_HIL
  void setTrace(MorseRssiTrace* trace) { _trace = trace; }
#endif

  static MorseRxResult validate(uint8_t wpm, uint32_t duration_ms) {
    if (!MorseTx::unitMillis(wpm)) return MorseRxResult::InvalidSpeed;
    if (duration_ms < MinDurationMillis || duration_ms > MaxDurationMillis)
      return MorseRxResult::InvalidDuration;
    return MorseRxResult::Started;
  }

  MorseRxResult start(uint8_t wpm, uint32_t duration_ms, uint32_t now) {
    const auto result = validate(wpm, duration_ms);
    if (result != MorseRxResult::Started) return result;
    clear();
    _started = _last_edge = now;
    _until = now + duration_ms;
    _nominal_unit = MorseTx::unitMillis(wpm);
    _unit_q5 = uint16_t(uint32_t(_nominal_unit) * UnitScale);
    _noise = _signal = 0;
    _samples = 0;
    _last_sample_at = now;
    _max_sample_gap_ms = 0;
    _last_rssi = _minimum_rssi = _maximum_rssi = NAN;
    _have_noise = _candidate_valid = _keyed = _floor_settled = false;
    _active = true;
#if defined(MESH_MORSE_HIL) && MESH_MORSE_HIL
    if (_trace) _trace->clear();
#endif
    return MorseRxResult::Started;
  }

  bool active() const { return _active; }
  bool keyed() const { return _active && _keyed; }
  bool learning(uint32_t now) const {
    return _active && static_cast<uint32_t>(now - _started) < NoiseLearningMillis;
  }
  uint32_t remainingMillis(uint32_t now) const {
    if (!_active) return 0;
    const int32_t left = static_cast<int32_t>(_until - now);
    return left > 0 ? static_cast<uint32_t>(left) : 0;
  }
  const char* text() const { return _capture; }
  size_t length() const { return _length; }
  bool truncated() const { return _truncated; }
  float noiseDbm() const { return _have_noise ? _noise : -200.0f; }
  uint16_t unitMillis() const { return uint16_t((_unit_q5 + UnitScale / 2) / UnitScale); }
  void diagnostics(MorseRxDiagnostics& out) const {
    out.noise_dbm = _have_noise ? _noise : NAN;
    out.last_dbm = _last_rssi;
    out.minimum_dbm = _minimum_rssi;
    out.maximum_dbm = _maximum_rssi;
    out.samples = _samples;
    out.max_sample_gap_ms = _max_sample_gap_ms;
    out.unit_ms = unitMillis();
    out.read_errors = 0;
  }

  size_t read(size_t offset, char* out, size_t capacity) const {
    if (!out || !capacity) return 0;
    if (offset >= _length) { out[0] = 0; return 0; }
    size_t count = _length - offset;
    if (count >= capacity) count = capacity - 1;
    memcpy(out, _capture + offset, count);
    out[count] = 0;
    return count;
  }

  void clear() {
    _length = 0;
    _capture[0] = 0;
    _truncated = _bad_pattern = _letter_flushed = _word_flushed = false;
    _code = 1;
    _symbols = 0;
  }

  void stop(uint32_t now) {
    if (!_active) return;
    // A keyed or debounce-pending tail may belong to an unfinished letter.
    // Never manufacture its last dash merely because the capture timed out.
    if (!_keyed && !_candidate_valid) flushLetter();
    _active = false;
    _keyed = _candidate_valid = false;
    _last_edge = now;
  }

  bool service(uint32_t now) {
    if (!_active) return false;
    if (_samples) {
      const uint32_t gap = static_cast<uint32_t>(now - _last_sample_at);
      if (gap > _max_sample_gap_ms) _max_sample_gap_ms = gap;
    }
    if (static_cast<int32_t>(now - _until) >= 0) {
      stop(now);
      return false;
    }
    if (!learning(now) && !_keyed && !_candidate_valid) flushGap(now);
    return _active;
  }

  void sample(float rssi_dbm, uint32_t now) {
    if (!service(now) || !isfinite(rssi_dbm) || rssi_dbm < -180.0f || rssi_dbm > 20.0f) return;
    _last_rssi = rssi_dbm;
    _last_sample_at = now;
    if (!_samples || rssi_dbm < _minimum_rssi) _minimum_rssi = rssi_dbm;
    if (!_samples || rssi_dbm > _maximum_rssi) _maximum_rssi = rssi_dbm;
    ++_samples;
    if (!_have_noise) {
      _have_noise = true;
      _noise = rssi_dbm;
      _signal = rssi_dbm + 12.0f;
    }
    if (learning(now)) {
      _noise += (rssi_dbm - _noise) * 0.05f;
      _signal = _noise + 12.0f;
      return;
    }

    const float span = _signal - _noise;
    float rise = span * 0.5f;
    if (rise < 6.0f) rise = 6.0f;
    float threshold = _noise + rise - (_keyed ? 3.0f : 0.0f);
    // Before the first confirmed OFF, some receivers still report a stale
    // pre-carrier floor. Allow for a provisional floor shift without a hard
    // signal-span discontinuity. This margin is a tested startup heuristic,
    // not a chip guarantee; after a real OFF the ordinary midpoint takes over
    // and tolerates strong within-mark fades without producing extra symbols.
    if (_keyed && !_floor_settled) {
      float provisional_fall = (span - StartupFloorUncertaintyDb) * 0.5f;
      if (provisional_fall < 5.0f) provisional_fall = 5.0f;
      if (threshold < _signal - provisional_fall) threshold = _signal - provisional_fall;
    }
    const bool raw_keyed = rssi_dbm >= threshold;
    if (!_keyed && !raw_keyed && !_candidate_valid) {
      // Drift slowly while quiet; follow a lower floor faster without letting
      // an isolated power spike permanently raise the threshold above CW.
      _noise += (rssi_dbm - _noise) * (rssi_dbm < _noise ? 0.05f : 0.01f);
      // A falling RF envelope may commit OFF before it reaches the final
      // valley. Keep the next rise anchored to the subsequently learned floor,
      // not to a transient shoulder left by the previous strong mark.
      _signal = _noise + 12.0f;
    }
    // Never adapt the mark estimate down toward quiet during OFF debounce:
    // doing so moves its own threshold before the falling edge can commit.
    if (_keyed && raw_keyed && rssi_dbm > _noise + 6.0f)
      _signal += (rssi_dbm - _signal) * 0.1f;

    if (raw_keyed == _keyed) { _candidate_valid = false; traceSample(rssi_dbm, now, raw_keyed); return; }
    if (!_candidate_valid || _candidate != raw_keyed) {
      _candidate = raw_keyed;
      _candidate_at = now;
      _candidate_valid = true;
      traceSample(rssi_dbm, now, raw_keyed);
      return;
    }
    uint16_t debounce = _unit_q5 / (4 * UnitScale);
    uint16_t minimum_debounce = 2;
#if defined(MESH_MORSE_HIL) && MESH_MORSE_HIL \
    && defined(MESH_MORSE_HIL_FAST_OFF_DEBOUNCE) \
    && MESH_MORSE_HIL_FAST_OFF_DEBOUNCE == 1
    // Controlled fast-CW bench experiment: permit a one-ms falling-edge
    // confirmation only for short nominal dots. Keep ON rejection and the
    // ordinary quarter-dot rule intact; production ignores this lab flag.
    if (!raw_keyed && _nominal_unit <= 12) minimum_debounce = 1;
#endif
    if (debounce < minimum_debounce) debounce = minimum_debounce;
    // A brief mark fade is not another symbol. Give OFF a little more time
    // than ON, but retain a ten-ms ceiling so sparse quiet spikes cannot keep
    // a very slow message keyed for an entire quarter-dot (up to 300 ms).
    const uint16_t maximum_debounce = raw_keyed ? 5 : 10;
    if (debounce > maximum_debounce) debounce = maximum_debounce;
    if (static_cast<uint32_t>(now - _candidate_at) < debounce) {
      traceSample(rssi_dbm, now, raw_keyed);
      return;
    }
    const uint32_t edge_at = _candidate_at;
    _candidate_valid = false;
    if (raw_keyed) {
      flushGap(edge_at);
      if (!_active) return;
      _keyed = true;
      // Seed immediately rather than taking a whole fast dot to train an EMA.
      _signal = rssi_dbm;
      _last_edge = edge_at;
      _letter_flushed = _word_flushed = false;
    } else {
      recordMark(static_cast<uint32_t>(edge_at - _last_edge));
      _keyed = false;
      _noise = rssi_dbm;
      _floor_settled = true;
      _signal = _noise + 12.0f; // do not hide the next, weaker mark with an old peak
      _last_edge = edge_at;
    }
    traceSample(rssi_dbm, now, raw_keyed);
  }

private:
  // Keep fractional timing in the existing 16-bit field: a whole-ms 1/8 EMA
  // has a four-ms rounding deadband and cannot adapt at fast Morse speeds.
  // Q5 supports the full 1 WPM, +25% range without adding receiver memory.
  static constexpr uint16_t UnitScale = 32;
  static_assert((1200UL * 5 / 4) * UnitScale <= UINT16_MAX,
                "fractional Morse timing must fit its existing 16-bit field");
  char _capture[CaptureCapacity + 1] = {};
  uint32_t _started = 0, _until = 0, _last_edge = 0, _candidate_at = 0;
  float _noise = 0, _signal = 0;
  float _last_rssi = NAN, _minimum_rssi = NAN, _maximum_rssi = NAN;
  uint32_t _samples = 0;
  uint32_t _last_sample_at = 0, _max_sample_gap_ms = 0;
  uint16_t _length = 0, _unit_q5 = 0, _nominal_unit = 0;
  uint8_t _code = 1, _symbols = 0;
  bool _active = false, _keyed = false, _have_noise = false;
  bool _floor_settled = false;
  bool _candidate = false, _candidate_valid = false;
  bool _bad_pattern = false, _letter_flushed = false, _word_flushed = false, _truncated = false;
#if defined(MESH_MORSE_HIL) && MESH_MORSE_HIL
  MorseRssiTrace* _trace = nullptr; // lifetime belongs to the radio wrapper
#endif

  void traceSample(float rssi, uint32_t now, bool raw_keyed) {
#if defined(MESH_MORSE_HIL) && MESH_MORSE_HIL
    if (_trace) _trace->sample(rssi, static_cast<uint32_t>(now - _started),
        (raw_keyed ? 1 : 0) | (_keyed ? 2 : 0) | (_candidate_valid ? 4 : 0)
        | (learning(now) ? 8 : 0));
#else
    (void)rssi; (void)now; (void)raw_keyed;
#endif
  }

  void append(char c) {
    if (c == ' ' && (!_length || _capture[_length - 1] == ' ')) return;
    if (_length >= CaptureCapacity) { capacityStop(); return; }
    _capture[_length++] = c;
    _capture[_length] = 0;
    if (_length == CaptureCapacity) capacityStop();
  }
  void capacityStop() {
    // Full capture is an explicit early stop, not an invisible rolling/drop
    // buffer. Retain the prefix, expose truncation, and resume the mesh radio.
    _truncated = true;
    _active = _keyed = _candidate_valid = false;
  }
  void flushLetter() {
    if (!_symbols && !_bad_pattern) return;
    char decoded = '?';
    if (!_bad_pattern) {
      for (char c = '!'; c <= 'Z'; ++c) {
        const uint8_t code = MorseTx::codeFor(c);
        if (code && code == _code) { decoded = c; break; }
      }
      // The printable loop ends at Z; '_' is also an ITU punctuation code.
      if (MorseTx::codeFor('_') == _code) decoded = '_';
    }
    append(decoded);
    _code = 1;
    _symbols = 0;
    _bad_pattern = false;
    _letter_flushed = true;
  }
  void flushGap(uint32_t now) {
    const uint32_t gap = static_cast<uint32_t>(now - _last_edge);
    // RSSI fall-edge delay lengthens marks while shortening the following
    // gaps. Never feed that fixed delay back into an even longer gap threshold.
    // Faster-peer adaptation still lowers the threshold; slower peers have
    // longer physical gaps and remain distinguishable at the nominal timing.
    const uint16_t nominal_q5 = uint16_t(uint32_t(_nominal_unit) * UnitScale);
    const uint16_t gap_unit_q5 = _unit_q5 < nominal_q5 ? _unit_q5 : nominal_q5;
    // Ordinary +/-20% gap jitter still separates an intra-letter gap (<=1.2
    // units) from a letter gap (>=2.4), and letters (<=3.6) from words (>=5.6).
    // Keep some margin at 2.25/5.5 units rather than merging shortened gaps.
    // This is not automatic Farnsworth-spacing or unknown-speed acquisition.
    if (gap * 4UL * UnitScale >= uint32_t(gap_unit_q5) * 9UL && !_letter_flushed) flushLetter();
    if (gap * 2UL * UnitScale >= uint32_t(gap_unit_q5) * 11UL && !_word_flushed && _letter_flushed) {
      append(' ');
      _word_flushed = true;
    }
  }
  void recordMark(uint32_t duration_ms) {
    const uint32_t duration_q5 = duration_ms * UnitScale;
    if (duration_q5 * 3UL < _unit_q5) return; // sub-third-dot glitches
    if (duration_q5 > uint32_t(_unit_q5) * 6UL || _symbols >= 7) {
      _bad_pattern = true;
      return;
    }
    const bool dash = duration_q5 >= uint32_t(_unit_q5) * 2UL;
    _code = uint8_t((_code << 1) | (dash ? 1 : 0));
    ++_symbols;
    uint32_t observed = dash ? (duration_ms + 1) / 3 : duration_ms;
    const uint32_t lower = uint32_t(_nominal_unit) * 3 / 4;
    const uint32_t upper = uint32_t(_nominal_unit) * 5 / 4;
    if (observed < lower) observed = lower;
    if (observed > upper) observed = upper;
    _unit_q5 = uint16_t((uint32_t(_unit_q5) * 7 + observed * UnitScale + 4) / 8);
  }
};

} // namespace mesh
