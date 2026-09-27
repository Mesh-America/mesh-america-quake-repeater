"""Host-only regression tests for the release partition LUT generator."""
import hashlib
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import precompute_esp32_partitions as catalog


def entry(kind, subtype, start, size, label):
    return struct.pack("<HBBII16sI", 0x50AA, kind, subtype,
                       start, size, label.encode(), 0)


def image(entries, offset=0x8000, checksum=True):
    table = b"".join(entries)
    if checksum:
        table += b"\xeb\xeb" + b"\xff" * 14 + hashlib.md5(table).digest()
    table = table.ljust(4096, b"\xff")
    return b"\xff" * offset + table


class PartitionCatalogTest(unittest.TestCase):
    def setUp(self):
        self.entries = [
            entry(1, 2, 0x9000, 0x5000, "nvs"),
            entry(1, 0, 0xE000, 0x2000, "otadata"),
            entry(0, 0x10, 0x10000, 0x140000, "app0"),
            entry(0, 0x11, 0x150000, 0x140000, "app1"),
            entry(1, 0x82, 0x290000, 0x170000, "spiffs"),
        ]

    def test_dual_slot_at_both_merged_offsets(self):
        for offset in (0x8000, 0x7000):
            result = catalog.parse_table(image(self.entries, offset))
            self.assertTrue(result["dualOta"])
            self.assertEqual(result["slotBytes"], 0x140000)

    def test_legacy_table_without_checksum(self):
        self.assertTrue(catalog.parse_table(
            image(self.entries, checksum=False))["dualOta"])

    def test_reject_corrupt_checksum_overlap_and_missing_table(self):
        broken = bytearray(image(self.entries))
        broken[0x8000 + 12] ^= 1
        for data in (broken, image(self.entries + [self.entries[0]]), b"no table"):
            with self.assertRaises(ValueError):
                catalog.parse_table(data)

    def test_single_app_is_not_migratable_via_ota(self):
        result = catalog.parse_table(image([
            entry(0, 0, 0x10000, 0x300000, "app0")]))
        self.assertFalse(result["dualOta"])
        self.assertIsNone(result["slotBytes"])

    def test_missing_otadata_is_not_dual_ota(self):
        result = catalog.parse_table(image(self.entries[2:]))
        self.assertFalse(result["dualOta"])

    def test_minimum_of_unequal_slots(self):
        self.entries[3] = entry(0, 0x11, 0x150000, 0x130000, "app1")
        self.assertEqual(catalog.parse_table(image(self.entries))["slotBytes"],
                         0x130000)

    def test_exact_filename_versions_and_profiles(self):
        cases = {
            "heltec_v4_repeater-v1.17.1-d929643-merged.bin":
                ("heltec_v4", "repeater", "v1.17.1"),
            "Heltec_v3_repeater-PowerSaving17.1.3-freshInstall-merged.bin":
                ("Heltec_v3", "repeater", "PowerSaving17.1.3"),
            "Heltec_v3_repeater-PowerSaving13.1-cleanInstall.bin":
                ("Heltec_v3", "repeater", "PowerSaving13.1"),
            "repeater-heltec-wsl3-powersaving09-merged.bin":
                ("heltec-wsl3", "repeater", "powersaving09"),
            "Generic_ESPNOW_repeatr-full-logging-ota-v1.17.1.6-halo-keymind-cascade-dev-306feebe-merged.bin":
                ("Generic_ESPNOW", "repeater_full_logging_ota",
                 "v1.17.1.6-halo-keymind-cascade-dev"),
            "Heltec_E290_companion_usb-ota-v1.17.1.1-abcdef12-merged.bin":
                ("Heltec_E290", "companion_radio_usb_ota", "v1.17.1.1"),
        }
        for name, expected in cases.items():
            self.assertTrue(catalog.is_merged_asset(name))
            self.assertEqual(catalog.asset_identity(name), expected)

    def test_range_is_bounded_even_if_server_ignores_it(self):
        class Response:
            status = 200
            url = "https://release-assets.githubusercontent.com/asset"
            headers = {}
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self, count):
                self.count = count
                return b"x" * count
        response = Response()
        with patch.object(catalog.urllib.request, "urlopen", return_value=response):
            self.assertEqual(len(catalog.read_prefix("https://github.com/a/b")),
                             catalog.PREFIX_BYTES)
        self.assertEqual(response.count, catalog.PREFIX_BYTES)

    def test_wrong_range_is_rejected(self):
        class Response:
            status = 206
            url = "https://github.com/a/b"
            headers = {"Content-Range": "bytes 4096-8192/99999"}
            def __enter__(self): return self
            def __exit__(self, *args): pass
        with patch.object(catalog.urllib.request, "urlopen", return_value=Response()):
            with self.assertRaises(ValueError):
                catalog.read_prefix("https://github.com/a/b")

    def test_release_inventory_excludes_drafts_and_retains_prereleases(self):
        class Result:
            returncode = 0
            stdout = '\n'.join(json.dumps(item) for item in [
                {"draft": True}, {"draft": False, "prerelease": True},
                {"draft": False, "prerelease": False}])
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(catalog.subprocess, "run", return_value=Result()) as run:
                items = catalog.releases("owner/repo", Path(directory))
                self.assertEqual(len(items), 2)
                self.assertIn("--paginate", run.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
