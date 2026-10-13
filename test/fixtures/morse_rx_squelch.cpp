#include <helpers/MorseRx.h>
#include <cassert>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <initializer_list>
#include <limits>

using mesh::MorseRx;

#if defined(MESH_MORSE_HIL) && MESH_MORSE_HIL
static_assert(sizeof(MorseRx) == 4168 + sizeof(void*), "squelch must not add decoder fields");
#else
static_assert(sizeof(MorseRx) == 4168, "shipping decoder layout must be unchanged");
#endif

struct Receiver {
  MorseRx rx;
  uint32_t now = 100;
  Receiver() {
    assert(rx.start(25, 300000, now) == mesh::MorseRxResult::Started);
    level(-120, 520);
  }
  void level(float dbm, uint32_t ms) {
    for (uint32_t sample = 0; sample < ms; ++sample) rx.sample(dbm, now++);
  }
  void finish() { level(-120, 400); rx.stop(now); }
};

static void unchanged_auto_weak_signal() {
#if defined(MESH_MORSE_HIL) && MESH_MORSE_HIL
  assert(mesh::setMorseHilSquelch(NAN));
#endif
  Receiver weak;
  weak.level(-113, 48); // valid seven-dB CW above this quiet floor
  weak.finish();
  assert(std::strcmp(weak.rx.text(), "E ") == 0);
}

#if defined(MESH_MORSE_HIL) && MESH_MORSE_HIL
static void setter_range_and_auto() {
  assert(std::isnan(mesh::morseHilSquelch())); // default AUTO, no saved setting
  for (float value : {-160.0f, -100.0f, 0.0f}) {
    assert(mesh::setMorseHilSquelch(value));
    assert(mesh::morseHilSquelch() == value);
  }
  assert(mesh::setMorseHilSquelch(-100));
  for (float invalid : {-160.01f, 0.01f,
                        std::numeric_limits<float>::infinity(),
                        -std::numeric_limits<float>::infinity()}) {
    assert(!mesh::setMorseHilSquelch(invalid));
    assert(mesh::morseHilSquelch() == -100);
  }
  assert(mesh::setMorseHilSquelch(NAN));
  assert(std::isnan(mesh::morseHilSquelch()));
}

static void quiet_prekey_cannot_absorb_the_real_dot() {
  assert(mesh::setMorseHilSquelch(NAN));
  Receiver automatic;
  automatic.level(-111, 100); // measured-style quiet excursion keys prematurely
  assert(automatic.rx.keyed());
  automatic.level(-40, 48);
  automatic.finish();
  assert(std::strcmp(automatic.rx.text(), "T ") == 0); // one false long mark, not a real dash

  assert(mesh::setMorseHilSquelch(-100));
  Receiver bounded;
  bounded.level(-111, 100);
  assert(!bounded.rx.keyed() && bounded.rx.length() == 0);
  bounded.level(-40, 48);
  bounded.finish();
  assert(std::strcmp(bounded.rx.text(), "E ") == 0); // reject RF noise before symbol recording
}

static void measured_style_quiet_is_empty_without_transcript_filtering() {
  assert(mesh::setMorseHilSquelch(NAN));
  Receiver automatic;
  for (unsigned pulse = 0; pulse < 8; ++pulse) {
    automatic.level(-111, 100);
    automatic.level(-120, 320);
  }
  automatic.finish();
  assert(automatic.rx.length() > 0); // negative control proves the fixture crosses AUTO

  assert(mesh::setMorseHilSquelch(-100));
  Receiver bounded;
  for (unsigned sample = 0; sample < 5000; ++sample) {
    const float dbm = sample % 109 < 40 ? -106 : (sample % 3 ? -115 : -124);
    bounded.level(dbm, 1);
    assert(!bounded.rx.keyed() && bounded.rx.length() == 0);
  }
  bounded.finish();
  assert(bounded.rx.length() == 0 && !bounded.rx.truncated());
}

static void falling_floor_has_three_db_hysteresis() {
  assert(mesh::setMorseHilSquelch(-100));
  Receiver bounded;
  bounded.level(-99, 48);
  assert(bounded.rx.keyed());
  bounded.level(-102, 20); // below the ON floor, but still above its -103 OFF floor
  assert(bounded.rx.keyed());
  bounded.level(-104, 15);
  assert(!bounded.rx.keyed());
  bounded.finish();
  assert(std::strcmp(bounded.rx.text(), "E ") == 0);

  // The bound is deliberately optional: enabling it rejects weaker real CW,
  // then AUTO returns the exact existing weak-signal behavior, not a new gate.
  Receiver weak;
  weak.level(-113, 48);
  weak.finish();
  assert(weak.rx.length() == 0);
  unchanged_auto_weak_signal();
}
#endif

int main() {
#if defined(MESH_MORSE_HIL) && MESH_MORSE_HIL
  setter_range_and_auto();
  quiet_prekey_cannot_absorb_the_real_dot();
  measured_style_quiet_is_empty_without_transcript_filtering();
  falling_floor_has_three_db_hysteresis();
#endif
  unchanged_auto_weak_signal();
  std::puts("actual squelch checks passed");
}
