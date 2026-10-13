#include <helpers/MorseRx.h>
#include <helpers/MorseTx.h>
#include <cassert>
#include <cstring>
#include <initializer_list>
#include <string>
#include <cstdio>

using mesh::MorseRx;

struct Receiver {
  MorseRx decoder;
  uint32_t now;
  uint16_t unit;
  explicit Receiver(uint8_t wpm = 25, uint32_t start = 100, uint32_t duration = 300000)
      : now(start), unit(mesh::MorseTx::unitMillis(wpm)) {
    assert(decoder.start(wpm, duration, now) == mesh::MorseRxResult::Started);
  }
  void level(float rssi, uint32_t duration) {
    for (uint32_t elapsed = 0; elapsed < duration; ++elapsed)
      decoder.sample(rssi, now++);
  }
  void quiet(uint32_t duration) { level(-110, duration); }
  void warmup() { quiet(MorseRx::NoiseLearningMillis + 20); }
  void pattern(const char* marks) {
    for (size_t i = 0; marks[i]; ++i) {
      level(-80, uint32_t(unit) * (marks[i] == '-' ? 3 : 1));
      if (marks[i + 1]) quiet(unit);
    }
  }
  void letter_gap() { quiet(uint32_t(unit) * 3); }
  void word_gap() { quiet(uint32_t(unit) * 7); }
  std::string text() const {
    std::string captured(decoder.text(), decoder.length());
    while (!captured.empty() && captured.back() == ' ') captured.pop_back();
    return captured;
  }
};

static void speed_and_gaps() {
  for (uint8_t speed : {1, 5, 12, 25, 40, 60}) {
    Receiver rx(speed); rx.warmup();
    rx.pattern("..."); rx.letter_gap();
    rx.pattern("---"); rx.letter_gap();
    rx.pattern("..."); rx.word_gap();
    assert(rx.text() == "SOS" && !rx.decoder.keyed() && rx.decoder.active());
    rx.pattern("."); rx.word_gap();
    assert(rx.text() == "SOS E");
    rx.decoder.stop(rx.now);
    assert(!rx.decoder.active() && rx.text() == "SOS E");
    const auto snapshot = rx.text();
    rx.level(-80, 10000); rx.quiet(10000);
    assert(rx.text() == snapshot); // retained transcript is not a live idle decoder
    rx.decoder.clear(); assert(rx.decoder.length() == 0 && !rx.decoder.truncated());
  }
}

static void alphabet_and_punctuation() {
  const char* marks[] = {".-", "-...", "-.-.", "-..", ".", "..-.", "--.", "....",
    "..", ".---", "-.-", ".-..", "--", "-.", "---", ".--.", "--.-", ".-.",
    "...", "-", "..-", "...-", ".--", "-..-", "-.--", "--..",
    "-----", ".----", "..---", "...--", "....-", ".....", "-....", "--...", "---..", "----.",
    ".-.-.-", "--..--", "..--..", ".----.", "-.-.--", "-..-.", "-.--.", "-.--.-", ".-...",
    "---...", "-.-.-.", "-...-", ".-.-.", "-....-", "..--.-", ".-..-.", "...-..-", ".--.-."};
  const char expected[] = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.,?'!/()&:;=+-_\"$@";
  static_assert(sizeof(expected) - 1 == sizeof(marks) / sizeof(*marks), "test table");
  Receiver rx(25); rx.warmup();
  for (const char* pattern : marks) { rx.pattern(pattern); rx.letter_gap(); }
  rx.word_gap();
  assert(rx.text() == expected);
}

static void falling_edge_lag_does_not_merge_letters() {
  for (unsigned lag : {4, 8, 12}) {
    Receiver rx(25); rx.warmup();
    const char* text="MORSE TEST 25";
    for (size_t letter=0; text[letter]; ++letter) {
      if (text[letter]==' ') continue;
      const auto code=mesh::MorseTx::codeFor(text[letter]);
      for (uint8_t bit=mesh::MorseTx::symbolCount(code); bit; --bit) {
        const unsigned units=code & (1U << (bit-1)) ? 3 : 1;
        // A narrow RSSI filter holds the falling envelope high for a fixed
        // delay, lengthening marks while shortening their following gap.
        rx.level(-80, units*rx.unit+lag);
        const unsigned gap=bit>1 ? 1 : (text[letter+1]==' ' || !text[letter+1] ? 7 : 3);
        rx.quiet(gap*rx.unit-lag);
      }
    }
    rx.decoder.stop(rx.now);
    assert(rx.text()==text);
  }
}

static void noise_and_keying_envelope() {
  Receiver rx; rx.warmup();
  for (unsigned i = 0; i < 10000; ++i) {
    // Low floor jitter plus isolated <2ms RF spikes cannot produce letters.
    const float signal = i % 317 == 0 ? -70 : -110 + int(i % 3) - 1;
    rx.decoder.sample(signal, rx.now++);
  }
  rx.word_gap(); assert(rx.decoder.length() == 0);
  // A slow PA rise/fall and one-millisecond dips must remain one mark.
  for (int dot = 0; dot < 3; ++dot) {
    rx.level(-108, 1); rx.level(-103, 1); rx.level(-96, 1);
    for (unsigned i = 0; i < rx.unit - 6U; ++i)
      rx.decoder.sample(i == 15 ? -110 : -80, rx.now++);
    rx.level(-96, 1); rx.level(-103, 1); rx.level(-108, 1);
    if (dot < 2) rx.quiet(rx.unit);
  }
  rx.word_gap(); assert(rx.text() == "S");
  Receiver silence; silence.warmup(); silence.quiet(20000);
  silence.decoder.stop(silence.now); assert(silence.decoder.length() == 0);
  for (unsigned duration : {10, 48 * 12}) {
    Receiver bad; bad.warmup(); bad.level(-80, duration); bad.word_gap();
    bad.decoder.stop(bad.now);
    assert(bad.text() == (duration == 10 ? "" : "?")); // never guess a valid dot/dash
  }
  Receiver diagnostic; diagnostic.warmup();
  mesh::MorseRxDiagnostics stats;
  diagnostic.decoder.diagnostics(stats);
  assert(stats.samples == MorseRx::NoiseLearningMillis + 20 && stats.noise_dbm == -110);
  diagnostic.pattern("."); diagnostic.word_gap(); diagnostic.decoder.stop(diagnostic.now);
  diagnostic.decoder.diagnostics(stats);
  assert(stats.minimum_dbm == -110 && stats.maximum_dbm == -80 && stats.last_dbm == -110);
  assert(stats.unit_ms == 48 && stats.read_errors == 0);
  const auto samples = stats.samples;
  diagnostic.level(NAN, 100); diagnostic.decoder.diagnostics(stats);
  assert(stats.samples == samples); // retained statistics do not accrue after capture ends
  for(uint32_t started : {100U,0xfffffff0U}) {
    Receiver gap(25,started); gap.warmup();
    gap.decoder.diagnostics(stats); assert(stats.max_sample_gap_ms==1);
    const uint32_t last_valid=gap.now-1;
    const auto count=stats.samples;
    gap.now+=200; const uint32_t invalid_at=gap.now;
    gap.decoder.sample(NAN,gap.now++);
    gap.decoder.diagnostics(stats);
    assert(stats.samples==count && stats.max_sample_gap_ms==uint32_t(invalid_at-last_valid));
    gap.now+=20; const uint32_t resumed=gap.now;
    gap.decoder.sample(-110,gap.now++); gap.decoder.diagnostics(stats);
    assert(stats.samples==count+1 && stats.max_sample_gap_ms==uint32_t(resumed-last_valid));
    gap.quiet(20); gap.decoder.diagnostics(stats);
    assert(stats.max_sample_gap_ms==uint32_t(resumed-last_valid));
  }
}

static void stop_and_expiry() {
  {
    Receiver rx; rx.warmup(); rx.pattern("."); rx.quiet(14);
    rx.decoder.stop(rx.now); assert(rx.text() == "E");
  }
  {
    Receiver rx; rx.warmup(); rx.pattern("."); rx.quiet(9);
    rx.decoder.stop(rx.now); assert(rx.decoder.length()==0); // OFF debounce is still incomplete
  }
  {
    Receiver rx; rx.warmup(); rx.pattern("."); rx.quiet(rx.unit);
    rx.level(-80, rx.unit / 2); // stopped in the middle of a multi-mark character
    rx.decoder.stop(rx.now); assert(rx.decoder.length() == 0 && !rx.decoder.keyed());
  }
  {
    Receiver rx(25, 0xfffffff0); rx.warmup();
    rx.pattern("..."); rx.letter_gap(); rx.pattern("---"); rx.letter_gap();
    rx.pattern("..."); rx.word_gap(); assert(rx.text() == "SOS");
    rx.now = uint32_t(0xfffffff0 + 300000);
    assert(!rx.decoder.service(rx.now));
    assert(!rx.decoder.active() && !rx.decoder.keyed() && rx.text() == "SOS");
  }
  {
    Receiver rx(25, 100, 1000); rx.warmup(); rx.level(-80, 1000);
    assert(!rx.decoder.service(rx.now) && !rx.decoder.active());
    assert(rx.decoder.length() == 0); // timeout cannot guess an unfinished held carrier
  }
  for (uint8_t speed : {uint8_t(0), uint8_t(mesh::MorseTx::MaxWpm + 1)}) {
    MorseRx invalid;
    assert(invalid.start(speed, 1000, 0) == mesh::MorseRxResult::InvalidSpeed);
    assert(!invalid.active());
  }
  for (uint32_t duration : {0U, 999U, 300001U, 0xffffffffU}) {
    MorseRx invalid;
    assert(invalid.start(25, duration, 0) == mesh::MorseRxResult::InvalidDuration);
    assert(!invalid.active());
  }
}

static void bounded_capture_and_restart() {
  Receiver rx(60); rx.warmup();
  for (size_t character = 0; character < MorseRx::CaptureCapacity + 100; ++character) {
    // Slightly fast dots remain within the bounded timing adaptation; 55ms
    // gaps are full letters even before that adaptation settles. This fills
    // 4096 bytes inside the hard five-minute session without a lab WPM override.
    rx.level(-80, 15); rx.quiet(55);
  }
  assert(rx.decoder.truncated() && rx.decoder.length() == MorseRx::CaptureCapacity);
  assert(!rx.decoder.active() && !rx.decoder.keyed());
  assert(rx.decoder.text()[rx.decoder.length()] == 0);
  for (size_t i = 0; i < rx.decoder.length(); ++i) assert(rx.decoder.text()[i] == 'E');
  const auto before = rx.text();
  rx.decoder.stop(rx.now);
  assert(rx.text() == before && rx.decoder.truncated());
  std::string reconstructed;
  size_t offset = 0;
  while (offset < rx.decoder.length()) {
    char page[23];
    const size_t copied = rx.decoder.read(offset, page, sizeof(page));
    assert(copied > 0 && copied < sizeof(page) && page[copied] == 0);
    reconstructed += page; offset += copied;
  }
  assert(reconstructed == std::string(rx.decoder.text(), rx.decoder.length()));
  for (size_t offset : {rx.decoder.length(), size_t(0xffffffffU)}) {
    char page[2] = {'X', 'Y'};
    assert(rx.decoder.read(offset, page, sizeof(page)) == 0 && page[0] == 0 && page[1] == 'Y');
  }
  char small[2] = {'X', 'Y'};
  assert(rx.decoder.read(0, small, 0) == 0 && small[0] == 'X');
  assert(rx.decoder.read(0, small, 1) == 0 && small[0] == 0 && small[1] == 'Y');
  assert(rx.decoder.read(0, nullptr, 10) == 0);
  assert(rx.decoder.start(0, 1000, rx.now) == mesh::MorseRxResult::InvalidSpeed);
  assert(rx.text() == before && rx.decoder.truncated() && !rx.decoder.active());
  assert(rx.decoder.start(25, 300000, rx.now) == mesh::MorseRxResult::Started);
  assert(rx.decoder.length() == 0 && !rx.decoder.truncated()); // only a new valid session clears
}

int main() {
  speed_and_gaps(); alphabet_and_punctuation(); noise_and_keying_envelope();
  falling_edge_lag_does_not_merge_letters(); stop_and_expiry(); bounded_capture_and_restart();
  std::printf("MorseRx size: %zu bytes\n", sizeof(MorseRx));
}
