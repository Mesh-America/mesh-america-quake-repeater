#!/usr/bin/env python3
"""Release integration checks for exact asset routing and stable staging."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import generate_mesh_america_release as catalogs
import package_cascade_release as package


SOURCE = "a" * 40
VERSION = "v1.17.1.9-halo-keymind-cascade-dev"
FAMILY = VERSION + "-" + SOURCE[:8]


class ReleasePublicationTest(unittest.TestCase):
    def record(self, directory, target, platform="ESP32_PLATFORM", sensor=""):
        directory.mkdir(parents=True, exist_ok=True)
        stem = target + "-" + FAMILY
        names = [stem + suffix for suffix in (
            [".uf2", ".zip"] if platform == "NRF52_PLATFORM" else [".bin", "-merged.bin"])]
        names += [stem + ".capabilities.json", stem + ".memory.json"]
        for name in names:
            (directory / name).write_bytes((name + "\n").encode("ascii"))
        row = {"artifact_target": target, "target": target.removesuffix("-" + sensor + "-ota") if sensor else target,
               "platform": platform, "build_profile": "auto", "verified": True,
               "sensor_profile": sensor, "files": names, "reductions": []}
        return row, [directory / name for name in names]

    def stage(self, directory):
        definitions = [("companion", "Station_G2_companion_radio_full", "ESP32_PLATFORM", ""),
                       ("repeater-room", "Station_G2_repeater", "ESP32_PLATFORM", ""),
                       ("lora-ota", "RAK_4631_repeater-full-ota", "NRF52_PLATFORM", "full"),
                       ("lora-ota", "RAK_4631_repeater-reduced-ota", "NRF52_PLATFORM", "reduced")]
        groups = {}
        for group, target, platform, sensor in definitions:
            row, files = self.record(directory / group, target, platform, sensor)
            groups.setdefault(group, []).append(row)
        plan = {"source": SOURCE, "version": "1.17.1.9", "groups": []}
        for group, rows in groups.items():
            path = directory / group
            (path / "TARGET-MANIFEST.json").write_text(json.dumps(rows))
            (path / "SHA256SUMS.txt").write_text("".join(
                hashlib.sha256(p.read_bytes()).hexdigest() + "  " + p.name + "\n"
                for p in sorted(path.iterdir())))
            plan["groups"].append({"key": group, "tag": FAMILY if group == "companion" else group + "-" + FAMILY,
                                   "target_count": len(rows)})
        (directory / "release-plan.json").write_text(json.dumps(plan))
        return plan

    def template(self):
        devices = []
        for hardware, platform, targets in (
                ("Station G2", "esp32", ["Station_G2_companion_radio_full", "Station_G2_repeater"]),
                ("RAK4631", "nrf52", ["RAK_4631_repeater"])):
            devices.append({"name": hardware, "type": platform, "maker": "test", "firmware": [
                {"role": "repeater", "version": {"old": {"notes": "stale old URLs",
                    "files": [{"name": target + "-v1.17.1.8-dev-12345678.bin"}]}}}
                for target in targets]})
        return {"maker": {"test": {"name": "Test"}}, "device": devices}

    def test_catalog_routes_each_asset_to_its_manifest_group_and_keeps_sensor_pairs(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            self.stage(directory)
            plan, family, records = catalogs.read_stage(directory)
            template = self.template()
            targets = {row["artifact_target"] for row, _, _ in records} | {
                "Station_G2_companion_radio_full", "Station_G2_repeater", "RAK_4631_repeater"}
            result = catalogs.generate(template, plan, family, records,
                                       catalogs.target_profiles(targets), "mikecarper/MeshCore")
            self.assertEqual([len(d["firmware"]) for d in result["device"]], [2, 2])
            for device in result["device"]:
                for firmware in device["firmware"]:
                    version = firmware["version"][FAMILY]
                    self.assertNotIn("stale", version["notes"])
                    for file in version["files"]:
                        target = catalogs.identity(file["name"])
                        expected = next(tag for row, tag, _ in records if row["artifact_target"] == target)
                        self.assertIn("/download/" + expected + "/", file["url"])
            self.assertEqual(template, self.template(), "input catalog was mutated")

    def test_catalog_rejects_corrupt_assets_and_cross_family_tags(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            plan = self.stage(directory)
            binary = next((directory / "companion").glob("*.bin"))
            original = binary.read_bytes()
            binary.write_bytes(b"corrupt")
            with self.assertRaisesRegex(ValueError, "checksum"):
                catalogs.read_stage(directory)
            binary.write_bytes(original)
            plan["groups"][1]["tag"] = FAMILY
            (directory / "release-plan.json").write_text(json.dumps(plan))
            with self.assertRaisesRegex(ValueError, "different family"):
                catalogs.read_stage(directory)

    def test_catalog_does_not_guess_an_unknown_hardware_card(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            row, files = self.record(directory, "Unknown_repeater")
            targets = {"Unknown_repeater", "Station_G2_companion_radio_full",
                       "Station_G2_repeater", "RAK_4631_repeater"}
            with self.assertRaisesRegex(ValueError, "exact hardware card"):
                catalogs.generate(self.template(), {"version": "1.17.1.9", "source": SOURCE, "groups": []},
                                  FAMILY, [(row, FAMILY, files)], catalogs.target_profiles(targets), "mikecarper/MeshCore")

    def test_catalog_retains_download_only_cards_for_new_sensor_profiles(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            self.stage(directory)
            plan, family, records = catalogs.read_stage(directory)
            template = self.template()
            template["device"][1]["type"] = "noflash"
            targets = {row["artifact_target"] for row, _, _ in records} | {
                "Station_G2_companion_radio_full", "Station_G2_repeater", "RAK_4631_repeater"}
            result = catalogs.generate(template, plan, family, records,
                                       catalogs.target_profiles(targets), "mikecarper/MeshCore")
            device = result["device"][1]
            self.assertEqual(device["type"], "noflash")
            self.assertEqual(len(device["firmware"]), 2)
            for firmware in device["firmware"]:
                version = firmware["version"][FAMILY]
                self.assertIn("Downloads only", version["notes"])
                self.assertTrue(all(file["type"] == "download" for file in version["files"]))
            # Even a merged ESP32 image must not enable a download-only card.
            for name in ("example-merged.bin", "example.bin", "example.zip", "example.uf2"):
                self.assertEqual(catalogs.file_entry(Path(name), "noflash", FAMILY,
                                                    "mikecarper/MeshCore")["type"], "download")
            # Real flasher/chip mismatches still fail instead of being guessed.
            template["device"][1]["type"] = "esp32"
            with self.assertRaisesRegex(ValueError, "exact hardware card|platform differs"):
                catalogs.generate(template, plan, family, records,
                                  catalogs.target_profiles(targets), "mikecarper/MeshCore")

    def test_stable_publication_notes_and_assets_are_ascii(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            row, files = self.record(base / "input", "Station_G2_companion_radio_usb")
            output = base / "stage"
            argv = ["package", "--input", str(base / "input"), "--output", str(output),
                    "--local-release", "--stable", "--version", "1.17.1.9", "--commit", SOURCE]
            with patch.object(sys, "argv", argv), patch.object(package, "collect_local_release",
                    return_value=([{"manifest": row, "files": files}], [],
                                  {"frequency": "910.525", "bandwidth": "62.5", "sf": "7", "cr": "5"})):
                package.main()
            plan = json.loads((output / "release-plan.json").read_text())
            self.assertFalse(plan["groups"][0]["prerelease"])
            notes = (output / "companion-notes.md").read_text(encoding="ascii")
            self.assertIn("Stable release", notes)
            self.assertNotIn("Development prerelease", notes)
            for path in output.rglob("*"):
                if path.is_file():
                    path.read_text(encoding="ascii")

    def test_local_release_preserves_selected_profiles_and_verifies_complete_inventory(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            row, files = self.record(directory / "firmware/companion", "Station_G2_companion_radio_usb")
            manifest = {"format": "meshcore-local-release-v1", "source_commit": SOURCE,
                        "firmware_version": VERSION, "profile": "cascade", "publication": "local-only",
                        "radio": {"frequency_mhz": 910.525, "bandwidth_khz": 62.5,
                                  "spreading_factor": 7, "coding_rate": 5},
                        "firmware_target_count": 1, "migration_board_role_count": 1,
                        "firmware": [{"target": row["target"], "artifact_target": row["artifact_target"],
                                      "profile": "auto", "platform": "ESP32_PLATFORM",
                                      "files": [str(p.relative_to(directory)) for p in files]}]}
            (directory / "manifest.json").write_text(json.dumps(manifest))
            migrations = directory / "esp32-partition-migration"
            migrations.mkdir()
            archive = migrations / ("example-" + FAMILY + "-migration.zip")
            archive.write_bytes(b"qualified migration fixture")
            bundle = directory / ("esp32-partition-migration-" + FAMILY + "-release.zip")
            with zipfile.ZipFile(bundle, "w") as z:
                z.writestr("release-manifest.json", "{}")
                z.writestr(archive.name, archive.read_bytes())
            checksum = directory / "SHA256SUMS.txt"
            checksum.write_text("".join(hashlib.sha256(p.read_bytes()).hexdigest() + "  " +
                                        str(p.relative_to(directory)) + "\n"
                                        for p in sorted(directory.rglob("*")) if p.is_file()))
            with patch.object(package, "collect_artifacts", return_value=[{"manifest": row, "files": files}]), \
                    patch("package_esp32_partition_migration.BOARDS", {"example": {}}), \
                    patch("build_esp32_partition_migration.verify_archive"):
                records, extras, _ = package.collect_local_release(directory, VERSION, SOURCE)
                self.assertEqual(len(records), 1)
                self.assertEqual(extras, [archive, bundle])
                with self.assertRaisesRegex(ValueError, "another source"):
                    package.collect_local_release(directory, VERSION, "b" * 40)
                (directory / "unqualified.bin").write_bytes(b"unexpected")
                with self.assertRaisesRegex(ValueError, "inventory is incomplete"):
                    package.collect_local_release(directory, VERSION, SOURCE)


if __name__ == "__main__":
    unittest.main()
