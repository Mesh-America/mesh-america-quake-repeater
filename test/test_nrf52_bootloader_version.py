"""Compile the real version reader; optionally verify the pinned 2.4.6 release."""
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]


class BootloaderVersionTest(unittest.TestCase):
    def test_firmware_uses_shared_reader(self):
        board = (ROOT / "src/helpers/NRF52Board.cpp").read_text()
        getter = board.split("bool NRF52Board::getBootloaderVersion(", 1)[1].split("\n}", 1)[0]
        self.assertIn("mesh::nrf52BootloaderRegion(", getter)
        self.assertIn("NRF_FICR->CODEPAGESIZE, NRF_FICR->CODESIZE", getter)
        self.assertIn("mbr_start, NRF_UICR->NRFFW[0]", getter)
        self.assertIn("mesh::nrf52BootloaderVersion(", getter)
        self.assertIn("bootloaderVersion, out, max_len", getter)
        self.assertNotIn("0x000FB000", getter)
        common = (ROOT / "src/helpers/CommonCLI.cpp").read_text()
        cli = common.split('configKeyEquals(config, "bootloader.ver")', 1)[1].split("} else {", 1)[0]
        self.assertIn("char ver[128]", cli)
        self.assertIn("_board->getBootloaderVersion(ver, sizeof(ver))", cli)

    def test_native_version_reader(self):
        compiler = shutil.which(os.environ.get("CXX", "g++"))
        self.assertIsNotNone(compiler, "g++ (or CXX) is required for this native test")
        with tempfile.TemporaryDirectory(prefix="meshcore-boot-version-") as temp:
            exe = Path(temp) / ("test.exe" if os.name == "nt" else "test")
            command = [compiler, "-std=c++17", "-O2", "-Wall", "-Wextra", "-Werror", "-Wno-unused-parameter",
                       "-I" + str(ROOT / "src"), "-isystem", str(ROOT / "test/mocks"),
                       str(ROOT / "test/fixtures/nrf52_bootloader_version/test_version.cpp"),
                       "-o", str(exe)]
            built = subprocess.run(command, capture_output=True, text=True, timeout=60)
            self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
            result = subprocess.run([str(exe)], capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("native cases passed", result.stdout)
            # Optional local/release artifacts; never downloaded or flashed by
            # this test. Each must be a raw bootloader image starting at F4000.
            for path in os.environ.get("MESHCORE_BOOTLOADER_IMAGES", "").split(os.pathsep):
                if path:
                    with self.subTest(image=path):
                        result = subprocess.run([str(exe), path], check=True, capture_output=True,
                                                text=True, timeout=20)
                        self.assertRegex(result.stdout, r"\d+\.\d+\.\d+")
            release = os.environ.get("MESHCORE_BOOTLOADER_MOTA_ZIP")
            if release:
                self.assertEqual(hashlib.sha256(Path(release).read_bytes()).hexdigest(),
                                 "04fe6d1b11b0c3b926289d6384dae5cb878462da"
                                 "a7fbbe9afb70f42d869f8003", "unexpected 2.4.6 release archive")
                sys.path.insert(0, str(ROOT / "tools/mota"))
                import motalib
                with zipfile.ZipFile(release) as archive:
                    names = [name for name in archive.namelist() if name.endswith(".mota")]
                    self.assertEqual(len(names), 17)
                    sd_name = "mota/update-heltec_mesh_tower_v2_sdcard_bootloader-0.11.0-OTAFIX2.4.6.mota"
                    self.assertIn(sd_name, names)
                    for name in names:
                        with self.subTest(release_image=name):
                            parsed = motalib.parse_container(archive.read(name))
                            self.assertEqual(motalib.verify(parsed), [])
                            if name == sd_name:
                                self.assertNotIn(b"UF2 Bootloader ", parsed.payload)
                                identity = motalib.parse_bootloader_identity(parsed.payload)
                                self.assertEqual(identity.crc32, 0x5DACDB3D)
                                self.assertEqual(identity.boot_version, 0x020406FF)
                            result = subprocess.run([str(exe), "--hex"], input=parsed.payload.hex(),
                                                    capture_output=True, text=True, timeout=20)
                            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                            self.assertIn("OTAFIX2.4.6", result.stdout)
                            if name == sd_name:
                                self.assertEqual(result.stdout.strip(), "OTAFIX2.4.6")
                    print(f"Verified version reader against {len(names)} signed OTAFIX 2.4.6 release images")


if __name__ == "__main__":
    unittest.main()
