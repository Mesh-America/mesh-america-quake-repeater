#!/usr/bin/env python3
"""Check observer channel selection and fork identity without invoking PIO."""
import importlib.util
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("verify_ota_channel", ROOT / "scripts/verify_ota_channel.py")
VERIFY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFY)
PROD = "https://observer.gessaman.com/v"
BETA = "https://observer.gessaman.com/beta/v"
CHANNEL_ENV = (
    "OTA_MANIFEST_BASE_URL", "OTA_MANIFEST_BASE_STABLE_URL", "OTA_MANIFEST_BASE_DEV_URL",
    "FIRMWARE_BUILD_NUMBER", "OTA_CHANNEL_TAG", "FILENAME_CHANNEL_TAG",
)


class ObserverBuildChannelTests(unittest.TestCase):
    def shell(self, body, settings=None):
        environment = {key: value for key, value in os.environ.items() if key not in CHANNEL_ENV}
        environment.update(settings or {})
        bash = shutil.which("bash")
        git_bash = Path("C:/Program Files/Git/bin/bash.exe")
        if os.name == "nt" and git_bash.is_file():
            bash = str(git_bash)
        result = subprocess.run(
            [bash, "-c", 'set -euo pipefail; cd "$1"; source build.sh; '
             'pio() { echo FORBIDDEN_PLATFORMIO >&2; return 99; }; ' + body,
             "observer-channel-test", ROOT.as_posix()],
            cwd=ROOT, env=environment, text=True, capture_output=True, timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("FORBIDDEN_PLATFORMIO", result.stdout + result.stderr)
        return result.stdout

    def flags(self, target, settings=None):
        output = self.shell(
            "PLATFORMIO_BUILD_FLAGS=-DKEEP_CALLER_FLAG=1; "
            f"apply_observer_ota_channel_flags {shlex.quote(target)}; "
            'printf "%s" "$PLATFORMIO_BUILD_FLAGS"', settings,
        )
        return dict(flag[2:].split("=", 1) for flag in shlex.split(output))

    def test_production_beta_and_custom_native_bases(self):
        for native in (PROD, BETA, "https://observer.gessaman.com/v-plus"):
            with self.subTest(native=native):
                flags = self.flags("Heltec_v3_repeater_observer_mqtt",
                                   {"OTA_MANIFEST_BASE_URL": native})
                self.assertEqual(flags["KEEP_CALLER_FLAG"], "1")
                self.assertEqual(flags["OTA_MANIFEST_BASE"], f'"{native}"')
                self.assertEqual(flags["OTA_MANIFEST_BASE_STABLE"], f'"{PROD}"')
                self.assertEqual(flags["OTA_MANIFEST_BASE_DEV"], f'"{BETA}"')

    def test_default_and_named_channel_overrides(self):
        self.assertEqual(self.flags("Heltec_v3_room_server_observer_mqtt")["OTA_MANIFEST_BASE"], f'"{PROD}"')
        flags = self.flags("Heltec_v3_room_server_observer_mqtt", {
            "OTA_MANIFEST_BASE_URL": "https://fork.test/preview/v",
            "OTA_MANIFEST_BASE_STABLE_URL": "https://fork.test/v",
            "OTA_MANIFEST_BASE_DEV_URL": "https://fork.test/dev/v",
        })
        self.assertEqual(flags["OTA_MANIFEST_BASE_STABLE"], '"https://fork.test/v"')
        self.assertEqual(flags["OTA_MANIFEST_BASE_DEV"], '"https://fork.test/dev/v"')

    def test_non_observer_keeps_destination_and_unset_flags(self):
        self.assertEqual(self.flags("Heltec_v3_repeater", {"OTA_MANIFEST_BASE_URL": BETA}),
                         {"KEEP_CALLER_FLAG": "1"})
        self.assertEqual(self.shell(
            "unset PLATFORMIO_BUILD_FLAGS; apply_observer_ota_channel_flags Heltec_v3_repeater; "
            'printf "%s" "${PLATFORMIO_BUILD_FLAGS-unset}"'), "unset")
        original = "-DOTA_MANIFEST_BASE='\"https://fork.test/v\"'"
        self.assertEqual(self.shell(
            f"PLATFORMIO_BUILD_FLAGS={shlex.quote(original)}; "
            'apply_observer_ota_channel_flags Heltec_v3_companion_radio_full; '
            'printf "%s" "$PLATFORMIO_BUILD_FLAGS"'), original)

    def test_observer_version_tags_keep_beta_identity(self):
        settings = {"FIRMWARE_BUILD_NUMBER": "9", "OTA_CHANNEL_TAG": "beta-dev",
                    "FILENAME_CHANNEL_TAG": "-dev"}
        self.assertEqual(self.shell(
            "get_firmware_version_string Heltec_v3_repeater_observer_mqtt v1.17.1 abc1234", settings),
            "v1.17.1.9-dev-abc1234")
        self.assertEqual(self.shell(
            "get_firmware_version_string Heltec_v3_repeater_observer_mqtt v1.17.1 abc1234 embedded", settings),
            "v1.17.1.9-observer-beta-dev-abc1234")
        self.assertEqual(self.shell(
            "get_firmware_version_string Heltec_v3_repeater v1.17.1 abc1234", settings),
            "v1.17.1-abc1234")
        self.assertEqual(self.shell(
            "get_firmware_version_string Heltec_v3_repeater_observer_mqtt v1.17.1 abc1234 embedded"),
            "v1.17.1-observer-abc1234")

    def test_variant_native_bases_do_not_override_workflow_channel(self):
        for path in ROOT.glob("variants/*/platformio.ini"):
            self.assertNotIn("-D OTA_MANIFEST_BASE=", path.read_text(), str(path))

    @staticmethod
    def blob(native=PROD, compat="2+keymind1"):
        return (f"ota-base-native:{native}\0ota-base-stable:{PROD}\0"
                f"ota-base-dev:{BETA}\0ota-compat:{compat}\0").encode()

    def test_verifier_requires_fork_capability_and_exact_channel(self):
        self.assertEqual(VERIFY.check(self.blob(), "prod", PROD, PROD, BETA, ("keymind1",)), [])
        self.assertTrue(VERIFY.check(self.blob(compat="2+eth"), "prod", PROD, PROD, BETA, ("keymind1",)))
        self.assertTrue(VERIFY.check(self.blob(BETA), "prod", PROD, PROD, BETA, ("keymind1",)))
        self.assertEqual(VERIFY.check(self.blob(BETA), "beta", BETA, PROD, BETA, ("keymind1",)), [])

    def test_verifier_checks_every_published_binary(self):
        with tempfile.TemporaryDirectory(prefix="mesh-observer-channel-") as temporary:
            directory = Path(temporary)
            (directory / "one.bin").write_bytes(self.blob())
            (directory / "two-merged.bin").write_bytes(self.blob(BETA))
            result = subprocess.run([
                os.sys.executable, str(ROOT / "scripts/verify_ota_channel.py"), "--expect", "prod",
                "--native-url", PROD, "--stable-url", PROD, "--dev-url", BETA,
                "--required-cap", "keymind1", "--bin-dir", str(directory),
            ], text=True, capture_output=True, timeout=10)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("two-merged.bin", result.stderr)
            self.assertIn("1 of 2 builds", result.stderr)


if __name__ == "__main__":
    unittest.main()
