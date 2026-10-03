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

    def test_main_writes_manifest_and_a_copy_of_the_package(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "firmware.zip").write_bytes(package(image()))
            code = qrm.main(["--zip", str(root / "firmware.zip"), "--env", ENV, "--commit", "abc", "--tag", "quake-v1.17.1.0", "--out", str(root / "dist")])
            self.assertEqual(code, 0)
            written = json.loads((root / "dist" / "manifest.json").read_text())
            self.assertTrue((root / "dist" / written["package"]["file"]).is_file())

    def test_main_fails_without_writing_anything_when_the_package_is_bad(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "firmware.zip").write_bytes(package(image(target=1)))
            code = qrm.main(["--zip", str(root / "firmware.zip"), "--env", ENV, "--commit", "abc", "--out", str(root / "dist")])
            self.assertEqual(code, 1)
            self.assertFalse((root / "dist").exists())


if __name__ == "__main__":
    unittest.main()
