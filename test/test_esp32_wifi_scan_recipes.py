#!/usr/bin/env python3
"""Resolve all tracked ESP32 scan hooks and execute builder fallback without PIO."""
import json
from pathlib import Path
import subprocess
import unittest

from platformio.project.config import ProjectConfig

ROOT = Path(__file__).resolve().parents[1]
HOOK = "pre:scripts/esp32_wifi_scan_fix.py"


class Esp32WiFiScanRecipeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Developer-local overlays must not alter the tracked regression matrix.
        cls.config = ProjectConfig(str(ROOT / "platformio.ini"), parse_extra=False)
        for path in sorted((ROOT / "variants").glob("*/platformio.ini")):
            cls.config.read(str(path), parse_extra=False)
        cls.config.read(str(ROOT / "tools/hil/profile_switch.ini"), parse_extra=False)

    def test_every_resolved_esp32_recipe_has_exactly_one_direct_scan_hook(self):
        tested = []
        for section in self.config.sections():
            if not section.startswith("env:"):
                continue
            platform = self.config.get(section, "platform", "").lower()
            if "espressif32" not in platform and "pioarduino" not in platform:
                continue
            with self.subTest(target=section):
                hooks = self.config.get(section, "extra_scripts", [])
                self.assertEqual(hooks.count(HOOK), 1, hooks)
                tested.append(section)
        self.assertGreater(len(tested), 400)
        for name in ("heltec_v4_partition_migrator", "xiao_s3_partition_legacy_seed",
                     "esp32_c3_4mb_partition_migrator", "profile_switch_heltec_v4"):
            self.assertIn("env:" + name, tested)

    def fallback(self, platform, configured, ambient="", disabled=False):
        options = [["env:fixture", [["extra_scripts", configured]]]]
        shell = r'''
source "$1/build_legacy.sh"
pio() { printf 'FORBIDDEN_PLATFORMIO\n' >&2; return 99; }
PIO_CONFIG_JSON=$2
PLATFORMIO_EXTRA_SCRIPTS=$3
if [ "$5" = 1 ]; then
  append_platformio_extra_script() { :; }
fi
ensure_esp32_wifi_scan_fix "$4" fixture
ensure_esp32_wifi_scan_fix "$4" fixture
printf '%s' "$PLATFORMIO_EXTRA_SCRIPTS"
'''
        result = subprocess.run(["bash", "-c", shell, "scan-hook", str(ROOT),
                                 json.dumps(options), ambient, platform,
                                 "1" if disabled else "0"], cwd=ROOT,
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("FORBIDDEN_PLATFORMIO", result.stdout + result.stderr)
        return result.stdout

    def test_actual_builder_fallback_preserves_overrides_and_is_idempotent(self):
        ambient = "pre:scripts/fixture_private.py"
        self.assertEqual(self.fallback("ESP32_PLATFORM", [], ambient), ambient + "\n" + HOOK)
        self.assertEqual(self.fallback("ESP32_PLATFORM", [HOOK], ambient), ambient)
        self.assertEqual(self.fallback("ESP32_PLATFORM", [], ambient + "\n" + HOOK), ambient + "\n" + HOOK)
        self.assertEqual(self.fallback("NRF52_PLATFORM", [], ambient), ambient)

    def test_disabled_fallback_cannot_satisfy_missing_hook(self):
        self.assertNotIn(HOOK, self.fallback("ESP32_PLATFORM", [], disabled=True))
        self.assertIn(HOOK, self.fallback("ESP32_PLATFORM", []))

    def test_fallback_precedes_recipe_binding_and_suite_is_wired_in_ci(self):
        source = (ROOT / "build_legacy.sh").read_text()
        body = source[source.index("build_firmware_one_profile() {"):]
        self.assertLess(body.index('ensure_esp32_wifi_scan_fix "$env_platform" "$pio_env_name"'),
                        body.index("BUILD_RECIPE_SHA256=$(compute_build_recipe_digest"))
        self.assertIn("          python3 -B test/test_esp32_wifi_scan_recipes.py -v\n",
                      (ROOT / ".github/workflows/run-unit-tests.yml").read_text())


if __name__ == "__main__":
    unittest.main()
