"""Qualify and carry GUI/font notices without changing firmware or DFU ZIPs."""
import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import package_pocket_gui_license as notice
import firmware_memory_manifest as memory
import firmware_build_recipe as recipe
import package_cascade_release as release

GUI = "_ZN4mesh2ui6pocket9PocketGui6headerEPKcS5_"
FONT = "u8g2_font_helvR08_tf"


def elf32(path, symbols=(GUI, FONT), flags=6, section_type=1, undefined=(), zero=()):
    names, table = bytearray(b"\0"), bytearray(16)
    data = b"CODE" * max(1, len(symbols))
    for i, name in enumerate(symbols):
        offset = len(names)
        names += name.encode() + b"\0"
        table += struct.pack("<IIIBBH", offset, 0x40000000 + i * 4,
                             0 if name in zero else 4, 0x12, 0, 0 if name in undefined else 1)
    payload = 52 + 4 * 40
    strings = payload + len(data)
    symtab = strings + len(names)
    header = b"\x7fELF\x01\x01\x01" + bytes(9)
    header += struct.pack("<HH5I6H", 2, 40, 1, 0, 0, 52, 0, 52, 0, 0, 40, 4, 0)
    sections = bytes(40)
    sections += struct.pack("<10I", 0, section_type, flags, 0x40000000, payload, len(data), 0, 0, 4, 0)
    sections += struct.pack("<10I", 0, 3, 0, 0, strings, len(names), 0, 0, 1, 0)
    sections += struct.pack("<10I", 0, 2, 0, 0, symtab, len(table), 2, 1, 4, 16)
    path.write_bytes(header + sections + data + names + table)


class PocketGuiLicenseTest(unittest.TestCase):
    def qualify(self, directory, stem, target="test_companion_radio_usb"):
        output = stem.parent / (stem.name + ".capabilities.json")
        result = subprocess.run([sys.executable, str(ROOT / "scripts/check_firmware_capabilities.py"),
            "--image", str(directory / "firmware.elf"), "--output", str(output),
            "--target", target, "--platform", "ESP32_PLATFORM", "--build-profile", "standard"],
            capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(output.read_text())

    @unittest.skipUnless(sys.platform.startswith("linux"), "requires a Linux ELF compiler")
    def test_compiler_produced_gui_and_font_symbols_qualify(self):
        compiler = shutil.which("g++")
        if compiler is None:
            self.skipTest("host g++ required")
        source = """
namespace mesh { namespace ui { namespace pocket {
class PocketGui { public: void header(const char*, const char*); };
void PocketGui::header(const char*, const char*) { asm volatile(\"\"); }
}}}
extern const unsigned char u8g2_font_helvR08_tf[] = {1, 2, 3, 4};
extern \"C\" void _start() {}
"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_path = root / "linked.cpp"
            input_path.write_text(source)
            result = subprocess.run([compiler, "-m32", "-O0", "-fno-pie", "-no-pie",
                "-fno-exceptions", "-fno-rtti", "-fno-stack-protector", "-nostdlib",
                "-Wl,-e,_start", "-Wl,--build-id=none", str(input_path),
                "-o", str(root / "firmware.elf")], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            evidence = notice.pocket_gui_evidence(root / "firmware.elf")
            self.assertEqual(len(evidence), 2)
            self.assertIn(FONT, evidence)
            self.qualify(root, root / "compiled")
            self.assertEqual(notice.collect_build_notice(root, root / "compiled").read_bytes(),
                             notice.notice_bytes())

    def test_notice_requires_allocated_gui_or_font_definitions(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "firmware.elf"
            elf32(path)
            self.assertEqual(notice.pocket_gui_evidence(path), sorted((GUI, FONT)))
            # A partially linked font still needs its font license.
            elf32(path, symbols=(FONT,), flags=2)
            self.assertEqual(notice.pocket_gui_evidence(path), [FONT])
            for kwargs in ({"flags": 0}, {"flags": 4}, {"section_type": 8},
                           {"symbols": (GUI,), "flags": 2},
                           {"symbols": (FONT, "other"), "undefined": (FONT,)},
                           {"symbols": (GUI, "other"), "zero": (GUI,)}):
                with self.subTest(kwargs=kwargs):
                    elf32(path, **kwargs)
                    self.assertEqual(notice.pocket_gui_evidence(path), [])
            path.write_bytes((GUI + " " + FONT).encode())
            self.assertEqual(notice.pocket_gui_evidence(path), [])

    def test_target_name_alone_never_creates_notice_and_stale_notice_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stem = root / "plain"
            elf32(root / "firmware.elf", symbols=("unrelated",))
            manifest = self.qualify(root, stem, "Mesh_pocket_companion_radio_full")
            self.assertNotIn("third_party_notices", manifest)
            self.assertIsNone(notice.collect_build_notice(root, stem))
            notice.sidecar(stem).write_bytes(notice.notice_bytes())
            with self.assertRaisesRegex(ValueError, "stale"):
                notice.collect_build_notice(root, stem)
            self.assertTrue(recipe.package_occupied(stem))

    def test_notice_is_hashed_with_memory_proof_and_staged_for_release(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            build, output = root / "build", root / "out"
            build.mkdir(); output.mkdir()
            elf32(build / "firmware.elf")
            version = "v1.18.0.1-test-deadbeef"
            stem = output / ("test_companion_radio_usb-" + version)
            manifest = self.qualify(build, stem)
            data = notice.notice_bytes()
            self.assertEqual(manifest["third_party_notices"], [notice.notice_record(stem, data)])
            # No artifact bytes are rewritten to carry notices.
            app = output / (stem.name + ".bin")
            merged = output / (stem.name + "-merged.bin")
            app.write_bytes(b"unchanged app"); merged.write_bytes(b"unchanged merged")
            sidecar = notice.collect_build_notice(build, stem)
            self.assertEqual(sidecar.read_bytes(), data)
            self.assertEqual(notice.collect_build_notice(build, stem), sidecar)
            report = dict(schema_version=1, passed=True, available_internal_bytes=80000,
                          required_heap_bytes=50000, largest_internal_region_bytes=80000,
                          required_contiguous_bytes=5120, target="build_env",
                          elf_sha256=hashlib.sha256((build / "firmware.elf").read_bytes()).hexdigest())
            (build / "firmware.memory.json").write_text(json.dumps(report))
            memory.package_report(build, stem)
            proof = memory.validate_package(stem)
            self.assertEqual(proof["files"][sidecar.name], hashlib.sha256(data).hexdigest())
            records = release.collect_artifacts(output, version)
            self.assertEqual(sum(path == sidecar for path in records[0]["files"]), 1)
            self.assertEqual(app.read_bytes(), b"unchanged app")
            self.assertEqual(merged.read_bytes(), b"unchanged merged")
            sidecar.write_bytes(b"truncated")
            with self.assertRaisesRegex(ValueError, "mismatched"):
                memory.validate_package(stem)
            sidecar.unlink()
            with self.assertRaisesRegex(ValueError, "missing"):
                memory.validate_package(stem)
            with self.assertRaisesRegex(ValueError, "missing"):
                release.collect_artifacts(output, version)

    def test_metadata_cannot_omit_or_replace_linked_notice(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stem = root / "gui"
            elf32(root / "firmware.elf")
            manifest = self.qualify(root, stem)
            manifest_path = root / "gui.capabilities.json"
            manifest["third_party_notices"] = []
            manifest_path.write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, "linked ELF"):
                notice.collect_build_notice(root, stem)
            manifest["third_party_notices"] = [notice.notice_record(stem, b"wrong")]
            manifest_path.write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, "source notice"):
                notice.collect_build_notice(root, stem)
            self.assertFalse(notice.valid_notice(b"MIT License"))


if __name__ == "__main__":
    unittest.main()
