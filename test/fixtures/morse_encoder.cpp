#include <helpers/MorseTx.h>
#include <cassert>
#include <cstring>
#include <initializer_list>
#include <string>
#include <vector>

using mesh::MorseTx;
using Result = mesh::MorseTxResult;
using Edge = MorseTx::Edge;

static std::string unpack(uint8_t code) {
  std::string result;
  const unsigned count = MorseTx::symbolCount(code);
  for (unsigned bit = count; bit; --bit)
    result += (code & (1U << (bit - 1))) ? '-' : '.';
  return result;
}

static void alphabet() {
  const char* letters[] = {".-", "-...", "-.-.", "-..", ".", "..-.", "--.", "....",
    "..", ".---", "-.-", ".-..", "--", "-.", "---", ".--.", "--.-", ".-.",
    "...", "-", "..-", "...-", ".--", "-..-", "-.--", "--.."};
  const char* digits[] = {"-----", ".----", "..---", "...--", "....-", ".....",
    "-....", "--...", "---..", "----."};
  for (int i = 0; i < 26; ++i) {
    assert(unpack(MorseTx::codeFor('A' + i)) == letters[i]);
    assert(MorseTx::codeFor('a' + i) == MorseTx::codeFor('A' + i));
  }
  for (int i = 0; i < 10; ++i) assert(unpack(MorseTx::codeFor('0' + i)) == digits[i]);
  const char punctuation[] = ".,?'!/()&:;=+-_\"$@";
  const char* patterns[] = {".-.-.-", "--..--", "..--..", ".----.", "-.-.--", "-..-.",
    "-.--.", "-.--.-", ".-...", "---...", "-.-.-.", "-...-", ".-.-.", "-....-",
    "..--.-", ".-..-.", "...-..-", ".--.-."};
  static_assert(sizeof(punctuation) - 1 == sizeof(patterns) / sizeof(*patterns), "test table");
  for (size_t i = 0; i < sizeof(punctuation) - 1; ++i)
    assert(unpack(MorseTx::codeFor(punctuation[i])) == patterns[i]);
  for (unsigned i = 0; i < 256; ++i) {
    const char c = static_cast<char>(i);
    const bool known = (c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z')
        || (c >= '0' && c <= '9') || (c && std::strchr(punctuation, c));
    assert(bool(MorseTx::codeFor(c)) == known);
  }
}

static void timing(const char* message, const std::vector<uint32_t>& phases,
                   uint32_t start) {
  MorseTx timer;
  uint32_t duration = 0;
  assert(MorseTx::validate(message, 25, &duration) == Result::Started);
  uint32_t total = 0;
  for (auto phase : phases) total += phase;
  assert(duration == total);
  assert(timer.start(message, 25, start) == Result::Started);
  assert(timer.active() && timer.keyed() && timer.remainingMillis(start) == total);
  uint32_t now = start;
  for (size_t phase = 0; phase < phases.size(); ++phase) {
    assert(timer.nextDeadline() == now + phases[phase]);
    assert(timer.advance(now + phases[phase] - 1) == Edge::None);
    assert(timer.keyed() == (phase % 2 == 0));
    now += phases[phase];
    const auto edge = timer.advance(now);
    if (phase + 1 == phases.size()) {
      assert(edge == Edge::Complete && !timer.active() && !timer.keyed());
    } else {
      assert(edge == (phase % 2 ? Edge::KeyDown : Edge::KeyUp));
      assert(timer.remainingMillis(now) == total - uint32_t(now - start));
    }
  }
  assert(timer.remainingMillis(now) == 0 && timer.advance(now) == Edge::None);
}

static void validation_and_limits() {
  assert(MorseTx::DefaultWpm == 25 && MorseTx::DefaultFrequencyMHz == 902.100f);
  assert(MorseTx::unitMillis(1) == 1200 && MorseTx::unitMillis(25) == 48);
  assert(MorseTx::unitMillis(60) == 20);
  for (unsigned speed = 1; speed <= MorseTx::MaxWpm; ++speed) {
    uint32_t duration = 0;
    assert(MorseTx::validate("T", speed, &duration) == Result::Started);
    assert(duration == 3U * ((1200U + speed / 2U) / speed));
  }
  for (uint8_t speed : {uint8_t(0), uint8_t(MorseTx::MaxWpm + 1)})
    assert(MorseTx::validate("E", speed) == Result::InvalidSpeed);
  for (const char* invalid : {"", "     ", "#", "line\nline", "tab\t", "\x80", "\xff"})
    assert(MorseTx::validate(invalid, 25) == Result::InvalidText);
  assert(MorseTx::validate(nullptr, 25) == Result::InvalidText);
  assert(MorseTx::validate(std::string(80, 'E').c_str(), 25) == Result::Started);
  assert(MorseTx::validate(std::string(81, 'E').c_str(), 25) == Result::TooLong);
  uint32_t duration = 0;
  assert(MorseTx::validate(std::string(38, 'E').c_str(), 1, &duration) == Result::Started);
  assert(duration == 178800);
  assert(MorseTx::validate(std::string(39, 'E').c_str(), 1) == Result::TooLong);
  assert(MorseTx::validate(std::string(80, 'T').c_str(), 1) == Result::TooLong);
  // A caller does not receive a duration for a rejected transmission.
  duration = 0x12345678;
  assert(MorseTx::validate("#", 25, &duration) == Result::InvalidText);
  assert(duration == 0x12345678);
  MorseTx timer;
  for (const char* invalid : {"", "#", "\xff"}) {
    assert(timer.start(invalid, 25, 0) == Result::InvalidText);
    assert(!timer.active() && !timer.keyed());
  }
}

static void slow_service_and_cancel() {
  MorseTx timer;
  assert(timer.start("SOS", 25, 100) == Result::Started);
  assert(timer.advance(10000) == Edge::KeyUp); // no missed-edge catch-up burst
  assert(!timer.keyed() && timer.nextDeadline() == 10048);
  for (int i = 0; i < 100; ++i) assert(timer.advance(10000) == Edge::None);
  assert(timer.advance(10048) == Edge::KeyDown);
  timer.stop();
  assert(!timer.active() && !timer.keyed() && !timer.remainingMillis(0));
  assert(timer.advance(20000) == Edge::None);
  assert(timer.start("T", 1, 0xfffffff0) == Result::Started);
  assert(timer.hardDeadline() == uint32_t(0xfffffff0 + 180000));
  assert(timer.advance(timer.hardDeadline() - 1) == Edge::Complete);
  assert(timer.start("SOS", 25, 0xfffffff0) == Result::Started);
  assert(timer.advance(timer.hardDeadline()) == Edge::Expired);
  assert(!timer.active() && !timer.keyed() && timer.advance(0) == Edge::None);
}

static void frequency_guard() {
  assert(!mesh::morseFrequencyOverlaps(902.100f, 910.525f, 500));
  assert(mesh::morseFrequencyOverlaps(902.100f, 902.100f, 500));
  assert(mesh::morseFrequencyOverlaps(902.100f, 902.350f, 500));
  assert(!mesh::morseFrequencyOverlaps(902.100f, 902.375f, 500));
  assert(!mesh::morseFrequencyOverlaps(902.100f, 0, 500));
  assert(!mesh::morseFrequencyOverlaps(902.100f, 902.100f, 0));
  assert(!mesh::morseFrequencyOverlaps(NAN, 902.100f, 500));
  assert(!mesh::morseFrequencyOverlaps(INFINITY, 902.100f, 500));
}

int main() {
  alphabet();
  validation_and_limits();
  timing("SOS", {48,48,48,48,48,144,144,48,144,48,144,144,48,48,48,48,48}, 100);
  timing("   a    B  ", {48,48,144,336,144,48,48,48,48,48,48}, 0xfffffff0);
  slow_service_and_cancel();
  frequency_guard();
}
