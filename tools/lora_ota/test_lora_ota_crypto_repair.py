"""Host dependency repair regressions. No network, installers or radio access."""

import contextlib
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import zipfile

import lora_ota as ota
from test_lora_ota import firmware, mota_blob, VERSION_NEW
from test_lora_ota_bootloader import boot_blob


class CryptographyRepairTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name) / "private-python"
        self.failure = ota.BootloaderCryptoError("No module named cryptography")
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(mock.patch.object(ota, "cryptography_repair_root", return_value=self.root))
        stack.enter_context(mock.patch.object(ota.sys.stdin, "isatty", return_value=True))
        self.prompt = stack.enter_context(mock.patch("builtins.input", return_value="yes"))
        self.activate = stack.enter_context(mock.patch.object(ota, "activate_cached_cryptography"))
        self.run = stack.enter_context(mock.patch.object(
            ota.subprocess, "run", return_value=subprocess.CompletedProcess([], 0),
        ))
        self.output = stack.enter_context(contextlib.redirect_stdout(io.StringIO()))

    def repair(self):
        ota.offer_cryptography_repair(self.failure)

    def test_approved_install_uses_same_interpreter_private_wheels_and_rechecks(self):
        with mock.patch.dict(os.environ, {"MESHCORE_ADMIN_PASSWORD": "do-not-inherit"}):
            self.repair()
        self.prompt.assert_called_once()
        self.assertTrue(self.root.is_dir())
        self.assertEqual(self.run.call_count, 2)
        probe, install = self.run.call_args_list
        self.assertEqual(probe.args[0][:3], [sys.executable, "-m", "pip"])
        self.assertIn("--version", probe.args[0])
        self.assertEqual(install.args[0], ota.cryptography_repair_command(self.root))
        self.assertIn("--only-binary=:all:", install.args[0])
        self.assertIn("--isolated", install.args[0])
        self.assertNotIn("--break-system-packages", install.args[0])
        for call in (probe, install):
            self.assertNotIn("MESHCORE_ADMIN_PASSWORD", call.kwargs["env"])
            self.assertEqual(call.kwargs["env"]["PIP_CONFIG_FILE"], os.devnull)
            self.assertEqual(call.kwargs["stdin"], subprocess.DEVNULL)
        self.assertEqual(install.kwargs["timeout"], ota.CRYPTOGRAPHY_REPAIR_TIMEOUT_SECONDS)
        self.activate.assert_called_once_with(self.root)

    def test_blank_decline_and_eof_never_install(self):
        for answer in ("", "no", "unexpected", EOFError()):
            with self.subTest(answer=answer):
                self.prompt.side_effect = answer if isinstance(answer, Exception) else None
                self.prompt.return_value = answer
                self.run.reset_mock()
                with self.assertRaisesRegex(ota.OtaError, "declined"):
                    self.repair()
                self.assertFalse(self.root.exists())
                self.assertEqual(self.run.call_count, 1)  # Read-only pip probe.
                self.activate.assert_not_called()

    def test_noninteractive_never_installs_and_prints_manual_command(self):
        with mock.patch.object(ota.sys.stdin, "isatty", return_value=False):
            with self.assertRaisesRegex(ota.OtaError, "--yes does not approve"):
                self.repair()
        self.prompt.assert_not_called()
        self.assertEqual(self.run.call_count, 1)
        self.assertFalse(self.root.exists())
        self.assertIn("Manual install command:", self.output.getvalue())
        self.assertIn(str(self.root), self.output.getvalue())

    def test_missing_pip_reports_exact_interpreter_bootstrap(self):
        self.run.return_value = subprocess.CompletedProcess([], 1)
        with self.assertRaisesRegex(ota.OtaError, "ensurepip") as error:
            self.repair()
        self.assertIn(sys.executable, str(error.exception))
        self.prompt.assert_not_called()
        self.assertFalse(self.root.exists())
        self.activate.assert_not_called()

    def test_pip_probe_failure_is_bounded_and_does_not_install(self):
        for error in (OSError("not executable"), subprocess.TimeoutExpired("pip", 30)):
            with self.subTest(error=error):
                self.run.side_effect = error
                with self.assertRaisesRegex(ota.OtaError, "cannot check pip"):
                    self.repair()
                self.prompt.assert_not_called()
                self.assertFalse(self.root.exists())

    def test_failed_install_never_activates_partial_files(self):
        self.run.side_effect = [subprocess.CompletedProcess([], 0), subprocess.CompletedProcess([], 1)]
        with self.assertRaisesRegex(ota.OtaError, "pip exit 1"):
            self.repair()
        self.activate.assert_not_called()

    def test_install_timeout_and_launch_failure_stop(self):
        for error in (OSError("cannot start"), subprocess.TimeoutExpired("pip", 600)):
            with self.subTest(error=error):
                self.run.side_effect = [subprocess.CompletedProcess([], 0), error]
                with mock.patch.object(Path, "is_dir", return_value=False), self.assertRaisesRegex(ota.OtaError, "repair failed"):
                    self.repair()
                self.activate.assert_not_called()

    def test_unwritable_cache_is_an_actionable_error(self):
        with mock.patch.object(Path, "mkdir", side_effect=PermissionError("read-only cache")):
            with self.assertRaisesRegex(ota.OtaError, "read-only cache"):
                self.repair()
        self.assertEqual(self.run.call_count, 1)
        self.activate.assert_not_called()

    def test_successful_installer_is_not_enough_if_crypto_check_fails(self):
        self.activate.side_effect = ota.OtaError("Ed25519 check failed")
        with self.assertRaisesRegex(ota.OtaError, "Ed25519 check failed"):
            self.repair()
        self.assertNotIn("self-test passed", self.output.getvalue())

    def test_cached_install_is_rechecked_without_pip_or_prompt(self):
        self.root.mkdir()
        with mock.patch.object(ota.sys.stdin, "isatty", return_value=False):
            self.repair()
        self.activate.assert_called_once_with(self.root)
        self.run.assert_not_called()
        self.prompt.assert_not_called()

    def test_bad_cache_offers_repair_and_rechecks_again(self):
        self.root.mkdir()
        self.activate.side_effect = [ota.OtaError("broken wheel"), None]
        self.repair()
        self.prompt.assert_called_once()
        self.assertEqual(self.run.call_count, 2)
        self.assertEqual(self.activate.call_count, 2)


class CryptoPreflightTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.folder = Path(directory.name)
        self.path = self.folder / "boot.mota"
        self.blob = boot_blob()
        self.path.write_bytes(self.blob)
        self.library = ota.bootloader_library()
        self.real_verify = self.library.verify
        self.missing = True
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        self.verify = stack.enter_context(mock.patch.object(self.library, "verify", side_effect=self.verify_package))
        self.repair = stack.enter_context(mock.patch.object(ota, "offer_cryptography_repair", side_effect=self.fix_crypto))
        self.tool = stack.enter_context(mock.patch.object(ota, "check_bootloader_tool"))
        self.meshcli = stack.enter_context(mock.patch.object(ota, "require_meshcli_version"))
        self.controller = stack.enter_context(mock.patch.object(ota, "Controller"))
        self.source = stack.enter_context(mock.patch.object(ota, "source_cli_command"))
        stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
        self.stderr = stack.enter_context(contextlib.redirect_stderr(io.StringIO()))

    def verify_package(self, parsed):
        if self.missing:
            raise ImportError("No module named cryptography")
        return self.real_verify(parsed)

    def fix_crypto(self, failure):
        self.assertIsInstance(failure, ota.BootloaderCryptoError)
        self.missing = False

    def args(self, *extra):
        return ota.build_parser().parse_args([str(self.path), "remote", "--no-install", *extra])

    def test_direct_bootloader_repaired_then_fully_verified(self):
        args = self.args()
        ota.preflight_inputs(args)
        self.repair.assert_called_once()
        self.assertEqual(self.verify.call_count, 2)
        self.assertEqual(args.package_kind, "bootloader")
        self.tool.assert_called_once()
        self.meshcli.assert_called_once()
        self.controller.assert_not_called()
        self.source.assert_not_called()

    def test_zip_dependency_failure_is_not_misreported_as_invalid_member(self):
        self.path = self.folder / "boot.zip"
        with zipfile.ZipFile(self.path, "w") as archive:
            archive.writestr("board/boot.mota", self.blob)
        ota.preflight_inputs(self.args("--zip-member", "board/boot.mota"))
        self.repair.assert_called_once()
        self.assertEqual(self.verify.call_count, 2)
        self.tool.assert_called_once()

    def test_working_crypto_never_offers_install(self):
        self.missing = False
        ota.preflight_inputs(self.args())
        self.repair.assert_not_called()
        self.tool.assert_called_once()

    def test_application_updates_do_not_require_crypto(self):
        self.path.write_bytes(mota_blob(firmware(b"app" * 1000, VERSION_NEW)))
        with mock.patch.object(ota, "require_command"):
            ota.preflight_inputs(self.args())
        self.verify.assert_not_called()
        self.repair.assert_not_called()

    def test_raw_tcp_command_does_not_require_crypto_or_package_tools(self):
        with mock.patch.object(ota, "tcp_cli_main", return_value=0) as raw:
            self.assertEqual(ota.main(["--tcp-cli", "127.0.0.1", "ota status"]), 0)
        raw.assert_called_once()
        self.verify.assert_not_called()
        self.repair.assert_not_called()

    def test_library_parsing_never_prompts_or_installs(self):
        with self.assertRaises(ota.BootloaderCryptoError):
            ota.parse_mota(self.blob)
        self.repair.assert_not_called()

    def test_unsafe_boot_action_rejected_before_offering_install(self):
        args = self.args("--yes")
        args.no_install = False
        with self.assertRaisesRegex(ota.OtaError, "use --no-install"):
            ota.preflight_inputs(args)
        self.repair.assert_not_called()
        self.tool.assert_not_called()

    def test_repair_is_attempted_only_once(self):
        self.repair.side_effect = None  # Simulate installer returning without fixing anything.
        with self.assertRaises(ota.BootloaderCryptoError):
            ota.preflight_inputs(self.args())
        self.repair.assert_called_once()
        self.tool.assert_not_called()

    def test_invalid_signature_still_fails_after_dependency_repair(self):
        bad = bytearray(self.blob)
        bad[137] ^= 1
        self.path.write_bytes(bad)
        with self.assertRaisesRegex(ota.OtaError, "invalid bootloader mOTA"):
            ota.preflight_inputs(self.args())
        self.repair.assert_called_once()
        self.tool.assert_not_called()
        self.meshcli.assert_not_called()

    def test_declined_repair_in_main_stops_before_any_radio_access(self):
        self.repair.side_effect = ota.OtaError("cryptography repair declined")
        status = ota.main([
            str(self.path), "remote", "--no-install", "--yes",
            "--controller-serial", "controller", "--source-serial", "source",
        ])
        self.assertEqual(status, 2)
        self.assertIn("cryptography repair declined", self.stderr.getvalue())
        self.controller.assert_not_called()
        self.source.assert_not_called()
        self.tool.assert_not_called()


class CryptoCacheTests(unittest.TestCase):
    def test_interpreter_identity_changes_cache(self):
        original = ota.cryptography_repair_root()
        with mock.patch.object(ota.sys, "executable", "another-python"):
            self.assertNotEqual(original, ota.cryptography_repair_root())
        with mock.patch.object(ota.sysconfig, "get_platform", return_value="another-architecture"):
            self.assertNotEqual(original, ota.cryptography_repair_root())

    def test_empty_cache_cannot_use_system_crypto_and_rolls_back_imports(self):
        import cryptography
        old_path = sys.path[:]
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ota.OtaError, "private installation did not provide"):
                ota.activate_cached_cryptography(Path(directory))
        self.assertEqual(sys.path, old_path)
        self.assertIs(sys.modules["cryptography"], cryptography)

    def test_real_ed25519_known_vector_and_tampered_message(self):
        import cryptography
        root = Path(cryptography.__file__).parent.parent
        with mock.patch.object(sys, "path", sys.path[:]):
            ota.activate_cached_cryptography(root)
            self.assertEqual(sys.path[0], str(root))


if __name__ == "__main__":
    unittest.main()
