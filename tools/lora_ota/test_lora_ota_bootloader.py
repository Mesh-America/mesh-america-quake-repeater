"""Offline bootloader staging and station-selection regression tests. No radios."""

import argparse
import contextlib
from dataclasses import replace
import io
import os
from pathlib import Path
import shutil
import struct
import tempfile
import unittest
from unittest import mock
import warnings
import zipfile
import zlib

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import lora_ota as ota
from test_lora_ota import firmware, mota_blob, prepare_args, target, VERSION_NEW


def boot_blob(*, storage=0x0A, version=0x0117010D):
    """Build a signed test-only candidate using the canonical reference builder."""
    ml = ota.bootloader_library()
    board, name, app_base = 0x239A0029, "3401_DFU", ml.NRF52_APP_BASE_S140_V6
    if storage == 0x0E:
        board, name, app_base = 0x28860044, "XIAO-SENSE-DFU", ml.NRF52_APP_BASE_S140_V7
        name = ml.XIAO_BOOT_DEVICE_NAME.rstrip(b"\0").decode("ascii")
    elif storage == 0x09:
        board, name = 0x239A0071, "TOWER_V2_OTA"
    image = bytearray(b"\xff" * ml.XIAO_BOOT_IMAGE_SIZE)
    struct.pack_into("<II", image, 0, 0x20040000, ml.XIAO_BOOT_IMAGE_START + 0x101)
    struct.pack_into("<8sHHB3x", image, 0x80, ml.XIAO_BOOT_CAPS_MAGIC, 3, 5, storage)
    offset = ml.BOOT_CANDIDATE_MANIFEST_OFFSET
    struct.pack_into(
        "<8sHHIII16sI", image, offset, ml.XIAO_BOOT_MANIFEST_MAGIC,
        ml.XIAO_BOOT_MANIFEST_VERSION, ml.XIAO_BOOT_MANIFEST_SIZE,
        ml.XIAO_BOOT_IMAGE_START, len(image), board, name.encode("ascii"), 0,
    )
    struct.pack_into(
        "<8sHHIHHIHHI", image, offset + ml.XIAO_BOOT_MANIFEST_SIZE,
        ml.BOOT_CONTINUITY_MAGIC, ml.BOOT_CONTINUITY_VERSION, ml.BOOT_CONTINUITY_SIZE,
        version, ml.BOOT_CONTINUITY_FAMILY_S140,
        0x0123 if app_base == ml.NRF52_APP_BASE_S140_V7 else 0x00B6,
        app_base, ml.BOOT_CONTINUITY_LAYOUT_ABI, 0, 0,
    )
    struct.pack_into("<I", image, offset + 40, zlib.crc32(image) & 0xFFFFFFFF)
    image = bytes(image)
    manifest = ml.build_manifest(
        target_id=ml.bootloader_target_id(board, name), fw_version=version,
        image_size=len(image), payload=image, block_size=1024,
        image_hash=ml.mh32(image), codec_id=ml.CODEC_FULL, is_full=True,
        sign_priv=Ed25519PrivateKey.from_private_bytes(b"\x01" * 32), bootloader=True,
    )
    return ml.build_container(manifest, image)


def boot_target(package):
    return replace(
        target(platform="nrf52", boot_codecs=5), bootloader_abi=3,
        boot_target_id=package.target_id, boot_hw_id=package.hw_id,
        boot_storage=package.bootloader_storage,
        nrf_sd=package.bootloader_storage == 9,
        nrf_qspi=package.bootloader_storage == 14,
    )


class BootloaderStagingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.blob = boot_blob()
        cls.package = ota.parse_mota(cls.blob)

    def test_signed_full_bootloader_is_identified(self):
        package = self.package
        self.assertTrue(package.is_bootloader)
        self.assertEqual(package.kind, "bootloader full")
        self.assertEqual(package.target_id, 0x23818A80)
        self.assertEqual(package.block_size, 1024)
        self.assertEqual(package.payload_size, 40960)

    def test_all_supported_storage_profiles(self):
        for storage in (10, 14, 9):
            with self.subTest(storage=storage):
                package = ota.parse_mota(boot_blob(storage=storage))
                self.assertEqual(ota.compatible_mota(package, boot_target(package)), (True, ""))

    def test_malformed_bootloaders_fail_closed(self):
        for offset in (9, 10, 11, 27, 28, 105, 137, 201, 205, 600):
            with self.subTest(offset=offset):
                bad = bytearray(self.blob)
                bad[offset] ^= 1
                with self.assertRaises(ota.OtaError):
                    ota.parse_mota(bytes(bad))

    def test_bootloader_is_not_an_application_full_exception(self):
        application = ota.parse_mota(mota_blob(firmware(b"test" * 1000, VERSION_NEW)))
        self.assertFalse(ota.compatible_mota(application, target(platform="nrf52"))[0])

    def test_bootloader_compatibility_requires_exact_live_contract(self):
        live = boot_target(self.package)
        for change in (
            dict(platform="esp32"), dict(boot_target_id=None),
            dict(boot_target_id=self.package.target_id ^ 1), dict(boot_hw_id="wrong"),
            dict(bootloader_abi=2), dict(bootloader_codecs=4),
            dict(boot_storage=14), dict(nrf_qspi=True), dict(max_block_size=512),
        ):
            with self.subTest(change=change):
                self.assertFalse(ota.compatible_mota(self.package, replace(live, **change))[0])

    def test_stage_only_is_required_even_with_yes(self):
        args = argparse.Namespace(no_install=False, yes=True)
        with self.assertRaisesRegex(ota.OtaError, "use --no-install"):
            ota.require_package_action(args, True)
        args.no_install = True
        ota.require_package_action(args, True)
        for key, value in (("prepare_only", True), ("allow_non_upgrade", True), ("base", Path("base.bin"))):
            with self.subTest(option=key):
                with self.assertRaises(ota.OtaError):
                    ota.require_package_action(argparse.Namespace(no_install=True, **{key: value}), True)

    def test_default_run_rejects_boot_before_contacting_radios(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "not-an-app.mota"
            path.write_bytes(self.blob)
            with (
                mock.patch.object(ota, "Controller") as controller,
                mock.patch.object(ota, "source_cli_command") as source,
                mock.patch.object(ota, "require_command") as require,
                contextlib.redirect_stdout(io.StringIO()),
                contextlib.redirect_stderr(io.StringIO()) as error,
            ):
                result = ota.main([
                    str(path), "remote", "--controller-serial", "controller",
                    "--source-serial", "source", "--yes",
                ])
            self.assertEqual(result, 2)
            self.assertIn("use --no-install", error.getvalue())
            controller.assert_not_called()
            source.assert_not_called()
            require.assert_not_called()

    def test_prepare_boot_stage_uses_motatool_verification(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "boot.mota"
            source.write_bytes(self.blob)
            args = prepare_args(source, "motatool")
            args.no_install = True
            with mock.patch.object(ota, "verify_with_motatool") as verify:
                path, package, body_hash = ota.prepare_package(args, boot_target(self.package), root)
            self.assertTrue(package.is_bootloader)
            self.assertIsNone(body_hash)
            self.assertEqual(path.read_bytes(), self.blob)
            verify.assert_called_once_with("motatool", path, None)

    def test_mixed_archive_requires_explicit_choice(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "mixed.zip"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("renamed.mota", self.blob)
                archive.writestr("firmware.bin", firmware(b"test" * 1000, VERSION_NEW))
            with self.assertRaisesRegex(ota.OtaError, "both application and bootloader"):
                ota.inspect_package_kind(path, None)
            self.assertEqual(ota.inspect_package_kind(path, "renamed.mota"), "bootloader")
            self.assertEqual(ota.inspect_package_kind(path, "firmware.bin"), "application")
            with self.assertRaisesRegex(ota.OtaError, "not found"):
                ota.inspect_package_kind(path, "missing.mota")

    def test_boot_archive_selects_matching_newest_and_never_falls_back(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "boot.zip"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("old.mota", self.blob)
                archive.writestr("new.mota", boot_blob(version=0x0117010E))
                archive.writestr("xiao.mota", boot_blob(storage=14))
            with zipfile.ZipFile(path) as archive:
                selected = ota.select_mota_from_zip(archive, boot_target(self.package), None, package_kind="bootloader")
                self.assertEqual(selected[1], "new.mota")
                with self.assertRaisesRegex(ota.OtaError, "unusable"):
                    ota.select_mota_from_zip(archive, target(platform="esp32"), None, package_kind="bootloader")

    def test_duplicate_zip_member_cannot_be_selected_by_name(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "duplicate.zip"
            with warnings.catch_warnings(), zipfile.ZipFile(path, "w") as archive:
                warnings.simplefilter("ignore", UserWarning)
                archive.writestr("boot.mota", self.blob)
                archive.writestr("boot.mota", self.blob)
            with self.assertRaisesRegex(ota.OtaError, "duplicated"):
                ota.inspect_package_kind(path, "boot.mota")

    def test_query_uses_boot_identity_not_application_id(self):
        controller = mock.Mock()
        controller.remote_command.return_value = (
            "BL board=239A0029 target=23818A80 name=3401_DFU "
            "crc=12345678 abi=3 caps=0A | staged:none mid=- hash=-"
        )
        live = replace(target(platform="nrf52", boot_codecs=5), bootloader_abi=3)
        result = ota.query_bootloader_target(controller, live)
        self.assertEqual(result.target_id, live.target_id)
        self.assertEqual(result.boot_target_id, self.package.target_id)
        self.assertEqual(result.boot_hw_id, self.package.hw_id)
        for reply in (
            "ERR this build cannot update its bootloader over LoRa",
            controller.remote_command.return_value.replace("23818A80", "00000000"),
            controller.remote_command.return_value.replace("abi=3", "abi=2"),
        ):
            controller.remote_command.return_value = reply
            with self.assertRaises(ota.OtaError):
                ota.query_bootloader_target(controller, live)

    def test_staging_prints_confirmation_but_never_installs(self):
        package = self.package
        args = argparse.Namespace(target="remote")
        controller = mock.Mock()
        reply = (
            "BL board=239A0029 target=23818A80 name=3401_DFU crc=12345678 abi=3 caps=0A "
            f"| staged:ready mid={package.manifest_id} hash={package.image_hash[:8].hex()}"
        )
        controller.remote_command.return_value = reply
        with contextlib.redirect_stdout(io.StringIO()) as output:
            ota.report_staged_update(controller, args, package)
        controller.remote_command.assert_called_once_with("remote", "ota bootloader status")
        self.assertIn("NOT installed", output.getvalue())
        self.assertIn(f"ota bootloader install {package.manifest_id}", output.getvalue())
        for bad in (reply.replace("staged:ready", "staged:none"), reply.replace(package.manifest_id, "00000000"), reply.replace(package.image_hash[:8].hex(), "0000000000000000")):
            controller.remote_command.return_value = bad
            with self.assertRaisesRegex(ota.OtaError, "exact staged"):
                ota.report_staged_update(controller, args, package)
        controller.reset_mock()
        with self.assertRaisesRegex(ota.OtaError, "explicit"):
            ota.request_install(controller, args, package)
        controller.remote_command.assert_not_called()

    def test_target_query_only_adds_boot_probe_for_boot_packages(self):
        replies = {
            "ota status": "OTA | no download | target:1234ABCD hw=TestBoard",
            "get bootloader.ver": "> 0.11.0-OTAFIX2.4.6",
            "ota self": "self body=100 image=156 base_hash=0011223344556677 | bootloader: abi=3 codecs=0x5",
            "ota stats": "OTA | fw v1.17.1.5",
            "ota bootloader status": (
                "BL board=239A0029 target=23818A80 name=3401_DFU "
                "crc=12345678 abi=3 caps=0A | staged:none mid=- hash=-"
            ),
        }
        for kind in ("application", "bootloader"):
            controller = mock.Mock()
            controller.remote_command.side_effect = lambda _target, command, **_kwargs: replies[command]
            with contextlib.redirect_stdout(io.StringIO()):
                result = ota.query_target(controller, argparse.Namespace(target="remote", package_kind=kind))
            if kind == "bootloader":
                self.assertEqual(result.boot_target_id, self.package.target_id)
                self.assertEqual(ota.compatible_mota(self.package, result), (True, ""))
            else:
                self.assertIsNone(result.boot_target_id)
                self.assertNotIn(mock.call("remote", "ota bootloader status"), controller.remote_command.call_args_list)

    def test_application_version_is_not_compared_to_bootloader_version(self):
        args = ota.build_parser().parse_args(["boot.mota", "remote", "--no-install", "--yes"])
        live = replace(boot_target(self.package), current_version="v99.0.0")
        with contextlib.redirect_stdout(io.StringIO()):
            ota.confirm_update(args, live, self.package)

    def test_boot_status_reply_filter(self):
        for reply in (
            "BL board=239A0029 target=23818A80", "Bootloader update unavailable: bad CRC",
            "ERR this build cannot update its bootloader over LoRa",
        ):
            self.assertTrue(ota.reply_matches_command("ota bootloader status", reply))
        self.assertFalse(ota.reply_matches_command("ota bootloader status", "OTA | no download | target:1234ABCD"))

    @unittest.skipUnless(os.environ.get("MOTATOOL_TEST_BIN") or shutil.which("motatool"), "motatool is not installed")
    def test_real_motatool_verifies_bootloader_and_rejects_wrong_signer_pin(self):
        tool = os.environ.get("MOTATOOL_TEST_BIN") or "motatool"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            package = root / "boot.mota"
            package.write_bytes(self.blob)
            pin = root / "signer.pub"
            pin.write_text(self.blob[105:137].hex(), encoding="ascii")
            ota.require_bootloader_tool_support(argparse.Namespace(package=package, motatool=tool))
            archive_path = root / "boot.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("boot.mota", self.blob)
            ota.require_bootloader_tool_support(argparse.Namespace(
                package=archive_path, zip_member="boot.mota", motatool=tool,
            ))
            ota.verify_with_motatool(tool, package, pin)
            pin.write_text("02" * 32, encoding="ascii")
            with self.assertRaises(ota.OtaError):
                ota.verify_with_motatool(tool, package, pin)

    def test_old_motatool_stops_before_any_radio_access(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "boot.mota"
            path.write_bytes(self.blob)
            args = ota.build_parser().parse_args([str(path), "remote", "--no-install"])
            with (
                mock.patch.object(ota, "require_command"),
                mock.patch.object(ota, "require_meshcli_version") as meshcli,
                mock.patch.object(ota, "run_checked", side_effect=ota.OtaError("unsupported format_ver 3")),
                mock.patch.object(ota, "motatool_repair_root", return_value=Path(directory) / "cache"),
                mock.patch.object(ota.shutil, "which", return_value="cargo"),
                mock.patch.object(ota.sys.stdin, "isatty", return_value=False),
                self.assertRaisesRegex(ota.OtaError, "separate interactive approval"),
            ):
                ota.preflight_inputs(args)
            meshcli.assert_not_called()

    def test_simulated_main_stages_bootloader_and_restores_radios(self):
        package = self.package
        destination_key, source_key = "a1" * 32, "b2" * 32
        controller = mock.Mock()
        controller._run.return_value = [{
            destination_key: {"adv_name": "remote", "public_key": destination_key},
            source_key: {"adv_name": "source", "public_key": source_key},
        }]
        normal = ota.RadioSettings(910.525, 62.5, 7, 5, False)
        controller.get_radio.return_value = normal

        def remote_command(station, command, **_kwargs):
            self.assertEqual(station, destination_key)
            replies = {
                "ota status": "OTA | no download | target:1234ABCD",
                "ota ls": "Updates 1",
                f"ota pull {package.manifest_id} flash": f"OK pulling mid={package.manifest_id} -> flash",
                "ota bootloader status": (
                    "BL board=239A0029 target=23818A80 name=3401_DFU crc=12345678 abi=3 caps=0A "
                    f"| staged:ready mid={package.manifest_id} hash={package.image_hash[:8].hex()}"
                ),
            }
            if command not in replies:
                self.fail(f"unexpected remote command: {command}")
            return replies[command]

        controller.remote_command.side_effect = remote_command
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "boot.mota"
            source.write_bytes(self.blob)
            seeder = mock.Mock()
            with contextlib.ExitStack() as stack:
                for name in (
                    "require_command", "require_meshcli_version", "require_bootloader_tool_support", "preflight_source_cli",
                    "ensure_source_clock_gate_safe", "ensure_controller_clock_safe",
                    "verify_with_motatool", "arm_target_temp_radio",
                    "switch_controller_to_temp_radio", "source_cli_command",
                ):
                    stack.enter_context(mock.patch.object(ota, name))
                stack.enter_context(mock.patch.object(ota, "read_source_name_bounded", return_value="source"))
                stack.enter_context(mock.patch.object(ota, "read_source_rxps", return_value=ota.RxpsSettings(False, 0, 0)))
                stack.enter_context(mock.patch.object(ota, "read_remote_rxps", return_value=ota.RxpsSettings(False, 0, 0)))
                stack.enter_context(mock.patch.object(
                    ota, "query_target", return_value=replace(boot_target(package), name=destination_key),
                ))
                stack.enter_context(mock.patch.object(ota, "read_lora_ota_participant_versions", return_value={}))
                rehearsal = stack.enter_context(mock.patch.object(ota, "run_temp_radio_preflight"))
                stack.enter_context(mock.patch.object(ota, "arm_source_temp_radio_once", return_value=True))
                stack.enter_context(mock.patch.object(ota, "SeederProcess", return_value=seeder))
                stack.enter_context(mock.patch.object(ota, "monitor_download"))
                cleanup = stack.enter_context(mock.patch.object(ota, "shorten_target_temp_window"))
                stack.enter_context(mock.patch.object(ota, "shorten_source_temp_window", return_value=True))
                install = stack.enter_context(mock.patch.object(ota, "request_install"))
                stack.enter_context(mock.patch.object(ota.time, "sleep"))
                output = stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
                error = stack.enter_context(contextlib.redirect_stderr(io.StringIO()))
                result = ota.main([
                    str(source), destination_key[:12], "--controller-serial", "controller",
                    "--source-serial", "source", "--password", "test-only",
                    "--no-install", "--yes", "--work-dir", str(root / "work"),
                ], controller_override=controller)
            self.assertEqual(result, 0, error.getvalue())
            self.assertIn("detected bootloader update", output.getvalue())
            self.assertIn("NOT installed", output.getvalue())
            rehearsal.assert_called_once()
            seeder.start.assert_called_once()
            cleanup.assert_called_once()
            controller.set_radio.assert_called_once_with(normal, "restore controller radio after staging")
            install.assert_not_called()
            self.assertIn(
                mock.call(destination_key, f"ota pull {package.manifest_id} flash", retry=False),
                controller.remote_command.call_args_list,
            )


class StationSelectionTests(unittest.TestCase):
    key = "3ee21f453f8f" + "ab" * 26
    name = "Ashport \U0001f4e1"

    def args(self, selector):
        return argparse.Namespace(
            target=selector, relay_values=[], source_contact_value=None,
            source_shares_controller=True,
        )

    def controller(self):
        controller = mock.Mock()
        controller._run.return_value = [{self.key: {"public_key": self.key, "adv_name": self.name}}]
        return controller

    def test_names_full_keys_and_prefixes_bind_to_one_full_key(self):
        for selector in (self.name, self.name.upper(), self.key, self.key.upper(), self.key[:12]):
            with self.subTest(selector=selector):
                args = self.args(selector)
                controller = self.controller()
                with contextlib.redirect_stdout(io.StringIO()):
                    ota.bind_contact_selectors(controller, args)
                self.assertEqual(args.target, self.key)
                controller._run.assert_called_once_with(["contacts"], "resolve OTA station identifiers")
                controller.remote_command.assert_not_called()

    def test_missing_and_ambiguous_identifiers_are_refused(self):
        controller = self.controller()
        with self.assertRaisesRegex(ota.OtaError, "no contact"):
            ota.bind_contact_selectors(controller, self.args("missing"))
        second = self.key[:-2] + "cd"
        controller._run.return_value[0][second] = {"public_key": second, "adv_name": self.name}
        for selector in (self.name, self.key[:12]):
            with self.assertRaisesRegex(ota.OtaError, "ambiguous"):
                ota.bind_contact_selectors(controller, self.args(selector))

    def test_same_radio_cannot_be_target_and_relay_under_aliases(self):
        args = self.args(self.name)
        args.relay_values = [(self.key[:12], "unused")]
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaisesRegex(ota.OtaError, "different radios"):
            ota.bind_contact_selectors(self.controller(), args)

    def test_remote_reply_accepts_key_selector_with_emoji_name(self):
        for selector in (self.name, self.key, self.key[:12]):
            controller = object.__new__(ota.Controller)
            controller.reply_timeout = 5
            controller._authenticated_targets = {selector}
            controller._run_marked = mock.Mock(return_value=(
                [{"adv_name": self.name, "public_key": self.key}],
                [{"txt_type": 1, "text": "OTA | no download | target:1234ABCD", "pubkey_prefix": self.key[:12]}],
            ))
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertIn("OTA", controller._remote_command_once(selector, "ota status", "unused"))

    def test_clock_and_ack_accept_key_selector(self):
        controller = object.__new__(ota.Controller)
        controller._execute = mock.Mock(side_effect=lambda commands, _label: argparse.Namespace(stdout=(
            commands[1] + '\n{"adv_name": "renamed", "public_key": "' + self.key + '"}\n1800000000\n'
        )))
        self.assertEqual(controller.get_contact_clock(self.key, self.key), 1800000000)
        controller._run_marked = mock.Mock(return_value=([], [
            {"adv_name": "renamed", "public_key": self.key},
            {"expected_ack": "12345678"}, {"code": "12345678"},
        ]))
        controller.prove_contact_ack(self.key, self.key, "proof")


if __name__ == "__main__":
    unittest.main()
