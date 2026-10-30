#!/usr/bin/env python3
"""Run the nRF52 LED policy and patched Bluefruit timer callback on the host."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = spec_from_file_location("nrf52_led_patch", ROOT / "scripts/nrf52_ble_cccd_fix.py")
PATCH = module_from_spec(SPEC)
SPEC.loader.exec_module(PATCH)

ARDUINO = r'''
#pragma once
#include <cassert>
#include <cstdint>
#define PINS_COUNT 64
#define OUTPUT 1
extern int led_level, writes;
inline int digitalPinToPinName(int pin) { return pin == 62 ? 0xff : pin; }
inline bool validPin(int pin) {
  return pin >= 0 && pin < PINS_COUNT && digitalPinToPinName(pin) != 0xff;
}
inline void digitalWrite(int pin, int value) {
  assert(validPin(pin));
  led_level = value;
  ++writes;
}
inline void digitalToggle(int pin) { digitalWrite(pin, !led_level); }
inline void pinMode(int pin, int) { assert(validPin(pin)); }
'''

BLUEFRUIT = r'''
#pragma once
#include <Arduino.h>
using TimerHandle_t = void*;
struct Advertiser {
  bool running = false;
  bool isRunning() const { return running; }
};
struct AdafruitBluefruit {
  bool ready = false, automatic = true, linked = false;
  bool _led_conn = true;
  int timer_starts = 0, timer_stops = 0, connection_queries = 0;
  Advertiser Advertising;
  void autoConnLed(bool enabled) {
    automatic = _led_conn = enabled;
    if (!enabled && ready) ++timer_stops;
  }
  unsigned connected() {
    assert(ready);
    ++connection_queries;
    return linked;
  }
  void _startConnLed() {
    assert(ready);
    if (automatic) ++timer_starts;
  }
#ifdef EXTERNAL_LED_METHOD
  void _setConnLed(bool on);
#else
  void _setConnLed(bool on) {
    assert(ready);
#ifdef LED_BLUE
    if (automatic) digitalWrite(LED_BLUE, on ? LED_STATE_ON : !LED_STATE_ON);
#else
    (void)on;
#endif
  }
#endif
};
using MockBluefruit = AdafruitBluefruit;
extern MockBluefruit Bluefruit;
'''

# Exact callback from the pinned Adafruit nRF52 Bluefruit52Lib/src/bluefruit.cpp.
# The build middleware patches this body in its private framework copy.
CALLBACK = r'''#include "bluefruit.h"
static void bluefruit_blinky_cb( TimerHandle_t xTimer )
{
  (void) xTimer;
  digitalToggle(LED_BLUE);
}

void AdafruitBluefruit::_setConnLed (bool on_off)
{
  if (_led_conn)
  {
    digitalWrite(LED_BLUE, on_off ? LED_STATE_ON : (1-LED_STATE_ON) );
  }
}
'''

HARNESS = r'''
#include <helpers/nrf52/BluetoothLed.h>
MockBluefruit Bluefruit;
int led_level = LED_STATE_ON, writes = 0;
int main() {
#if defined(DISABLE_BLE_LED) || !defined(LED_BLUE)
  const bool supported = false;
#else
  const bool supported = validPin(LED_BLUE);
#endif
  // With the default enabled preference, the helper may configure the owner
  // before begin(), but must not query a connection or start a missing timer.
  mesh_nrf52::applyBluetoothLedPolicy();
  assert(Bluefruit.automatic == supported);
  assert(Bluefruit.timer_starts == 0 && Bluefruit.timer_stops == 0);
  assert(Bluefruit.connection_queries == 0);

  // Saved preferences are applied before begin() has created an LED timer.
  mesh::leds::setEnabled(false);
  mesh_nrf52::applyBluetoothLedPolicy();
  assert(!Bluefruit.automatic);
  assert(Bluefruit.timer_starts == 0 && Bluefruit.timer_stops == 0);
  assert(Bluefruit.connection_queries == 0);
#if defined(LED_BLUE)
  if (validPin(LED_BLUE)) assert(led_level == !LED_STATE_ON);
#endif

  // A later stack start must preserve the off preference.
  Bluefruit.ready = true;
  Bluefruit.Advertising.running = true;
  mesh_nrf52::bluetoothLedStarted();
  assert(!Bluefruit.automatic && Bluefruit.timer_starts == 0);

  // Enabling again restores the current state without restarting Bluetooth.
  mesh::leds::setEnabled(true);
  mesh_nrf52::applyBluetoothLedPolicy();
  assert(Bluefruit.automatic == supported);
  if (supported) {
    assert(Bluefruit.timer_starts == 1);
    assert(led_level == !LED_STATE_ON);
  } else {
    assert(Bluefruit.timer_starts == 0);
  }

  Bluefruit.Advertising.running = false;
  Bluefruit.linked = true;
  mesh_nrf52::applyBluetoothLedPolicy();
#if defined(RAK_BOARD) && defined(BLE_PIN_CODE)
  if (supported) assert(led_level == !LED_STATE_ON);
#else
  if (supported) assert(led_level == LED_STATE_ON);
#endif
  mesh::leds::setEnabled(false);
  mesh_nrf52::applyBluetoothLedPolicy();
  assert(!Bluefruit.automatic);
#ifdef LED_BLUE
  if (validPin(LED_BLUE)) assert(led_level == !LED_STATE_ON);
  else assert(writes == 0);
#else
  assert(writes == 0);
#endif
}
'''

TIMER_HARNESS = r'''
MockBluefruit Bluefruit;
int led_level = LED_STATE_ON, writes = 0;
int main() {
  Bluefruit.ready = true;
  // A previously queued callback can still arrive after autoConnLed(false).
  mesh::leds::setEnabled(false);
  for (int i = 0; i < 4; ++i) {
    bluefruit_blinky_cb(nullptr);
    if (validPin(LED_BLUE)) assert(led_level == !LED_STATE_ON);
  }
  Bluefruit._setConnLed(true);
  if (validPin(LED_BLUE)) assert(led_level == !LED_STATE_ON);
  mesh::leds::setEnabled(true);
  bluefruit_blinky_cb(nullptr);
#ifdef DISABLE_BLE_LED
  if (validPin(LED_BLUE)) assert(led_level == !LED_STATE_ON);
#else
  if (validPin(LED_BLUE)) assert(led_level == LED_STATE_ON);
#endif
  // PR #2694: advertising still blinks on a RAK Companion, but connecting
  // leaves the LED dark. Other boards retain the steady connected indicator.
  Bluefruit.linked = true;
  Bluefruit._setConnLed(true);
#if defined(DISABLE_BLE_LED) || (defined(RAK_BOARD) && defined(BLE_PIN_CODE))
  if (validPin(LED_BLUE)) assert(led_level == !LED_STATE_ON);
#else
  if (validPin(LED_BLUE)) assert(led_level == LED_STATE_ON);
#endif
#if defined(RAK_BOARD) && defined(BLE_PIN_CODE)
  // Stopping the advertising timer is asynchronous. Any callback already
  // queued when the connection completes must leave the RAK indicator dark.
  for (int i = 0; i < 4; ++i) {
    bluefruit_blinky_cb(nullptr);
    if (validPin(LED_BLUE)) assert(led_level == !LED_STATE_ON);
  }
#endif
  Bluefruit.linked = false;
  Bluefruit._setConnLed(false);
  if (validPin(LED_BLUE)) assert(led_level == !LED_STATE_ON);
#if defined(RAK_BOARD) && defined(BLE_PIN_CODE)
  // A later disconnection lets the existing advertising timer blink again.
  bluefruit_blinky_cb(nullptr);
#ifdef DISABLE_BLE_LED
  if (validPin(LED_BLUE)) assert(led_level == !LED_STATE_ON);
#else
  if (validPin(LED_BLUE)) assert(led_level == LED_STATE_ON);
#endif
#endif
  if (!validPin(LED_BLUE)) assert(writes == 0);
}
'''


def compile_run(case, source, defines, expect_success=True):
    if "AdafruitBluefruit::_setConnLed" in source:
        defines = [*defines, "EXTERNAL_LED_METHOD"]
    compiler = shutil.which("c++") or shutil.which("g++")
    case.assertIsNotNone(compiler, "run this host suite where c++ is available")
    with tempfile.TemporaryDirectory(prefix="mesh-nrf52-led-policy-") as folder:
        folder = Path(folder)
        (folder / "Arduino.h").write_text(ARDUINO)
        (folder / "bluefruit.h").write_text(BLUEFRUIT)
        (folder / "case.cpp").write_text(source)
        binary = folder / ("case.exe" if os.name == "nt" else "case")
        built = subprocess.run([
            compiler, "-std=c++11", "-Wall", "-Wextra", "-Werror",
            "-I", str(folder), "-I", str(ROOT / "src"),
            *["-D" + value for value in defines], str(folder / "case.cpp"),
            "-o", str(binary)], text=True, capture_output=True, timeout=30)
        case.assertEqual(built.returncode, 0, built.stderr)
        result = subprocess.run([str(binary)], text=True, capture_output=True, timeout=10)
        if expect_success:
            case.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        else:
            case.assertNotEqual(result.returncode, 0, "negative control did not fail")


class Nrf52LedPolicyTests(unittest.TestCase):
    def test_policy_before_start_and_during_advertising_and_connection(self):
        for polarity in (0, 1):
            for disabled in (False, True):
                defines = ["LED_BLUE=12", f"LED_STATE_ON={polarity}"]
                if disabled:
                    defines.append("DISABLE_BLE_LED")
                with self.subTest(polarity=polarity, disabled=disabled):
                    compile_run(self, HARNESS, defines)

    def test_absent_and_unmapped_pins_never_enable_bluefruit_led(self):
        for pin in (None, "-1", "255", "PINS_COUNT", "62"):
            defines = ["LED_STATE_ON=0"] + ([] if pin is None else ["LED_BLUE=" + pin])
            with self.subTest(pin=pin):
                compile_run(self, HARNESS, defines)

    def test_rak_companion_policy_leaves_connection_indicator_off(self):
        # https://github.com/meshcore-dev/MeshCore/pull/2694
        for flags in (["RAK_BOARD"], ["BLE_PIN_CODE=123456"],
                      ["RAK_BOARD", "BLE_PIN_CODE=123456"]):
            with self.subTest(flags=flags):
                compile_run(self, HARNESS, ["LED_BLUE=12", "LED_STATE_ON=0", *flags])

    def test_pending_callback_respects_saved_policy_and_compile_time_disable(self):
        source = PATCH.patched_led_source(CALLBACK) + TIMER_HARNESS
        for polarity in (0, 1):
            for disabled in (False, True):
                defines = ["LED_BLUE=12", f"LED_STATE_ON={polarity}"]
                if disabled:
                    defines.append("DISABLE_BLE_LED")
                with self.subTest(polarity=polarity, disabled=disabled):
                    compile_run(self, source, defines)

    def test_pending_callback_ignores_invalid_pins(self):
        source = PATCH.patched_led_source(CALLBACK) + TIMER_HARNESS
        for pin in ("-1", "255", "PINS_COUNT", "62"):
            with self.subTest(pin=pin):
                compile_run(self, source, ["LED_BLUE=" + pin, "LED_STATE_ON=0"])

    def test_rak_companion_blinks_while_advertising_then_goes_dark(self):
        source = PATCH.patched_led_source(CALLBACK) + TIMER_HARNESS
        for flags in (["RAK_BOARD"], ["BLE_PIN_CODE=123456"],
                      ["RAK_BOARD", "BLE_PIN_CODE=123456"],
                      ["RAK_BOARD", "BLE_PIN_CODE=123456", "DISABLE_BLE_LED"]):
            for polarity in (0, 1):
                with self.subTest(flags=flags, polarity=polarity):
                    compile_run(self, source,
                                ["LED_BLUE=12", f"LED_STATE_ON={polarity}", *flags])

    def test_unpatched_callback_negative_control(self):
        compile_run(self, "#include <helpers/LedPolicy.h>\n" + CALLBACK + TIMER_HARNESS,
                    ["LED_BLUE=12", "LED_STATE_ON=0"], expect_success=False)

    def test_patch_is_idempotent_and_rejects_unrecognized_callback(self):
        patched = PATCH.patched_led_source(CALLBACK)
        self.assertEqual(PATCH.patched_led_source(patched), patched)
        with self.assertRaises(RuntimeError):
            PATCH.patched_led_source(CALLBACK.replace("digitalToggle(LED_BLUE);", "changed();"))


if __name__ == "__main__":
    unittest.main()
