from copy import deepcopy
from types import SimpleNamespace
import unittest

import build_rak3401_legacy24_bundle as bundle


class Legacy24BundleTests(unittest.TestCase):
    def setUp(self):
        self.source = dict(body_hash="0123456789ABCDEF", size=413792)
        self.target = dict(sha256="ab" * 32, version="1.16.11.0", size=393800)
        self.manifest = SimpleNamespace(
            is_full=False, is_bootloader=False, codec_id=2,
            target_id=bundle.search.EXPECTED_TARGET_ID, hw_id=b"RAK_3401\0\0",
            base_hash=bytes.fromhex(self.source["body_hash"]),
            image_hash=bytes.fromhex(self.target["sha256"]),
            fw_version=bundle.search.motalib.pack_version(self.target["version"]),
            image_size=self.target["size"], block_size=2048,
        )

    def test_exact_application_delta(self):
        bundle.validate_manifest(self.manifest, self.source, self.target, 2048)

    def test_rejects_other_image_types_and_every_identity_mismatch(self):
        for field, value in (
            ("is_full", True), ("is_bootloader", True), ("codec_id", 3),
            ("target_id", 0), ("hw_id", b"RAK_4631"),
            ("base_hash", b"\0" * 8), ("image_hash", b"\0" * 32),
            ("fw_version", 1), ("image_size", 1), ("block_size", 4096),
        ):
            with self.subTest(field=field):
                manifest = deepcopy(self.manifest)
                setattr(manifest, field, value)
                with self.assertRaises(ValueError):
                    bundle.validate_manifest(manifest, self.source, self.target, 2048)

    def test_exact_zero_margin_is_valid(self):
        self.assertEqual(bundle.validate_workspace(self.source, self.target, 0x72000, 245426, 0), 0)

    def test_workspace_constraints(self):
        for memory, size, margin in (
            (0x73000, 245426, -4096),  # Overlaps the stored package.
            (0x72001, 245426, 0),     # Not page aligned.
            (0x72000, 245426, 4096),  # Different from the searched geometry.
            (0x64000, 245426, 57344), # Insufficient source plus two-page headroom.
        ):
            with self.subTest(memory=memory, size=size, margin=margin):
                with self.assertRaises(ValueError):
                    bundle.validate_workspace(self.source, self.target, memory, size, margin)


if __name__ == "__main__":
    unittest.main()
