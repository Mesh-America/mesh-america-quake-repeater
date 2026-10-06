#!/usr/bin/env python3
"""Execute Full defaults and the actual Companion idle branch with host fakes."""

from pathlib import Path
import os
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def function(source, signature):
    start = source.index(signature)
    opening = source.index("{", start)
    depth = 0
    for end in range(opening, len(source)):
        depth += (source[end] == "{") - (source[end] == "}")
        if depth == 0:
            return source[start:end + 1]
    raise AssertionError(signature)


def run_cpp(source, defines=()):
    with tempfile.TemporaryDirectory(prefix="mesh-full-sleep-") as directory:
        cpp = Path(directory) / "test.cpp"
        exe = Path(directory) / "test"
        cpp.write_text(source)
        built = subprocess.run(
            [os.environ.get("CXX", "c++"), "-std=c++17", "-Wall", "-Wextra",
             "-I", str(ROOT / "src"),
             *("-D" + flag for flag in defines), str(cpp), "-o", str(exe)],
            text=True, capture_output=True)
        if built.returncode:
            raise AssertionError(built.stderr)
        return subprocess.run([str(exe)], text=True, capture_output=True)


class FullSleepTest(unittest.TestCase):
    def test_full_optional_logging_starts_off_and_saved_intent_wins(self):
        cli = (ROOT / "src/helpers/CommonCLI.cpp").read_text()
        start = cli.index("#if defined(ESP32_PLATFORM) && defined(MESHCORE_EXPANDED_PARTITION_PROFILE)",
                          cli.index("void CommonCLI::loadPrefs("))
        default = cli[start:cli.index("  _prefs->usb_debug_enabled", start)]
        logger = (ROOT / "src/helpers/UsbLogging.cpp").read_text()
        start = logger.index("#if defined(ENABLE_USB_INTERFACE)", logger.index("namespace mesh {"))
        early = logger[start:logger.index("static std::atomic<bool> usb_logging_preference_known", start)]
        # Execute the real persisted-byte read; neither a fresh default nor an
        # upgrade is allowed to silently discard an explicit logging choice.
        persisted = ""
        for line in cli.splitlines():
            if "file.read" in line and "usb_logging_enabled" in line:
                start = cli.index(line.strip())
                persisted = cli[start:cli.index(";", start) + 1]
                break
        self.assertTrue(persisted)
        source = r'''
#include <atomic>
#include <cassert>
#include <cstdint>
@EARLY@
struct Prefs { uint8_t usb_logging_enabled = 99; } prefs;
struct File { uint8_t value; void read(uint8_t* out, unsigned) { *out = value; } } file;
int main() {
  auto* _prefs = &prefs;
  @DEFAULT@
  assert(prefs.usb_logging_enabled == EXPECTED_DEFAULT);
  assert(usb_logging_enabled.load() == (EXPECTED_DEFAULT != 0));
  file.value = 1;
  @PERSISTED@
  assert(prefs.usb_logging_enabled == 1);
  file.value = 0;
  @PERSISTED@
  assert(prefs.usb_logging_enabled == 0);
}
'''.replace("@EARLY@", early).replace("@DEFAULT@", default).replace("@PERSISTED@", persisted)
        for flags in (("ESP32_PLATFORM", "MESHCORE_EXPANDED_PARTITION_PROFILE", "EXPECTED_DEFAULT=0"),
                      ("ESP32_PLATFORM", "EXPECTED_DEFAULT=1"),
                      ("MESHCORE_EXPANDED_PARTITION_PROFILE", "EXPECTED_DEFAULT=1")):
            with self.subTest(flags=flags):
                result = run_cpp(source, flags)
                self.assertEqual(result.returncode, 0, result.stderr)
        broken = run_cpp(source.replace("_prefs->usb_logging_enabled = 0;",
                                        "_prefs->usb_logging_enabled = 1;"),
                         ("ESP32_PLATFORM", "MESHCORE_EXPANDED_PARTITION_PROFILE", "EXPECTED_DEFAULT=0"))
        self.assertNotEqual(broken.returncode, 0)

    def test_compiled_full_transports_do_not_exclude_runtime_idle_sleep(self):
        main = (ROOT / "examples/companion_radio/main.cpp").read_text()
        ready = function(main, "static bool companionNativeUsbLightSleepReady()")
        usb_held = function((ROOT / "src/helpers/ESP32Board.h").read_text(),
                            "bool isUsbSleepHeld()")
        start = main.index("  // USB power alone")
        end = main.index("#if defined(ESP32) && defined(WIFI_SSID)",
                         main.index("else if (the_mesh.getNodePrefs()->powersaving_enabled)", start))
        branch = main[start:end]
        source = r'''
#include <cassert>
#include <cstdint>
#include <helpers/UsbHostSleepPolicy.h>
static uint32_t now = 1000;
uint32_t millis() { return now; }
using esp_err_t = int;
enum wifi_mode_t { WIFI_MODE_NULL, WIFI_MODE_STA, WIFI_MODE_AP, WIFI_MODE_APSTA };
constexpr int ESP_OK = 0, ESP_ERR_WIFI_NOT_INIT = 1, ESP_ERR_WIFI_NOT_STARTED = 2;
static wifi_mode_t sdk_mode = WIFI_MODE_NULL;
static int sdk_result = ESP_OK, sleeps = 0, yields = 0;
constexpr int ESP_BT_CONTROLLER_STATUS_ENABLED = 1;
static bool bt_controller_active = false;
int esp_bt_controller_get_status() { return bt_controller_active ? 1 : 0; }
constexpr int ESP_BLUEDROID_STATUS_ENABLED = 1;
static bool bt_host_active = false;
int esp_bluedroid_get_status() { return bt_host_active ? 1 : 0; }
int esp_wifi_get_mode(wifi_mode_t* mode) { *mode = sdk_mode; return sdk_result; }
int esp_sleep_enable_timer_wakeup(uint64_t us) { assert(us == 10000); return ESP_OK; }
int esp_light_sleep_start() { ++sleeps; return ESP_OK; }
int pdMS_TO_TICKS(int ms) { return ms; }
void vTaskDelay(int) { ++yields; }
void delay(int) { ++yields; }
struct Board {
  bool host = false, ota = false, test = false;
  mesh::UsbHostSleepPolicy usb_host_sleep_policy;
  bool isUsbHostConnected() { usb_host_sleep_policy.observe(host, millis()); return host; }
  @USB_HELD@
  bool isOTAUpdateRunning() const { return ota; }
  bool isRadioTestActive() const { return test; }
} board;
struct Prefs { bool powersaving_enabled = true; } prefs;
struct Mesh {
  bool pending = false;
  Prefs* getNodePrefs() { return &prefs; }
  bool hasPendingWork() const { return pending; }
} the_mesh;
struct Interfaces { bool pending = false; bool hasPendingIO() const { return pending; } } interface_manager;
struct Sensors { bool gps_uart = false; bool gpsUsesSerialUart(uint8_t uart) const { return uart == 1 && gps_uart; } } sensors;
struct Button { bool polling = false; bool needsPolling() const { return polling; } } user_btn;
struct Wireless { unsigned services = 0; unsigned enabled() const { return services; } } companion_wireless;
namespace mesh {
bool logging = false, watchdog = false;
bool isUsbLoggingEnabled() { return logging; }
bool isUsbLoggingWatchdogArmed() { return watchdog; }
namespace wireless {
struct Control { bool transition = false; bool pending() const { return transition; } } controller;
Control& control() { return controller; }
}
}
@READY@
void idle() { @BRANCH@ }
template<class T> void blocks(T& flag) {
  flag = true; int before = sleeps; idle(); assert(sleeps == before); flag = false;
}
int main() {
  idle(); assert(sleeps == 1);
  for (unsigned service : {1u, 2u, 4u}) {
    companion_wireless.services = service; int before = sleeps; idle(); assert(sleeps == before);
  }
  companion_wireless.services = 0;
  for (wifi_mode_t mode : {WIFI_MODE_STA, WIFI_MODE_AP, WIFI_MODE_APSTA}) {
    sdk_mode = mode; int before = sleeps; idle(); assert(sleeps == before);
  }
  sdk_mode = WIFI_MODE_NULL;
  for (int result : {ESP_ERR_WIFI_NOT_INIT, ESP_ERR_WIFI_NOT_STARTED}) {
    sdk_result = result; int before = sleeps; idle(); assert(sleeps == before + 1);
  }
  sdk_result = 99; int before = sleeps; idle(); assert(sleeps == before); sdk_result = ESP_OK;
  blocks(board.ota); blocks(board.test); blocks(the_mesh.pending);
  blocks(interface_manager.pending); blocks(user_btn.polling); blocks(mesh::logging);
  blocks(bt_controller_active);
  blocks(bt_host_active); blocks(sensors.gps_uart);
  blocks(mesh::watchdog); blocks(mesh::wireless::controller.transition);
  prefs.powersaving_enabled = false; before = sleeps; idle(); assert(sleeps == before);
  prefs.powersaving_enabled = true; idle(); assert(sleeps == before + 1);
  // The real board policy must observe USB even while pending work/logging
  // inhibit this branch. A rebooting host cannot disappear for one SOF gap
  // and cause Full to shut down its console immediately.
  the_mesh.pending = true; board.host = true; idle();
  board.host = false; the_mesh.pending = false; now += 6;
  before = sleeps; idle(); assert(sleeps == before);
  now += 120000; idle(); assert(sleeps == before + 1);
}
'''.replace("@READY@", ready).replace("@BRANCH@", branch).replace("@USB_HELD@", usb_held)
        source = "#include <initializer_list>\n" + source
        flags = ("ESP32_PLATFORM", "ESP32", "ENABLE_USB_INTERFACE", "ARDUINO_USB_CDC_ON_BOOT=1",
                 'WIFI_SSID=""', "BLE_PIN_CODE=123456", "MESH_USB_LOGGING_AVAILABLE=1",
                 "CONFIG_BLUEDROID_ENABLED=1",
                 "MESH_ESP32_USB_CONSOLE_COOPERATIVE=1", "MESH_ESP32_USB_HOST_LOSS_SLEEP_GRACE_MS=120000UL",
                 "MOMENTARY_BUTTON_WAKE_FROM_SLEEP=1", "PIN_USER_BTN=0", "DISPLAY_CLASS=Mock")
        for pm in (0, 1):
            with self.subTest(pm=pm):
                result = run_cpp(source, (*flags, f"COMPANION_IDF_PM_AVAILABLE={pm}"))
                self.assertEqual(result.returncode, 0, result.stderr)
        broken = run_cpp(source.replace("companion_wireless.enabled() != 0", "false"),
                         (*flags, "COMPANION_IDF_PM_AVAILABLE=0"))
        self.assertNotEqual(broken.returncode, 0)


if __name__ == "__main__":
    unittest.main()
