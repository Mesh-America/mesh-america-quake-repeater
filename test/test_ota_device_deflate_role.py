"""Offline effective-source qualification; never invokes PlatformIO/hardware."""

import importlib.util
import configparser
from pathlib import Path
import re
from types import SimpleNamespace
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "ota_device_deflate_role", ROOT / "scripts/ota_device_deflate_role.py")
POLICY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(POLICY)
DEFINE = POLICY.DEFINITION


class DeviceDeflateRoleTests(unittest.TestCase):
    def policy(self, **updates):
        options = {
            "platform": "espressif32", "mcu": "esp32s3",
            "src_filter": "+<*.cpp> +<helpers/ota/*.cpp> +<../examples/simple_repeater>",
            "flags": "-DENABLE_OTA=1 -DESP32_PLATFORM -DOTA_FLASH_STORE=1",
        }
        options.update(updates)
        return POLICY.role_policy(**options)

    def test_all_three_infrastructure_roles_on_classic_and_s3(self):
        for role in ("simple_repeater", "simple_room_server", "simple_sensor"):
            for mcu in ("esp32", "esp32s3", "esp32s2", "esp32c3", "esp32c6"):
                with self.subTest(role=role, mcu=mcu):
                    self.assertEqual(self.policy(mcu=mcu, src_filter="+<../examples/" + role + "/*.cpp>"),
                                     {DEFINE: 1})

    def test_external_nrf52_and_adaptive_rak_are_compile_eligible(self):
        for store in ("OTA_QSPI_STORE", "OTA_SD_STORE", "OTA_RAK_AUTO_STORE"):
            with self.subTest(store=store):
                self.assertEqual(self.policy(platform="nordicnrf52", mcu="nrf52840",
                                             flags="-DENABLE_OTA -DNRF52_PLATFORM -D" + store),
                                 {DEFINE: 1})

    def test_internal_nrf52_and_non_ota_or_other_platforms_excluded(self):
        for updates in (
                {"platform": "nordicnrf52", "mcu": "nrf52840",
                 "flags": "-DENABLE_OTA -DNRF52_PLATFORM -DOTA_FLASH_STORE"},
                {"platform": "ststm32", "mcu": "stm32f411"},
                {"platform": "raspberrypi", "mcu": "rp2040"},
                {"flags": "-DESP32_PLATFORM -UENABLE_OTA"},
                {"flags": "-DESP32_PLATFORM -DENABLE_OTA -DDISABLE_LORA_OTA=1"},
                {"platform": "espressif32", "mcu": "nrf52840"},
                {"flags": "-DENABLE_OTA -DNRF52_PLATFORM -DOTA_QSPI_STORE"}):
            with self.subTest(updates=updates):
                self.assertEqual(self.policy(**updates), {})

    def test_source_role_not_environment_names_selects_encoder(self):
        for role in ("companion_radio", "simple_secure_chat", "kiss_modem",
                     "partition_expander", "esp32_partition_migrator",
                     "esp32_partition_legacy_seed", "unknown"):
            with self.subTest(role=role):
                self.assertEqual(self.policy(src_filter="+<../examples/" + role + "/*.cpp>"), {})
        self.assertEqual(self.policy(src_filter="+<*>"), {})

    def test_any_selected_excluded_role_beats_infrastructure_include(self):
        for source in POLICY.EXCLUDED_SOURCES:
            self.assertEqual(self.policy(
                src_filter="+<../examples/simple_repeater> +<" + source + ">"), {})

    def test_effective_ordered_exclusion_and_later_reinclude(self):
        source = "../examples/simple_repeater"
        self.assertEqual(self.policy(src_filter="+<" + source + "> -<" + source + ">"), {})
        self.assertEqual(self.policy(src_filter="+<" + source + "> -<" + source
                                               + "> +<" + source + "/*.cpp>"), {DEFINE: 1})
        self.assertEqual(self.policy(src_filter="+<../examples/simple_repeater> "
                                               "+<../examples/companion_radio> "
                                               "-<../examples/companion_radio>"), {DEFINE: 1})

    def test_mixed_infrastructure_roles_fail_closed(self):
        self.assertEqual(self.policy(src_filter="+<../examples/simple_repeater> "
                                               "+<../examples/simple_room_server>"), {})

    def test_companion_and_seeder_flags_exclude_even_misnamed_infrastructure(self):
        for flag in ("OTA_SEEDER_ONLY=1", "OTA_SEEDER_ONLY=0", "COMPANION_RADIO_FULL=1",
                     "COMPANION_FEATURE_USB_MOTA_SOURCE=1"):
            self.assertEqual(self.policy(flags="-DENABLE_OTA -DESP32_PLATFORM -D" + flag), {})

    def test_explicit_boolean_opt_out_or_eligible_enable_is_preserved(self):
        for flags in ("-D" + DEFINE + "=0", "-U" + DEFINE, "-D" + DEFINE + "=1"):
            self.assertEqual(self.policy(flags="-DENABLE_OTA -DESP32_PLATFORM " + flags), {})
        self.assertEqual(self.policy(cppdefines=[(DEFINE, 0)]), {})
        self.assertEqual(self.policy(flags="-DENABLE_OTA -DESP32_PLATFORM -D" + DEFINE + "=0",
                                     cppdefines=[(DEFINE, 1)]), {})

    def test_unsafe_enable_and_nonboolean_overrides_are_rejected(self):
        for source in ("companion_radio", "unknown", "kiss_modem"):
            with self.subTest(source=source):
                with self.assertRaises(ValueError):
                    self.policy(src_filter="+<../examples/" + source + ">",
                                flags="-DENABLE_OTA -DESP32_PLATFORM -D" + DEFINE + "=1")
        for value in ("2", "-1", "true", "yes", "garbage"):
            with self.assertRaises(ValueError):
                self.policy(flags="-DENABLE_OTA -DESP32_PLATFORM -D" + DEFINE + "=" + value)

    def test_unset_or_zero_storage_flags_do_not_enable_internal_nrf(self):
        self.assertEqual(self.policy(platform="nordicnrf52", mcu="nrf52840",
                                     flags="-DENABLE_OTA -DNRF52_PLATFORM -DOTA_QSPI_STORE=0"), {})
        self.assertEqual(self.policy(platform="nordicnrf52", mcu="nrf52840",
                                     flags="-DENABLE_OTA -DNRF52_PLATFORM -UOTA_QSPI_STORE"), {})

    def test_flag_and_filter_lists_and_windows_slashes(self):
        self.assertEqual(self.policy(flags=["-D ENABLE_OTA=1", "-D ESP32_PLATFORM"],
                                     src_filter=["+<*.cpp>", "+<..\\examples\\simple_sensor\\*.cpp>"]),
                         {DEFINE: 1})

    def test_install_uses_effective_filter_and_emits_one_common_definition(self):
        class Env(dict):
            def PioPlatform(self):
                return SimpleNamespace(name="espressif32")

            def BoardConfig(self):
                return {"build.mcu": "esp32s3"}

            def AppendUnique(self, **options):
                self["appended"] = options

            def GetProjectOption(self, name, default):
                raise AssertionError("Effective SRC_FILTER must take precedence")

        env = Env(SRC_FILTER="+<../examples/simple_sensor>",
                  BUILD_FLAGS="-DENABLE_OTA -DESP32_PLATFORM", CPPDEFINES=[])
        POLICY.install(env)
        self.assertEqual(env["appended"], {"CPPDEFINES": [(DEFINE, 1)]})
        env["SRC_FILTER"] = ""
        del env["appended"]
        POLICY.install(env)
        self.assertNotIn("appended", env)

    def test_recipe_hooks_and_default_header_are_fail_closed(self):
        ini = (ROOT / "platformio.ini").read_text(encoding="utf-8")
        for name in ("esp32_base", "nrf52_base"):
            section = ini.split("[" + name + "]", 1)[1].split("\n[", 1)[0]
            self.assertIn("pre:scripts/ota_device_deflate_role.py", section)
        header = (ROOT / "src/helpers/ota/OtaDeflateConfig.h").read_text(encoding="utf-8")
        self.assertIn("#define MESHCORE_OTA_DEVICE_DEFLATE 0", header)
        self.assertNotIn("defined(ESP32_PLATFORM)", header)

    def test_real_representative_recipe_inheritance(self):
        # Read the recipes without calling PlatformIO (which must remain
        # single-process). Resolve only static section/option interpolation.
        config = configparser.ConfigParser(interpolation=None, strict=False,
                                            inline_comment_prefixes=(";",))
        config.read([str(ROOT / "platformio.ini")]
                    + [str(path) for path in sorted((ROOT / "variants").glob("*/platformio.ini"))],
                    encoding="utf-8")

        def option(section, key):
            if config.has_option(section, key):
                raw = config.get(section, key)
            else:
                parents = config.get(section, "extends", fallback="").split(",")
                raw = next((option(parent.strip(), key) for parent in parents
                            if parent.strip() and option(parent.strip(), key)), "")
            return re.sub(r"\$\{([^}]+)\}",
                          lambda match: option(*match[1].rsplit(".", 1)), raw)

        cases = (
            ("Heltec_v2_repeater", "esp32", True),
            ("heltec_v4_repeater", "esp32s3", True),
            ("heltec_v4_room_server", "esp32s3", True),
            ("Xiao_nrf52_repeater", "nrf52840", True),
            ("RAK_3401_repeater_rak13302_w25q16_lora_ota", "nrf52840", True),
            ("RAK_3401_repeater_unified_lora_ota", "nrf52840", True),
            ("RAK_3401_repeater_lora_ota_no_external_sensors", "nrf52840", False),
            ("heltec_v4_companion_radio_usb", "esp32s3", False),
            ("heltec_v4_companion_radio_ble", "esp32s3", False),
            ("heltec_v4_companion_radio_wifi_femon", "esp32s3", False),
            ("Xiao_nrf52_companion_radio_usb", "nrf52840", False),
            ("Xiao_nrf52_companion_radio_ble", "nrf52840", False),
            ("Xiao_nrf52_kiss_modem", "nrf52840", False),
        )
        for name, mcu, expected in cases:
            with self.subTest(name=name):
                section = "env:" + name
                platform = option(section, "platform")
                platform = "espressif32" if "espressif32" in platform else platform
                result = POLICY.role_policy(platform, mcu, option(section, "build_src_filter"),
                                            option(section, "build_flags"))
                self.assertEqual(result, {DEFINE: 1} if expected else {})
                self.assertIn("pre:scripts/ota_device_deflate_role.py",
                              option(section, "extra_scripts"))


if __name__ == "__main__":
    unittest.main()
