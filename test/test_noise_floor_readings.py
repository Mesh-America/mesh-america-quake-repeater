"""Execute the production freshness API and publication paths with real estimators."""

from pathlib import Path
import os
import subprocess
import sys
import tempfile
import unittest

from test_radio_receive_contract import ROOT, method, transition_harness


FIXTURE = r'''
struct UnsupportedRadio {
  @DEFAULT_GETTER@
  @DEFAULT_REQUEST@
};

static void fill(NoiseFloorEstimator& estimator, float dbm) {
  for (unsigned i = 0; i < NoiseFloorEstimator::SAMPLE_COUNT; ++i) {
    now_ms += NoiseFloorEstimator::SAMPLE_INTERVAL_MS;
    assert(estimator.add(dbm, now_ms));
  }
}
static uint32_t reading(const RadioLibWrapper& w, unsigned profile, float expected) {
  float dbm = 999;
  uint32_t published = 999;
  assert(w.getNoiseFloorReading(profile, dbm, published));
  assert(fabsf(dbm - expected) < 0.02f);
  return published;
}
static void missing(const RadioLibWrapper& w, unsigned profile) {
  float dbm = 999;
  uint32_t published = 999;
  assert(!w.getNoiseFloorReading(profile, dbm, published));
  assert(dbm == 999 && published == 999);
}
static void baseline(RadioLibWrapper& w, float primary = -120, float secondary = -118) {
  w._noise_floor_valid = w._noise_floor_secondary_valid = false;
  fill(w._floor_estimator, primary);
  if (w._profiles.enabled()) fill(w._secondary_floor_estimator, secondary);
  w._nf_refresh_requested = true;
  w.loop();
}
static void dual(RadioLibWrapper& w) {
  mesh::RadioProfileConfig second;
  second.params.freq = 911.15f;
  second.params.bw = 250;
  second.params.sf = 7;
  second.params.cr = 5;
  second.mode = mesh::RadioProfileMode::RxTx;
  w._profiles.setSecondary(second, false);
  w._profiles.primary = second.params;
  w._profile_rxps_suspended = true;
  w._profile_scan_generation[0] = w._profiles.generation[0];
  w._profile_scan_generation[1] = w._profiles.generation[1];
}
int main(int argc, char** argv) {
  assert(argc == 2);
  const char* scenario = argv[1];
  if (!strcmp(scenario, "unsupported")) {
    UnsupportedRadio radio;
    float dbm = 123;
    uint32_t published = 456;
    for (unsigned profile : {0U, 1U, 2U, 255U}) {
      assert(!radio.getNoiseFloorReading(profile, dbm, published));
      assert(dbm == 123 && published == 456);
      radio.requestNoiseFloorMeasurement();
    }
    RadioLibWrapper w;
    for (unsigned profile : {0U, 1U, 2U, 255U}) missing(w, profile);
  } else if (!strcmp(scenario, "single")) {
    RadioLibWrapper w;
    baseline(w);
    const uint32_t first = now_ms;
    assert(reading(w, 0, -120) == first);
    missing(w, 1); missing(w, 2); missing(w, 255);
    w.requestNoiseFloorMeasurement();
    assert(reading(w, 0, -120) == first);
    fill(w._floor_estimator, -120);
    w.loop();
    assert(now_ms != first && reading(w, 0, -120) == now_ms);
    const uint32_t second = now_ms;
    w.requestNoiseFloorMeasurement();
    fill(w._floor_estimator, -60);
    w.loop();
    assert(reading(w, 0, -120) == second); // held rise is not a publication
    assert(w._nf_last_calib == now_ms && now_ms != second);
    w.requestNoiseFloorMeasurement();
    w.busy = true;
    w.loop(); // arm a bounded window, then let it expire without idle RSSI
    now_ms += NF_CONTINUOUS_TIMEOUT_MS;
    w.loop();
    assert(!w._nf_refresh_requested);
    assert(reading(w, 0, -120) == second);
  } else if (!strcmp(scenario, "dual")) {
    RadioLibWrapper w;
    dual(w); baseline(w);
    const uint32_t first = now_ms;
    assert(reading(w, 0, -120) == first && reading(w, 1, -118) == first);
    w.requestNoiseFloorMeasurement();
    fill(w._floor_estimator, -120);
    fill(w._secondary_floor_estimator, -60); // one profile may hold while the other publishes
    w.loop();
    assert(reading(w, 0, -120) == now_ms);
    assert(reading(w, 1, -118) == first);
    const uint32_t primary = now_ms;
    w.requestNoiseFloorMeasurement();
    w.busy = true; w.loop();
    now_ms += NF_CONTINUOUS_TIMEOUT_MS;
    w.loop();
    assert(!w._nf_refresh_requested);
    assert(reading(w, 0, -120) == primary && reading(w, 1, -118) == first);
    w._profiles.secondary.mode = mesh::RadioProfileMode::Off;
    missing(w, 1);
  } else if (!strcmp(scenario, "invalidate")) {
    RadioLibWrapper w;
    dual(w); baseline(w);
    ++w._profiles.generation[1]; // reject the old profile before scanner service
    missing(w, 1);
    assert(reading(w, 0, -120) == now_ms);
    ++w._profiles.generation[0]; missing(w, 0);
    w.recalibrateNoiseFloor();
    missing(w, 0); missing(w, 1);
    assert(w._nf_published_valid == 0 && w._nf_refresh_requested);
    RadioLibWrapper gain;
    baseline(gain);
    assert(gain.setRxBoostedGainMode(true));
    missing(gain, 0);
    RadioLibWrapper reset;
    baseline(reset);
    reset.resetAGC();
    assert(reset._noise_floor_valid); // legacy filter can retain its last value
    missing(reset, 0); // telemetry cannot claim that value was measured after reset
  } else if (!strcmp(scenario, "rollover")) {
    for (bool two : {false, true}) {
      RadioLibWrapper w;
      if (two) dual(w);
      w._noise_floor_valid = w._noise_floor_secondary_valid = false;
      now_ms = UINT32_MAX - 10000;
      fill(w._floor_estimator, -120);
      if (two) fill(w._secondary_floor_estimator, -118);
      now_ms = 0;
      w.loop();
      assert(reading(w, 0, -120) == 0);
      if (two) assert(reading(w, 1, -118) == 0);
      w.requestNoiseFloorMeasurement();
      fill(w._floor_estimator, -120);
      if (two) fill(w._secondary_floor_estimator, -118);
      w.loop();
      assert(reading(w, 0, -120) == now_ms && now_ms != 0);
    }
  } else if (!strcmp(scenario, "request")) {
    for (unsigned owner : {0U, 1U, 2U, 3U, 4U, 5U, 6U}) {
      RadioLibWrapper w;
      baseline(w);
      const uint32_t published = now_ms;
      if (owner == 0) w.packet = true;
      if (owner == 1) w.state = STATE_TX_WAIT;
      if (owner == 2) w._cw_active = true;
      if (owner == 3) w._morse_owned = true;
      if (owner == 4) w._morse_rx_owned = true;
      if (owner == 5) w._beacon_owned = true;
      if (owner == 6) w.busy = true;
      const unsigned arms = w.arms, stops = w.stops, reads = w.reads;
      const unsigned scans = w.radio.scans, resets = w.agc_resets;
      w.requestNoiseFloorMeasurement();
      assert(reading(w, 0, -120) == published && w._nf_refresh_requested);
      assert(w._floor_estimator.add(-120, now_ms));
      w.loop();
      const auto deadline = w._nf_calib_deadline;
      for (unsigned i = 0; i < 4; ++i) {
        now_ms += 1;
        w.requestNoiseFloorMeasurement();
        assert(w._floor_estimator.count() == 1 && w._nf_calib_deadline == deadline);
      }
      assert(w.arms == arms && w.stops == stops && w.reads == reads);
      assert(w.radio.scans == scans && w.agc_resets == resets);
      assert(reading(w, 0, -120) == published);
    }
  } else assert(false);
  printf("PASS: %s\n", scenario);
}
'''


class NoiseFloorReadingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="meshcore-noise-reading-")
        cls.addClassCleanup(cls.directory.cleanup)
        work = Path(cls.directory.name)
        source = (ROOT / "src/helpers/radiolib/RadioLibWrappers.cpp").read_text()
        header = (ROOT / "src/helpers/radiolib/RadioLibWrappers.h").read_text()
        dispatcher = (ROOT / "src/Dispatcher.h").read_text()
        harness = transition_harness(source).split("struct LegacyRadio {", 1)[0]
        api = "\n".join(method(header, signature).replace(" override", "") for signature in (
            "bool getNoiseFloorReading(", "void requestNoiseFloorMeasurement("))
        harness = harness.replace("  bool tryResetAGC();", api + "\n  bool tryResetAGC();")
        harness = harness.replace("#include <cassert>", "#include <cassert>\n#include <cstring>")
        harness = harness.replace("bool serviceCarrierWave() { return false; }",
            "bool _morse_owned = false, _morse_rx_owned = false, _beacon_owned = false;\n"
            "  bool serviceCarrierWave() { return _cw_active || _morse_owned || _morse_rx_owned; }")
        loop = method(source, "void RadioLibWrapper::loop(")
        harness = harness.replace(loop,
            "#define MESH_ENABLE_TX_BEACONS 1\n#define MESH_ENABLE_CARRIER_TOOLS 1\n"
            + loop + "\n#undef MESH_ENABLE_TX_BEACONS\n#undef MESH_ENABLE_CARRIER_TOOLS\n")
        fixture = FIXTURE.replace("@DEFAULT_GETTER@", method(dispatcher,
            "virtual bool getNoiseFloorReading(")).replace("@DEFAULT_REQUEST@", method(dispatcher,
            "virtual void requestNoiseFloorMeasurement("))
        cls.binaries = {}
        flags = [] if not sys.platform.startswith("linux") else [
            "-fsanitize=address,undefined", "-fno-sanitize-recover=all", "-fno-pie", "-no-pie"]
        for family in ("sx1262", "other"):
            cpp, binary = work / (family + ".cpp"), work / family
            cpp.write_text((harness + fixture).replace("\u2014", "-"), encoding="ascii")
            built = subprocess.run([os.environ.get("CXX", "g++"), "-std=c++17", "-O1", "-g",
                "-Wall", "-Wextra", "-Werror", *flags,
                *(["-DUSE_SX1262=1"] if family == "sx1262" else []),
                "-I", str(ROOT / "src"), str(cpp), "-o", str(binary)],
                capture_output=True, text=True, timeout=60)
            if built.returncode:
                raise AssertionError(built.stdout + built.stderr)
            cls.binaries[family] = binary

    def run_case(self, scenario):
        for family, binary in self.binaries.items():
            with self.subTest(family=family):
                result = subprocess.run([str(binary), scenario], capture_output=True,
                                        text=True, timeout=20)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("PASS: " + scenario, result.stdout)

    def test_unsupported_and_unmeasured_profiles_are_missing(self):
        self.run_case("unsupported")

    def test_single_only_successful_publications_advance_timestamp(self):
        self.run_case("single")

    def test_dual_publication_timestamps_remain_independent(self):
        self.run_case("dual")

    def test_profile_gain_and_rf_reset_invalidate_telemetry_readings(self):
        self.run_case("invalidate")

    def test_millis_zero_and_rollover_are_valid_publication_times(self):
        self.run_case("rollover")

    def test_requests_join_collection_without_interrupting_radio_owners(self):
        self.run_case("request")


if __name__ == "__main__":
    unittest.main()
