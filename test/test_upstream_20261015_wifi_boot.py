#!/usr/bin/env python3
"""Keep upstream dynamic-WiFi flags on the Companion's existing boot policy."""
from pathlib import Path
import subprocess
import tempfile
import unittest

from test_t114_autodisplay_recipes import defines
from test_upstream_observer_recipes import Recipes
from test_replay_reset_integration import extract_braced


ROOT = Path(__file__).resolve().parents[1]
COMPANION = ROOT / "examples/companion_radio"


class DynamicWiFiBootContractTest(unittest.TestCase):
    def test_new_ble_wifi_recipes_keep_dynamic_setup_and_queue_capacity(self):
        recipes = Recipes()
        for name in (
            "heltec_v4_tft_companion_radio_ble_femon",
            "heltec_v4_3_tft_companion_radio_ble_femoff",
            "heltec_v4_expansionkit_tft_companion_radio_ble_femon",
            "heltec_v4_3_expansionkit_tft_companion_radio_ble_femoff",
            "T_Beam_S3_Supreme_SX1262_companion_radio_ble",
            "T_Beam_S3_Supreme_SX1262_companion_radio_ble_ps",
        ):
            with self.subTest(target=name):
                section = "env:" + name
                flags = defines(recipes.value(section, "build_flags"))
                self.assertEqual(flags["ENABLE_WIFI_INTERFACE"], "1")
                self.assertEqual(flags["BLE_PIN_CODE"], "123456")
                self.assertEqual(flags["OFFLINE_QUEUE_SIZE"], "512")
                self.assertNotIn("WIFI_SSID", flags)
                self.assertNotIn("WIFI_PWD", flags)
                for source in ("helpers/wifi/SerialWifiInterface.cpp",
                               "helpers/WiFiSetupPortal.cpp",
                               "helpers/esp32/WiFiOtaSeeder.cpp"):
                    self.assertTrue(recipes.includes(section, source), source)

    def test_dynamic_wifi_helpers_link_without_companion_header_normalization(self):
        portal = (ROOT / "src/helpers/WiFiSetupPortal.cpp").read_text()
        seeder = (ROOT / "src/helpers/esp32/WiFiOtaSeeder.cpp").read_text()

        def guard(source):
            lines = iter(source.splitlines())
            line = next(line for line in lines if line.startswith("#if "))
            result = line
            while line.endswith("\\"):
                line = next(lines)
                result += "\n" + line
            return result

        helper_source = '''
#include <helpers/WiFiSetupPortal.h>
#include <helpers/esp32/WiFiOtaSeeder.h>
#include <helpers/CLICommandUtils.h>
#include <Preferences.h>
#include <strings.h>
@PORTAL_GUARD@
@PORTAL_METHODS@
#endif
@SEEDER_GUARD@
namespace mesh { namespace ota {
static bool listener_active = true, tcp_folder_attached = false;
@SEEDER_METHODS@
} }
#endif
'''.replace("@PORTAL_GUARD@", guard(portal)).replace("@SEEDER_GUARD@", guard(seeder))
        helper_source = helper_source.replace("@PORTAL_METHODS@", "\n".join(
            extract_braced(portal, signature) for signature in (
                "bool WiFiSetupPortal::loadStoredCredentials(",
                "bool WiFiSetupPortal::isPlaceholderSSID(")))
        helper_source = helper_source.replace("@SEEDER_METHODS@", "\n".join(
            extract_braced(seeder, signature) for signature in (
                "bool WiFiOtaSeeder::isListening(", "bool WiFiOtaSeeder::isAttached(")))
        caller = '''
#include <helpers/WiFiSetupPortal.h>
#include <helpers/esp32/WiFiOtaSeeder.h>
#include <Preferences.h>
#include <cassert>
#if @PORTAL@
static void portalTest() {
  assert(WiFiSetupPortal::isPlaceholderSSID(""));
  assert(!WiFiSetupPortal::isPlaceholderSSID("mesh"));
  char ssid[32] = {}, password[65] = {};
  assert(!WiFiSetupPortal::loadStoredCredentials(ssid, sizeof(ssid), password, sizeof(password)));
  nvs_values["ssid"] = {PT_STR, "mesh", 0};
  nvs_values["password"] = {PT_STR, "password", 0};
  assert(WiFiSetupPortal::loadStoredCredentials(ssid, sizeof(ssid), password, sizeof(password)));
}
#else
class WiFiSetupPortal {}; // disabled declarations must stay absent
#endif
#if @SEEDER@
static void seederTest() {
  assert(mesh::ota::WiFiOtaSeeder::isListening());
  assert(!mesh::ota::WiFiOtaSeeder::isAttached());
}
#else
namespace mesh { namespace ota { class WiFiOtaSeeder {}; } }
#endif
int main() {
#if @PORTAL@
  portalTest();
#endif
#if @SEEDER@
  seederTest();
#endif
}
'''
        cases = (
            (("ESP32_PLATFORM", "ENABLE_WIFI_INTERFACE", "ENABLE_OTA=1"), 1, 1),
            (("ESP32_PLATFORM", 'WIFI_SSID="legacy"', "ENABLE_OTA=1"), 1, 1),
            (("ESP32_PLATFORM", "ENABLE_OTA=1"), 0, 0),
            (("ESP32_PLATFORM", "ENABLE_WIFI_INTERFACE"), 1, 0),
            (("ESP32_PLATFORM", "WIFI_OTA_SEEDER", "ENABLE_OTA=1"), 0, 1),
            (("NRF52_PLATFORM", "ENABLE_WIFI_INTERFACE", "ENABLE_OTA=1"), 0, 0),
        )
        with tempfile.TemporaryDirectory(prefix="dynamic-wifi-helpers-") as temporary:
            folder = Path(temporary)
            (folder / "Arduino.h").write_text("#pragma once\n#include <stddef.h>\n#include <stdint.h>\n")
            (folder / "IPAddress.h").write_text(
                "#pragma once\nstruct IPAddress { IPAddress(int,int,int,int) {} };\n")
            (folder / "Preferences.h").write_text(
                (ROOT / "test/fixtures/wifi_credentials_preferences.h").read_text())
            helper = folder / "helpers.cpp"
            helper.write_text(helper_source)
            for index, (flags, has_portal, has_seeder) in enumerate(cases):
                with self.subTest(defines=flags):
                    main = folder / "main.cpp"
                    main.write_text(caller.replace("@PORTAL@", str(has_portal))
                                    .replace("@SEEDER@", str(has_seeder)))
                    binary = folder / str(index)
                    built = subprocess.run([
                        "c++", "-std=c++17", "-Wall", "-Wextra", "-Werror",
                        "-I", str(folder), "-I", str(ROOT / "src"),
                        *["-D" + flag for flag in flags], str(helper), str(main),
                        "-o", str(binary),
                    ], text=True, capture_output=True, timeout=30)
                    self.assertEqual(built.returncode, 0, built.stderr)
                    ran = subprocess.run([str(binary)], capture_output=True, text=True, timeout=10)
                    self.assertEqual(ran.returncode, 0, ran.stderr)

    def test_real_include_order_normalizes_before_feature_selection(self):
        mesh = (COMPANION / "MyMesh.h").read_text()
        abstract = (COMPANION / "AbstractUITask.h").read_text()
        self.assertLess(mesh.index('#include "AbstractUITask.h"'),
                        mesh.index('#include "CompanionFeatures.h"'))
        self.assertIn('#include "NodePrefs.h"', abstract)
        # Execute the actual normalization directives, omitting only the SDK
        # types after the first include, then include the real feature header.
        prefs = (COMPANION / "NodePrefs.h").read_text()
        normalization = prefs[:prefs.index("#include <Arduino.h>")].replace("#pragma once", "")
        implementation = (COMPANION / "MyMesh.cpp").read_text()
        end = implementation.index("  _prefs.wifi_enabled = 1;")
        start = implementation.rfind("#if", 0, end)
        end = implementation.index("#endif", end) + len("#endif")
        wifi_defaults = implementation[start:end]
        bluetooth_default = "  _prefs.bluetooth_enabled = 1;"
        self.assertIn(bluetooth_default, implementation)
        cases = (
            # defines, terminal feature, WiFi macro, default WiFi, default SSID
            (("ESP32_PLATFORM", "ENABLE_WIFI_INTERFACE", "BLE_PIN_CODE=123456"), 1, 1, 0, ""),
            (("ESP32_PLATFORM", "ENABLE_WIFI_INTERFACE", "BLE_PIN_CODE=123456", "ENABLE_USB_INTERFACE"), 1, 1, 0, ""),
            (("ESP32_PLATFORM", "ENABLE_WIFI_INTERFACE"), 1, 1, 1, ""),
            (("ESP32_PLATFORM", "BLE_PIN_CODE=123456"), 0, 0, 0, ""),
            (("ESP32_PLATFORM", "ENABLE_WIFI_INTERFACE", "BLE_PIN_CODE=123456", 'WIFI_SSID="saved-build-ssid"'), 1, 1, 0, "saved-build-ssid"),
            (("ESP32_PLATFORM", "ENABLE_WIFI_INTERFACE", "BLE_PIN_CODE=123456", "WEBCONFIG_DISABLED"), 0, 1, 0, ""),
            (("NRF52_PLATFORM", "BLE_PIN_CODE=123456"), 0, 0, 0, ""),
        )
        with tempfile.TemporaryDirectory(prefix="dynamic-wifi-boot-") as directory:
            for index, (defines, terminal, has_wifi, wifi_on, ssid) in enumerate(cases):
                with self.subTest(defines=defines):
                    program = normalization + r'''
#include "examples/companion_radio/CompanionFeatures.h"
#include <cassert>
#include <cstring>
static_assert(COMPANION_FEATURE_TEXT_TERMINAL == @TERMINAL@,
              "dynamic WiFi must expose WebConfig's text terminal");
#if @HAS_WIFI@
#ifndef WIFI_SSID
#error Dynamic WiFi must enter the existing WIFI_SSID boot routing
#endif
static_assert(sizeof(WIFI_SSID) == sizeof("@SSID@"), "keep credentials unchanged");
#else
#ifdef WIFI_SSID
#error Do not invent WiFi support on an ordinary BLE-only target
#endif
#endif
#ifdef WIFI_PWD
#error Enabling the interface must not inject WiFi credentials
#endif
int main() {
  struct { int wifi_enabled = -1, bluetooth_enabled = -1; } _prefs;
@WIFI_DEFAULTS@
@BLUETOOTH_DEFAULT@
  assert(_prefs.wifi_enabled == @WIFI_ON@);
  assert(_prefs.bluetooth_enabled == 1);
#if @HAS_WIFI@
  assert(strcmp(WIFI_SSID, "@SSID@") == 0);
#endif
}
'''
                    for key, value in {
                        "TERMINAL": terminal, "HAS_WIFI": has_wifi,
                        "SSID": ssid, "WIFI_ON": wifi_on,
                        "WIFI_DEFAULTS": wifi_defaults,
                        "BLUETOOTH_DEFAULT": bluetooth_default,
                    }.items():
                        program = program.replace("@" + key + "@", str(value))
                    binary = Path(directory) / str(index)
                    built = subprocess.run([
                        "c++", "-std=c++17", "-Wall", "-Wextra", "-Werror",
                        "-I", str(ROOT), "-I", str(ROOT / "src"),
                        *["-D" + define for define in defines],
                        "-x", "c++", "-", "-o", str(binary),
                    ], input=program, text=True, capture_output=True, timeout=30)
                    self.assertEqual(built.returncode, 0, built.stderr)
                    ran = subprocess.run([str(binary)], capture_output=True,
                                         text=True, timeout=10)
                    self.assertEqual(ran.returncode, 0, ran.stderr)


if __name__ == "__main__":
    unittest.main()
