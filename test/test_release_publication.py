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
    def record(self, directory, target, platform="ESP32_PLATFORM", sensor="", *,
               publication_target=None, build_profile="auto"):
        directory.mkdir(parents=True, exist_ok=True)
        stem = (publication_target or target) + "-" + FAMILY
        names = [stem + suffix for suffix in (
            [".uf2", ".zip"] if platform == "NRF52_PLATFORM" else [".bin", "-merged.bin"])]
        names += [stem + ".capabilities.json", stem + ".memory.json"]
        for name in names:
            (directory / name).write_bytes((name + "\n").encode("ascii"))
        row = {"artifact_target": target, "target": target.removesuffix("-" + sensor + "-ota") if sensor else target,
               "platform": platform, "build_profile": build_profile, "verified": True,
               "sensor_profile": sensor, "files": names, "reductions": [],
               "source_commit": SOURCE, "ota_update_methods": ["lora"]}
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

    def test_catalog_accepts_standard_and_full_with_the_same_logical_identity(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            plan = self.stage(directory)
            target = "Station_G2_repeater"
            published = target + "-full-usb-wifi-ota"
            row, _ = self.record(directory / "full-profiles", target,
                                 publication_target=published, build_profile="full")
            folder = directory / "full-profiles"
            (folder / "TARGET-MANIFEST.json").write_text(json.dumps([row]))
            (folder / "SHA256SUMS.txt").write_text("".join(
                hashlib.sha256(p.read_bytes()).hexdigest() + "  " + p.name + "\n"
                for p in sorted(folder.iterdir())))
            plan["groups"].append({"key": "full-profiles", "tag": "full-profiles-" + FAMILY,
                                   "target_count": 1})
            (directory / "release-plan.json").write_text(json.dumps(plan))
            plan, family, records = catalogs.read_stage(directory)
            self.assertEqual([row["artifact_target"] for row, _, _ in records].count(target), 2)
            targets = {row["publication_target"] for row, _, _ in records} | {
                "Station_G2_companion_radio_full", target, "RAK_4631_repeater"}
            result = catalogs.generate(self.template(), plan, family, records,
                                       catalogs.target_profiles(targets), "mikecarper/MeshCore")
            entries = result["device"][0]["firmware"]
            self.assertEqual(len(entries), 3)
            full = next(entry for entry in entries if entry["subTitle"].startswith(published))
            self.assertIn("Full profile", full["subTitle"])
            self.assertTrue(all("/full-profiles-" + FAMILY + "/" in file["url"]
                                for file in full["version"][FAMILY]["files"]))
            # Matching filenames do not authorize a profile for another board
            # or a fabricated Full infix on a standard qualified build.
            for change in ({"artifact_target": "Other_repeater"}, {"build_profile": "auto"},
                           {"source_commit": "b" * 40}):
                (folder / "TARGET-MANIFEST.json").write_text(json.dumps([{**row, **change}]))
                (folder / "SHA256SUMS.txt").write_text("".join(
                    hashlib.sha256(p.read_bytes()).hexdigest() + "  " + p.name + "\n"
                    for p in sorted(folder.iterdir()) if p.name != "SHA256SUMS.txt"))
                with self.subTest(change=change), self.assertRaises(ValueError):
                    catalogs.read_stage(directory)
            # A second source suffix cannot hide inside an otherwise familiar
            # family filename while keeping the original cap/memory stems.
            wrong = {**row, "files": list(row["files"])}
            for index, name in enumerate(wrong["files"]):
                if name.endswith(".bin"):
                    extra = name.replace(FAMILY, FAMILY + "-bbbbbbbb")
                    (folder / name).rename(folder / extra)
                    wrong["files"][index] = extra
            (folder / "TARGET-MANIFEST.json").write_text(json.dumps([wrong]))
            (folder / "SHA256SUMS.txt").write_text("".join(
                hashlib.sha256(p.read_bytes()).hexdigest() + "  " + p.name + "\n"
                for p in sorted(folder.iterdir()) if p.name != "SHA256SUMS.txt"))
            with self.assertRaisesRegex(ValueError, "exact release source/version"):
                catalogs.read_stage(directory)

    def test_local_release_distinguishes_standard_and_full_by_exact_qualified_files(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            target = "Station_G2_companion_radio_usb"
            folder = directory / "firmware/companion"
            standard, standard_files = self.record(folder, target)
            full, full_files = self.record(folder, target,
                publication_target=target + "-full-usb-wifi-ota", build_profile="full")
            records = [{"manifest": row, "files": files} for row, files in
                       ((standard, standard_files), (full, full_files))]
            manifest = {"format": "meshcore-local-release-v1", "source_commit": SOURCE,
                        "firmware_version": VERSION, "profile": "cascade", "publication": "local-only",
                        "radio": {"frequency_mhz": 910.525, "bandwidth_khz": 62.5,
                                  "spreading_factor": 7, "coding_rate": 5},
                        "firmware_target_count": 2, "migration_board_role_count": 1,
                        "firmware": [{"target": row["target"], "artifact_target": row["artifact_target"],
                            "profile": row["build_profile"], "platform": row["platform"],
                            "files": [str(p.relative_to(directory)) for p in files]}
                            for row, files in ((standard, standard_files), (full, full_files))]}
            migrations = directory / "esp32-partition-migration"
            migrations.mkdir()
            archive = migrations / ("example-" + FAMILY + "-migration.zip")
            archive.write_bytes(b"qualified migration fixture")
            bundle = directory / ("esp32-partition-migration-" + FAMILY + "-release.zip")
            with zipfile.ZipFile(bundle, "w") as z:
                z.writestr("release-manifest.json", "{}")
                z.writestr(archive.name, archive.read_bytes())
            def write_inventory():
                (directory / "manifest.json").write_text(json.dumps(manifest))
                (directory / "SHA256SUMS.txt").write_text("".join(
                    hashlib.sha256(p.read_bytes()).hexdigest() + "  " + str(p.relative_to(directory)) + "\n"
                    for p in sorted(directory.rglob("*")) if p.is_file() and p.name != "SHA256SUMS.txt"))
            with patch.object(package, "collect_artifacts", return_value=records), \
                 patch("package_esp32_partition_migration.BOARDS", {"example": {}}), \
                 patch("build_esp32_partition_migration.verify_archive"):
                write_inventory()
                self.assertEqual(len(package.collect_local_release(directory, VERSION, SOURCE)[0]), 2)
                for field, value in (("artifact_target", "Other_companion_radio_usb"),
                                     ("profile", "auto")):
                    original = manifest["firmware"][1][field]
                    manifest["firmware"][1][field] = value
                    write_inventory()
                    with self.subTest(field=field), self.assertRaisesRegex(ValueError, "manifest disagrees"):
                        package.collect_local_release(directory, VERSION, SOURCE)
                    manifest["firmware"][1][field] = original
                manifest["firmware"][1]["files"] = manifest["firmware"][0]["files"]
                write_inventory()
                with self.assertRaisesRegex(ValueError, "inventory disagrees"):
                    package.collect_local_release(directory, VERSION, SOURCE)

    def test_stable_publication_notes_and_assets_are_ascii(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            row, files = self.record(base / "input", "Station_G2_companion_radio_usb")
            row.pop("source_commit")  # Actual older cap manifests inherit validated release provenance.
            output = base / "stage"
            argv = ["package", "--input", str(base / "input"), "--output", str(output),
                    "--local-release", "--stable", "--version", "1.17.1.9", "--commit", SOURCE]
            with patch.object(sys, "argv", argv), patch.object(package, "collect_local_release",
                    return_value=([{"manifest": row, "files": files}], [],
                                  {"frequency": "910.525", "bandwidth": "62.5", "sf": "7", "cr": "5"})):
                package.main()
            plan = json.loads((output / "release-plan.json").read_text())
            self.assertFalse(plan["groups"][0]["prerelease"])
            staged_rows = json.loads((output / "companion/TARGET-MANIFEST.json").read_text())
            self.assertEqual(staged_rows[0]["source_commit"], SOURCE)
            self.assertNotIn("source_commit", row, "raw capability record was relabeled")
            notes = (output / "companion-notes.md").read_text(encoding="ascii")
            self.assertIn("Stable release", notes)
            self.assertNotIn("Development prerelease", notes)
            for path in output.rglob("*"):
                if path.is_file():
                    path.read_text(encoding="ascii")
            bad = {**row, "source_commit": "b" * 40}
            bad_argv = list(argv)
            bad_argv[bad_argv.index(str(output))] = str(base / "wrong-source-stage")
            with patch.object(sys, "argv", bad_argv), patch.object(package, "collect_local_release",
                    return_value=([{"manifest": bad, "files": files}], [],
                                  {"frequency": "910.525", "bandwidth": "62.5", "sf": "7", "cr": "5"})), \
                    self.assertRaisesRegex(ValueError, "another source"):
                package.main()

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
