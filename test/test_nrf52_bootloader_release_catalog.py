#!/usr/bin/env python3
"""Standalone release assets remain exact-board, complete and independently auditable."""

from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import struct
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from intelhex import IntelHex
import package_nrf52_bootloaders as package


def digest(data):
    return hashlib.sha256(data).hexdigest()


def uf2(candidate, *, omitted=()):
    """A bootloader UF2, including independent MBR and UICR records."""
    writes = [(0, b"M" * 256)]
    writes += [(package.embedded.BOOT_BASE + offset, candidate[offset:offset + 256])
               for offset in range(0, len(candidate), 256) if offset not in omitted]
    writes += [(0x10001000, b"U" * 256)]
    blocks = []
    for index, (address, payload) in enumerate(writes):
        blocks.append(struct.pack("<8I", 0x0A324655, 0x9E5D5157, 0x2000, address,
            256, index, len(writes), package.BOOTLOADER_UF2_FAMILY)
            + payload + b"\0" * 220 + struct.pack("<I", 0x0AB16F30))
    return b"".join(blocks)


class StandaloneBootloaderCatalogTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.project = self.root / "project"
        (self.project / "docs/_data").mkdir(parents=True)
        self.destination, self.cache = self.root / "stage", self.root / "cache"
        self.payloads, self.candidates = {}, {}
        profiles = []
        for name, value, aliases in (("zeta", 0xA5, ["board_z"]),
                                     ("alpha", 0x5A, ["board_a", "board_a_qspi"])):
            candidate = bytes([value]) * (package.embedded.BOOT_SIZE - 512) + b"\xff" * 512
            self.candidates[name] = candidate
            image = IntelHex()
            image.frombytes(candidate, offset=package.embedded.BOOT_BASE)
            text = io.StringIO()
            image.write_hex_file(text)
            contents = {"hex": text.getvalue().encode("ascii"), "uf2": uf2(candidate),
                        "zip": ("qualified exact-profile ZIP: " + name).encode("ascii")}
            profile = dict(id=name, label=name + " exact board", storage="qspi", deviceName=name,
                           meshcoreHardware=aliases, files={})
            for kind, payload in contents.items():
                prefix = name + "_bootloader-" + package.embedded.TAG
                filename = ("update-" + prefix + "_mbr.uf2" if kind == "uf2" else
                            prefix + "_s140_7.3.0." + kind)
                url = ("https://github.com/" + package.embedded.REPOSITORY + "/releases/download/"
                       + package.embedded.TAG + "/" + filename)
                profile["files"][kind] = dict(name=filename, size=len(payload), sha256=digest(payload), url=url)
                self.payloads[url] = payload
            profiles.append(profile)
        self.manifest = dict(schemaVersion=1, repository=package.embedded.REPOSITORY,
            tag=package.embedded.TAG, version=package.embedded.VERSION, prerelease=False,
            releaseUrl="https://github.com/" + package.embedded.REPOSITORY + "/releases/tag/" + package.embedded.TAG,
            profiles=profiles, coverage=dict(releasedProfiles=2, releasedHardware=3),
            unavailableProfiles=[dict(id="pending_board", reason="No normal release.")],
            recoveryProfiles=[dict(id="recovery_only", files={"zip": {"url": "never-download"}})])
        self.pin = mock.patch.object(package.embedded, "MANIFEST_SHA256", "")
        self.pin.start()
        self.addCleanup(self.pin.stop)
        self.write_manifest()
        self.requests = []
        self.download = mock.Mock(side_effect=self.urlopen)
        for module in (package, package.embedded):
            patcher = mock.patch.object(module, "urlopen", self.download)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = mock.patch.object(package.embedded, "validate_candidate_zip", side_effect=self.validate_zip)
        self.validate = patcher.start()
        self.addCleanup(patcher.stop)

    def write_manifest(self):
        raw = (json.dumps(self.manifest, sort_keys=True) + "\n").encode("ascii")
        (self.project / "docs/_data/bootloader_manifest.json").write_bytes(raw)
        package.embedded.MANIFEST_SHA256 = digest(raw)

    def urlopen(self, url, *, timeout):
        self.assertEqual(timeout, 60)
        self.requests.append(url)
        return io.BytesIO(self.payloads[url])

    def validate_zip(self, data, profile, project_root):
        # The production ZIP identity/layout parser has its own real-format suite.
        # Stub only that boundary while running the real download and HEX/UF2 checks.
        self.assertEqual(project_root, self.project)
        self.assertEqual(data, self.payloads[profile["files"]["zip"]["url"]])
        return self.candidates[profile["id"]], SimpleNamespace(device_name=profile["deviceName"],
            board_id=123, app_base=0x27000, softdevice_fwid=0x100)

    def stage(self, destination=None):
        return package.stage_bootloader_catalog(destination or self.destination,
            project_root=self.project, cache_dir=self.cache)

    def files(self, directory):
        return {path.name: path.read_bytes() for path in directory.iterdir()}

    def replace_payload(self, profile, kind, payload):
        asset = profile["files"][kind]
        self.payloads[asset["url"]] = payload
        asset.update(size=len(payload), sha256=digest(payload))
        self.write_manifest()

    def test_complete_catalog_is_deterministic_cached_and_offline_verifiable(self):
        receipt = self.stage()
        self.assertEqual(receipt["profile_count"], 2)
        self.assertEqual(receipt["hardware_count"], 3)
        self.assertEqual([p["id"] for p in receipt["profiles"]], ["alpha", "zeta"])
        self.assertEqual(receipt["excluded_profiles"], ["pending_board"])
        self.assertEqual(len(receipt["assets"]), 6)
        self.assertEqual(set(self.requests), set(self.payloads))
        self.assertEqual(len(self.requests), 6)
        for asset in receipt["assets"]:
            data = (self.destination / asset["path"]).read_bytes()
            self.assertEqual(len(data), asset["size"])
            self.assertEqual(digest(data), asset["sha256"])
            self.assertEqual(asset["name"], asset["path"])
        before = self.files(self.destination)
        self.assertNotIn("recovery_only", " ".join(before))
        with mock.patch.object(package, "urlopen", side_effect=AssertionError("network forbidden")), \
                mock.patch.object(package.embedded, "urlopen", side_effect=AssertionError("network forbidden")), \
                mock.patch.object(package.embedded, "download_zip", side_effect=AssertionError("download forbidden")):
            self.assertEqual(package.validate_bootloader_catalog(self.destination, project_root=self.project), receipt)
        second = self.root / "second"
        self.assertEqual(self.stage(second), receipt)
        self.assertEqual(self.files(second), before)
        self.assertEqual(len(self.requests), 6)  # Every second download came from verified cache.
        self.assertNotIn(str(self.root), json.dumps(receipt))
        self.assertEqual(sorted(self.cache.iterdir()), sorted(path for path in self.cache.iterdir()
            if any(path.name == asset["sha256"] + "-" + asset["name"] for asset in receipt["assets"])))

    def test_corrupt_cache_is_refetched_and_only_verified_bytes_are_published(self):
        self.stage()
        profile = self.manifest["profiles"][0]
        asset = profile["files"]["hex"]
        cache = self.cache / (asset["sha256"] + "-" + asset["name"])
        cache.write_bytes(b"x" * asset["size"])
        self.stage(self.root / "second")
        self.assertEqual(self.requests.count(asset["url"]), 2)
        self.assertEqual(cache.read_bytes(), self.payloads[asset["url"]])

    def test_invalid_catalog_metadata_fails_before_any_asset_download(self):
        original = deepcopy(self.manifest)
        for fault in ("traversal", "wrong_url", "zero_size", "bool_size", "bad_hash", "missing_format",
                      "duplicate_profile", "duplicate_hardware", "coverage", "unavailable_overlap"):
            self.manifest = deepcopy(original)
            profile = self.manifest["profiles"][0]
            asset = profile["files"]["hex"]
            if fault == "traversal":
                asset["name"] = "../boot.hex"
            elif fault == "wrong_url":
                asset["url"] = "https://example.invalid/" + asset["name"]
            elif fault == "zero_size":
                asset["size"] = 0
            elif fault == "bool_size":
                asset["size"] = True
            elif fault == "bad_hash":
                asset["sha256"] = "A" * 64
            elif fault == "missing_format":
                profile["files"].pop("uf2")
            elif fault == "duplicate_profile":
                self.manifest["profiles"].append(deepcopy(profile))
            elif fault == "duplicate_hardware":
                self.manifest["profiles"][1]["meshcoreHardware"].append("board_z")
            elif fault == "coverage":
                self.manifest["coverage"]["releasedHardware"] = 4
            else:
                self.manifest["unavailableProfiles"][0]["id"] = profile["id"]
            self.write_manifest()
            with self.subTest(fault=fault), self.assertRaises(ValueError):
                self.stage()
            self.assertEqual(self.requests, [])
            self.assertFalse(self.destination.exists())

    def test_changed_source_manifest_pin_fails_before_asset_download(self):
        path = self.project / "docs/_data/bootloader_manifest.json"
        path.write_bytes(path.read_bytes() + b" ")
        with self.assertRaisesRegex(ValueError, "pinned OTAFIX"):
            self.stage()
        self.assertEqual(self.requests, [])
        self.assertFalse(self.destination.exists())

    def test_late_bad_download_keeps_output_absent_and_cache_free_of_partial_files(self):
        profile = self.manifest["profiles"][0]  # zeta sorts last, after a complete first profile.
        asset = profile["files"]["uf2"]
        self.payloads[asset["url"]] += b"unexpected trailing byte"
        with self.assertRaisesRegex(ValueError, "size/SHA-256 mismatch"):
            self.stage()
        self.assertGreater(len(self.requests), 3)
        self.assertFalse(self.destination.exists())
        self.assertFalse((self.cache / (asset["sha256"] + "-" + asset["name"])).exists())
        self.assertFalse(list(self.cache.glob("otafix-*")))
        self.assertFalse(list(self.root.glob(".stage-*")))

    def test_paired_formats_must_reproduce_the_zip_candidate_even_when_asset_hashes_match(self):
        original = deepcopy(self.manifest)
        original_payloads = self.payloads.copy()
        for kind in ("hex", "uf2"):
            self.manifest = deepcopy(original)
            self.payloads = original_payloads.copy()
            profile = self.manifest["profiles"][0]
            other_profile = self.manifest["profiles"][1]
            other = self.payloads[other_profile["files"][kind]["url"]]
            self.replace_payload(profile, kind, other)
            with self.subTest(kind=kind), self.assertRaisesRegex(ValueError, "exact.*profile bootloader"):
                self.stage()
            self.assertFalse(self.destination.exists())

    def test_sparse_uf2_erased_tail_is_allowed_but_missing_live_bytes_are_rejected(self):
        profile = self.manifest["profiles"][0]
        candidate = self.candidates[profile["id"]]
        erased = (len(candidate) - 512, len(candidate) - 256)
        self.replace_payload(profile, "uf2", uf2(candidate, omitted=erased))
        self.stage()
        self.replace_payload(profile, "uf2", uf2(candidate, omitted=(0,)))
        with self.assertRaisesRegex(ValueError, "exact.*profile bootloader"):
            self.stage(self.root / "bad")
        self.assertFalse((self.root / "bad").exists())

    def test_uf2_rejects_application_family_unsafe_writes_overlap_and_bad_block_metadata(self):
        original = deepcopy(self.manifest)
        profile = original["profiles"][0]
        data = self.payloads[profile["files"]["uf2"]["url"]]
        for fault in ("application_family", "unsafe_address", "overlap", "block_index", "block_count", "magic"):
            self.manifest = deepcopy(original)
            damaged = bytearray(data)
            if fault == "application_family":
                struct.pack_into("<I", damaged, 28, 0xADA52840)
            elif fault == "unsafe_address":
                struct.pack_into("<I", damaged, 12, 0x27000)
            elif fault == "overlap":
                struct.pack_into("<I", damaged, 512 + 12, 0)
            elif fault == "block_index":
                struct.pack_into("<I", damaged, 20, 1)
            elif fault == "block_count":
                struct.pack_into("<I", damaged, 24, 1)
            else:
                struct.pack_into("<I", damaged, 508, 0)
            self.replace_payload(self.manifest["profiles"][0], "uf2", bytes(damaged))
            with self.subTest(fault=fault), self.assertRaisesRegex(ValueError, "UF2 geometry"):
                self.stage()
            self.assertFalse(self.destination.exists())

    def test_offline_validator_rejects_missing_extra_mutated_and_symlinked_contents(self):
        self.stage()
        original = self.files(self.destination)
        asset_name = self.manifest["profiles"][0]["files"]["hex"]["name"]
        for fault in ("missing", "extra", "hash", "inventory", "checksums", "readme", "manifest", "symlink"):
            directory = self.root / ("tampered-" + fault)
            directory.mkdir()
            for name, data in original.items():
                (directory / name).write_bytes(data)
            if fault == "missing":
                (directory / asset_name).unlink()
            elif fault == "extra":
                (directory / "unqualified.hex").write_bytes(b"extra")
            elif fault == "symlink":
                (directory / asset_name).unlink()
                (directory / asset_name).symlink_to(self.destination / asset_name)
            else:
                path = directory / {"hash": asset_name, "inventory": package.INVENTORY_NAME,
                    "checksums": package.CHECKSUMS_NAME, "readme": package.README_NAME,
                    "manifest": package.MANIFEST_NAME}[fault]
                data = path.read_bytes()
                path.write_bytes(bytes([data[0] ^ 1]) + data[1:])
            with self.subTest(fault=fault), self.assertRaises(ValueError):
                package.validate_bootloader_catalog(directory, project_root=self.project)
        self.assertEqual(len(self.requests), 6)

    def test_nonempty_destination_and_symlink_cache_are_refused_without_mutation(self):
        self.destination.mkdir()
        marker = self.destination / "keep"
        marker.write_bytes(b"original")
        with self.assertRaisesRegex(ValueError, "empty directory"):
            self.stage()
        self.assertEqual(marker.read_bytes(), b"original")
        marker.unlink()
        target = self.root / "cache-target"
        target.mkdir()
        self.cache.symlink_to(target, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "cache must not be a symlink"):
            self.stage()
        self.assertEqual(list(self.destination.iterdir()), [])
        self.assertEqual(self.requests, [])


if __name__ == "__main__":
    unittest.main()
