"""Deployed bootloader-version compatibility. All radio replies are simulated."""

import argparse
import contextlib
from dataclasses import replace
import io
from pathlib import Path
import unittest
from unittest import mock

import lora_ota as ota


class BootloaderVersionCompatibilityTests(unittest.TestCase):
    def controller(self, version_reply, **overrides):
        replies = {
            # Exact status/identity from the MeshTower SD 2.4.6 bug report.
            "ota status": (
                "OTA | this fw 6CC371C7 (485K) hw=Heltec_tower_v2 | "
                "target:0A9DBBF0 | maxblk:2048 | bl:SD blrc:00 | no download | "
                "serving:off (0) | keys:2 | env:Heltec_tower_"
            ),
            "get bootloader.ver": version_reply,
            # ota self/stats were not in the report: synthetic valid replies.
            "ota self": (
                "self body=100 image=156 base_hash=0011223344556677 | "
                "bootloader: SD apply OK (abi=3 codecs=0x5)"
            ),
            "ota stats": "OTA | fw v1.17.1.5",
            "ota bootloader status": (
                "BL board=239A0071 target=1150F50E name=TOWER_V2_OTA "
                "crc=5DACDB3D abi=3 caps=09 | staged:none mid=- hash=-"
            ),
        }
        replies.update(overrides)

        def remote_command(_target, command, **kwargs):
            if command == "get bootloader.ver":
                self.assertIs(kwargs.get("retry"), False)
            value = replies[command]  # Unexpected/mutating commands fail the test.
            if isinstance(value, Exception):
                raise value
            return value

        controller = mock.Mock()
        controller.remote_command.side_effect = remote_command
        return controller

    def query(self, controller, kind="application"):
        with contextlib.redirect_stdout(io.StringIO()) as output:
            result = ota.query_target(
                controller, argparse.Namespace(target="remote", package_kind=kind)
            )
        return result, output.getvalue()

    def test_reply_formats_and_filter(self):
        for reply, expected in (
            ("> unknown", ("nrf52", None)),
            ("> unsupported", (None, None)),
            ("Unknown command", (None, None)),
            ("ERROR: unknown command: get bootloader.ver", (None, None)),
            ("unknown config: bootloader.ver", (None, None)),
            ("Command not found", (None, None)),
            ("Error: unsupported", ("esp32", None)),
            ("> 0.11.0-OTAFIX2.4.2", ("nrf52", "0.11.0-OTAFIX2.4.2")),
            ("> OTAFIX2.4.6", ("nrf52", "OTAFIX2.4.6")),
            ("> OTAFIX2.4.6-preview.12", ("nrf52", "OTAFIX2.4.6-preview.12")),
            ("> 0.11.0 (base)", ("nrf52", "0.11.0 (base)")),
        ):
            with self.subTest(reply=reply):
                self.assertEqual(ota.parse_bootloader_version_reply(reply), expected)
                self.assertTrue(ota.reply_matches_command("get bootloader.ver", reply))
        for unrelated in ("OTA | target:1234ABCD", "self base_hash=0011223344556677", "", "> two words"):
            with self.subTest(unrelated=unrelated):
                self.assertFalse(ota.reply_matches_command("get bootloader.ver", unrelated))

    def test_unavailable_getter_does_not_block_application_or_bootloader(self):
        for kind in ("application", "bootloader"):
            for reply in (
                "> unknown", "> unsupported", "Unknown command",
                "ERROR: unknown command: get bootloader.ver",
                "unknown config: bootloader.ver", "Error: unsupported", "unexpected reply",
                ota.TransmissionError("no matching CLI reply"),
                ota.OtaError("optional command unavailable"),
            ):
                with self.subTest(kind=kind, reply=reply):
                    controller = self.controller(reply)
                    result, warning = self.query(controller, kind)
                    self.assertEqual(result.platform, "nrf52")
                    self.assertTrue(result.nrf_sd)
                    self.assertIsNone(result.bootloader_version)
                    self.assertEqual(result.bootloader_abi, 3)
                    self.assertEqual(result.bootloader_codecs, 5)
                    self.assertEqual(result.current_version, "v1.17.1.5")
                    self.assertIn("[warn]", warning)
                    calls = controller.remote_command.call_args_list
                    self.assertEqual(sum(call.args[1] == "get bootloader.ver" for call in calls), 1)
                    if kind == "bootloader":
                        self.assertEqual(result.boot_target_id, 0x1150F50E)
                        self.assertEqual(result.boot_storage, 9)
                    else:
                        self.assertIsNone(result.boot_target_id)
                        self.assertNotIn(mock.call("remote", "ota bootloader status"), calls)

    def test_new_metadata_and_base_formats_work_with_old_host_topology(self):
        for version in ("OTAFIX2.4.6", "OTAFIX2.4.6-preview.12", "0.11.0 (base)"):
            with self.subTest(version=version):
                result, _ = self.query(self.controller("> " + version), "bootloader")
                self.assertEqual(result.bootloader_version, version)
                self.assertEqual(result.boot_target_id, 0x1150F50E)

    def test_missing_version_never_bypasses_capability_or_identity_checks(self):
        cases = (
            ({"ota self": "self base_hash=0011223344556677 | bootloader: SD apply OK"}, "ABI and codec"),
            ({"ota self": "self base_hash=0011223344556677 | bootloader: NO SD mota-apply"}, "cannot apply"),
            ({"ota self": "self missing hash | bootloader: SD apply OK"}, "base hash"),
            ({"ota self": "self base_hash=0011223344556677 | maxblk:4096"}, "maxblk"),
            ({"ota bootloader status": "Unknown command"}, "cannot stage"),
            ({"ota bootloader status": (
                "BL board=239A0071 target=00000000 name=TOWER_V2_OTA "
                "crc=5DACDB3D abi=3 caps=09 | staged:none mid=- hash=-"
            )}, "target ID"),
            ({"ota bootloader status": (
                "BL board=239A0071 target=1150F50E name=TOWER_V2_OTA "
                "crc=5DACDB3D abi=2 caps=09 | staged:none mid=- hash=-"
            )}, "bootloader ABI"),
        )
        for reply in ("> unknown", ota.TransmissionError("lost optional reply"), "Error: unsupported"):
            for overrides, expected in cases:
                with self.subTest(reply=reply, expected=expected):
                    with self.assertRaisesRegex(ota.OtaError, expected):
                        self.query(self.controller(reply, **overrides), "bootloader")

    def test_missing_version_never_bypasses_bootloader_package_checks(self):
        # Existing signed-package fixture/reference builder; no second parser.
        from test_lora_ota_bootloader import boot_blob
        package = ota.parse_mota(boot_blob(storage=9, version=0x020406FF))
        target, _ = self.query(self.controller("> unknown"), "bootloader")
        self.assertEqual(ota.compatible_mota(package, target), (True, ""))
        for changed in (
            replace(target, boot_target_id=0), replace(target, boot_hw_id="wrong"),
            replace(target, bootloader_abi=2), replace(target, bootloader_codecs=4),
            replace(target, boot_storage=10), replace(target, max_block_size=512),
        ):
            with self.subTest(target=changed):
                self.assertFalse(ota.compatible_mota(package, changed)[0])

    def test_esp32_unsupported_remains_supported(self):
        result, _ = self.query(self.controller("Error: unsupported", **{
            "ota status": "OTA | target:1234ABCD hw=Heltec_v4 | maxblk:2048",
            "ota self": "self base_hash=0011223344556677",
        }))
        self.assertEqual(result.platform, "esp32")
        self.assertIsNone(result.bootloader_version)

    def test_required_probe_failure_is_not_hidden(self):
        with self.assertRaisesRegex(ota.OtaError, "admin login failed"):
            self.query(self.controller(
                ota.OtaError("admin login failed"),
                **{"ota self": ota.OtaError("admin login failed")},
            ))

    def test_both_launchers_use_the_shared_runner(self):
        root = Path(__file__).resolve().parent
        for name in ("lora_ota.sh", "lora_ota.ps1"):
            self.assertIn("lora_ota.py", (root / name).read_text())


if __name__ == "__main__":
    unittest.main()
