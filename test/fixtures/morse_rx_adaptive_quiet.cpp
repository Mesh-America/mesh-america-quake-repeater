// Synthetic envelopes reproduce the detector defect, not an RF qualification.
// The shipping decoder sees the same samples in the positive/negative runs.
#include <helpers/MorseRx.h>
#include <cassert>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <initializer_list>

struct Receiver {
  mesh::MorseRx rx;
  uint32_t now;
  uint32_t cadence;
  Receiver(uint32_t step = 2, uint32_t started = 100) : now(started), cadence(step) {
    assert(rx.start(25, 300000, now) == mesh::MorseRxResult::Started);
  }
  void level(float dbm, uint32_t duration) {
    for (uint32_t elapsed = 0; elapsed < duration; elapsed += cadence, now += cadence)
      rx.sample(dbm, now);
  }
  void arm(float floor, float excursion) {
    level(floor, 100);
    level(excursion, 100);
    level(floor, 100);
    level(excursion, 100);
    level(floor, 120);
    assert(!rx.keyed() && rx.length() == 0);
  }
};

static void learned_noise_cannot_prekey_a_real_dot() {
  for (uint32_t cadence = 1; cadence <= 10; ++cadence) for (float floor : {-140.0f, -126.0f, -90.0f}) {
    Receiver r(cadence);
    const float peak = floor + 15.5f;
    r.arm(floor, peak);
    r.level(peak, 100);
    assert(!r.rx.keyed() && r.rx.length() == 0);
    r.level(floor + 75, 48);
    r.level(floor, 400);
    r.rx.stop(r.now);
    assert(std::strcmp(r.rx.text(), "E ") == 0);
    mesh::MorseRxDiagnostics stats;
    r.rx.diagnostics(stats);
    assert(stats.minimum_dbm == floor && stats.maximum_dbm == floor + 75);
    assert(stats.last_dbm == floor && stats.max_sample_gap_ms == cadence);
    assert(!r.rx.active() && !r.rx.truncated());
  }
}

static void recurrent_learned_excursions_stay_quiet_until_expiry() {
  for (uint32_t cadence = 1; cadence <= 10; ++cadence) for (uint32_t started : {100U, 0xffffff00U}) {
    Receiver r(cadence, started);
    r.arm(-126, -110.5f);
    while (r.rx.active()) {
      r.level(-110.5f, 100);
      r.level(-126, 320);
      assert(!r.rx.keyed() && r.rx.length() == 0);
    }
    assert(!r.rx.truncated() && r.rx.remainingMillis(r.now) == 0);
    char page[8] = {'X'};
    assert(r.rx.read(0, page, sizeof(page)) == 0 && page[0] == 0);
    mesh::MorseRxDiagnostics before, after;
    r.rx.diagnostics(before);
    r.level(-20, 1000);
    r.rx.diagnostics(after);
    assert(after.samples == before.samples && after.maximum_dbm == before.maximum_dbm);
    // A new valid session resets the learned environment and its transcript.
    assert(r.rx.start(25, 300000, r.now) == mesh::MorseRxResult::Started);
    r.level(-126, 520);
    r.level(-119, 48);
    r.level(-126, 400);
    r.rx.stop(r.now);
    assert(std::strcmp(r.rx.text(), "E ") == 0);
  }
}

static void weak_cw_is_relative_to_the_observed_environment() {
  for (uint32_t cadence = 1; cadence <= 10; ++cadence) for (float floor : {-150.0f, -127.5f, -100.0f, -70.0f}) {
    Receiver r(cadence);
    r.level(floor, 520);
    r.level(floor + 6, 48); // unchanged six-dB margin on a stable floor
    r.level(floor, 400);
    r.rx.stop(r.now);
    assert(std::strcmp(r.rx.text(), "E ") == 0);

    Receiver noisy(cadence);
    noisy.arm(floor, floor + 15.5f);
    noisy.level(floor + 22.5f, 48); // seven dB above learned noise peaks
    noisy.level(floor, 400);
    noisy.rx.stop(noisy.now);
    assert(std::strcmp(noisy.rx.text(), "E ") == 0);

    Receiver settled(cadence);
    settled.arm(floor, floor + 15.5f);
    settled.level(floor, 65000); // the noisier arming environment has gone away
    settled.level(floor + 7, 48);
    settled.level(floor, 400);
    settled.rx.stop(settled.now);
    assert(std::strcmp(settled.rx.text(), "E ") == 0);
  }
}

static void startup_outlier_spikes_and_late_arming_changes() {
  for (uint32_t cadence = 1; cadence <= 10; ++cadence) for (uint32_t started : {100U, 0xffffff00U}) {
    Receiver stale(cadence, started);
    stale.level(-75, cadence); // one stale initial reading, then a complete quiet arm
    stale.level(-126, 520);
    stale.level(-120, 48); // first message retains the six-dB boundary
    stale.level(-126, 400);
    stale.rx.stop(stale.now);
    assert(std::strcmp(stale.rx.text(), "E ") == 0);

    {
      Receiver spike(cadence, started);
      spike.level(-126, 300);
      spike.level(-50, cadence); // an isolated arming spike cannot poison the envelope
      spike.level(-126, 220);
      spike.level(-119, 48);
      spike.level(-126, 400);
      spike.rx.stop(spike.now);
      assert(std::strcmp(spike.rx.text(), "E ") == 0);
    }

    // Any final settling sample can be an outlier; the 50-ms phase boundary
    // must not retain it as the learned quiet ceiling for the whole capture.
    for (uint32_t at = 0; at < 50; at += cadence) {
      Receiver boundary(cadence, started);
      boundary.level(-126, at);
      boundary.level(-50, cadence);
      boundary.level(-126, 520);
      boundary.level(-119, 48);
      boundary.level(-126, 400);
      boundary.rx.stop(boundary.now);
      assert(std::strcmp(boundary.rx.text(), "E ") == 0);
    }

    Receiver late(cadence, started);
    late.level(-126, 350);
    late.level(-110.5f, 170); // sustained change late in the existing arm window
    late.level(-126, 100);
    late.level(-110.5f, 100);
    assert(!late.rx.keyed() && late.rx.length() == 0);
    late.level(-103.5f, 48);
    late.level(-126, 400);
    late.rx.stop(late.now);
    assert(std::strcmp(late.rx.text(), "E ") == 0);
  }
}

int main() {
  learned_noise_cannot_prekey_a_real_dot();
  recurrent_learned_excursions_stay_quiet_until_expiry();
  weak_cw_is_relative_to_the_observed_environment();
  startup_outlier_spikes_and_late_arming_changes();
  std::puts("actual adaptive quiet checks passed");
}
