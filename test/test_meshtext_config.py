"""Check effective feature guards without overriding Meshtext enablement.

Preprocess the production header in both Arduino include orders. These cases
catch a working host codec being advertised for a firmware build that omitted
it, and catch different class layouts between Arduino and shared mesh sources.
No PlatformIO or hardware is used.
"""

from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class MeshtextConfigTest(unittest.TestCase):
    def setUp(self):
        self.compiler = shutil.which("g++") or shutil.which("clang++")
        if self.compiler is None:
            self.skipTest("a C++ preprocessor is required")

    def effective(self, defines, *, arduino_first=False, sdk_target=None):
        with tempfile.TemporaryDirectory(prefix="meshcore-mt-config-") as folder:
            work = Path(folder)
            (work / "Arduino.h").write_text(
                "#pragma once\n#ifndef ARDUINO\n#define ARDUINO 10819\n#endif\n",
                encoding="ascii",
            )
            (work / "sdkconfig.h").write_text(
                "#pragma once\n" + ("#define " + sdk_target + " 1\n" if sdk_target else ""),
                encoding="ascii",
            )
            includes = ["helpers/MeshtextConfig.h", "Arduino.h"]
            if arduino_first:
                includes.reverse()
            source = "".join("#include <" + name + ">\n" for name in includes)
            source += "MESH_ENABLE_MESHTEXT_CHAT\n"
            result = subprocess.run(
                [self.compiler, "-E", "-P", "-x", "c++", "-",
                 "-I", str(work), "-I", str(ROOT / "src"),
                 *("-D" + define for define in defines)],
                input=source, capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            return result.stdout.strip()

    def assert_orders(self, defines, expected, **kwargs):
        for arduino_first in (False, True):
            with self.subTest(defines=defines, arduino_first=arduino_first, **kwargs):
                self.assertEqual(self.effective(defines, arduino_first=arduino_first, **kwargs),
                                 str(expected))

    def test_rak4631_full_companion_is_enabled_in_every_translation_unit(self):
        self.assert_orders(["NRF52_PLATFORM", "RAK_4631", "COMPANION_RADIO_FULL", "USE_SX1262"], 1)

    def test_nrf52_default_stays_scoped_to_qualified_hardware_and_role(self):
        enabled = ["NRF52_PLATFORM", "RAK_4631", "COMPANION_RADIO_FULL", "USE_SX1262"]
        for missing in enabled:
            self.assert_orders([item for item in enabled if item != missing], 0)
        self.assert_orders(["NRF52_PLATFORM", "RAK_3401", "COMPANION_RADIO_FULL", "USE_SX1262"], 0)
        self.assert_orders(enabled + ["MESH_PRIMARY_ESPNOW=1"], 0)
        self.assert_orders(enabled + ["MESH_PRIMARY_ESPNOW=0"], 1)

    def test_esp32_s3_full_keeps_effective_sdk_target_enablement(self):
        enabled = ["ESP32_PLATFORM", "ARDUINO=10819", "COMPANION_RADIO_FULL", "USE_SX1262"]
        self.assert_orders(enabled, 1, sdk_target="CONFIG_IDF_TARGET_ESP32S3")
        self.assert_orders(enabled + ["MESH_PRIMARY_ESPNOW=0"], 1,
                           sdk_target="CONFIG_IDF_TARGET_ESP32S3")
        self.assert_orders(enabled + ["MESH_PRIMARY_ESPNOW=1"], 0,
                           sdk_target="CONFIG_IDF_TARGET_ESP32S3")
        for target in (None, "CONFIG_IDF_TARGET_ESP32", "CONFIG_IDF_TARGET_ESP32S2"):
            self.assert_orders(enabled, 0, sdk_target=target)
        for missing in ("COMPANION_RADIO_FULL", "USE_SX1262"):
            self.assert_orders([item for item in enabled if item != missing], 0,
                               sdk_target="CONFIG_IDF_TARGET_ESP32S3")

    def test_explicit_enable_and_disable_override_defaults(self):
        self.assert_orders(["MESH_ENABLE_MESHTEXT_CHAT=1"], 1)
        self.assert_orders(["NRF52_PLATFORM", "RAK_4631", "COMPANION_RADIO_FULL",
                            "USE_SX1262", "MESH_ENABLE_MESHTEXT_CHAT=0"], 0)
        self.assert_orders(["ESP32_PLATFORM", "ARDUINO=10819", "COMPANION_RADIO_FULL",
                            "USE_SX1262", "MESH_ENABLE_MESHTEXT_CHAT=0"], 0,
                           sdk_target="CONFIG_IDF_TARGET_ESP32S3")


if __name__ == "__main__":
    unittest.main()
