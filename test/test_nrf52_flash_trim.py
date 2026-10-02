import importlib.util
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("nrf52_flash_trim", ROOT / "scripts/nrf52_flash_trim.py")
TRIM = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TRIM)


class Nrf52FlashTrimTest(unittest.TestCase):
    def policy(self, name="RAK_4631_repeater", role="simple_repeater", **kwargs):
        options = dict(platform="nordicnrf52", mcu="nrf52840", env_name=name,
                       src_filter="+<*.cpp> +<../examples/%s>" % role)
        options.update(kwargs)
        return TRIM.trim_policy(**options)

    def test_every_infrastructure_role_keeps_compact_crypto_and_names(self):
        for role in ("simple_repeater", "simple_room_server", "simple_sensor", "kiss_modem"):
            with self.subTest(role=role):
                defines = self.policy(role=role)
                for name in ("MESH_NRF52_FLASH_TRIM", "ED25519_COMPACT_BASE",
                             "ED25519_COMPACT_SHA512", "OTA_TARGET_NAME_FRONT_CODED",
                             "SSD1306_NO_SPLASH"):
                    self.assertEqual(defines[name], 1)
                self.assertEqual(defines["CFG_TUD_HID"], 0)
                self.assertNotIn("CFG_TUD_CDC", defines)
                self.assertFalse(any(name.startswith("CFG_TUH") for name in defines))

    def test_every_companion_alias_is_excluded(self):
        for suffix in ("companion_radio_full", "companion_radio_usb", "companion_radio_ble",
                       "companion_radio_wifi", "companion_radio_serial", "companion_radio_ethernet",
                       "companion_usb", "companion_ble", "comp_radio_usb", "terminal_chat", "term_chat"):
            with self.subTest(suffix=suffix):
                self.assertEqual(self.policy(name="RAK_4631_" + suffix), {})

    def test_source_filter_and_synthetic_alias_also_exclude_companion(self):
        for role in ("companion_radio/*.cpp", "simple_secure_chat/main.cpp"):
            self.assertEqual(self.policy(name="custom", role=role), {})
        for flags in ('-DCOMPANION_RADIO_FULL=1', '-D COMPANION_FEATURE_USB_MOTA_SOURCE=1',
                      '-DOTA_VARIANT=\'"RAK_4631_terminal_chat"\'',
                      '-DOTA_VARIANT=\'"RAK_4631_companion_radio_full"\''):
            with self.subTest(flags=flags):
                self.assertEqual(self.policy(flags=flags), {})
        self.assertEqual(self.policy(cppdefines=[("COMPANION_RADIO_FULL", 1)]), {})

    def test_unknown_roles_other_platforms_and_explicit_optout_are_unchanged(self):
        for options in (dict(role="custom"), dict(platform="espressif32", mcu="esp32"),
                        dict(platform="ststm32", mcu="stm32f411"),
                        dict(flags="-DMESH_NRF52_FLASH_TRIM=0")):
            self.assertEqual(self.policy(**options), {})

    def test_effective_filter_is_ordered_and_does_not_include_outside_source_by_wildcard(self):
        self.assertEqual(self.policy(src_filter="+<*> +<../examples/simple_repeater> -<../examples/simple_repeater>"), {})
        self.assertEqual(self.policy(src_filter="+<*>"), {})
        self.assertTrue(self.policy(src_filter="+<../examples/companion_radio> -<../examples/companion_radio> +<../examples/simple_repeater>"))

    def test_board_and_user_defines_are_not_overridden(self):
        defines = self.policy(flags="-D CFG_TUD_HID=1 -UED25519_COMPACT_BASE -USSD1306_NO_SPLASH")
        self.assertNotIn("CFG_TUD_HID", defines)
        self.assertNotIn("ED25519_COMPACT_BASE", defines)
        self.assertNotIn("SSD1306_NO_SPLASH", defines)
        self.assertEqual(TRIM.flag_defines("-DMESH_NRF52_FLASH_TRIM=1 -UMESH_NRF52_FLASH_TRIM")["MESH_NRF52_FLASH_TRIM"], None)

    def test_cc310_archive_is_exact_and_requires_supported_mcu_and_enabled_crypto(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            archive = Path(temp_dir) / "libraries/Adafruit_nRFCrypto" / TRIM.CC310_ARCHIVE
            archive.parent.mkdir(parents=True)
            archive.write_bytes(b"future-sdk")
            enabled = {"USE_CC310_HW_CRYPTO": "1"}
            self.assertFalse(TRIM.supported_cc310(temp_dir, "nrf52840", enabled))
            with patch.object(TRIM, "CC310_ARCHIVE_SHA256", TRIM.hashlib.sha256(b"future-sdk").hexdigest()):
                self.assertTrue(TRIM.supported_cc310(temp_dir, "nrf52840", enabled))
                self.assertFalse(TRIM.supported_cc310(temp_dir, "nrf52832", enabled))
                self.assertFalse(TRIM.supported_cc310(temp_dir, "nrf52840", {"USE_CC310_HW_CRYPTO": "0"}))
                self.assertFalse(TRIM.supported_cc310(temp_dir, "nrf52840", {}))

    def test_profile_wiring_is_nrf52_only_and_companion_common_flags_unchanged(self):
        config = (ROOT / "platformio.ini").read_text()
        nrf = config.split("[nrf52_base]", 1)[1].split("\n[", 1)[0]
        self.assertIn("pre:scripts/nrf52_flash_trim.py", nrf)
        self.assertEqual(config.count("pre:scripts/nrf52_flash_trim.py"), 1)
        self.assertNotIn("ED25519_COMPACT", nrf)
        self.assertNotIn("CFG_TUD_HID", nrf)
        self.assertNotIn("SSD1306_NO_SPLASH", nrf)
        self.assertIn("-D MESH_NRF52_LOOP_STACK_WORDS=2048", nrf)

    def test_tft_force_include_is_per_library_and_preserves_existing_include_pair(self):
        self.assertTrue(TRIM.source_selected("+<helpers/ui/ST7735Display.cpp>",
                                             "helpers/ui/ST7735Display.cpp"))
        self.assertFalse(TRIM.source_selected("+<helpers/ui/*.cpp> -<helpers/ui/ST7735Display.cpp>",
                                              "helpers/ui/ST7735Display.cpp"))
        class LibraryEnvironment(dict):
            def Append(self, **kwargs):
                for key, value in kwargs.items():
                    self.setdefault(key, []).extend(value)

            def subst(self, text):
                return text.replace("$PROJECT_DIR", str(ROOT))

        library = LibraryEnvironment(CCFLAGS=["-include", "SoftDeviceSvcCompat.h"])
        source = object()
        self.assertIs(TRIM.trim_tft_library(library, source), source)
        self.assertEqual(library["CCFLAGS"].count("-include"), 2)
        before = list(library["CCFLAGS"])
        TRIM.trim_tft_library(library, source)
        self.assertEqual(library["CCFLAGS"], before)

    def test_install_does_not_mutate_excluded_roles_and_scopes_wrapper_build(self):
        class Platform:
            name = "nordicnrf52"

            def get_package_dir(self, _name):
                return "sdk"

        class BuildEnvironment(dict):
            def PioPlatform(self):
                return Platform()

            def BoardConfig(self):
                return {"build.mcu": "nrf52840"}

            def AppendUnique(self, **kwargs):
                for name, values in kwargs.items():
                    for value in values:
                        if value not in self.setdefault(name, []):
                            self[name].append(value)

            def BuildSources(self, *args):
                self.setdefault("BUILT_SOURCES", []).append(args)

        base = dict(BUILD_FLAGS=["-DUSE_CC310_HW_CRYPTO=1"],
                    SRC_FILTER=["+<../examples/simple_repeater>"], CPPDEFINES=[])
        excluded = BuildEnvironment(**base, PIOENV="RAK_4631_companion_radio_full")
        before = dict(excluded)
        TRIM.install(excluded)
        self.assertEqual(excluded, before)
        active = BuildEnvironment(BUILD_FLAGS=list(base["BUILD_FLAGS"]),
                                  SRC_FILTER=list(base["SRC_FILTER"]), CPPDEFINES=[],
                                  PIOENV="RAK_4631_repeater")
        with patch.object(TRIM, "supported_cc310", return_value=True):
            TRIM.install(active)
        self.assertTrue(active["MESH_NRF52_FLASH_TRIM_ACTIVE"])
        self.assertIn("-Wl,--wrap=CRYS_ECPKI_GetEcDomain", active["LINKFLAGS"])
        self.assertEqual(active["BUILT_SOURCES"][0][-1], "+<Cc310DomainTrim.c>")

    @unittest.skipUnless(shutil.which("cc"), "a native C compiler is required")
    def test_wrapped_domain_preserves_p256_and_rejects_unused_curves(self):
        fixture = ROOT / "test/fixtures/nrf52_flash_trim"
        with tempfile.TemporaryDirectory() as temp_dir:
            executable = Path(temp_dir) / "cc310-trim-test"
            subprocess.run(["cc", "-std=c99", "-Wall", "-Wextra", "-Werror",
                            "-DMESH_NRF52_FLASH_TRIM=1", "-I" + str(fixture),
                            str(ROOT / "src/helpers/nrf52/Cc310DomainTrim.c"),
                            str(fixture / "test_domain_trim.c"), "-o", str(executable)], check=True)
            subprocess.run([str(executable)], check=True)


if __name__ == "__main__":
    unittest.main()
