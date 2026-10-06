#!/usr/bin/env python3
"""Tests for scripts/quake_release_manifest.py (run by the Quake Repeater release workflow)."""

import hashlib
import io
import json
import struct
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import quake_release_manifest as qrm  # noqa: E402

ENV = "MeshAmerica_Quake_Repeater_RAK3401"
VERSION = (1 << 24) | (17 << 16) | (1 << 8) | 0  # 1.17.1.0
HARDWARE_ID = "MeshAmerica_Quake"


def image(body=b"firmware-body" * 50, version=VERSION, target=None, hw_id=HARDWARE_ID, body_len=None, hash_ok=True):
    target = qrm.target_id_for_env(ENV) if target is None else target
    body_hash = hashlib.sha256(body).digest()[:8] if hash_ok else b"\0" * 8
    trailer = b"EndF" + struct.pack("<I", len(body) if body_len is None else body_len) + body_hash
    trailer += struct.pack("<II", version, target) + hw_id.encode().ljust(32, b"\0")
    assert len(trailer) == qrm.ENDF_LENGTH
    return body + trailer


def intel_hex(data, start=0x26000):
    """Intel HEX for `data` placed at `start`, 16 bytes a record, as the nRF52 build writes it."""
    def record(kind, address, payload):
        body = bytes([len(payload), address >> 8, address & 0xFF, kind]) + payload
        return ":" + (body + bytes([(-sum(body)) & 0xFF])).hex().upper()

    lines, upper = [], None
    for offset in range(0, len(data), 16):
        address = start + offset
        if address >> 16 != upper:
            upper = address >> 16
            lines.append(record(4, 0, upper.to_bytes(2, "big")))
        lines.append(record(0, address & 0xFFFF, data[offset:offset + 16]))
    lines.append(record(1, 0, b""))
    return "\n".join(lines) + "\n"


def package(app_image, manifest=None, extra=None):
    manifest = manifest or {"manifest": {"application": {"bin_file": "firmware.bin", "dat_file": "firmware.dat"}}}
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        archive.writestr("firmware.bin", app_image)
        archive.writestr("firmware.dat", b"\0" * 14)
        for name, data in (extra or {}).items():
            archive.writestr(name, data)
    return buffer.getvalue()


class ManifestTest(unittest.TestCase):
    def build(self, data, tag=None):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "firmware.zip"
            path.write_bytes(data)
            return qrm.build_manifest(path, ENV, "abc123", tag, "2026-10-03T00:00:00Z"), path.stat().st_size

    def test_target_id_is_first_four_bytes_little_endian_of_sha256(self):
        self.assertEqual(qrm.target_id_for_env(ENV), 0x7763803B)  # the value in variants/meshamerica_quake/platformio.ini

    def test_produces_the_facts_the_catalog_needs(self):
        data = package(image())
        manifest, size = self.build(data, tag="quake-v1.17.1.0")
        self.assertEqual(manifest["version"], "1.17.1.0")
        self.assertEqual(manifest["targetId"], "0x7763803b")
        self.assertEqual(manifest["hardwareId"], HARDWARE_ID)
        self.assertEqual(manifest["package"]["size"], size)
        self.assertEqual(manifest["package"]["sha256"], hashlib.sha256(data).hexdigest())
        self.assertEqual(manifest["package"]["file"], f"{ENV}-1.17.1.0.zip")
        self.assertEqual(manifest["commit"], "abc123")

    def test_accepts_a_build_without_a_tag(self):
        manifest, _ = self.build(package(image()))
        self.assertIsNone(manifest["tag"])

    def test_rejects_a_tag_that_does_not_name_the_version_in_the_image(self):
        with self.assertRaisesRegex(qrm.ManifestError, "expected quake-v1.17.1.0"):
            self.build(package(image()), tag="quake-v9.9.9.9")

    def test_rejects_an_image_built_for_another_environment(self):
        with self.assertRaisesRegex(qrm.ManifestError, "target id"):
            self.build(package(image(target=0x12345678)))

    def test_rejects_missing_or_damaged_identity(self):
        cases = {
            "no identity block": b"x" * 200,
            "wrong length": image(body_len=5),
            "wrong hash": image(hash_ok=False),
            "empty hardware id": image(hw_id=""),
            "no version": image(version=0),
        }
        for name, data in cases.items():
            with self.subTest(name), self.assertRaises(qrm.ManifestError):
                self.build(package(data))

    def test_rejects_packages_that_would_touch_the_bootloader_or_softdevice(self):
        for forbidden in ("bootloader", "softdevice", "softdevice_bootloader"):
            manifest = {"manifest": {"application": {"bin_file": "firmware.bin", "dat_file": "firmware.dat"}, forbidden: {"bin_file": "x.bin"}}}
            with self.subTest(forbidden), self.assertRaisesRegex(qrm.ManifestError, forbidden):
                self.build(package(image(), manifest=manifest, extra={"x.bin": b"1"}))

    def test_rejects_malformed_packages(self):
        with self.assertRaisesRegex(qrm.ManifestError, "valid zip"):
            self.build(b"not a zip")
        for manifest in (None, [], {"manifest": None}, {"manifest": {}}, {"manifest": {"application": {}}}):
            with self.subTest(manifest), self.assertRaises(qrm.ManifestError):
                self.build(package(image(), manifest=manifest or {"manifest": manifest}))

    def test_publishes_the_hex_only_when_it_is_the_same_image_as_the_package(self):
        app = image()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "firmware.zip").write_bytes(package(app))
            (root / "firmware.hex").write_text(intel_hex(app))
            manifest = qrm.build_manifest(root / "firmware.zip", ENV, "abc", None, "2026-10-03T00:00:00Z", root / "firmware.hex")
            self.assertEqual(manifest["hex"]["file"], f"{ENV}-1.17.1.0.hex")
            self.assertEqual(manifest["hex"]["sha256"], hashlib.sha256((root / "firmware.hex").read_bytes()).hexdigest())
            (root / "other.hex").write_text(intel_hex(image(body=b"different" * 60)))
            with self.assertRaises(qrm.ManifestError):
                qrm.build_manifest(root / "firmware.zip", ENV, "abc", None, "2026-10-03T00:00:00Z", root / "other.hex")

    def test_rejects_a_damaged_hex_file(self):
        app = image()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "firmware.zip").write_bytes(package(app))
            text = intel_hex(app).replace(":10", ":11", 1)  # breaks a record's length and checksum
            (root / "bad.hex").write_text(text)
            with self.assertRaises(qrm.ManifestError):
                qrm.build_manifest(root / "firmware.zip", ENV, "abc", None, "2026-10-03T00:00:00Z", root / "bad.hex")
            (root / "empty.hex").write_text(":00000001FF\n")
            with self.assertRaises(qrm.ManifestError):
                qrm.build_manifest(root / "firmware.zip", ENV, "abc", None, "2026-10-03T00:00:00Z", root / "empty.hex")

    def test_main_writes_the_hex_beside_the_package(self):
        app = image()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "firmware.zip").write_bytes(package(app))
            (root / "firmware.hex").write_text(intel_hex(app))
            code = qrm.main(["--zip", str(root / "firmware.zip"), "--hex", str(root / "firmware.hex"), "--env", ENV,
                             "--commit", "abc", "--out", str(root / "dist")])
            self.assertEqual(code, 0)
            written = json.loads((root / "dist" / "manifest.json").read_text())
            self.assertEqual((root / "dist" / written["hex"]["file"]).read_text(), (root / "firmware.hex").read_text())

    def test_main_writes_manifest_and_a_copy_of_the_package(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "firmware.zip").write_bytes(package(image()))
            code = qrm.main(["--zip", str(root / "firmware.zip"), "--env", ENV, "--commit", "abc", "--tag", "quake-v1.17.1.0", "--out", str(root / "dist")])
            self.assertEqual(code, 0)
            written = json.loads((root / "dist" / "manifest.json").read_text())
            self.assertTrue((root / "dist" / written["package"]["file"]).is_file())

    def test_main_can_name_the_manifest_for_a_second_image(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "firmware.zip").write_bytes(package(image()))
            name = "manifest-" + ENV + ".json"
            code = qrm.main(["--zip", str(root / "firmware.zip"), "--env", ENV, "--commit", "abc", "--out", str(root / "dist"), "--manifest-name", name])
            self.assertEqual(code, 0)
            self.assertTrue((root / "dist" / name).is_file())
            self.assertFalse((root / "dist" / "manifest.json").exists())

    def test_main_refuses_a_manifest_name_with_a_path(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "firmware.zip").write_bytes(package(image()))
            with self.assertRaises(SystemExit):
                qrm.main(["--zip", str(root / "firmware.zip"), "--env", ENV, "--commit", "abc", "--out", str(root / "dist"), "--manifest-name", "../x.json"])

    def test_main_fails_without_writing_anything_when_the_package_is_bad(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "firmware.zip").write_bytes(package(image(target=1)))
            code = qrm.main(["--zip", str(root / "firmware.zip"), "--env", ENV, "--commit", "abc", "--out", str(root / "dist")])
            self.assertEqual(code, 1)
            self.assertFalse((root / "dist").exists())


if __name__ == "__main__":
    unittest.main()
