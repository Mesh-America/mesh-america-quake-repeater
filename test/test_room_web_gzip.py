#!/usr/bin/env python3
"""Verify exact page identity, generation recovery and role-owned resources."""
import gzip
import importlib.util
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from generate_room_web_html import generate, page_bytes, render, source_page, SOURCE, OUTPUT
from test_replay_reset_integration import extract_braced


class RoomWebGzipTests(unittest.TestCase):
    def test_checked_in_page_preserves_every_source_byte(self):
        raw = source_page((ROOT / SOURCE).read_text(encoding="ascii"))
        packed = page_bytes((ROOT / OUTPUT).read_text(encoding="ascii"))
        self.assertEqual(gzip.decompress(packed), raw)
        self.assertLess(len(packed), len(raw) // 3)
        self.assertFalse(generate(ROOT, check=True))

    def test_stale_and_corrupt_assets_fail_check_and_regenerate_idempotently(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            (root / SOURCE).parent.mkdir(parents=True)
            (root / SOURCE).write_text('static const char ROOM_WEB_HTML[] PROGMEM = R"roomhtml(<title>Room test</title>)roomhtml";\n')
            with self.assertRaises(ValueError):
                generate(root, check=True)
            self.assertTrue(generate(root))
            first = (root / OUTPUT).read_bytes()
            self.assertFalse(generate(root))
            self.assertEqual((root / OUTPUT).read_bytes(), first)
            (root / OUTPUT).write_bytes(first.replace(b"0x1f,", b"0x00,", 1))
            with self.assertRaises(ValueError):
                generate(root, check=True)
            self.assertTrue(generate(root))
            self.assertEqual((root / OUTPUT).read_bytes(), first)
            (root / SOURCE).write_text((root / SOURCE).read_text().replace("Room test", "Room changed"))
            with self.assertRaises(ValueError):
                generate(root, check=True)
            self.assertTrue(generate(root))
            self.assertIn(b"Room changed", gzip.decompress(page_bytes((root / OUTPUT).read_text())))

    def test_renderer_refuses_a_different_page(self):
        with self.assertRaises(ValueError):
            render(b"expected", gzip.compress(b"different", mtime=0))
        with self.assertRaises(ValueError):
            source_page("missing constant")

    def test_only_room_role_owns_page_and_default_callback_links_without_it(self):
        shared = (ROOT / "src/helpers/esp32/WebConfigServer.cpp").read_text()
        self.assertNotIn('#include "RoomWebHtml', shared)
        header = (ROOT / "src/helpers/esp32/WebConfigServer.h").read_text()
        callback = extract_braced(header, "virtual const uint8_t* roomPageGzip(")
        room = (ROOT / "examples/simple_room_server/MyMesh.cpp").read_text()
        provider = extract_braced(room, "const uint8_t* MyMesh::roomPageGzip(")
        self.assertIn('sizeof(ROOM_WEB_HTML_GZ)', provider)
        # Compile the real default callback and prove that a non-Room role
        # needs no page header or storage while still answering safely.
        compiler = shutil.which("g++")
        self.assertIsNotNone(compiler)
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "default.cpp"
            source.write_text('#include <cstddef>\n#include <cstdint>\n#include <cassert>\nstruct Callback {\n'
                              + callback + '\n};\nint main() { Callback c; size_t n=99; assert(c.roomPageGzip(n)==nullptr && n==0); }\n')
            binary = source.with_suffix("")
            subprocess.run([compiler, "-std=c++11", "-Os", str(source), "-o", str(binary)], check=True)
            subprocess.run([str(binary)], check=True)
            symbols = subprocess.check_output(["nm", "-C", str(binary)], text=True)
            self.assertNotIn("ROOM_WEB_HTML", symbols)


if __name__ == "__main__":
    unittest.main()
