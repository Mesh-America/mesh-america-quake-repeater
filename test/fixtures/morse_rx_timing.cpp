#include <helpers/MorseTx.h>
#include <cassert>
#include <cstdio>
#include <cstring>
#include <initializer_list>
#include <string>
#include <type_traits>
// Exercise the actual timing methods independently of RF threshold acquisition.
// Production gains no test-only public API or state.
#define private public
#include <helpers/MorseRx.h>
#undef private

using mesh::MorseRx;
static_assert(std::is_same<decltype(MorseRx::_unit_q5), uint16_t>::value,
              "fractional timing must reuse the 16-bit timing field");
#if defined(MESH_MORSE_HIL) && MESH_MORSE_HIL
static_assert(sizeof(MorseRx) == 4168 + sizeof(void*), "HIL decoder size changed");
#else
static_assert(sizeof(MorseRx) == 4168, "production decoder must remain 4168 bytes");
#endif

static void begin(MorseRx& rx, uint8_t wpm, uint32_t now = 100) {
  assert(rx.start(wpm, 300000, now) == mesh::MorseRxResult::Started);
  assert(rx._unit_q5 == uint32_t(rx._nominal_unit) * 32);
  assert(rx.unitMillis() == rx._nominal_unit);
}

static void mark(MorseRx& rx, uint32_t duration) {
  rx.recordMark(duration);
  assert(!rx._bad_pattern && rx._symbols == 1);
  rx.flushLetter();
}

static void fractional_drift_and_integer_negative_control() {
  for (uint8_t wpm : {1, 25, 60, 120, 200, 240}) {
    for (int difference : {-1, 1}) {
      for (bool dash : {false, true}) {
        MorseRx rx;
        begin(rx, wpm);
        const uint16_t nominal = rx._nominal_unit;
        const uint16_t observed = uint16_t(int(nominal) + difference);
        uint16_t old_unit = nominal;
        for (unsigned count = 0; count < 64; ++count) {
          old_unit = uint16_t((uint32_t(old_unit) * 7 + observed + 4) / 8);
          mark(rx, uint32_t(observed) * (dash ? 3 : 1));
        }
        assert(old_unit == nominal); // the former whole-ms update never moves
        assert(rx.unitMillis() == observed);
        const int error = int(rx._unit_q5) - int(observed) * 32;
        assert(error >= -4 && error <= 4);
        mesh::MorseRxDiagnostics stats;
        rx.diagnostics(stats);
        assert(stats.unit_ms == observed); // API still reports rounded ms
      }
    }
  }
}

static void first_ambiguous_and_warmed_borderline_marks() {
  MorseRx first;
  begin(first, 240);
  first.recordMark(10);
  first.flushLetter();
  assert(std::strcmp(first.text(), "T") == 0); // no history can identify this first ambiguous mark

  MorseRx trained;
  begin(trained, 240);
  mark(trained, 6);
  assert(trained._unit_q5 == 164 && trained.unitMillis() == 5); // 5.125 ms, not 5 ms
  trained.clear(); // retain timing, clear only the already captured training E
  trained.recordMark(10);
  trained.flushLetter();
  assert(std::strcmp(trained.text(), "E") == 0);
  assert(trained._unit_q5 == 168); // observed 10 is still clamped to the existing 6-ms upper limit
}

static void unchanged_bounds_and_checked_duration_limits() {
  for (uint8_t wpm : {1, 25, 60, 120, 200, 240}) {
    MorseRx rx;
    begin(rx, wpm);
    const uint16_t nominal = rx._nominal_unit;
    const uint32_t lower = uint32_t(nominal) * 3 / 4;
    const uint32_t upper = uint32_t(nominal) * 5 / 4;
    for (unsigned count = 0; count < 64; ++count) {
      mark(rx, 3 * (upper + 1));
      assert(rx._unit_q5 >= lower * 32 && rx._unit_q5 <= upper * 32);
    }
    assert(rx.unitMillis() == upper);
    for (unsigned count = 0; count < 96; ++count) {
      mark(rx, nominal / 2);
      assert(rx._unit_q5 >= lower * 32 && rx._unit_q5 <= upper * 32);
    }
    assert(rx.unitMillis() == lower);
    begin(rx, wpm);
    const uint16_t before = rx._unit_q5;
    rx.recordMark(uint32_t(nominal) * 7);
    assert(rx._bad_pattern && rx._symbols == 0 && rx._unit_q5 == before);
    rx.clear();
    rx.recordMark(nominal / 4);
    assert(rx._symbols == 0 && rx._unit_q5 == before); // rejected sub-third-dot must not train timing
  }
}

static void fractional_gap_comparisons() {
  MorseRx rx;
  begin(rx, 240);
  rx._unit_q5 = 132; // 4.125 ms: faster than the nominal five-ms unit
  rx._last_edge = 100;
  rx._code = 2;
  rx._symbols = 1;
  rx.flushGap(108);
  assert(rx.length() == 0); // eight ms is still shorter than two fractional units
  rx.flushGap(109);
  assert(std::strcmp(rx.text(), "E") == 0);
  rx.flushGap(120);
  assert(std::strcmp(rx.text(), "E") == 0); // 20 ms is shorter than five fractional units
  rx.flushGap(121);
  assert(std::strcmp(rx.text(), "E ") == 0);

  begin(rx, 240);
  rx._unit_q5 = 192; // a slower learned unit must not inflate the gap thresholds
  rx._last_edge = 100;
  rx._code = 2;
  rx._symbols = 1;
  rx.flushGap(109);
  assert(rx.length() == 0);
  rx.flushGap(110);
  assert(std::strcmp(rx.text(), "E") == 0);
  rx.flushGap(124);
  assert(std::strcmp(rx.text(), "E") == 0);
  rx.flushGap(125);
  assert(std::strcmp(rx.text(), "E ") == 0);
}

struct SampledReceiver {
  MorseRx rx;
  uint32_t now;
  explicit SampledReceiver(uint32_t started) : now(started) {
    begin(rx, 240, now);
    level(-110, 520);
  }
  void level(float dbm, uint32_t duration) {
    for (uint32_t sample = 0; sample < duration; ++sample) rx.sample(dbm, now++);
  }
};

static void actual_envelope_and_rollover() {
  for (uint32_t started : {100U, 0xffffff00U}) {
    SampledReceiver first(started);
    first.level(-80, 10);
    first.level(-110, 40);
    first.rx.stop(first.now);
    assert(std::strcmp(first.rx.text(), "T ") == 0);

    SampledReceiver trained(started);
    trained.level(-80, 6);
    trained.level(-110, 20);
    assert(trained.rx._unit_q5 == 164);
    trained.level(-80, 10);
    trained.level(-110, 40);
    trained.rx.stop(trained.now);
    assert(std::strcmp(trained.rx.text(), "EE ") == 0);
    assert(trained.rx._unit_q5 == 168 && !trained.rx.active());
  }
}

int main() {
  fractional_drift_and_integer_negative_control();
  first_ambiguous_and_warmed_borderline_marks();
  unchanged_bounds_and_checked_duration_limits();
  fractional_gap_comparisons();
  actual_envelope_and_rollover();
  std::printf("Q5 timing checks passed; MorseRx size: %zu bytes\n", sizeof(MorseRx));
}
