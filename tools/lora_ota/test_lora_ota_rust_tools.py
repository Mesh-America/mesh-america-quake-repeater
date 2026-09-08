"""Toolchain preflight regressions; fake executables are never actually run."""

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


class RustToolSelectionTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.outputs = {}
        self.args = argparse.Namespace(cargo=None, rustc=None)
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(mock.patch.dict(os.environ, {
            "PATH": str(self.root), "PATHEXT": ".com;.exe;.bat;.cmd",
        }, clear=True))
        self.probe = stack.enter_context(mock.patch.object(ota.subprocess, "run", side_effect=self.run_probe))
        self.rustup = stack.enter_context(mock.patch.object(ota, "installed_rustup_cargos", return_value=[]))
        stack.enter_context(mock.patch.object(ota, "resolve_rustup_proxy", side_effect=lambda path, _: path))
        self.output = stack.enter_context(contextlib.redirect_stdout(io.StringIO()))

    def executable(self, name, version):
        suffix = ".exe" if os.name == "nt" else ""
        path = self.root / (name + suffix)
        path.write_bytes(b"test placeholder: must never execute")
        path.chmod(0o755)
        tool = "cargo" if name.startswith("cargo") else "rustc"
        self.outputs[str(path)] = f"{tool} {version} (test-only build)"
        return str(path)

    def pair(self, version, suffix=""):
        return self.executable("cargo" + suffix, version), self.executable("rustc" + suffix, version)

    def run_probe(self, command, **kwargs):
        self.assertEqual(command[1:], ["--version"])
        self.assertIn(command[0], self.outputs)
        return subprocess.CompletedProcess(command, 0, self.outputs[command[0]], "")

    def select(self):
        return ota.select_motatool_build_tools(self.args)

    def test_compatible_default_pair_is_preserved(self):
        cargo, rustc = self.pair("1.91.0")
        self.pair("1.98.0", "-1.98")
        selected = self.select()
        self.assertEqual((selected.cargo, selected.rustc), (cargo, rustc))
        self.rustup.assert_not_called()
        self.assertEqual(self.probe.call_count, 2)

    def test_reported_ubuntu_old_default_selects_versioned_pair(self):
        old_cargo, _ = self.pair("1.75.0")
        cargo, rustc = self.pair("1.91.0", "-1.91")
        selected = self.select()
        self.assertEqual((selected.cargo, selected.rustc), (cargo, rustc))
        self.assertEqual(self.probe.call_args_list[0].args[0][0], old_cargo)
        self.assertIn("1.75.0", self.output.getvalue())
        self.assertEqual(selected.environment()["RUSTC"], rustc)
        self.assertEqual(selected.environment()["CARGO"], cargo)

    def test_new_cargo_with_old_rustc_is_not_accepted(self):
        self.executable("cargo", "1.91.0")
        self.executable("rustc", "1.75.0")
        with self.assertRaisesRegex(ota.OtaError, "rustc 1.75.0"):
            self.select()

    def test_edition_2024_alone_is_not_enough_for_icu_dependencies(self):
        self.pair("1.85.0")
        with self.assertRaisesRegex(ota.OtaError, "1.86.0 or newer"):
            self.select()

    def test_minimum_supported_pair_is_accepted(self):
        self.pair("1.86.0")
        self.assertEqual(self.select().rustc_version, (1, 86, 0))

    def test_incompatible_major_minor_pair_is_rejected(self):
        self.executable("cargo", "1.91.0")
        self.executable("rustc", "1.90.0")
        with self.assertRaisesRegex(ota.OtaError, "toolchain mismatch"):
            self.select()

    def test_patch_release_difference_is_allowed(self):
        self.executable("cargo", "1.91.1")
        self.executable("rustc", "1.91.0")
        self.assertEqual(self.select().cargo_version, (1, 91, 1))

    def test_missing_unversioned_cargo_can_use_versioned_pair(self):
        cargo, _ = self.pair("1.91.0", "-1.91")
        self.assertEqual(self.select().cargo, cargo)

    def test_versioned_cargo_does_not_fall_back_to_old_unversioned_rustc(self):
        self.executable("cargo-1.91", "1.91.0")
        self.executable("rustc", "1.75.0")
        with self.assertRaisesRegex(ota.OtaError, "rustc-1.91"):
            self.select()

    def test_versioned_candidates_are_ranked_numerically(self):
        self.pair("1.9.0", "-1.9")
        self.pair("1.91.0", "-1.91")
        cargo, _ = self.pair("1.100.0", "-1.100")
        self.assertEqual(self.select().cargo, cargo)

    def test_versioned_cargo_can_use_compatible_unversioned_compiler(self):
        self.executable("cargo-1.91", "1.91.0")
        rustc = self.executable("rustc", "1.91.0")
        self.assertEqual(self.select().rustc, rustc)

    def test_new_default_cargo_can_find_matching_versioned_compiler(self):
        self.executable("cargo", "1.91.0")
        self.executable("rustc", "1.75.0")
        rustc = self.executable("rustc-1.91", "1.91.0")
        self.assertEqual(self.select().rustc, rustc)

    def test_explicit_cargo_is_not_replaced(self):
        self.args.cargo, _ = self.pair("1.75.0")
        self.pair("1.91.0", "-1.91")
        with self.assertRaisesRegex(ota.OtaError, "not silently replaced"):
            self.select()
        self.assertEqual(self.probe.call_count, 1)
        self.rustup.assert_not_called()

    def test_explicit_versioned_pair_is_used(self):
        cargo, rustc = self.pair("1.91.0", "-1.91")
        self.args.cargo = "cargo-1.91"
        self.args.rustc = "rustc-1.91"
        self.assertEqual(self.select().rustc, rustc)
        self.assertEqual(self.select().cargo, cargo)

    def test_explicit_missing_cargo_never_falls_back(self):
        self.pair("1.91.0")
        self.args.cargo = "missing-cargo"
        with self.assertRaisesRegex(ota.OtaError, "missing-cargo"):
            self.select()
        self.probe.assert_not_called()

    def test_explicit_old_compiler_environment_is_not_silently_overridden(self):
        self.pair("1.91.0")
        compiler = self.executable("rustc-1.75", "1.75.0")
        for variable in ("RUSTC", "CARGO_BUILD_RUSTC"):
            with self.subTest(variable=variable), mock.patch.dict(os.environ, {variable: compiler}):
                with self.assertRaisesRegex(ota.OtaError, "rustc 1.75.0"):
                    self.select()

    def test_cli_compiler_takes_precedence_over_environment(self):
        self.pair("1.91.0")
        old = self.executable("rustc-1.75", "1.75.0")
        self.args.rustc = "rustc"
        with mock.patch.dict(os.environ, {"RUSTC": old}):
            self.assertEqual(self.select().rustc_version, (1, 91, 0))

    def test_installed_rustup_toolchain_is_fallback(self):
        self.pair("1.75.0")
        tools = self.root / "installed-stable" / "bin"
        tools.mkdir(parents=True)
        cargo, rustc = self.pair("1.91.0", "-1.91")
        actual_cargo = tools / Path(cargo).name.replace("-1.91", "")
        actual_rustc = tools / Path(rustc).name.replace("-1.91", "")
        Path(cargo).rename(actual_cargo)
        Path(rustc).rename(actual_rustc)
        self.outputs[str(actual_cargo)] = self.outputs[cargo]
        self.outputs[str(actual_rustc)] = self.outputs[rustc]
        self.rustup.return_value = [str(actual_cargo)]
        self.assertEqual(self.select().rustc, str(actual_rustc))

    def test_malformed_version_fails_closed(self):
        cargo, _ = self.pair("unknown")
        with self.assertRaisesRegex(ota.OtaError, "cannot determine a stable cargo version"):
            self.select()
        self.assertIn(cargo, self.output.getvalue())

    def test_nightly_is_not_automatically_selected(self):
        self.pair("1.91.0-nightly")
        with self.assertRaisesRegex(ota.OtaError, "stable cargo version"):
            self.select()

    def test_no_toolchain_explains_non_root_stable_fix(self):
        with self.assertRaises(ota.OtaError) as error:
            self.select()
        message = str(error.exception)
        self.assertIn("--cargo cargo-1.91 --rustc rustc-1.91", message)
        self.assertIn("Root access and nightly are not required", message)
        self.assertIn("No build or radio changes", message)


class RustProbeTests(unittest.TestCase):
    def test_probe_is_bounded_noninteractive_and_strips_admin_secret(self):
        result = subprocess.CompletedProcess([], 0, "cargo 1.91.0\n", "")
        with (
            mock.patch.object(ota.subprocess, "run", return_value=result) as run,
            mock.patch.dict(os.environ, {"MESHCORE_ADMIN_PASSWORD": "secret"}),
        ):
            self.assertEqual(ota.rust_host_output(["cargo", "--version"]), "cargo 1.91.0")
        options = run.call_args.kwargs
        self.assertEqual(options["timeout"], ota.RUST_TOOL_PROBE_TIMEOUT_SECONDS)
        self.assertEqual(options["stdin"], subprocess.DEVNULL)
        self.assertEqual(options["env"]["RUSTUP_AUTO_INSTALL"], "0")
        self.assertNotIn("MESHCORE_ADMIN_PASSWORD", options["env"])

    def test_probe_timeout_and_missing_executable_are_actionable(self):
        for error in (FileNotFoundError("not installed"), subprocess.TimeoutExpired("cargo", 10)):
            with mock.patch.object(ota.subprocess, "run", side_effect=error):
                with self.assertRaisesRegex(ota.OtaError, "cannot probe cargo"):
                    ota.rust_host_output(["cargo", "--version"])

    def test_failed_probe_preserves_diagnostic(self):
        result = subprocess.CompletedProcess([], 1, "", "toolchain not installed")
        with mock.patch.object(ota.subprocess, "run", return_value=result):
            with self.assertRaisesRegex(ota.OtaError, "toolchain not installed"):
                ota.rust_host_output(["cargo", "--version"])

    def test_rustup_discovery_only_uses_installed_stable_toolchains(self):
        def output(command):
            if command[1:] == ["toolchain", "list"]:
                return "stable-host (default)\n1.91.0-host\nnightly-host\nbeta-host\ncustom\n"
            return "/installed/" + command[3] + "/cargo"
        with (
            mock.patch.object(ota.shutil, "which", return_value="rustup"),
            mock.patch.object(ota, "rust_host_output", side_effect=output) as probe,
        ):
            self.assertEqual(ota.installed_rustup_cargos(), [
                "/installed/stable-host/cargo", "/installed/1.91.0-host/cargo",
            ])
        self.assertEqual(probe.call_count, 3)
        self.assertTrue(all(call.args[0][1] in ("toolchain", "which") for call in probe.call_args_list))

    def test_proxy_is_resolved_to_real_binary_before_build_cwd_changes(self):
        with (
            mock.patch.object(ota.shutil, "which", return_value="rustup"),
            mock.patch.object(ota.os.path, "samefile", return_value=True),
            mock.patch.object(ota, "rust_host_output", return_value="/installed/stable/bin/cargo") as probe,
            mock.patch.object(ota, "rust_executable", side_effect=lambda path: path),
        ):
            self.assertEqual(ota.resolve_rustup_proxy("proxy/cargo", "cargo"), "/installed/stable/bin/cargo")
        probe.assert_called_once_with(["rustup", "which", "cargo"])

    def test_build_environment_is_private_and_pins_both_binaries(self):
        pair = ota.RustBuildTools("/new/cargo", "/new/rustc", (1, 91, 0), (1, 91, 0))
        with mock.patch.dict(os.environ, {"CARGO": "old-cargo", "RUSTC": "old-rustc"}):
            env = pair.environment()
            self.assertEqual(env["CARGO"], "/new/cargo")
            self.assertEqual(env["RUSTC"], "/new/rustc")
            self.assertEqual(os.environ["CARGO"], "old-cargo")
            self.assertEqual(os.environ["RUSTC"], "old-rustc")


if __name__ == "__main__":
    unittest.main()
