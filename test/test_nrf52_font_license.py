"""Font notices travel with licensed firmware without changing DFU payloads."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import struct
import sys
import tempfile
import unittest
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import package_nrf52_font_license as font_license
import firmware_memory_manifest as memory
import package_cascade_release as release
import nrf52_flash_trim as trim


class BuildEnvironment(dict):
    def __init__(self, **changes):
        super().__init__(MESH_NRF52_FLASH_TRIM_ACTIVE=True,
                         PIOENV="Heltec_t114_repeater", BUILD_FLAGS=[],
                         CPPDEFINES=["NRF52_PLATFORM", "ST7789", ("MESH_NRF52_FLASH_TRIM", 1)])
        self.update(changes)
        self.actions = []
        self.dependencies = []

    def Depends(self, target, sources):
        self.dependencies.append((target, sources))

    def AddPostAction(self, target, action):
        self.actions.append((target, action))

    def subst(self, value):
        return (value.replace("$PROJECT_DIR", str(ROOT))
                .replace("$BUILD_DIR", str(self.get("BUILD_DIR", "build")))
                .replace("${PROGNAME}", "firmware"))

    def PioPlatform(self):
        class Platform:
            name = "nordicnrf52"

            def get_package_dir(self, _name):
                return None
        return Platform()

    def BoardConfig(self):
        return {"build.mcu": "nrf52840"}

    def AppendUnique(self, **changes):
        for name, values in changes.items():
            for value in values:
                if value not in self.setdefault(name, []):
                    self[name].append(value)


class Nrf52FontLicenseTest(unittest.TestCase):
    def dfu(self, path):
        manifest = {"manifest": {"application": {"bin_file": "firmware.bin",
                                                "dat_file": "firmware.dat"}}}
        with ZipFile(path, "w") as archive:
            for name, data in (("manifest.json", json.dumps(manifest).encode()),
                               ("firmware.bin", bytes(range(256)) * 8),
                               ("firmware.dat", b"original-init-packet")):
                info = ZipInfo(name, (2026, 1, 2, 3, 4, 6))
                info.compress_type = ZIP_DEFLATED
                archive.writestr(info, data)
        return manifest

    def test_notice_matches_generated_source_copyright_license_and_provenance(self):
        notice = font_license.notice_bytes().decode()
        generated = (ROOT / "src/helpers/ui/CompactNotoFonts.h").read_text(encoding="utf-8")
        copyright = "Copyright 2015 Google Inc. All Rights Reserved."
        end = "OTHER DEALINGS IN THE FONT SOFTWARE."
        source_license = generated.split(copyright, 1)[1].split(end, 1)[0]
        packaged_license = notice.split(copyright, 1)[1].split(end, 1)[0]
        self.assertEqual(source_license, packaged_license)
        for item in (copyright, "MeshFontProduction9", "OFL-1.1",
                     "4efc2789b9fcaa87b6b55f19c25ac9a2919e4f9ca31d6b5b97bea7977d729d4f",
                     "2.000;GOOG;noto-source:20170915:90ef993387c0"):
            self.assertIn(item, notice)
            self.assertIn(item, generated)
        self.assertNotIn(b"\r", font_license.notice_bytes())

    def test_only_effective_production_mode_installs_for_qualified_infrastructure(self):
        for role in ("repeater", "room_server", "sensor", "kiss"):
            self.assertTrue(font_license.qualifies(BuildEnvironment(PIOENV="custom_" + role)))
        self.assertTrue(font_license.qualifies(BuildEnvironment(BUILD_FLAGS="-DMESH_NRF52_FONT_MODE=9")))
        self.assertTrue(font_license.qualifies(BuildEnvironment(
            BUILD_FLAGS="-DMESH_NRF52_FONT_MODE=0 -DMESH_ARIAL_EXPERIMENT=9")))
        exclusions = (
            dict(MESH_NRF52_FLASH_TRIM_ACTIVE=False),
            dict(PIOENV="Heltec_t114_companion_radio_ble"),
            dict(BUILD_FLAGS='-DOTA_VARIANT=\'"custom_companion_radio_full"\''),
            dict(BUILD_FLAGS="-DCOMPANION_FEATURE_USB_MOTA_SOURCE=1"),
            dict(BUILD_FLAGS="-DCOMPANION_RADIO_FULL=0"),
            dict(BUILD_FLAGS="-UMESH_NRF52_FLASH_TRIM"),
            dict(BUILD_FLAGS="-DMESH_NRF52_FLASH_TRIM=0"),
            dict(BUILD_FLAGS="-UST7789"), dict(BUILD_FLAGS="-UNRF52_PLATFORM"),
            dict(BUILD_FLAGS="-DMESH_NRF52_FONT_MODE=0"),
            dict(BUILD_FLAGS="-DMESH_NRF52_FONT_MODE=9 -DMESH_ARIAL_EXPERIMENT=7"),
            dict(BUILD_FLAGS="-DMESH_ARIAL_EXPERIMENT=unknown"),
            dict(CPPDEFINES=["NRF52_PLATFORM", ("MESH_NRF52_FLASH_TRIM", 1)]),
        )
        for changes in exclusions:
            with self.subTest(changes=changes):
                env = BuildEnvironment(**changes)
                before = dict(env)
                self.assertFalse(font_license.install(env))
                self.assertEqual(env, before)
                self.assertEqual(env.actions, [])
                self.assertEqual(env.dependencies, [])

    def test_install_dependencies_and_cached_build_callback(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            self.dfu(directory / "firmware.zip")
            env = BuildEnvironment(BUILD_DIR=directory)
            self.assertTrue(font_license.install(env))
            self.assertFalse(font_license.install(env))
            self.assertEqual([target for target, _action in env.actions],
                             ["$BUILD_DIR/${PROGNAME}.zip", "buildprog"])
            self.assertIn(str(font_license.NOTICE_PATH), env.dependencies[0][1])
            self.assertIn(str(ROOT / "scripts/package_nrf52_font_license.py"), env.dependencies[0][1])
            env.actions[1][1]([], [], env)
            self.assertEqual((directory / "firmware.font-license.txt").read_bytes(), font_license.notice_bytes())
            before = (directory / "firmware.zip").read_bytes()
            (directory / "firmware.font-license.txt").unlink()
            env.actions[1][1]([], [], env)
            self.assertEqual((directory / "firmware.zip").read_bytes(), before)
            self.assertTrue((directory / "firmware.font-license.txt").is_file())

    def test_trim_install_integrates_notice_for_display_infrastructure_only(self):
        for role in ("simple_repeater", "simple_room_server", "simple_sensor", "kiss_modem"):
            env = BuildEnvironment(MESH_NRF52_FLASH_TRIM_ACTIVE=False,
                                   CPPDEFINES=["NRF52_PLATFORM", "ST7789"],
                                   SRC_FILTER=["+<../examples/" + role + ">"])
            trim.install(env)
            self.assertTrue(env["MESH_NRF52_FONT_LICENSE_INSTALLED"])
            self.assertEqual(len(env.actions), 2)
        for changes in (
                dict(CPPDEFINES=["NRF52_PLATFORM"]),
                dict(PIOENV="Heltec_t114_companion_radio_usb"),
                dict(SRC_FILTER=["+<../examples/companion_radio>"]),
                dict(BUILD_FLAGS="-DMESH_NRF52_FONT_MODE=0")):
            env = BuildEnvironment(MESH_NRF52_FLASH_TRIM_ACTIVE=False,
                                   SRC_FILTER=["+<../examples/simple_repeater>"])
            env.update(changes)
            trim.install(env)
            self.assertNotIn("MESH_NRF52_FONT_LICENSE_INSTALLED", env)
            self.assertEqual(env.actions, [])

    def test_zip_original_entries_manifest_and_physical_payload_bytes_are_unchanged(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            package = directory / "firmware.zip"
            self.dfu(package)
            with ZipFile(package) as archive:
                entries = {info.filename: (archive.read(info), vars(info).copy()
                           if hasattr(info, "__dict__") else
                           (info.CRC, info.compress_size, info.file_size, info.date_time, info.header_offset,
                            info.compress_type, info.external_attr)) for info in archive.infolist()}
                original_payload_prefix = package.read_bytes()[:archive.start_dir]
            sidecar = font_license.package_font_license(package)
            self.assertEqual(package.read_bytes()[:len(original_payload_prefix)], original_payload_prefix)
            with ZipFile(package) as archive:
                self.assertEqual(set(archive.namelist()), set(entries) | {"FONT-LICENSE.txt"})
                for name, (data, attributes) in entries.items():
                    info = archive.getinfo(name)
                    actual = vars(info).copy() if hasattr(info, "__dict__") else (
                        info.CRC, info.compress_size, info.file_size, info.date_time, info.header_offset,
                        info.compress_type, info.external_attr)
                    self.assertEqual(archive.read(name), data)
                    self.assertEqual(actual, attributes)
                self.assertIsNone(archive.testzip())
                self.assertEqual(archive.read("FONT-LICENSE.txt"), sidecar.read_bytes())
                self.assertEqual(archive.getinfo("FONT-LICENSE.txt").date_time, (1980, 1, 1, 0, 0, 0))

    def test_deterministic_and_idempotent_without_rewriting_cached_files(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            first, second = directory / "one.zip", directory / "two.zip"
            self.dfu(first)
            shutil.copyfile(first, second)
            sidecar = font_license.package_font_license(first)
            font_license.package_font_license(second)
            self.assertEqual(first.read_bytes(), second.read_bytes())
            before = (first.read_bytes(), first.stat().st_mtime_ns, sidecar.stat().st_mtime_ns)
            font_license.package_font_license(first)
            self.assertEqual((first.read_bytes(), first.stat().st_mtime_ns, sidecar.stat().st_mtime_ns), before)

    def test_refuses_foreign_entries_and_sidecars_before_mutating_zip(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            package = directory / "firmware.zip"
            self.dfu(package)
            sidecar = directory / "firmware.font-license.txt"
            sidecar.write_bytes(b"user's unrelated text")
            before = package.read_bytes()
            with self.assertRaisesRegex(ValueError, "refusing to overwrite"):
                font_license.package_font_license(package)
            self.assertEqual(package.read_bytes(), before)
            self.assertEqual(sidecar.read_bytes(), b"user's unrelated text")
            sidecar.unlink()
            with ZipFile(package, "a") as archive:
                archive.writestr("FONT-LICENSE.txt", b"another license")
            before = package.read_bytes()
            with self.assertRaisesRegex(ValueError, "unexpected or duplicate"):
                font_license.package_font_license(package)
            self.assertEqual(package.read_bytes(), before)
            self.assertFalse(sidecar.exists())

    def test_collection_ignores_stale_source_notice_and_rejects_stale_output(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            build = directory / "build"
            output = directory / "out"
            build.mkdir()
            output.mkdir()
            self.dfu(build / "firmware.zip")
            source_sidecar = build / "firmware.font-license.txt"
            source_sidecar.write_bytes(font_license.notice_bytes())
            stem = output / "unaffected"
            self.assertIsNone(font_license.collect_build_notice(build, stem))
            self.assertTrue(source_sidecar.exists())
            stale = output / "unaffected.font-license.txt"
            stale.write_bytes(font_license.notice_bytes())
            with self.assertRaisesRegex(ValueError, "stale output"):
                font_license.collect_build_notice(build, stem)
            self.assertEqual(stale.read_bytes(), font_license.notice_bytes())

    def test_notice_is_staged_hashed_and_tampering_or_removal_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            build, output = directory / "build", directory / "out"
            build.mkdir()
            output.mkdir()
            self.dfu(build / "firmware.zip")
            font_license.package_font_license(build / "firmware.zip")
            label = "v1.17.1.5-halo-keymind-cascade-dev"
            version = label + "-deadbeef"
            stem = output / ("Heltec_t114_repeater-" + version)
            shutil.copyfile(build / "firmware.zip", output / (stem.name + ".zip"))
            uf2_data = (struct.pack("<8I", 0x0A324655, 0x9E5D5157, 0x2000, 0x26000,
                                    256, 0, 1, 0xADA52840)
                        + b"u" * 256 + b"\0" * 220 + struct.pack("<I", 0x0AB16F30))
            (output / (stem.name + ".uf2")).write_bytes(uf2_data)
            notice = font_license.collect_build_notice(build, stem)
            manifest = dict(schema_version=2, target="Heltec_t114_repeater",
                            artifact_target="Heltec_t114_repeater", platform="NRF52_PLATFORM",
                            verified=True, ota_update_verified=True, verification=[], build_profile="standard")
            (output / (stem.name + ".capabilities.json")).write_text(json.dumps(manifest))
            elf = build / "firmware.elf"
            elf.write_bytes(b"qualified-ELF")
            report = dict(schema_version=1, passed=True, available_internal_bytes=80000,
                          required_heap_bytes=50000, largest_internal_region_bytes=80000,
                          required_contiguous_bytes=5120,
                          elf_sha256=hashlib.sha256(elf.read_bytes()).hexdigest(), target="build_env")
            (build / "firmware.memory.json").write_text(json.dumps(report))
            memory.package_report(build, stem)
            proof = memory.validate_package(stem)
            self.assertEqual(proof["files"][notice.name], hashlib.sha256(notice.read_bytes()).hexdigest())
            records = release.collect_artifacts(output, version)
            self.assertIn(notice, records[0]["files"])
            self.assertEqual(sum(path == notice for path in records[0]["files"]), 1)
            self.assertEqual((output / (stem.name + ".uf2")).read_bytes(), uf2_data)
            commit = "deadbeef" + "0" * 32
            status = directory / "status"
            status.write_text("state=completed\nexit_code=0\n"
                              f"working_directory={directory}\noutput_directory=out\n"
                              f"source_commit={commit}\nfirmware_version={label}\nfirmware_profile=cascade\n"
                              "radio_frequency=909.5\nradio_bandwidth=500\nradio_sf=5\nradio_cr=5\n")
            result = subprocess.run([sys.executable, str(ROOT / "scripts/package_cascade_release.py"),
                                     "--input", str(output), "--output", str(directory / "stage"),
                                     "--build-status", str(status), "--commit", commit],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            staged = directory / "stage/repeater-room"
            self.assertEqual((staged / notice.name).read_bytes(), notice.read_bytes())
            self.assertIn(notice.name, (staged / "TARGET-MANIFEST.json").read_text())
            checksums = dict(line.split("  ", 1)[::-1] for line in
                             (staged / "SHA256SUMS.txt").read_text().splitlines())
            self.assertEqual(checksums[notice.name], hashlib.sha256(notice.read_bytes()).hexdigest())
            notice.write_bytes(b"tampered")
            with self.assertRaisesRegex(ValueError, "mismatched font-license"):
                memory.validate_package(stem)
            notice.unlink()
            with self.assertRaisesRegex(ValueError, "missing or mismatched"):
                memory.validate_package(stem)

    def test_adafruit_loader_accepts_extra_notice_when_installed(self):
        site_packages = (Path.home() / ".platformio/packages/tool-adafruit-nrfutil/site-packages")
        if not (site_packages / "nordicsemi/dfu/package.py").is_file():
            self.skipTest("local Adafruit nRF DFU utility is not installed")
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            package = directory / "firmware.zip"
            self.dfu(package)
            font_license.package_font_license(package)
            code = (
                "import sys; from pathlib import Path; "
                "sys.path.insert(0,sys.argv[1]); "
                "from nordicsemi.dfu.package import Package; "
                "m=Package.unpack_package(sys.argv[2],sys.argv[3]); "
                "assert m.application.bin_file=='firmware.bin'; "
                "assert m.application.dat_file=='firmware.dat'; "
                "assert (Path(sys.argv[3])/'FONT-LICENSE.txt').is_file()"
            )
            result = subprocess.run([sys.executable, "-c", code, str(site_packages), str(package),
                                     str(directory / "unpacked")], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
