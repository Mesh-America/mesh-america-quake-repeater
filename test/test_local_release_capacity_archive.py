#!/usr/bin/env python3
"""Exercise production archival and resume wiring without invoking PlatformIO."""

import fcntl
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

REPO = Path(os.environ.get("CAPACITY_ARCHIVE_REPO", str(Path(__file__).resolve().parents[1])))
sys.path.insert(0, str(REPO / "scripts"))
from firmware_build_recipe import package_occupied
MODULE = Path(os.environ.get("CAPACITY_ARCHIVE_MODULE", str(REPO / "scripts/build_local_release.py")))
SPEC = importlib.util.spec_from_file_location("capacity_archive_release", MODULE)
BUILD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILD)
VERSION = "v1.17.1.9-halo-keymind-cascade-dev"
SOURCE = "8d31b3932de614ac38d238f1a01010bc5f362fe8"
TARGET = "heltec_v4_repeater_lora_ota_no_external_sensors"


class CapacityArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="mesh-capacity-archive-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.work = self.root / ".releases" / (".build-" + VERSION + "-" + SOURCE[:8])
        (self.work / "build-logs").mkdir(parents=True)

    def attempt(self, target=TARGET, *, infix="-ota"):
        stem = f"{target}{infix}-{VERSION}-{SOURCE[:8]}"
        manifest = self.work / (stem + ".capabilities.json")
        value = {"schema_version": 2, "target": target, "artifact_target": target,
                 "platformio_env": "heltec_v4_repeater", "platform": "ESP32_PLATFORM",
                 "build_profile": "standard", "verified": True,
                 "ota_update_verified": True,
                 "ota_update_evidence": "firmware fits both OTA application slots; otadata present",
                 "verification": [{"capability": "ota.update.lora", "present": True,
                                   "source": "packaged application", "evidence": "OTA: status"}],
                 "build_recipe": {"schema_version": 1, "sha256": "a" * 64}}
        manifest.write_text(json.dumps(value, indent=2) + "\n", encoding="ascii")
        log = self.work / "build-logs" / (target + "-standard.log")
        log.write_text(
            f'    -DFIRMWARE_VERSION="{VERSION}-{SOURCE[:8]}"\n'
            f"Verified 1 capability marker(s); manifest: {manifest}\n"
            "ESP32 app image is 1334184 bytes, exceeding portable LoRa-OTA "
            "slot 0x10000..0x150000 (1310720 bytes) by 23464 bytes\n"
            f"DEFERRED: {target} (standard) exceeds the portable OTA slot; "
            "the expanded FULL pass is required.\n", encoding="ascii")
        return manifest, log

    def archive(self, **kwargs):
        return BUILD.archive_capacity_rejected_attempts(
            self.work, VERSION, SOURCE, project_root=self.root, **kwargs)

    def mutate(self, manifest, **updates):
        value = json.loads(manifest.read_text()); value.update(updates)
        manifest.write_text(json.dumps(value) + "\n", encoding="ascii")

    def assert_preserved(self, manifest, log):
        raw_manifest, raw_log = manifest.read_bytes(), log.read_bytes()
        before = sorted(path.name for path in self.work.parent.iterdir())
        result = self.archive()
        self.assertEqual(result["archived"], [])
        self.assertEqual(manifest.read_bytes(), raw_manifest)
        self.assertEqual(log.read_bytes(), raw_log)
        self.assertEqual(sorted(path.name for path in self.work.parent.iterdir()), before)
        self.assertEqual(len(result["preserved"]), 1)

    def test_real_log_shape_preserves_raw_bytes_and_leaves_log_in_place(self):
        manifest, log = self.attempt()
        raw_manifest, raw_log = manifest.read_bytes(), log.read_bytes()
        self.assertTrue(package_occupied(manifest.with_name(
            manifest.name.removesuffix(".capabilities.json"))))
        result = self.archive(); archive = Path(result["archive"])
        self.assertEqual(len(result["archived"]), 1)
        self.assertFalse(manifest.exists())
        self.assertFalse(package_occupied(manifest.with_name(
            manifest.name.removesuffix(".capabilities.json"))))
        self.assertEqual(log.read_bytes(), raw_log)
        self.assertEqual((archive / "manifests" / manifest.name).read_bytes(), raw_manifest)
        self.assertEqual((archive / "logs" / log.name).read_bytes(), raw_log)
        self.assertEqual(archive.parent, self.work.parent)
        self.assertNotIn(archive, self.work.rglob("*"))
        index = json.loads((archive / "index.json").read_text(encoding="ascii"))
        self.assertEqual(index["state"], "archived")
        self.assertEqual(index["source_commit"], SOURCE)
        record = index["attempts"][0]
        self.assertEqual(record["manifest_sha256"], hashlib.sha256(raw_manifest).hexdigest())
        self.assertEqual(record["original_log_sha256"], hashlib.sha256(raw_log).hexdigest())
        self.assertEqual(record["image_bytes"] - record["portable_limit_bytes"], 23464)
        self.assertEqual(self.archive()["archived"], [])

    def test_plain_c6_filename_and_multiple_attempts_receive_unique_archive(self):
        self.attempt("Xiao_C6_repeater_", infix="")
        self.attempt()
        first = self.archive()
        self.assertEqual(len(first["archived"]), 2)
        self.attempt()
        second = self.archive()
        self.assertNotEqual(first["archive"], second["archive"])
        self.assertTrue(Path(first["archive"]).is_dir())

    def test_log_only_precollection_size_deferral_needs_no_archive(self):
        manifest, log = self.attempt("Station_G2_repeater_lora_ota_no_external_sensors")
        manifest.unlink(); raw_log = log.read_bytes()
        result = self.archive()
        self.assertEqual(result["archived"], [])
        self.assertIsNone(result["archive"])
        self.assertEqual(log.read_bytes(), raw_log)

    def test_any_firmware_memory_license_unknown_sidecar_or_directory_is_preserved(self):
        for suffix in (".bin", "-merged.bin", ".uf2", ".zip", ".hex", ".memory.json",
                       ".font-license.txt", ".unexpected", ".directory", ".bin-link"):
            with self.subTest(suffix=suffix):
                manifest, log = self.attempt()
                sibling = self.work / (manifest.name.removesuffix(".capabilities.json") + suffix)
                if suffix == ".directory": sibling.mkdir()
                elif suffix == ".bin-link": sibling.symlink_to(self.root / "missing.bin")
                else: sibling.write_bytes(b"original evidence or qualified firmware")
                self.assert_preserved(manifest, log)
                if sibling.is_dir(): sibling.rmdir()
                else: sibling.unlink()

    def test_unknown_failures_and_incomplete_or_nonstandard_contracts_are_preserved(self):
        faults = [{"verified": False}, {"ota_update_verified": False},
                  {"platform": "NRF52_PLATFORM"}, {"build_profile": "full"},
                  {"artifact_target": "different"}, {"schema_version": 1},
                  {"schema_version": 2.0},
                  {"verification": []}, {"verification": [{"present": False}]},
                  {"ota_update_evidence": "firmware does not fit both OTA application slots"},
                  {"build_recipe": None}, {"build_recipe": {"schema_version": 1, "sha256": "x" * 64}},
                  {"build_recipe": {"schema_version": True, "sha256": "a" * 64}},
                  {"build_recipe": {"schema_version": 1, "sha256": "a" * 64, "unknown": 1}}]
        for fault in faults:
            with self.subTest(fault=fault):
                manifest, log = self.attempt(); self.mutate(manifest, **fault)
                self.assert_preserved(manifest, log)
        manifest, log = self.attempt(); manifest.write_bytes(b"{malformed")
        self.assert_preserved(manifest, log)

    def test_nested_firmware_is_not_hidden_by_flat_manifest_scan(self):
        manifest, log = self.attempt()
        nested = self.work / "nested"; nested.mkdir()
        (nested / (manifest.name.removesuffix(".capabilities.json") + ".bin")).write_bytes(b"firmware")
        self.assert_preserved(manifest, log)

    def test_numeric_source_identity_and_final_failure_consistency_are_required(self):
        replacements = [("23464 bytes", "23465 bytes"), ("1310720 bytes", "1310721 bytes"),
                        ("1334184 bytes", "1310719 bytes"),
                        ("portable LoRa-OTA slot", "ota_0"),
                        (SOURCE[:8], "deadbeef"), ("(standard)", "(full)"),
                        ("Verified 1 capability", "Failed 1 capability"),
                        ("; the expanded FULL pass is required.", "; unknown failure.")]
        for old, new in replacements:
            with self.subTest(old=old):
                manifest, log = self.attempt()
                log.write_text(log.read_text().replace(old, new), encoding="ascii")
                self.assert_preserved(manifest, log)
        manifest, log = self.attempt()
        with log.open("a") as output: output.write("FAILED: unrelated compiler error\n")
        self.assert_preserved(manifest, log)

    def test_wrong_source_version_or_target_filename_is_not_consumed(self):
        for token, replacement in ((SOURCE[:8], "deadbeef"), (VERSION, VERSION.replace("1.9", "1.8")),
                                   (TARGET, "different_target")):
            with self.subTest(token=token):
                manifest, log = self.attempt()
                renamed = manifest.with_name(manifest.name.replace(token, replacement))
                manifest.rename(renamed)
                self.assert_preserved(renamed, log); renamed.unlink()

    def test_symlink_manifest_log_log_directory_or_work_is_never_consumed(self):
        manifest, log = self.attempt()
        original = self.root / "original.capabilities.json"
        manifest.rename(original); manifest.symlink_to(original)
        self.assert_preserved(manifest, log)
        manifest.unlink(); original.rename(manifest)
        real_log = self.root / "original.log"; log.rename(real_log); log.symlink_to(real_log)
        self.assert_preserved(manifest, log)
        log.unlink(); real_log.rename(log)
        real_logs = self.root / "original-logs"
        log.parent.rename(real_logs); log.parent.symlink_to(real_logs, target_is_directory=True)
        self.assert_preserved(manifest, log)
        alias = self.root / "work-alias"; alias.symlink_to(self.work, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "unsafe work/archive"):
            BUILD.archive_capacity_rejected_attempts(alias, VERSION, SOURCE, project_root=self.root)

    def test_archive_overlap_and_held_build_lock_leave_every_package_byte_untouched(self):
        manifest, log = self.attempt(); raw_manifest, raw_log = manifest.read_bytes(), log.read_bytes()
        for parent in (self.work, self.work / "nested"):
            with self.subTest(parent=parent), self.assertRaisesRegex(ValueError, "unsafe work/archive"):
                self.archive(archive_parent=parent)
        lock_path = self.root / ".pio" / "build-sh.lock"; lock_path.parent.mkdir()
        lock_path.write_bytes(b"original active build lock owner\n")
        with lock_path.open("a+") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaisesRegex(RuntimeError, "active build owns"):
                self.archive()
        self.assertEqual(lock_path.read_bytes(), b"original active build lock owner\n")
        self.assertEqual(manifest.read_bytes(), raw_manifest)
        self.assertEqual(log.read_bytes(), raw_log)
        self.assertEqual(list(self.work.parent.glob(".capacity-rejected-*")), [])

    def test_complete_scan_recheck_blocks_changes_before_any_move(self):
        first, _ = self.attempt(); second, _ = self.attempt("second_repeater")
        original = BUILD.capacity_rejected_attempt; calls = 0
        def racing(*args):
            nonlocal calls
            calls += 1
            record = original(*args)
            if calls == 2: self.mutate(first, verified=False)
            return record
        with mock.patch.object(BUILD, "capacity_rejected_attempt", side_effect=racing):
            with self.assertRaises(ValueError): self.archive()
        self.assertTrue(first.exists()); self.assertTrue(second.exists())
        self.assertEqual(list(self.work.parent.glob(".capacity-rejected-*")), [])

    def test_late_failure_keeps_moved_raw_evidence_and_marks_partial_archive(self):
        first, _ = self.attempt(); second, _ = self.attempt("second_repeater")
        raw_first, raw_second = first.read_bytes(), second.read_bytes()
        original = BUILD.capacity_rejected_attempt; calls = 0
        def racing(*args):
            nonlocal calls
            calls += 1
            if calls == 6: raise ValueError("injected late race")
            return original(*args)
        with mock.patch.object(BUILD, "capacity_rejected_attempt", side_effect=racing):
            with self.assertRaisesRegex(ValueError, "injected late race"): self.archive()
        archive, = self.work.parent.glob(".capacity-rejected-*")
        self.assertFalse(first.exists()); self.assertTrue(second.exists())
        self.assertEqual((archive / "manifests" / first.name).read_bytes(), raw_first)
        self.assertEqual(second.read_bytes(), raw_second)
        index = json.loads((archive / "index.json").read_text())
        self.assertEqual(index["state"], "interrupted")
        self.assertEqual(index["moved_manifests"], [first.name])

    def test_resume_main_archives_before_matrix_and_nonresume_dryrun_do_not_archive(self):
        (self.work / "build-logs").rmdir()
        for arguments, expected in ((["--resume"], True), ([], False), (["--resume", "--dry-run"], False)):
            with self.subTest(arguments=arguments):
                order = []
                def archive(*args):
                    order.append("archive")
                    return {"archived": [], "preserved": [], "archive": None}
                def matrix(*args):
                    order.append("matrix")
                    raise RuntimeError("stop before any external build")
                with mock.patch.object(BUILD, "ROOT", self.root), \
                     mock.patch.object(BUILD, "git", side_effect=[SOURCE, ""]), \
                     mock.patch.object(BUILD, "archive_capacity_rejected_attempts", side_effect=archive), \
                     mock.patch.object(BUILD, "run_logged", side_effect=matrix), \
                     mock.patch.object(BUILD, "resolve_pio_build_dir", return_value=self.root / ".pio/build"), \
                     mock.patch.object(sys, "argv", ["build_local_release.py"] + arguments), \
                     mock.patch("sys.stdout", new=io.StringIO()), \
                     mock.patch("sys.stderr", new=io.StringIO()):
                    if "--dry-run" in arguments: BUILD.main()
                    else:
                        with self.assertRaisesRegex(RuntimeError, "stop before"): BUILD.main()
                self.assertEqual(order, ["archive", "matrix"] if expected else
                                 ([] if "--dry-run" in arguments else ["matrix"]))

    def test_explicit_release_ci_step_runs_capacity_archive_regressions(self):
        workflow = Path(os.environ.get("CAPACITY_ARCHIVE_WORKFLOW", str(
            REPO / ".github/workflows/run-unit-tests.yml"))).read_text(encoding="utf-8")
        command = "python3 -B test/test_local_release_capacity_archive.py"
        self.assertEqual(workflow.count(command), 1)
        # This workflow lists host suites explicitly, rather than discovering
        # test files. Keep the new resume boundary in the existing release step.
        self.assertIn("python3 -B test/test_release_publication.py\n"
                      "          python3 -B test/test_local_release_full_selection.py\n"
                      "          " + command, workflow)


if __name__ == "__main__":
    unittest.main()
