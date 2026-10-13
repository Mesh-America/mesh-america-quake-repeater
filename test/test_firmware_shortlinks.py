"""Keep short firmware URLs pinned, binary, bounded and safe to mirror."""

import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from urllib.request import Request


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/firmware_shortlinks.py"
SPEC = importlib.util.spec_from_file_location("firmware_shortlinks", SCRIPT)
SHORTLINKS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SHORTLINKS)

UF2 = struct.pack("<II", 0x0A324655, 0x9E5D5157) + bytes(504)
ZIP = b"PK\x03\x04" + b"application DFU fixture" * 7
TAG = "rak4631-full-companion-v1.17.1.10-preview2"


def registry(data=UF2, extension="uf2"):
    return {"schemaVersion": 1, "repository": "mikecarper/MeshCore", "links": [{
        "filename": "rak4631-1.17.1.10-p2." + extension,
        "version": "1.17.1.10", "releaseTag": TAG,
        "asset": "RAK_4631_companion_radio_full-v1.17.1.10-halo-keymind-cascade-preview2-015a3e8e." + extension,
        "sha256": hashlib.sha256(data).hexdigest(), "size": len(data),
        "label": "RAK4631 Full Companion preview2"}]}


class Response(io.BytesIO):
    def __init__(self, data, content_type="application/octet-stream", url=None):
        super().__init__(data)
        self.headers = {"Content-Type": content_type}
        self.url = url or "https://release-assets.githubusercontent.com/example"

    def read(self, size=-1):
        return super().read(min(size, 17) if size >= 0 else 17)

    def geturl(self):
        return self.url


class FirmwareShortlinkTests(unittest.TestCase):
    def load(self, manifest):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "registry.json"
            path.write_text(json.dumps(manifest), encoding="ascii")
            return SHORTLINKS.load_manifest(path)

    def test_real_preview_url_is_derived_from_fixed_repository(self):
        manifest = self.load(registry())
        self.assertEqual(SHORTLINKS.download_url(manifest, manifest["links"][0]),
            "https://github.com/mikecarper/MeshCore/releases/download/" + TAG + "/"
            "RAK_4631_companion_radio_full-v1.17.1.10-halo-keymind-cascade-preview2-015a3e8e.uf2")
        foreign = dict(manifest["links"][0], asset="other-v1.17.1.10.uf2")
        with self.assertRaisesRegex(ValueError, "not in"):
            SHORTLINKS.download_url(manifest, foreign)

    def test_registry_rejects_paths_mutable_names_wrong_sources_and_bad_types(self):
        changes = [
            ("filename", "../rak4631-1.17.1.10.uf2"),
            ("filename", "directory/rak4631-1.17.1.10.uf2"),
            ("filename", "https://example.com/1.17.1.10.uf2"),
            ("filename", "rak4631-latest-1.17.1.10.uf2"),
            ("filename", "rak4631-1.17.1.100-p2.uf2"),
            ("filename", "rak4631-1.17.1.10-p2.html"),
            ("asset", "other-v1.17.1.10.zip"),
            ("asset", "https://example.com/v1.17.1.10.uf2"),
            ("asset", "firmware-v1.17.1.10.uf2?download=1"),
            ("releaseTag", "latest-v1.17.1.10"),
            ("releaseTag", "v1.17.1.9-preview2"),
            ("version", "latest"), ("version", "v1.17.1.10"),
            ("sha256", "a" * 63), ("sha256", "z" * 64),
            ("sha256", int("1" * 64)),
            ("size", 0), ("size", True), ("size", 32 * 1024 * 1024 + 1),
            ("label", "bad\nlabel"), ("label", "")]
        for field, value in changes:
            with self.subTest(field=field, value=value):
                manifest = registry()
                manifest["links"][0][field] = value
                with self.assertRaises(ValueError):
                    self.load(manifest)
        for field, value in (("repository", "attacker/MeshCore"), ("schemaVersion", True),
                             ("schemaVersion", 2), ("links", [])):
            manifest = registry()
            manifest[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.load(manifest)
        manifest = registry()
        manifest["links"].append(dict(manifest["links"][0]))
        with self.assertRaisesRegex(ValueError, "duplicate"):
            self.load(manifest)

    def test_published_aliases_cannot_disappear_or_change_but_labels_can(self):
        previous = registry()
        current = copy.deepcopy(previous)
        current["links"][0]["label"] = "Improved description"
        current["links"].extend(registry(ZIP, "zip")["links"])
        SHORTLINKS.validate_immutable(previous, current)
        SHORTLINKS.validate_immutable(None, current)
        for field, value in (("releaseTag", TAG + "-changed"),
                             ("asset", "different-v1.17.1.10.uf2"),
                             ("sha256", "a" * 64), ("size", 1024)):
            modified = copy.deepcopy(current)
            modified["links"][0][field] = value
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "retargeted"):
                SHORTLINKS.validate_immutable(previous, modified)
        removed = registry(ZIP, "zip")
        with self.assertRaisesRegex(ValueError, "removed"):
            SHORTLINKS.validate_immutable(previous, removed)

    def test_mirror_streams_real_bytes_and_reuses_only_validated_cache(self):
        manifest = registry()
        manifest["links"].extend(registry(ZIP, "zip")["links"])
        calls = []
        def opener(url):
            calls.append(url)
            return Response(UF2 if url.endswith(".uf2") else ZIP)
        with tempfile.TemporaryDirectory() as directory:
            output, cache = Path(directory) / "out", Path(directory) / "cache"
            published = SHORTLINKS.mirror(manifest, output, cache, opener)
            self.assertEqual([path.read_bytes() for path in published], [UF2, ZIP])
            self.assertEqual(len(calls), 2)
            self.assertTrue(all(url.startswith("https://github.com/mikecarper/MeshCore/releases/download/")
                                for url in calls))
            SHORTLINKS.mirror(manifest, output, cache, opener)
            self.assertEqual(len(calls), 2)
            # Corruption with the same size must not bypass the cache check.
            cached = cache / (manifest["links"][0]["sha256"] + ".uf2")
            cached.write_bytes(UF2[:20] + b"!" + UF2[21:])
            published[0].unlink()
            SHORTLINKS.mirror(manifest, output, cache, opener)
            self.assertEqual(len(calls), 3)
            self.assertEqual(published[0].read_bytes(), UF2)
            self.assertEqual(cached.read_bytes(), UF2)
            self.assertFalse(list(output.glob(".firmware-*")))
            self.assertFalse(list(cache.glob(".firmware-*")))

    def test_existing_alias_conflicts_fail_before_any_download(self):
        manifest = registry()
        with tempfile.TemporaryDirectory() as directory:
            output, cache = Path(directory) / "out", Path(directory) / "cache"
            output.mkdir()
            alias = output / manifest["links"][0]["filename"]
            conflict = UF2[:20] + b"!" + UF2[21:]
            alias.write_bytes(conflict)
            def opener(_url):
                self.fail("existing alias conflicts must fail before network work")
            with self.assertRaisesRegex(ValueError, "SHA-256"):
                SHORTLINKS.mirror(manifest, output, cache, opener)
            self.assertEqual(alias.read_bytes(), conflict)

    def test_alias_created_during_download_is_not_overwritten(self):
        manifest = registry()
        with tempfile.TemporaryDirectory() as directory:
            output, cache = Path(directory) / "out", Path(directory) / "cache"
            alias = output / manifest["links"][0]["filename"]
            def opener(_url):
                alias.write_bytes(b"existing unrelated file")
                return Response(UF2)
            with self.assertRaises(ValueError):
                SHORTLINKS.mirror(manifest, output, cache, opener)
            self.assertEqual(alias.read_bytes(), b"existing unrelated file")

    def test_bad_network_data_never_publishes_or_poison_cache(self):
        cases = ((registry(), UF2[:-1], "application/octet-stream", None),
                 (registry(), UF2 + b"excess", "application/octet-stream", None),
                 (registry(), UF2[:20] + b"!" + UF2[21:], "application/octet-stream", None),
                 (registry(), UF2, "text/html", None),
                 (registry(), UF2, "application/javascript", None),
                 (registry(), UF2, "application/octet-stream", "http://release-assets.githubusercontent.com/example"),
                 (registry(), UF2, "application/octet-stream", "https://attacker.example/download"),
                 (registry(b"<!DOCTYPE html><html>redirect</html>", "bin"),
                  b"<!DOCTYPE html><html>redirect</html>", "application/octet-stream", None),
                 (registry(b"window.location = 'https://example.com';", "bin"),
                  b"window.location = 'https://example.com';", "application/octet-stream", None),
                 (registry(b"not firmware", "uf2"), b"not firmware", "application/octet-stream", None))
        for manifest, data, content_type, url in cases:
            with self.subTest(content_type=content_type, url=url, data=data[:20]):
                with tempfile.TemporaryDirectory() as directory:
                    output, cache = Path(directory) / "out", Path(directory) / "cache"
                    with self.assertRaises(ValueError):
                        SHORTLINKS.mirror(manifest, output, cache,
                            lambda _url: Response(data, content_type, url))
                    self.assertFalse(list(output.iterdir()))
                    self.assertFalse(list(cache.iterdir()))

    def test_redirects_allow_only_github_https_asset_delivery(self):
        handler = SHORTLINKS._ReleaseRedirect()
        request = Request("https://github.com/mikecarper/MeshCore/releases/download/" + TAG + "/app.uf2")
        for url in ("http://github.com/app.uf2", "https://github.com.attacker.example/app.uf2",
                    "https://attacker.example/app.uf2", "https://user:secret@github.com/app.uf2"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                handler.redirect_request(request, None, 302, "Found", {}, url)
        allowed = handler.redirect_request(request, None, 302, "Found", {},
            "https://release-assets.githubusercontent.com/example?token=signed")
        self.assertEqual(allowed.full_url,
            "https://release-assets.githubusercontent.com/example?token=signed")

    def test_cli_check_only_runs_without_network_and_enforces_previous(self):
        with tempfile.TemporaryDirectory() as directory:
            current, previous = Path(directory) / "current.json", Path(directory) / "previous.json"
            manifest = registry()
            current.write_text(json.dumps(manifest), encoding="ascii")
            previous.write_text(json.dumps(manifest), encoding="ascii")
            command = [sys.executable, str(SCRIPT), "--manifest", str(current), "--check-only"]
            result = subprocess.run(command, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            result = subprocess.run(command + ["--previous", str(previous)],
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            manifest["links"][0]["sha256"] = "a" * 64
            current.write_text(json.dumps(manifest), encoding="ascii")
            result = subprocess.run(command + ["--previous", str(previous)],
                                    capture_output=True, text=True, timeout=10)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("retargeted", result.stderr)


if __name__ == "__main__":
    unittest.main()
