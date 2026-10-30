"""Execute the real ESP32 role sleep branches and their absolute-deadline handoff.

Uses production role branches and ProfileIdleSleep.h, with host-only clock,
mesh and board fakes. It does not access hardware or invoke PlatformIO.
"""

import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from cpp_source import body

ROOT = Path(__file__).resolve().parents[1]


PRELUDE = r'''
#include <cassert>
#include <cstdint>
#include <initializer_list>
#include <helpers/PowerSavingDiagnostics.h>
#include <helpers/PowerManagementUtils.h>
#define ESP32_PLATFORM 1
#define POWERSAVING_FIRSTSLEEP_SECS 1
#define POWERSAVING_FIRST_SLEEP_SECS 1
static uint64_t clock_us=100000;
int64_t esp_timer_get_time() { return static_cast<int64_t>(clock_us); }
static uint32_t millis() { return static_cast<uint32_t>(clock_us/1000); }
static uint32_t micros() { return static_cast<uint32_t>(clock_us); }
#include <helpers/esp32/ProfileIdleSleep.h>
struct Mesh {
  uint32_t budget=30000, noise_delay=50, profile_ms=10;
  uint32_t queue_work_us=0, noise_work_us=0, startup_work_us=0, query_work_us=0;
  bool dual=true, noise=false, startup_ready=true, profile_ready=true, late_ready=true;
  unsigned queries=0;
  uint32_t query_at=0;
  uint32_t getPowerSaveSleepMilliseconds(uint32_t limit) const {
    assert(limit==30000); clock_us+=queue_work_us; return budget;
  }
  bool getNextNoiseFloorWakeDelay(uint32_t& out) const {
    clock_us+=noise_work_us; out=noise_delay; return noise;
  }
  bool millisHasNowPassed(uint32_t) const { clock_us+=startup_work_us; return startup_ready; }
  bool isDualRadioActive() const { return dual; }
  bool getDualRadioIdleDelay(uint32_t& out) {
    ++queries; query_at=static_cast<uint32_t>(clock_us);
    clock_us+=query_work_us; out=profile_ms;
    return profile_ready && late_ready;
  }
} the_mesh;
struct Board {
  unsigned absolute_calls=0, legacy_calls=0, actual_sleeps=0;
  uint32_t deadline=0, last_legacy_ms=0, setup_us=0, useful_us=0;
  bool ready=true;
  void sleep(uint32_t seconds) { ++legacy_calls; last_legacy_ms=seconds*1000; }
  void sleepMilliseconds(uint32_t ms) { ++legacy_calls; last_legacy_ms=ms; }
  void sleepUntilMicroseconds(uint32_t at) {
    ++absolute_calls; deadline=at; clock_us+=setup_us;
    const int32_t remaining=static_cast<int32_t>(at-static_cast<uint32_t>(clock_us));
    // Models the board API's final deadline check; the production board
    // implementation has its own executing test and SDK build coverage.
    if (ready && remaining>=2000) { ++actual_sleeps; useful_us=remaining; }
  }
} board;
static void reset(uint64_t start=100000) { the_mesh=Mesh{}; board=Board{}; clock_us=start; }
'''

INFRA_MAIN = r'''
int main() {
  for (uint64_t start : {100000ULL, 0xffffff00ULL, 0x100000100ULL}) {
    for (uint32_t profile : {2U,3U,4U,5U,6U,7U,8U,9U,10U}) {
      reset(start); the_mesh.profile_ms=profile; idle(true);
      assert(the_mesh.queries==1 && board.absolute_calls==1 && board.actual_sleeps==1);
      assert(board.deadline==static_cast<uint32_t>(start+profile*1000));
      assert(board.useful_us==profile*1000 && board.legacy_calls==0);
    }
    // A due queue/calibration, startup hold, or outer guard never reaches
    // the handoff. No branch substitutes a longer legacy board sleep.
    reset(start); the_mesh.budget=0; idle(true);
    assert(the_mesh.queries==0 && board.absolute_calls==0 && board.legacy_calls==0);
    reset(start); the_mesh.noise=true; the_mesh.noise_delay=0; idle(true);
    assert(the_mesh.queries==0 && board.absolute_calls==0 && board.legacy_calls==0);
    reset(start); the_mesh.startup_ready=false; idle(true);
    assert(the_mesh.queries==0 && board.absolute_calls==0 && board.legacy_calls==0);
    reset(start); idle(false);
    assert(the_mesh.queries==0 && board.absolute_calls==0 && board.legacy_calls==0);

    // Every form of late scanner rejection retains zero-delay polling.
    reset(start); the_mesh.profile_ready=false; idle(true);
    assert(the_mesh.queries==1 && board.absolute_calls==0 && board.legacy_calls==0);
    reset(start); the_mesh.late_ready=false; idle(true);
    assert(the_mesh.queries==1 && board.absolute_calls==0 && board.legacy_calls==0);
    for (uint32_t bad : {0U,1U,11U,UINT32_MAX}) {
      reset(start); the_mesh.profile_ms=bad; idle(true);
      assert(the_mesh.queries==1 && board.absolute_calls==0 && board.legacy_calls==0);
    }

    // The queue/noise deadline begins before queue calculation and startup
    // work. Seven ms of setup must leave only three of its original ten.
    reset(start); the_mesh.budget=10; the_mesh.queue_work_us=4000;
    the_mesh.noise_work_us=1000; the_mesh.startup_work_us=2000; idle(true);
    assert(the_mesh.queries==1 && board.actual_sleeps==1 && board.legacy_calls==0);
    assert(board.deadline==static_cast<uint32_t>(start+10000) && board.useful_us==3000);
    reset(start); the_mesh.noise=true; the_mesh.noise_delay=5;
    the_mesh.queue_work_us=2000; idle(true);
    assert(board.deadline==static_cast<uint32_t>(start+5000) && board.useful_us==3000);
    reset(start); the_mesh.budget=2; idle(true);
    assert(board.deadline==static_cast<uint32_t>(start+2000) && board.actual_sleeps==1);
    reset(start); the_mesh.budget=1; idle(true);
    assert(board.absolute_calls==0 && board.legacy_calls==0);

    // Expiration while traversing the role gate never restarts that budget.
    reset(start); the_mesh.budget=10; the_mesh.queue_work_us=10000; idle(true);
    assert(the_mesh.queries==1 && board.absolute_calls==0 && board.legacy_calls==0);
    reset(start); the_mesh.noise=true; the_mesh.noise_delay=2;
    the_mesh.noise_work_us=2000; idle(true);
    assert(board.absolute_calls==0 && board.legacy_calls==0);

    // Query and wake-source setup can consume budget after the helper's
    // observation. The absolute deadline survives; the board rejects <2ms.
    reset(start); the_mesh.query_work_us=7000; board.setup_us=2000; idle(true);
    assert(board.absolute_calls==1 && board.deadline==static_cast<uint32_t>(start+10000));
    assert(board.actual_sleeps==0 && board.legacy_calls==0);
    reset(start); the_mesh.query_work_us=1000; board.setup_us=1000; idle(true);
    assert(board.deadline==static_cast<uint32_t>(start+10000) && board.useful_us==8000);
    reset(start); board.ready=false; idle(true);
    assert(board.absolute_calls==1 && board.actual_sleeps==0 && board.legacy_calls==0);

    // Single-profile behavior remains the original direct milliseconds API,
    // including a one-ms deadline that is too short for timed radio2 sleep.
    for (uint32_t budget : {0U,1U,2U,50U,999U,1001U,30000U}) {
      reset(start); the_mesh.dual=false; the_mesh.budget=budget; idle(true);
      assert(the_mesh.queries==0 && board.absolute_calls==0);
      assert(board.legacy_calls==(budget!=0));
      if (budget) assert(board.last_legacy_ms==budget);
      reset(start); the_mesh.dual=false; the_mesh.budget=budget;
      the_mesh.noise=true; the_mesh.noise_delay=3; idle(true);
      assert(board.legacy_calls==(budget!=0));
      if (budget) assert(board.last_legacy_ms==(budget<3 ? budget : 3));
    }
  }
}
'''


COMPANION_STUBS = r'''
#define ENABLE_USB_INTERFACE 1
#if TEST_NATIVE_USB
#define ARDUINO_USB_CDC_ON_BOOT 1
#endif
static bool native_ready=true;
static uint32_t native_setup_us=0;
bool companionNativeUsbLightSleepReady() { clock_us+=native_setup_us; return native_ready; }
using esp_err_t=int;
constexpr int ESP_OK=0;
static unsigned sdk_timer_calls=0, sdk_sleep_calls=0, yields=0;
static uint32_t sdk_timer_us=0;
int esp_sleep_enable_timer_wakeup(uint64_t value) {
  ++sdk_timer_calls; sdk_timer_us=value; return ESP_OK;
}
int esp_light_sleep_start() { ++sdk_sleep_calls; return ESP_OK; }
int pdMS_TO_TICKS(int ms) { return ms; }
void vTaskDelay(int) { ++yields; }
void delay(int) { ++yields; }
struct Prefs { bool powersaving_enabled=true; } prefs;
namespace mesh {
bool isUsbLoggingWatchdogArmed() { return false; }
namespace wireless {
struct Control { bool pending() const { return false; } } controller;
Control& control() { return controller; }
}
}
'''

COMPANION_MAIN = r'''
int main() {
  for (uint64_t start : {100000ULL, 0xffffff00ULL, 0x100000100ULL}) {
    for (uint32_t profile : {2U,3U,4U,5U,6U,7U,8U,9U,10U}) {
      reset(start); the_mesh.profile_ms=profile; idle();
      assert(board.absolute_calls==1 && board.actual_sleeps==1);
      assert(board.deadline==static_cast<uint32_t>(start+profile*1000));
      assert(board.legacy_calls==0 && yields==0 && sdk_sleep_calls==0);
    }
    reset(start); the_mesh.noise=true; the_mesh.noise_delay=0; idle();
    assert(board.absolute_calls==0 && board.legacy_calls==0 && yields==0);
    reset(start); the_mesh.noise=true; the_mesh.noise_delay=3; idle();
    assert(board.deadline==static_cast<uint32_t>(start+3000) && board.useful_us==3000);
    reset(start); the_mesh.profile_ready=false; idle();
    assert(the_mesh.queries==0 && board.absolute_calls==0 && yields==0);
    reset(start); the_mesh.late_ready=false; idle();
    assert(the_mesh.queries==1 && board.absolute_calls==0 && yields==0);
    for (uint32_t bad : {0U,1U,11U,UINT32_MAX}) {
      reset(start); the_mesh.profile_ms=bad; idle();
      assert(board.absolute_calls==0 && yields==0);
    }
    reset(start); the_mesh.query_work_us=9000; idle();
    assert(board.deadline==static_cast<uint32_t>(start+10000) && board.actual_sleeps==0);
    assert(yields==0 && sdk_sleep_calls==0);
    reset(start); board.ready=false; idle();
    assert(board.absolute_calls==1 && board.actual_sleeps==0 && yields==0);
#if TEST_NATIVE_USB
    reset(start); native_ready=false; idle();
    assert(board.absolute_calls==0 && yields==0);
    native_ready=true; native_setup_us=9000;
    reset(start); idle();
    assert(board.absolute_calls==0 && yields==0); // readiness consumed the original slice
    native_setup_us=0;
#endif
  }
  reset(); the_mesh.dual=false; idle();
  assert(board.absolute_calls==0 && the_mesh.queries==0);
#if TEST_NATIVE_USB
  assert(sdk_timer_calls==1 && sdk_timer_us==10000 && sdk_sleep_calls==1 && yields==0);
#else
  assert(sdk_timer_calls==0 && sdk_sleep_calls==0 && yields==1);
#endif
}
'''


class ActualEsp32RoleHandoffTest(unittest.TestCase):
    def compile_run(self, source, name):
        with tempfile.TemporaryDirectory(prefix="meshcore-private-role-handoff-") as tmp:
            path=Path(tmp)
            (path/"esp_timer.h").write_text("#pragma once\n#include <stdint.h>\nint64_t esp_timer_get_time();\n")
            (path/"test.cpp").write_text(source, encoding="ascii")
            flags=["-std=c++17", "-Wall", "-Wextra", "-Werror", "-Wno-unused-function"]
            if os.name!="nt":
                flags += ["-fsanitize=address,undefined", "-fno-sanitize-recover=all", "-fno-pie", "-no-pie"]
            built=subprocess.run([os.environ.get("CXX","c++"), *flags, "-I",tmp,
                "-I",str(ROOT/"src"),str(path/"test.cpp"),"-o",str(path/"test")],
                capture_output=True,text=True,timeout=60)
            self.assertEqual(built.returncode,0,name+" compile:\n"+built.stdout+built.stderr)
            ran=subprocess.run([str(path/"test")],capture_output=True,text=True,timeout=20)
            self.assertEqual(ran.returncode,0,name+" execute:\n"+ran.stdout+ran.stderr)

    def test_actual_infrastructure_gates_with_production_helper(self):
        for role in ("simple_repeater","simple_room_server","simple_sensor"):
            with self.subTest(role=role):
                source=(ROOT/"examples"/role/"main.cpp").read_text()
                gate=body(source,"  if (can_power_save) {")
                self.compile_run(PRELUDE+"\nvoid idle(bool can_power_save) {\n"+gate+"\n}\n"+INFRA_MAIN,role)

    def test_actual_companion_native_and_uart_gates_with_production_helper(self):
        source=(ROOT/"examples/companion_radio/main.cpp").read_text()
        start=source.index("  // USB power alone")
        end=source.index("#if defined(ESP32) && defined(WIFI_SSID)",start)
        branch=source[start:end]
        fixture=PRELUDE.replace("  uint32_t budget=30000", "  struct Prefs* getNodePrefs();\n"
            "  bool canIdleDualRadio() const { return !dual || profile_ready; }\n"
            "  mesh::powerdiag::Mask pendingWorkReason() const { return 0; }\n"
            "  uint32_t budget=30000")
        fixture=fixture.replace("  unsigned absolute_calls=0", "  bool isUsbSleepHeld() const { return false; }\n"
            "  unsigned absolute_calls=0")
        fixture+=COMPANION_STUBS+"\nPrefs* Mesh::getNodePrefs() { return &prefs; }\n"
        fixture+="void idle() { const bool morse_timing=false;\n"+branch+"\n}\n"+COMPANION_MAIN
        for native in (0,1):
            with self.subTest(native=native):
                self.compile_run(f"#define TEST_NATIVE_USB {native}\n"+fixture,f"companion-native={native}")


if __name__ == "__main__":
    unittest.main()
