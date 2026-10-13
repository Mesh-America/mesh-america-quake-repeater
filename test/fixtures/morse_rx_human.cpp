#include <helpers/MorseRx.h>
#include <algorithm>
#include <cassert>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <string>
#include <vector>

struct Segment { bool keyed; uint32_t duration; };
enum class Style { Standard, Jitter, Slowing, Speeding, Mixed, Farnsworth, WideFarnsworth };

static uint32_t scaled(double millis) { return std::max(1U, uint32_t(std::lround(millis))); }

static std::vector<Segment> waveform(const char* text, uint32_t nominal, Style style) {
  constexpr double dot_jitter[] = {.85, 1.10, .95, 1.15, 1.0};
  constexpr double dash_ratio[] = {2.5, 3.1, 3.5, 2.8, 3.2};
  constexpr double intra_jitter[] = {.80, 1.10, 1.20, .95};
  constexpr double letter_jitter[] = {2.8, 3.2, 3.5, 3.0};
  constexpr double word_jitter[] = {6.5, 7.0, 8.0};
  std::vector<Segment> result;
  unsigned marks = 0, letters = 0, words = 0;
  const size_t size = strlen(text);
  for (size_t index = 0; index < size; ++index) {
    if (text[index] == ' ') continue;
    const double progress = double(index) / double(size - 1);
    double unit = nominal;
    if (style == Style::Slowing || style == Style::Mixed) unit *= 1.0 + .20 * progress;
    if (style == Style::Speeding) unit *= 1.0 - .20 * progress;
    const bool jitter = style == Style::Jitter || style == Style::Mixed;
    const uint8_t code = mesh::MorseTx::codeFor(text[index]);
    assert(code);
    const uint8_t count = mesh::MorseTx::symbolCount(code);
    for (uint8_t bit = count; bit; --bit) {
      const bool dash = ((code >> (bit - 1)) & 1) != 0;
      const double mark = dash ? (jitter ? dash_ratio[marks % 5] : 3.0)
                               : (jitter ? dot_jitter[marks % 5] : 1.0);
      result.push_back({true, scaled(unit * mark)});
      ++marks;
      if (bit > 1) result.push_back({false, scaled(unit * (jitter ? intra_jitter[marks % 4] : 1.0))});
    }
    const bool word = index + 1 < size && text[index + 1] == ' ';
    const double spacing = style == Style::Farnsworth ? 1.5 : style == Style::WideFarnsworth ? 2.0 : 1.0;
    const double gap = word ? (jitter ? word_jitter[words++ % 3] : 7.0)
                            : (jitter ? letter_jitter[letters++ % 4] : 3.0);
    result.push_back({false, scaled(unit * gap * spacing)});
  }
  return result;
}

static std::string run(uint8_t wpm, Style style, uint32_t cadence, uint16_t& learned) {
  constexpr const char* text = "CQ DE TEST 73 SOS";
  mesh::MorseRx decoder;
  assert(decoder.start(wpm, mesh::MorseRx::MaxDurationMillis, 0) == mesh::MorseRxResult::Started);
  const auto segments = waveform(text, mesh::MorseTx::unitMillis(wpm), style);
  uint32_t elapsed = 0;
  for (; elapsed < 600; elapsed += cadence) decoder.sample(-120.0f, elapsed);
  size_t position = 0;
  uint32_t end = elapsed + segments[0].duration;
  while (position < segments.size()) {
    while (elapsed >= end && ++position < segments.size()) end += segments[position].duration;
    if (position == segments.size()) break;
    decoder.sample(segments[position].keyed ? -60.0f : -120.0f, elapsed);
    elapsed += cadence;
  }
  const uint32_t finish = elapsed + mesh::MorseTx::unitMillis(wpm) * 8U;
  for (; elapsed < finish; elapsed += cadence) decoder.sample(-120.0f, elapsed);
  assert(decoder.active() && !decoder.truncated());
  decoder.stop(elapsed);
  learned = decoder.unitMillis();
  return decoder.text();
}

int main() {
  const struct { const char* name; Style style; } styles[] = {
    {"standard", Style::Standard}, {"jitter", Style::Jitter},
    {"slowing", Style::Slowing}, {"speeding", Style::Speeding},
    {"mixed", Style::Mixed}, {"farnsworth_1_5", Style::Farnsworth},
    {"farnsworth_2_0", Style::WideFarnsworth}
  };
  unsigned failures = 0;
  for (uint8_t wpm : {5, 10, 15, 20, 25, 30, 40}) {
    for (uint32_t cadence : {1U, 2U}) {
      for (const auto& style : styles) {
        uint16_t learned = 0;
        const auto actual = run(wpm, style.style, cadence, learned);
        // The final quiet word gap intentionally leaves one trailing space.
        // Compare every captured byte; do not normalize extra spaces or noise.
        const bool exact = actual == "CQ DE TEST 73 SOS ";
        printf("%u\t%u\t%s\t%u\t%s\t%s\n", wpm, cadence, style.name, learned,
               exact ? "PASS" : "FAIL", actual.c_str());
#ifdef REQUIRE_HUMAN_PASS
        if (!exact) ++failures;
#endif
      }
    }
  }
  return failures ? 1 : 0;
}
