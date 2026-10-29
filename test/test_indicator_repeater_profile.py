"""Resolve the real Indicator repeater recipes without PlatformIO or hardware."""
import configparser
import fnmatch
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
N8 = "SenseCapIndicator-LoRa_repeater"
N16 = "SenseCapIndicator-LoRa-N16R2_repeater"


class IndicatorRepeaterProfileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = configparser.ConfigParser(interpolation=None, strict=False)
        cls.config.read([ROOT / "platformio.ini",
            ROOT / "variants/sensecap_indicator-espnow/platformio.ini"], encoding="ascii")

    def option(self, section, option, depth=0):
        self.assertLess(depth, 30)
        if self.config.has_option(section, option):
            value = self.config.get(section, option)
            return re.sub(r"\$\{([^}]+)\}", lambda match:
                self.option(*match[1].rsplit(".", 1), depth=depth + 1), value)
        for parent in self.config.get(section, "extends", fallback="").split(","):
            if parent.strip():
                try:
                    return self.option(parent.strip(), option, depth + 1)
                except KeyError:
                    pass
        raise KeyError((section, option))

    def flags(self, target):
        return [line.strip() for line in self.option("env:" + target, "build_flags").splitlines()
                if line.strip() and not line.lstrip().startswith((";", "#"))]

    def definitions(self, target):
        definitions = {}
        for flag in self.flags(target):
            match = re.fullmatch(r"-([DU])\s*(\w+)(?:=(.*))?", flag)
            if not match:
                continue
            kind, name, value = match.groups()
            if kind == "U":
                definitions.pop(name, None)
            else:
                definitions[name] = (value or "1").strip("'")
        return definitions

    def selected(self, target, source):
        result = False
        rules = self.option("env:" + target, "build_src_filter")
        for action, pattern in re.findall(r"([+-])<([^>]+)>", rules):
            if "/" not in pattern and "/" in source:
                continue
            match = fnmatch.fnmatchcase(source, pattern)
            if not any(character in pattern for character in "*?["):
                match = match or source.startswith(pattern.rstrip("/") + "/")
            if match:
                result = action == "+"
        return result

    def test_real_radio_and_display_are_retained_in_both_memory_variants(self):
        for target in (N8, N16):
            with self.subTest(target=target):
                definitions = self.definitions(target)
                self.assertIn("SENSECAP_INDICATOR_LORA", definitions)
                self.assertNotIn("MESH_PRIMARY_ESPNOW", definitions)
                self.assertNotIn("DISABLE_WIFI_OTA", definitions)
                self.assertEqual(definitions["WRAPPER_CLASS"], "IndicatorSX1262Wrapper")
                self.assertEqual(definitions["DISPLAY_CLASS"], "SCIndicatorDisplay")
                self.assertEqual(definitions["INDICATOR_WIFI_FONT_RECOVERY"], "1")
                self.assertEqual(definitions["MOTA_HW_ID"], '"' + target[:-9] + '"')
                self.assertEqual([definitions[key] for key in ("P_LORA_NSS", "P_LORA_RESET",
                    "P_LORA_BUSY", "P_LORA_DIO_1")], ["64", "65", "66", "67"])
                for source in ("../examples/simple_repeater/main.cpp", "../examples/simple_repeater/MyMesh.cpp",
                        "../variants/sensecap_indicator-espnow/target.cpp",
                        "../variants/sensecap_indicator-espnow/IndicatorRadioHal.cpp",
                        "../variants/sensecap_indicator-espnow/IndicatorFontClient.cpp",
                        "helpers/ui/LGFXDisplay.cpp", "helpers/ota/OtaContext.cpp",
                        "helpers/esp32/WebConfigServer.cpp"):
                    self.assertTrue(self.selected(target, source), source)
                for source in ("helpers/esp32/ESPNOWRadio.cpp", "../examples/companion_radio/main.cpp"):
                    self.assertFalse(self.selected(target, source), source)
                self.assertIn("AsyncElegantOTA", self.option("env:" + target, "lib_deps"))

    def test_flash_partition_and_psram_modes_are_explicit(self):
        for target, flash, mode, psram, table, size in (
                (N8, "8MB", "qio_opi", "opi", "dual_ota_2560k_preserve_spiffs.csv", "2621440"),
                (N16, "16MB", "qio_qspi", "qspi", "dual_ota_6400k_preserve_spiffs.csv", "6553600")):
            with self.subTest(target=target):
                for key, expected in (("board_upload.flash_size", flash),
                        ("board_build.arduino.memory_type", mode), ("board_build.psram_type", psram),
                        ("board_upload.maximum_size", size)):
                    self.assertEqual(self.option("env:" + target, key), expected)
                self.assertEqual(self.option("env:" + target, "board_build.partitions"),
                    "variants/sensecap_indicator-espnow/" + table)

    def test_actual_full_overlay_uses_lora_not_overridden_primary_espnow_flag(self):
        rows = [["env:" + target, [["build_flags", self.flags(target)]]] for target in (N8, N16)]
        environment = dict(os.environ, INDICATOR_TEST_CONFIG=json.dumps(rows))
        script = r'''
set -euo pipefail
source build.sh
PIO_CONFIG_JSON=$INDICATOR_TEST_CONFIG
for target in SenseCapIndicator-LoRa_repeater SenseCapIndicator-LoRa-N16R2_repeater; do
  PIO_ENV_PLATFORM_BY_NAME[$target]=ESP32_PLATFORM
  PIO_ENV_BOARD_BY_NAME[$target]=esp32-s3-devkitc-1
  PIO_ENV_FULL_BUILD_BY_NAME[$target]=1
  PIO_ENV_MQTT_BY_NAME[$target]=0
  supports_esp32_full_shared_espnow "$target"
  is_esp32_full_only_bulk_target "$target"
  [[ $(get_exact_identity_full_pio_env "$target") == "$target" ]]
  ESP32_FULL_BUILD=1
  PLATFORMIO_BUILD_FLAGS=''
  PLATFORMIO_BUILD_SRC_FILTER=''
  apply_esp32_full_shared_bridge_profile "$target"
  [[ $PLATFORMIO_BUILD_FLAGS == *-DWITH_UDP_BRIDGE=1* ]]
  [[ $PLATFORMIO_BUILD_FLAGS == *-DWITH_ESPNOW_BRIDGE=1* ]]
  [[ $PLATFORMIO_BUILD_SRC_FILTER == *UDPBridgeSettings.cpp* ]]
done
PIO_CONFIG_JSON='[["env:bad", [["build_flags", ["-DMESH_PRIMARY_ESPNOW=1", "-UMESH_PRIMARY_ESPNOW", "-DMESH_PRIMARY_ESPNOW=1"]]]]]'
pio_env_has_effective_define bad MESH_PRIMARY_ESPNOW
PIO_CONFIG_JSON='[["env:bad", [["build_flags", ["-DMESH_ESPNOW_RADIO=1"]]]]]'
pio_env_has_effective_define bad MESH_ESPNOW_RADIO
'''
        result = subprocess.run(["bash", "-c", script], cwd=ROOT, env=environment,
            capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
