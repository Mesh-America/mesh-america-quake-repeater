#include <helpers/MorseRx.h>
#include <cassert>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <initializer_list>
#include <vector>

static_assert(sizeof(mesh::MorseRx) == 4168, "gap fix must not add receiver memory");
struct Segment { bool keyed; uint32_t duration; };
static uint32_t rounded(double value) { return uint32_t(std::lround(value)); }

static std::vector<Segment> envelope(const char* text, uint32_t nominal) {
  // A bounded human-envelope model, not a replay of the sparse physical trace:
  // 10% faster pace, 15% shortened gap phases, and an RF OFF-edge delay of
  // roughly one tenth of a dot. Marks use +11.1% phase jitter at that pace,
  // staying nominal before the same delay lengthens their measured envelope.
  // This puts real letter/word quiet below 2.25/5.5 but above the 2/5 midpoints.
  const double peer = nominal * 0.9;
  const uint32_t bias = rounded(nominal * 0.1);
  std::vector<Segment> result;
  const size_t length = std::strlen(text);
  for (size_t position = 0; position < length; ++position) {
    if (text[position] == ' ') continue;
    const uint8_t code = mesh::MorseTx::codeFor(text[position]);
    assert(code);
    const uint8_t symbols = mesh::MorseTx::symbolCount(code);
    for (uint8_t bit = symbols; bit; --bit) {
      const bool dash = ((code >> (bit - 1)) & 1) != 0;
      result.push_back({true, nominal * (dash ? 3U : 1U) + bias});
      if (bit > 1) result.push_back({false, nominal - bias});
    }
    const bool word = position + 1 == length || text[position + 1] == ' ';
    result.push_back({false, rounded(peer * (word ? 7.0 : 3.0) * .85) - bias});
  }
  return result;
}

int main() {
  constexpr const char* text = "VW MN DOG";
  unsigned mismatches = 0;
  for (uint8_t wpm : {25, 60, 120}) {
    for (uint32_t cadence : {1U, 2U}) {
      mesh::MorseRx receiver;
      assert(receiver.start(wpm, 300000, 0) == mesh::MorseRxResult::Started);
      uint32_t now = 0;
      for (; now < 600; now += cadence) receiver.sample(-120, now);
      const auto segments = envelope(text, mesh::MorseTx::unitMillis(wpm));
      size_t position = 0;
      uint32_t end = now + segments[0].duration;
      while (position < segments.size()) {
        while (now >= end && ++position < segments.size()) end += segments[position].duration;
        if (position == segments.size()) break;
        receiver.sample(segments[position].keyed ? -40 : -120, now);
        now += cadence;
      }
      const uint32_t finish = now + mesh::MorseTx::unitMillis(wpm) * 8;
      for (; now < finish; now += cadence) receiver.sample(-120, now);
      receiver.stop(now);
      const bool exact = std::strcmp(receiver.text(), "VW MN DOG ") == 0;
      if (!exact) ++mismatches;
      std::printf("%u\t%u\t%s\t%s\n", wpm, cadence, exact ? "PASS" : "FAIL", receiver.text());
    }
  }
#if REQUIRE_TIGHT_PASS
  assert(mismatches == 0);
#else
  assert(mismatches == 6); // the former boundaries fail every tight waveform
#endif
}
