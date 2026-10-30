"""Execute ESP32 scanner publication and its late, integer-only idle query."""

import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from cpp_source import body
from test_radio_profile_scan import HARNESS as SCAN_HARNESS


ROOT = Path(__file__).resolve().parents[1]

ESP_MEMBERS = r'''
  uint64_t _esp32_profile_visit_started_us=0, _esp32_profile_idle_stamp_us=0;
  uint32_t _esp32_profile_idle_visit_us=0, _esp32_profile_idle_switch_us=0;
  uint32_t _esp32_profile_idle_generation[2]={};
  uint16_t _esp32_profile_idle_preamble=0;
  uint8_t _esp32_profile_idle_profile=0;
  uint32_t _wd_observe_until=0;
  bool _rx_retry_pending=false, _morse_owned=false;
  bool _beacon_owned=false, _beacon_restoring=false, _morse_rx_owned=false;
  bool getProfileIdleDelay(uint32_t&) const;
'''

COMMON = r'''
// Complete both independent baselines after startup without faking the idle
// token: its RX stamp, generation, preamble and visit come from the scanner.
static void ready(RadioLibWrapper& w, uint8_t sf=11, float bw=125) {
  w._profiles.primary.sf=w._cur_sf=sf;
  w._profiles.primary.bw=w._cur_bw=bw;
  w.enable();
  assert(w._profiles.switchTestReady());
  w._nf_refresh_requested=w._nf_calib_active=false;
  w._noise_floor_valid=w._noise_floor_secondary_valid=true;
  w.serviceProfileScan();
  assert(w._esp32_profile_idle_visit_us>0);
}
static bool idle(RadioLibWrapper& w, uint32_t expected) {
  uint32_t delay=999;
  const bool allowed=w.getProfileIdleDelay(delay);
  assert(delay==expected);
  return allowed;
}
'''

ADMISSION = r'''
int main() {
  RadioLibWrapper w; ready(w);
  const uint64_t start=w._esp32_profile_visit_started_us;
  const uint32_t visit=w._esp32_profile_idle_visit_us;
  assert(visit>30000);
  // Frontend settling keeps polling even when the whole visit is long.
  elapsed_us=start+RadioLibWrapper::NoiseFloorSettleMillis*1000-1;
  assert(!idle(w,0));
  elapsed_us=start+RadioLibWrapper::NoiseFloorSettleMillis*1000;
  assert(idle(w,10));
  // The original RX stamp survives repeated loop passes on the same tuple.
  w.serviceProfileScan();
  assert(w._esp32_profile_visit_started_us==start && idle(w,10));

  // Visit end is strict: require 4 ms guard plus at least 2 ms of useful idle.
  for (uint32_t remaining=0; remaining<=17000; ++remaining) {
    elapsed_us=start+visit-remaining;
    const auto usable=remaining>=6000 ? (remaining-4000)/1000 : 0;
    const auto expected=usable>10 ? 10 : usable;
    assert(idle(w,expected)==(expected!=0));
  }
  elapsed_us=start+visit+1;
  assert(!idle(w,0));
  // Stale low-32-bit clock equality after a full wrap is never a new visit.
  elapsed_us=start+0x100000000ULL+10000;
  assert(!idle(w,0));
  elapsed_us=start-1;
  assert(!idle(w,0));

  // A late IRQ, RX restart, owner or changed tuning proof revokes admission.
  auto denied=[&](auto mutate) {
    RadioLibWrapper fresh; ready(fresh);
    elapsed_us=fresh._esp32_profile_visit_started_us+10000;
    assert(idle(fresh,10));
    mutate(fresh);
    assert(!idle(fresh,0));
  };
  denied([](auto& x){x._profiles.secondary.mode=mesh::RadioProfileMode::Off;});
  denied([](auto& x){x._esp32_profile_idle_visit_us=0;});
  denied([](auto& x){x._params_valid=false;});
  denied([](auto& x){x.state=STATE_TX_WAIT;});
  denied([](auto& x){x._profile_rxps_suspended=false;});
  denied([](auto& x){x._rx_ps_enabled=true;});
  denied([](auto& x){x._rx_ps_armed=true;});
  denied([](auto& x){x._rx_hold_continuous=true;});
  denied([](auto& x){x._rx_retry_pending=true;});
  denied([](auto& x){x._profile_retry_at=1;});
  denied([](auto& x){x._profile_refresh_required=true;});
  denied([](auto& x){x._profile_repair_required=true;});
  denied([](auto& x){x._nf_refresh_requested=true;});
  denied([](auto& x){x._nf_calib_active=true;});
  denied([](auto& x){x._noise_floor_valid=false;});
  denied([](auto& x){x._noise_floor_secondary_valid=false;});
  denied([](auto& x){x._wd_observe_until=1;});
  denied([](auto& x){x._cw_active=true;});
  denied([](auto& x){x._morse_owned=true;});
  denied([](auto& x){x._beacon_owned=true;});
  denied([](auto& x){x._morse_rx_owned=true;});
  denied([](auto& x){x.events.record();});
  denied([](auto& x){x._profiles.resetSwitchTest();});
  denied([](auto& x){x._active_profile=2;});
  denied([](auto& x){x._active_profile^=1;});
  denied([](auto& x){++x._profile_generation;});
  denied([](auto& x){++x._profiles.generation[0];});
  denied([](auto& x){++x._profiles.generation[1];});
  denied([](auto& x){++x._profile_scan_generation[0];});
  denied([](auto& x){++x._profile_scan_generation[1];});
  denied([](auto& x){++x._esp32_profile_idle_generation[0];});
  denied([](auto& x){++x._esp32_profile_idle_generation[1];});
  denied([](auto& x){++x._esp32_profile_visit_started_us;});
  denied([](auto& x){++x._physical_preamble;});
  denied([](auto& x){++x._profiles.switch_test_max_us[1];});

  // Both scanner generations matter even if a replacement copied the same
  // active tuple and its retune sample budget happened to be unchanged.
  denied([](auto& x){
    ++x._profiles.generation[1]; ++x._profile_scan_generation[1];
  });
}
'''

SCANNER = r'''
int main() {
  RadioLibWrapper w; ready(w);
  auto start=w._esp32_profile_visit_started_us;
  elapsed_us=start+10000;
  assert(idle(w,10));
  w._cw_active=true; w.serviceProfileScan();
  assert(w._esp32_profile_idle_visit_us==0 && !idle(w,0));
  w._cw_active=false; w.serviceProfileScan(); assert(idle(w,10));
  w._profile_retry_at=millis()+1000; w.serviceProfileScan();
  assert(w._esp32_profile_idle_visit_us==0);
  w._profile_retry_at=0; w.serviceProfileScan(); assert(idle(w,10));
  w.busy=true; w.serviceProfileScan(); assert(!idle(w,0));
  w.busy=false; w.packet=true; w.serviceProfileScan(); assert(!idle(w,0));
  w.packet=false; w.events.record(); w.serviceProfileScan(); assert(!idle(w,0));
  w.events.claim(); w.serviceProfileScan(); assert(idle(w,10));

  // A timer wake advances the same clock the scanner uses. It cannot let a
  // due scan spend an extra visit on the old profile or reuse its old budget.
  auto previous=w._active_profile;
  elapsed_us=start+w._esp32_profile_idle_visit_us;
  w.serviceProfileScan();
  assert(w._active_profile!=previous && !idle(w,0));
  start=w._esp32_profile_visit_started_us;
  w.serviceProfileScan();
  assert(w._esp32_profile_idle_stamp_us==start && !idle(w,0));

  // The fast visit is sub-ms (SF5/BW500) and must keep polling throughout.
  RadioLibWrapper fast; ready(fast,5,500);
  assert(fast._esp32_profile_idle_visit_us<1000 && !idle(fast,0));
  elapsed_us+=fast._esp32_profile_idle_visit_us;
  fast.serviceProfileScan();
  assert(!idle(fast,0));

  // A long hold spanning micros() wrap still causes a real hop on release.
  RadioLibWrapper wrap; ready(wrap);
  const auto old_profile=wrap._active_profile;
  elapsed_us=wrap._esp32_profile_visit_started_us+0x100000000ULL+10000;
  wrap.serviceProfileScan();
  assert(wrap._active_profile!=old_profile && !idle(wrap,0));
  assert(wrap._esp32_profile_visit_started_us==elapsed_us);
  assert(wrap._profile_visit_stamp==uint32_t(elapsed_us));

  RadioLibWrapper changed; ready(changed);
  elapsed_us=changed._esp32_profile_visit_started_us+10000;
  assert(idle(changed,10));
  auto replacement=changed._profiles.secondary;
  replacement.params.freq+=1;
  changed._profiles.setSecondary(replacement,false);
  assert(!idle(changed,0));
  changed.serviceProfileScan();
  assert(changed._esp32_profile_idle_visit_us==0 && !idle(changed,0));
  assert(changed._nf_refresh_requested && !changed._noise_floor_secondary_valid);
  changed._profiles.setSecondary({},false);
  changed.serviceProfileScan();
  assert(changed._esp32_profile_idle_visit_us==0 && !idle(changed,0));
  assert(!changed._profile_rxps_suspended && changed._rx_ps_enabled);
}
'''


class Esp32ProfileIdleTest(unittest.TestCase):
    @staticmethod
    def fixture():
        source = (ROOT / "src/helpers/radiolib/RadioLibWrappers.cpp").read_text()
        names = [("uint8_t", "beginReconfigure"), ("void", "endReconfigure"),
                 ("void", "serviceProfileScan")] + [("mesh::RadioParamApplyResult", name) for name in
                 ("tuneProfile", "prepareTransmitProfile", "tryRestoreCodingRate",
                  "trySetParams", "trySetPrimaryParams")]
        methods = "\n".join(body(source, f"{kind} RadioLibWrapper::{name}(") for kind, name in names)
        methods += "\n" + body(source,
            "mesh::RadioParamApplyResult RadioLibWrapper::prepareTransmitProfile(uint8_t profile, bool")
        query = body(source, "bool RadioLibWrapper::getProfileIdleDelay(")
        # This final admission must never perform SPI, derive float timing or
        # run the scanner. Every such operation precedes the published proof.
        for forbidden in ("profilePreamble(", "listenUs(", "profileTimestamp(",
                          "isChipBusy(", "isPacketPendingOrReceiving(", "tuneProfile("):
            assert forbidden not in query, forbidden
        methods += "\n" + query
        wrapper = (ROOT / "src/helpers/radiolib/CustomSX1262Wrapper.h").read_text()
        methods += "\n" + body(wrapper, "void setProfileStandbyWarm(").replace(
            "void setProfileStandbyWarm(bool enabled) override",
            "void RadioLibWrapper::setProfileStandbyWarm(bool enabled)")
        fixture = SCAN_HARNESS.split("int main()", 1)[0]
        fixture = fixture.replace("  bool _cw_active=false;", ESP_MEMBERS + "\n  bool _cw_active=false;")
        fixture = fixture.replace("static uint64_t elapsed_us;", """
#define MESH_ENABLE_TX_BEACONS 1
#define MESH_ENABLE_MORSE_RX 1
static uint64_t elapsed_us;
int64_t esp_timer_get_time() { return static_cast<int64_t>(elapsed_us); }
""")
        fixture = fixture.replace("state=STATE_RX; _profile_visit_stamp=profileTimestamp(_profiles.enabled());",
            "state=STATE_RX; _esp32_profile_visit_started_us=elapsed_us; "
            "_profile_visit_stamp=profileTimestamp(_profiles.enabled());")
        return "#include <helpers/esp32/PowerTestControls.h>\n" + fixture.replace("@METHODS@", methods) + COMMON

    def run_fixture(self, main):
        with tempfile.TemporaryDirectory(prefix="meshcore-esp32-profile-idle-") as directory:
            folder = Path(directory)
            (folder / "Arduino.h").write_text("#pragma once\n#include <cstdint>\n#include <cmath>\n")
            (folder / "test.cpp").write_text(self.fixture() + main)
            flags = ["-std=c++17", "-Wall", "-Wextra", "-Werror", "-DESP32_PLATFORM=1"]
            if os.name != "nt":
                flags += ["-fsanitize=address,undefined", "-fno-sanitize-recover=all", "-fno-pie", "-no-pie"]
            result = subprocess.run([os.environ.get("CXX", "c++"), *flags,
                "-I", directory, "-I", str(ROOT / "src"), str(folder / "test.cpp"),
                "-o", str(folder / "test")], capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            result = subprocess.run([str(folder / "test")], capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_late_integer_admission_boundaries_and_revocation(self):
        self.run_fixture(ADMISSION)

    def test_real_scanner_clock_hops_and_failed_publication(self):
        self.run_fixture(SCANNER)


if __name__ == "__main__":
    unittest.main()
