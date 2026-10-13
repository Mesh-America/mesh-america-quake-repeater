#pragma once

#include <stddef.h>
#include <stdint.h>
#include <math.h>

namespace mesh {

#ifndef MESH_MORSE_MAX_WPM
#define MESH_MORSE_MAX_WPM 60
#endif
static_assert(MESH_MORSE_MAX_WPM >= 1 && MESH_MORSE_MAX_WPM <= 255,
              "Morse WPM must fit the command/API byte");

enum class MorseTxResult : uint8_t {
  Started, Stopped, Busy, Unsupported, InvalidFrequency, Overlap,
  InvalidText, InvalidSpeed, TooLong, Failed
};

// A keyed, unmodulated carrier has no LoRa receive-bandwidth setting. Its
// occupied spectrum is determined by the keying envelope and oscillator.
// Keep its centre at least 10 kHz beyond both configured LoRa passbands;
// this prevents tuple overlap, not interference with unrelated RF users.
inline bool morseFrequencyOverlaps(float carrier_mhz, float profile_mhz,
                                   float bandwidth_khz) {
  return isfinite(carrier_mhz) && isfinite(profile_mhz) && isfinite(bandwidth_khz)
      && profile_mhz > 0 && bandwidth_khz > 0
      // float MHz tuples quantize by about 61 Hz in the 900 MHz band. Keep a
      // conservative 100 Hz tolerance so a nominal guard-edge value cannot
      // round outward and accidentally pass the non-overlap check.
      && fabsf(carrier_mhz - profile_mhz) * 1000.0f <= bandwidth_khz * 0.5f + 10.1f;
}

// Portable, bounded ITU Morse encoder/timer. The leading 1 in each code is a
// length sentinel; subsequent bits are dot=0/dash=1, most significant first.
// No heap, delay(), or pre-expanded sequence of hundreds of marks is needed.
class MorseTx {
public:
  static constexpr float DefaultFrequencyMHz = 902.100f;
  static constexpr uint8_t DefaultWpm = 25;
  static constexpr uint8_t MinWpm = 1;
  static constexpr uint8_t MaxWpm = MESH_MORSE_MAX_WPM;
  static constexpr size_t MaxTextLength = 80;
  static constexpr uint32_t MaxDurationMillis = 180000UL;
  enum class Edge : uint8_t { None, KeyDown, KeyUp, Complete, Expired };

  static uint8_t codeFor(char character) {
    if (character >= 'a' && character <= 'z') character -= 'a' - 'A';
    static const uint8_t letters[] = {
      5,24,26,12,2,18,14,16,4,23,13,20,7,6,15,22,29,10,8,3,9,17,11,25,27,28
    };
    static const uint8_t digits[] = {63,47,39,35,33,32,48,56,60,62};
    if (character >= 'A' && character <= 'Z') return letters[character - 'A'];
    if (character >= '0' && character <= '9') return digits[character - '0'];
    switch (character) {
      case '.': return 85;  case ',': return 115; case '?': return 76;
      case '\'': return 94; case '!': return 107; case '/': return 50;
      case '(': return 54;  case ')': return 109; case '&': return 40;
      case ':': return 120; case ';': return 106; case '=': return 49;
      case '+': return 42;  case '-': return 97;  case '_': return 77;
      case '"': return 82;  case '$': return 137; case '@': return 90;
      default: return 0;
    }
  }

  static uint8_t symbolCount(uint8_t code) {
    uint8_t count = 0;
    while (code > 1) { code >>= 1; ++count; }
    return count;
  }

  static uint16_t unitMillis(uint8_t wpm) {
    return wpm >= MinWpm && wpm <= MaxWpm ? (1200U + wpm / 2) / wpm : 0;
  }

  static MorseTxResult validate(const char* text, uint8_t wpm,
                                uint32_t* duration_ms = nullptr) {
    const uint16_t unit = unitMillis(wpm);
    if (!unit) return MorseTxResult::InvalidSpeed;
    if (!text) return MorseTxResult::InvalidText;
    uint32_t units = 0;
    bool have_character = false, have_space = false;
    size_t length = 0;
    for (; length <= MaxTextLength && text[length]; ++length) {
      const char character = text[length];
      if (character == ' ') { if (have_character) have_space = true; continue; }
      const uint8_t code = codeFor(character);
      if (!code) return MorseTxResult::InvalidText;
      if (have_character) units += have_space ? 7 : 3;
      const uint8_t count = symbolCount(code);
      for (uint8_t bit = count; bit; --bit) {
        units += (code & (1U << (bit - 1))) ? 3 : 1;
        if (bit > 1) ++units;
      }
      have_character = true;
      have_space = false;
    }
    if (length > MaxTextLength) return MorseTxResult::TooLong;
    if (!have_character) return MorseTxResult::InvalidText;
    const uint32_t duration = units * unit;
    if (duration > MaxDurationMillis) return MorseTxResult::TooLong;
    if (duration_ms) *duration_ms = duration;
    return MorseTxResult::Started;
  }

  MorseTxResult start(const char* text, uint8_t wpm, uint32_t now) {
    uint32_t duration;
    const auto result = validate(text, wpm, &duration);
    if (result != MorseTxResult::Started) return result;
    size_t output = 0;
    bool space = false;
    // Canonicalize case and collapse/trim spaces only after full validation.
    for (size_t input = 0; text[input]; ++input) {
      char c = text[input];
      if (c == ' ') { if (output) space = true; continue; }
      if (space) _text[output++] = ' ';
      space = false;
      if (c >= 'a' && c <= 'z') c -= 'a' - 'A';
      _text[output++] = c;
    }
    _text[output] = 0;
    _unit = unitMillis(wpm);
    _character = _symbol = 0;
    _code = codeFor(_text[0]);
    _count = symbolCount(_code);
    _active = _keyed = true;
    _remaining = duration;
    _phase_ms = markUnits() * _unit;
    _next = now + _phase_ms;
    _hard_end = now + MaxDurationMillis;
    return MorseTxResult::Started;
  }

  void stop() { _active = _keyed = false; _remaining = 0; }
  bool active() const { return _active; }
  bool keyed() const { return _active && _keyed; }
  uint32_t hardDeadline() const { return _hard_end; }
  uint32_t nextDeadline() const { return _next; }
  // Hardware mode commands can take milliseconds. Start the entire next
  // mark/gap after that command completes, rather than shortening Morse at
  // the faster WPM values by the SPI/oscillator transition time.
  void edgeApplied(uint32_t now) { if (_active) _next = now + _phase_ms; }

  uint32_t remainingMillis(uint32_t now) const {
    if (!_active) return 0;
    const int32_t phase_left = static_cast<int32_t>(_next - now);
    const uint32_t other = _remaining > _phase_ms ? _remaining - _phase_ms : 0;
    return other + (phase_left > 0 ? static_cast<uint32_t>(phase_left) : 0);
  }

  Edge advance(uint32_t now) {
    if (!_active) return Edge::None;
    if (static_cast<int32_t>(now - _hard_end) >= 0) {
      stop();
      return Edge::Expired;
    }
    if (static_cast<int32_t>(now - _next) < 0) return Edge::None;
    _remaining = _remaining > _phase_ms ? _remaining - _phase_ms : 0;
    if (_keyed) {
      _keyed = false;
      uint8_t gap = 1;
      if (++_symbol >= _count) {
        if (!_text[++_character]) { stop(); return Edge::Complete; }
        gap = 3;
        if (_text[_character] == ' ') { ++_character; gap = 7; }
        _symbol = 0;
        _code = codeFor(_text[_character]);
        _count = symbolCount(_code);
      }
      _phase_ms = gap * _unit;
      // Rebase on actual service time. Never key a burst of missed edges.
      _next = now + _phase_ms;
      return Edge::KeyUp;
    }
    _keyed = true;
    _phase_ms = markUnits() * _unit;
    _next = now + _phase_ms;
    return Edge::KeyDown;
  }

private:
  char _text[MaxTextLength + 1] = {};
  uint32_t _next = 0, _hard_end = 0, _remaining = 0;
  uint16_t _unit = 0, _phase_ms = 0;
  uint8_t _character = 0, _symbol = 0, _code = 0, _count = 0;
  bool _active = false, _keyed = false;
  uint8_t markUnits() const { return (_code & (1U << (_count - 1 - _symbol))) ? 3 : 1; }
};

} // namespace mesh
