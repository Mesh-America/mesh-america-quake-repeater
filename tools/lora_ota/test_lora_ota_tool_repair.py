"""Automatic host-tool repair tests. All installer execution is mocked."""

import argparse
import contextlib
import io
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

import lora_ota as ota
from test_lora_ota_bootloader import boot_blob


class MotatoolRepairTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.folder = Path(directory.name)
        self.root = self.folder / "private-install"
        self.binary = self.root / "bin" / ("motatool.exe" if os.name == "nt" else "motatool")
        self.probe = self.folder / "boot.mota"
        self.probe.write_bytes(boot_blob())
        self.args = argparse.Namespace(motatool="old-motatool", yes=True, package=self.probe)
        self.failure = ota.OtaError("unsupported format_ver 3")
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(mock.patch.object(ota, "motatool_repair_root", return_value=self.root))
        stack.enter_context(mock.patch.object(ota.shutil, "which", return_value="cargo"))
        stack.enter_context(mock.patch.object(ota.sys.stdin, "isatty", return_value=True))
        self.prompt = stack.enter_context(mock.patch("builtins.input", return_value="yes"))
        self.check = stack.enter_context(mock.patch.object(ota, "check_bootloader_tool"))
        self.install = stack.enter_context(mock.patch.object(ota.subprocess, "run", side_effect=self.fake_install))
        self.output = stack.enter_context(contextlib.redirect_stdout(io.StringIO()))

    def fake_install(self, command, **kwargs):
        self.binary.parent.mkdir(parents=True, exist_ok=True)
        self.binary.write_bytes(b"test-only installer output, not executable")
        return subprocess.CompletedProcess(command, 0)

    def repair(self):
        ota.offer_motatool_repair(self.args, self.probe, self.failure)

    def test_consent_installs_pinned_private_tool_rechecks_and_selects_it(self):
        with mock.patch.dict(os.environ, {"MESHCORE_ADMIN_PASSWORD": "never-pass-to-build"}):
            self.repair()
        self.prompt.assert_called_once()
        self.install.assert_called_once()
        command = self.install.call_args.args[0]
        self.assertEqual(command, ota.motatool_repair_command(self.root))
        self.assertIn(ota.MOTATOOL_REPAIR_REPOSITORY, command)
        self.assertIn(ota.MOTATOOL_REPAIR_REVISION, command)
        self.assertIn("--locked", command)
        self.assertNotIn("MESHCORE_ADMIN_PASSWORD", self.install.call_args.kwargs["env"])
        self.assertEqual(self.install.call_args.kwargs["stdin"], subprocess.DEVNULL)
        self.assertEqual(self.install.call_args.kwargs["timeout"], ota.MOTATOOL_REPAIR_TIMEOUT_SECONDS)
        self.check.assert_called_once_with(str(self.binary), self.probe)
        self.assertEqual(self.args.motatool, str(self.binary))
        self.assertIn("Existing motatool installations and PATH will not be changed", self.output.getvalue())

    def test_decline_or_blank_never_creates_install_directory(self):
        for answer in ("", "no", "n", "anything else"):
            with self.subTest(answer=answer):
                self.prompt.return_value = answer
                with self.assertRaisesRegex(ota.OtaError, "declined"):
                    self.repair()
                self.assertFalse(self.root.exists())
                self.install.assert_not_called()
                self.assertEqual(self.args.motatool, "old-motatool")

    def test_eof_does_not_approve_install(self):
        self.prompt.side_effect = EOFError
        with self.assertRaisesRegex(ota.OtaError, "declined"):
            self.repair()
        self.assertFalse(self.root.exists())
        self.install.assert_not_called()

    def test_yes_flag_never_approves_repair_in_noninteractive_run(self):
        self.assertTrue(self.args.yes)
        with mock.patch.object(ota.sys.stdin, "isatty", return_value=False):
            with self.assertRaisesRegex(ota.OtaError, "--yes does not approve"):
                self.repair()
        self.prompt.assert_not_called()
        self.install.assert_not_called()
        self.assertIn("Manual install command:", self.output.getvalue())
        self.assertIn("--motatool", self.output.getvalue())
        self.assertFalse(self.root.exists())

    def test_missing_cargo_gives_prerequisite_without_installing_anything(self):
        with mock.patch.object(ota.shutil, "which", return_value=None):
            with self.assertRaisesRegex(ota.OtaError, "https://rustup.rs"):
                self.repair()
        self.install.assert_not_called()
        self.prompt.assert_not_called()
        self.assertFalse(self.root.exists())

    def test_cargo_failure_stops_and_preserves_original_selection(self):
        self.install.side_effect = None
        self.install.return_value = subprocess.CompletedProcess([], 101)
        with self.assertRaisesRegex(ota.OtaError, "Cargo exit 101"):
            self.repair()
        self.check.assert_not_called()
        self.assertEqual(self.args.motatool, "old-motatool")

    def test_cargo_timeout_or_launch_failure_stops(self):
        for error in (OSError("cannot start compiler"), subprocess.TimeoutExpired("cargo", 3600)):
            with self.subTest(error=error):
                self.install.side_effect = error
                with self.assertRaisesRegex(ota.OtaError, "repair failed"):
                    self.repair()
                self.check.assert_not_called()
                self.assertEqual(self.args.motatool, "old-motatool")

    def test_installer_success_without_binary_is_not_success(self):
        self.install.side_effect = None
        self.install.return_value = subprocess.CompletedProcess([], 0)
        with self.assertRaisesRegex(ota.OtaError, "did not produce"):
            self.repair()
        self.check.assert_not_called()
        self.assertEqual(self.args.motatool, "old-motatool")

    def test_failed_postinstall_check_does_not_select_bad_tool(self):
        self.check.side_effect = ota.OtaError("still unsupported")
        with self.assertRaisesRegex(ota.OtaError, "still failed bootloader verification"):
            self.repair()
        self.assertEqual(self.args.motatool, "old-motatool")

    def test_default_tool_reuses_rechecked_cache_without_download_or_prompt(self):
        self.args.motatool = "motatool"
        self.fake_install([])
        with mock.patch.object(ota.sys.stdin, "isatty", return_value=False):
            self.repair()
        self.prompt.assert_not_called()
        self.install.assert_not_called()
        self.check.assert_called_once_with(str(self.binary), self.probe)
        self.assertEqual(self.args.motatool, str(self.binary))

    def test_custom_tool_is_not_silently_replaced_even_with_valid_cache(self):
        self.fake_install([])
        self.prompt.return_value = "no"
        with self.assertRaisesRegex(ota.OtaError, "declined"):
            self.repair()
        self.assertIn("cached motatool", self.prompt.call_args.args[0])
        self.assertEqual(self.args.motatool, "old-motatool")
        self.install.assert_not_called()

    def test_approved_cached_tool_needs_no_cargo(self):
        self.fake_install([])
        with mock.patch.object(ota.shutil, "which", return_value=None):
            self.repair()
        self.install.assert_not_called()
        self.assertEqual(self.check.call_count, 2)
        self.assertEqual(self.args.motatool, str(self.binary))

    def test_bad_cache_requires_new_consent_and_recheck(self):
        self.args.motatool = "motatool"
        self.fake_install([])
        self.check.side_effect = [ota.OtaError("old cached tool"), None]
        self.repair()
        self.prompt.assert_called_once()
        self.install.assert_called_once()
        self.assertEqual(self.check.call_count, 2)

    def test_working_tool_does_not_offer_or_install(self):
        with mock.patch.object(ota, "offer_motatool_repair") as offer:
            ota.require_bootloader_tool_support(self.args)
        offer.assert_not_called()
        self.install.assert_not_called()

    def test_missing_or_incompatible_tool_reaches_the_offer(self):
        self.check.side_effect = self.failure
        with mock.patch.object(ota, "offer_motatool_repair") as offer:
            ota.require_bootloader_tool_support(self.args)
        offer.assert_called_once_with(self.args, self.probe, self.failure)

    def test_repair_failure_in_main_never_contacts_radios(self):
        self.check.side_effect = self.failure
        self.prompt.return_value = "no"
        with (
            mock.patch.object(ota, "Controller") as controller,
            mock.patch.object(ota, "source_cli_command") as source,
            contextlib.redirect_stderr(io.StringIO()),
        ):
            status = ota.main([
                str(self.probe), "remote", "--controller-serial", "controller",
                "--source-serial", "source", "--no-install", "--yes",
            ])
        self.assertEqual(status, 2)
        self.prompt.assert_called_once()
        self.install.assert_not_called()
        controller.assert_not_called()
        source.assert_not_called()

    def test_repaired_binary_is_selected_before_meshcli_preflight(self):
        self.check.side_effect = [self.failure, None]
        args = ota.build_parser().parse_args([str(self.probe), "remote", "--no-install"])
        with mock.patch.object(ota, "require_meshcli_version") as meshcli:
            ota.preflight_inputs(args)
        self.assertEqual(args.motatool, str(self.binary))
        meshcli.assert_called_once()


if __name__ == "__main__":
    unittest.main()
