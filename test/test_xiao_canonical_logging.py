#!/usr/bin/env python3
"""Canonical QSPI repeater promises must match the compiled USB logger."""

import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
TARGETS = (
    "ikoka_handheld_nrf_e22_30dbm_repeater",
    "ikoka_nano_nrf_22dbm_repeater",
    "ikoka_nano_nrf_30dbm_repeater",
    "ikoka_nano_nrf_33dbm_repeater",
    "ikoka_stick_nrf_22dbm_repeater",
    "ikoka_stick_nrf_30dbm_repeater",
    "ikoka_stick_nrf_33dbm_repeater",
    "Xiao_nrf52_repeater",
    "solarxiao_30S_repeater",
    "solarxiao_33S_repeater",
)


def build_policy(target, *, disable_debug=0, packet="", debug="off",
                 sensor_profile="", infix="", qspi=True):
    # Source only the production helpers. No PlatformIO command is necessary:
    # the three inventory facts below are the helper's board-selection input.
    command = r'''
set -euo pipefail
source build.sh
env_name="$1"
DISABLE_DEBUG="$2"
PACKET_LOGGING_OVERRIDE="$3"
MESHDEBUG_OVERRIDE="$4"
NRF52_OTA_SENSOR_PROFILE="$5"
FIRMWARE_FILENAME_INFIX="$6"
PIO_ENV_PLATFORM_BY_NAME["$env_name"]=NRF52_PLATFORM
PIO_ENV_BOARD_BY_NAME["$env_name"]=seeed-xiao-afruitnrf52-nrf52840
PIO_ENV_QSPI_OTA_BY_NAME["$env_name"]="$7"
BUILD_PROFILE_FOR_TARGET=standard
PLATFORMIO_BUILD_FLAGS=""
BUILD_APPLICATION_EXPECTATIONS=()
disable_debug_flags "$env_name"
apply_debug_overrides "$env_name"
apply_mqtt_bridge_override "$env_name"
disable_usb_logging_for_mqtt "$env_name"
apply_merged_standard_usb_logging_profile "$env_name"
declare_full_logging_application_contract "$env_name"
printf '%s\n' "$PLATFORMIO_BUILD_FLAGS"
printf '%s\n' "${BUILD_APPLICATION_EXPECTATIONS[@]}"
'''
    environment = os.environ.copy()
    # Prevent a caller's global build options from turning a host policy test
    # into a different, unrelated profile.
    for name in ("MQTT_BRIDGE_OVERRIDE", "MQTT_DEBUG_OVERRIDE",
                 "PLATFORMIO_BUILD_FLAGS", "MESHDEBUG_OVERRIDE",
                 "PACKET_LOGGING_OVERRIDE", "DISABLE_DEBUG"):
        environment.pop(name, None)
    result = subprocess.run(
        ["bash", "-c", command, "xiao-logging-policy", target,
         str(disable_debug), packet, debug, sensor_profile, infix,
         "1" if qspi else "0"],
        cwd=ROOT, env=environment, text=True, capture_output=True, check=True,
    )
    lines = result.stdout.splitlines()
    return shlex.split(lines[0]), lines[1:]


class XiaoCanonicalLoggingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.compiler = shutil.which("g++") or shutil.which("c++")
        if cls.compiler is None:
            raise unittest.SkipTest("C++ preprocessor required")
        cls.temporary = tempfile.TemporaryDirectory()
        cls.includes = Path(cls.temporary.name)
        (cls.includes / "Arduino.h").write_text("// No peripherals are needed.\n",
                                              encoding="ascii")
        cls.macros_cache = {}

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def macros(self, flags):
        key = tuple(flags)
        if key in self.macros_cache:
            return self.macros_cache[key]
        # PlatformIO emits define flags before undefine flags. Reproduce that
        # ordering so a trailing -U defeats a superficially correct -D, just
        # as in the failed packaged Full/Reduced images.
        defines = [flag for flag in flags if flag.startswith("-D")]
        undefines = [flag for flag in flags if flag.startswith("-U")]
        result = subprocess.run(
            [self.compiler, "-x", "c++", "-E", "-dM", "-",
             "-DARDUINO=10819", "-DNRF52_PLATFORM=1", "-DUSE_TINYUSB=1",
             "-DMESH_PACKET_LOGGING=1", "-I", str(self.includes),
             "-I", str(ROOT / "src"), *defines, *undefines],
            input='#include <helpers/UsbLogging.h>\n', text=True,
            capture_output=True, check=True,
        )
        macros = {}
        for line in result.stdout.splitlines():
            if line.startswith("#define "):
                parts = line.split(maxsplit=2)
                macros[parts[1]] = parts[2] if len(parts) == 3 else ""
        self.macros_cache[key] = macros
        return macros

    def assert_logger_contract(self, expectations):
        self.assertIn(
            "logging.usb.packets=%s: %s, len=%d (type=%d, route=%s, payload_len=%d)",
            expectations,
        )
        self.assertIn("logging.usb.control=OK - USB logging %s (saved)",
                      expectations)

    def test_canonical_sensor_pairs_keep_logger_with_verbose_debug_disabled(self):
        for target in TARGETS:
            for sensor_profile in ("", "full", "reduced"):
                for disable_debug, packet in ((0, ""), (1, ""), (1, "off"),
                                              (0, "off")):
                    with self.subTest(target=target, sensors=sensor_profile,
                                      disable_debug=disable_debug, packet=packet):
                        flags, expectations = build_policy(
                            target, disable_debug=disable_debug, packet=packet,
                            sensor_profile=sensor_profile,
                            infix="sensor-ota" if sensor_profile else "",
                        )
                        macros = self.macros(flags)
                        self.assertEqual(macros.get("MESH_PACKET_LOGGING"), "1")
                        self.assertEqual(macros.get("MESH_USB_LOGGING_AVAILABLE"), "1")
                        self.assertNotIn("MESH_DEBUG", macros)
                        self.assert_logger_contract(expectations)

    def test_canonical_debug_opt_in_keeps_the_same_packet_contract(self):
        for disable_debug in (0, 1):
            with self.subTest(disable_debug=disable_debug):
                flags, expectations = build_policy(
                    TARGETS[0], disable_debug=disable_debug,
                    debug="on", packet="on",
                )
                macros = self.macros(flags)
                self.assertEqual(macros.get("MESH_PACKET_LOGGING"), "1")
                self.assertEqual(macros.get("MESH_USB_LOGGING_AVAILABLE"), "1")
                if disable_debug:
                    self.assertNotIn("MESH_DEBUG", macros)
                else:
                    self.assertEqual(macros.get("MESH_DEBUG"), "1")
                self.assert_logger_contract(expectations)

    def test_noncanonical_images_still_honor_explicit_logging_off(self):
        cases = (
            (TARGETS[0], {"infix": "custom"}),
            (TARGETS[0], {"qspi": False}),
            ("Xiao_nrf52_room_server", {}),
            ("Xiao_nrf52_repeater_bridge_rs232", {}),
        )
        for target, options in cases:
            for disable_debug, packet in ((1, ""), (0, "off"), (1, "off")):
                with self.subTest(target=target, options=options,
                                  disable_debug=disable_debug, packet=packet):
                    flags, expectations = build_policy(
                        target, disable_debug=disable_debug, packet=packet,
                        **options,
                    )
                    macros = self.macros(flags)
                    self.assertNotIn("MESH_PACKET_LOGGING", macros)
                    self.assertEqual(macros.get("MESH_USB_LOGGING_AVAILABLE"), "0")
                    self.assertFalse(any(item.startswith("logging.usb.")
                                         for item in expectations))


if __name__ == "__main__":
    unittest.main()
