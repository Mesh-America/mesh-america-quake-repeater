#include <helpers/MorseRx.h>
#include <cassert>
#include <cstdio>
#include <cstring>
#include <initializer_list>

#if !defined(MESH_MORSE_HIL) || !MESH_MORSE_HIL
#error "This end-to-end fixture requires the actual HIL transmitter"
#endif

int main() {
  const struct { const char* name; mesh::MorseHilTimingConfig timing; } profiles[] = {
    {"normal", {0, 0, 0, 1}},
    {"bench_preset", {15, 10, 25, 12345}},
    {"jitter20", {20, 0, 0, 1}},
    {"speeding20", {0, -20, 0, 2}},
    {"slowing20", {0, 20, 0, 2}},
    {"spacing50", {0, 0, 50, 3}},
    {"mixed_speeding", {15, -10, 25, 6789}},
    {"tight_human", {20, -10, 0, 6789}}
  };
  constexpr const char* message = "CQ DE TEST 73 SOS";
  // Rates above production's 60 WPM ceiling are explicit lab-only stress
  // vectors, including the fractional 5 ms phase quantization at 240 WPM.
  for (uint8_t wpm : {5, 10, 15, 20, 25, 30, 40, 60, 120, 200, 240}) {
    for (uint32_t cadence : {1U, 2U}) {
      for (const auto& profile : profiles) {
        assert(mesh::setMorseHilTiming(profile.timing));
        mesh::MorseTx sender;
        mesh::MorseRx receiver;
        assert(receiver.start(wpm, mesh::MorseRx::MaxDurationMillis, 0) == mesh::MorseRxResult::Started);
        uint32_t now = 0;
        for (; now < 600; ++now) if (now % cadence == 0) receiver.sample(-120, now);
        assert(sender.start(message, wpm, now) == mesh::MorseTxResult::Started);
        while (sender.active()) {
          const auto edge = sender.advance(now);
          if (edge != mesh::MorseTx::Edge::None) sender.edgeApplied(now);
          if (now % cadence == 0) receiver.sample(sender.keyed() ? -60 : -120, now);
          ++now;
        }
        const uint32_t finish = now + mesh::MorseTx::unitMillis(wpm) * 8U;
        for (; now < finish; ++now) if (now % cadence == 0) receiver.sample(-120, now);
        receiver.stop(now);
        const bool exact = strcmp(receiver.text(), "CQ DE TEST 73 SOS ") == 0;
        printf("%u\t%u\t%s\t%s\t%s\n", wpm, cadence, profile.name,
               exact ? "PASS" : "FAIL", receiver.text());
      }
    }
  }
  assert(mesh::setMorseHilTiming({}));
  // The Python contract checks every row byte-for-byte, including the one
  // explicitly unsupported high-speed spacing/sampling combination. Keeping
  // all rows lets it characterize limits without hiding them as feature passes.
  return 0;
}
