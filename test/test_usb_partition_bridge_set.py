"""Hermetic, no-hardware checks for the independent six-profile USB set."""

import contextlib
import io
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import build_esp32_partition_migration as recipe
import package_usb_partition_bridges as package
from package_esp32_partition_migration import (
    USB_BRIDGE_MARKER, USB_NVS_GUARD_MARKER, USB_BRIDGE_PROFILES,
)


class UsbPartitionBridgeSetTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="usb-bridge-set-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.build = self.root / "custom build tree"
        self.output = self.root / "release" / "meshcore-usb-partition-bridges.zip"
        self.provenance = {"source_commit": "0123456789abcdef" * 2 + "01234567",
                           "working_tree_dirty": True, "source_tree_sha256": "a" * 64}
        self.images = {}
        for (chip, mib), environment in USB_BRIDGE_PROFILES.items():
            header = bytearray(24)
            header[0:3] = b"\xe9\x01\x02"
            header[3] = {4: 2, 8: 3, 16: 4}[mib] << 4
            struct.pack_into("<H", header, 12, chip)
            image = bytes(header) + USB_BRIDGE_MARKER + b"\0" + USB_NVS_GUARD_MARKER
            path = self.build / environment / "firmware.bin"
            path.parent.mkdir(parents=True)
            path.write_bytes(image)
            self.images[environment] = image

    def test_complete_set_records_exact_profiles_source_and_capabilities(self):
        path = package.package_set(self.build, self.output, self.provenance)
        manifest = package.verify_set(path)
        self.assertEqual(package.FORMAT, manifest["format"])
        self.assertTrue(manifest["working_tree_dirty"])
        self.assertEqual(self.provenance["source_commit"], manifest["source_commit"])
        self.assertEqual(self.provenance["source_tree_sha256"], manifest["source_tree_sha256"])
        self.assertEqual(set(USB_BRIDGE_PROFILES),
                         {(row["chip"], row["flash_bytes"] // 1048576)
                          for row in manifest["bridges"]})
        with zipfile.ZipFile(path) as archive:
            self.assertEqual(9, len(archive.namelist()))
            for row in manifest["bridges"]:
                self.assertEqual(self.images[row["environment"]], archive.read(row["file"]))
                self.assertEqual(row["chip"] != 0, row["automatic_rom_return"])
                self.assertEqual(row["chip"] == 0, row["uart_completion_status"])
                self.assertTrue(row["host_software_bootloader_entry"])
                self.assertFalse(row["application_usb_cdc"])
            self.assertIn(b"No physical BOOT", archive.read("README.md"))
            self.assertNotIn("full-application.bin", archive.namelist())

    def test_every_profile_is_mandatory_before_output_publication(self):
        for environment, image in self.images.items():
            with self.subTest(environment=environment):
                path = self.build / environment / "firmware.bin"
                path.unlink()
                with self.assertRaises(FileNotFoundError):
                    package.package_set(self.build, self.output, self.provenance)
                self.assertFalse(self.output.parent.exists())
                path.write_bytes(image)

    def test_wrong_chip_capacity_mode_and_either_missing_marker_refuse(self):
        environment = USB_BRIDGE_PROFILES[9, 16]
        path = self.build / environment / "firmware.bin"
        image = self.images[environment]
        chip = bytearray(image); struct.pack_into("<H", chip, 12, 0)
        capacity = bytearray(image); capacity[3] = 0x20
        mode = bytearray(image); mode[2] = 0
        for broken in (bytes(chip), bytes(capacity), bytes(mode),
                       image.replace(USB_BRIDGE_MARKER, b"wifi-only"),
                       image.replace(USB_NVS_GUARD_MARKER, b"unsafe-startup"),
                       image + b"\0" * 0x140000):
            with self.subTest(length=len(broken)):
                path.write_bytes(broken)
                with self.assertRaises(ValueError):
                    package.package_set(self.build, self.output, self.provenance)
                self.assertFalse(self.output.parent.exists())

    def test_atomic_reproducible_reuse_does_not_overwrite_different_set(self):
        package.package_set(self.build, self.output, self.provenance)
        original = self.output.read_bytes()
        package.package_set(self.build, self.output, self.provenance)
        self.assertEqual(original, self.output.read_bytes())
        changed = {**self.provenance, "source_tree_sha256": "b" * 64}
        with self.assertRaisesRegex(ValueError, "existing USB bridge set differs"):
            package.package_set(self.build, self.output, changed)
        self.assertEqual(original, self.output.read_bytes())
        self.assertEqual([self.output], list(self.output.parent.iterdir()))

    def test_verifier_rejects_corruption_and_extra_inventory(self):
        package.package_set(self.build, self.output, self.provenance)
        with zipfile.ZipFile(self.output) as archive:
            files = {name: archive.read(name) for name in archive.namelist()}
        for extra, corrupt in ((True, False), (False, True)):
            damaged = self.root / f"damaged-{extra}.zip"
            changed = files.copy()
            if extra:
                changed["surprise.bin"] = b"unchecked"
            if corrupt:
                name = next(name for name in files if name.endswith(".bin"))
                changed[name] += b"corrupted"
            with zipfile.ZipFile(damaged, "w") as archive:
                for name, data in changed.items():
                    archive.writestr(name, data)
            with self.assertRaises(ValueError):
                package.verify_set(damaged)

    def test_provenance_pins_runtime_guard_and_lineending_normalized_source(self):
        source_root = self.root / "source"
        for name in package.SOURCE_FILES:
            path = source_root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes((name + "\r\n").encode())
        with mock.patch.object(subprocess, "check_output", side_effect=[
                self.provenance["source_commit"], " M examples/runtime.cpp"]):
            first = package.source_provenance(source_root)
        self.assertTrue(first["working_tree_dirty"])
        self.assertIn("scripts/esp32_partition_migration_nvs_guard.py", first["source_files"])
        self.assertIn("src/helpers/ESP32PartitionMigrationUsbRecovery.h", first["source_files"])
        for name in package.SOURCE_FILES:
            (source_root / name).write_bytes((name + "\n").encode())
        with mock.patch.object(subprocess, "check_output", side_effect=[
                self.provenance["source_commit"], ""]):
            second = package.source_provenance(source_root)
        self.assertFalse(second["working_tree_dirty"])
        self.assertEqual(first["source_tree_sha256"], second["source_tree_sha256"])
        (source_root / package.SOURCE_FILES[0]).write_bytes(b"changed runtime\n")
        with mock.patch.object(subprocess, "check_output", side_effect=[
                self.provenance["source_commit"], " M runtime"]):
            third = package.source_provenance(source_root)
        self.assertNotEqual(second["source_tree_sha256"], third["source_tree_sha256"])

    def test_usb_only_recipe_dry_run_needs_no_version_or_full_build(self):
        result = subprocess.run([
            sys.executable, "-B", str(ROOT / "scripts/build_esp32_partition_migration.py"),
            "--usb-only", "--dry-run", "--output-root", str(self.output.parent),
        ], cwd=ROOT, text=True, capture_output=True, check=True)
        self.assertEqual(6, result.stdout.count("pio run -e "))
        self.assertNotIn("build-firmware", result.stdout)
        self.assertNotIn("Full", result.stdout)
        self.assertFalse(self.output.parent.exists())
        self.assertEqual(set(USB_BRIDGE_PROFILES.values()),
                         {command[3] for command in recipe.usb_build_steps(3)})

    def test_usb_only_recipe_runs_six_serial_builds_then_independent_packager(self):
        calls = []
        with mock.patch.object(recipe, "git_output", return_value="01234567") as git, \
                mock.patch.object(recipe.shutil, "which", return_value="/mock/pio"), \
                mock.patch.object(recipe, "resolve_pio_build_dir", return_value=self.build), \
                mock.patch.object(recipe.subprocess, "run", side_effect=lambda command, **kwargs:
                                  calls.append((command, kwargs))), \
                contextlib.redirect_stdout(io.StringIO()):
            args = recipe.argparse.Namespace(board=None, role=None, output_root=self.output.parent,
                                             jobs=2, dry_run=False)
            recipe.build_usb_only(args, recipe.argparse.ArgumentParser())
        self.assertEqual(7, len(calls))
        self.assertTrue(all(command[:2] == ["pio", "run"] for command, _ in calls[:6]))
        self.assertIn("scripts/package_usb_partition_bridges.py", calls[-1][0])
        self.assertTrue(all(kwargs["env"]["PLATFORMIO_BUILD_DIR"] == str(self.build)
                            for _, kwargs in calls))
        self.assertEqual([mock.call("rev-parse", "--short=8", "HEAD")], git.call_args_list)

    def test_guard_middleware_is_early_and_exclusive_to_six_usb_environments(self):
        config = (ROOT / "variants/esp32_partition_migrator/platformio.ini").read_text()
        for environment in USB_BRIDGE_PROFILES.values():
            section = config.split(f"[env:{environment}]", 1)[1].split("\n[env:", 1)[0]
            self.assertIn("pre:scripts/esp32_partition_migration_nvs_guard.py", section)
            self.assertNotIn("post:scripts/esp32_partition_migration_nvs_guard.py", section)
            self.assertIn("-D MESHCORE_MIGRATION_USB=1", section)
            self.assertIn("${env:esp32_s3_4mb_partition_migrator.extra_scripts}", section)
        self.assertEqual(6, config.count("pre:scripts/esp32_partition_migration_nvs_guard.py"))


if __name__ == "__main__":
    unittest.main()
