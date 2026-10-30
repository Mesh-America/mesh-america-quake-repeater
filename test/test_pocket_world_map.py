#!/usr/bin/env python3
"""Qualify the real bounded world-map decoder, projection and generated pack."""
import importlib.util
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest
import zlib

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("pack_world_map", ROOT / "tools/meshpocket_map/pack_world_map.py")
packer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(packer)


def run(command):
    result = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if result.returncode:
        raise AssertionError("command failed: " + " ".join(map(str, command)) + "\n" + result.stdout)
    return result.stdout


class PocketWorldMapTests(unittest.TestCase):
    def test_generated_pack_bounds_and_roundtrip(self):
        header = packer.OUTPUT.read_text(encoding="utf-8")
        chunks = [tuple(map(int, row)) for row in re.findall(
            r"\{(\d+), (\d+), (\d+), (-?\d+), (-?\d+), (-?\d+), (-?\d+)\}", header)]
        data_section = header.split("static const uint8_t kDeflate[] = {", 1)[1].split("};", 1)[0]
        packed = bytes(int(byte, 16) for byte in re.findall(r"0x([0-9a-f]{2})", data_section))
        self.assertEqual(len(chunks), 32)
        self.assertEqual(len(packed) + 24 * len(chunks), 80658)
        self.assertIn("kRingCount = 1422;", header)
        offset = 0
        for start, size, raw_size, west, south, east, north in chunks:
            self.assertEqual(start, offset)
            self.assertLessEqual(raw_size, 3072)
            self.assertLessEqual(west, east)
            self.assertLessEqual(south, north)
            stream = zlib.decompressobj(wbits=-15)
            raw = stream.decompress(packed[start:start + size])
            self.assertTrue(stream.eof)
            self.assertFalse(stream.unused_data)
            self.assertEqual(len(raw), raw_size)
            offset += size
        self.assertEqual(offset, len(packed))

    def test_simplification_retains_tiny_islands_and_dateline(self):
        island = [(170.0, -20.0), (170.001, -20.0), (170.001, -20.001),
                  (170.0, -20.001), (170.0, -20.0)]
        simplified = packer.simplify(island)
        self.assertGreaterEqual(len(set(simplified)), 3)
        self.assertEqual(simplified[0], simplified[-1])
        crossing = [(179.8, -20.0), (-179.8, -20.0), (-179.8, -20.4),
                    (179.8, -20.4), (179.8, -20.0)]
        simplified = packer.simplify(crossing)
        self.assertLess(max(p[0] for p in simplified) - min(p[0] for p in simplified), 1000)
        self.assertEqual(simplified[0], simplified[-1])
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            list(packer.source_rings(b"incorrect source archive"))

    def test_real_renderer_and_parser_under_sanitizers(self):
        cc, cxx = shutil.which("gcc"), shutil.which("g++")
        if not cc or not cxx:
            self.skipTest("GCC/G++ unavailable")
        with tempfile.TemporaryDirectory(prefix="mesh-pocket-map-") as temporary:
            directory = Path(temporary)
            # Windows MinGW commonly has no sanitizer runtime. Linux CI runs
            # the same real renderer with both bounds/undefined checks active.
            sanitizer = [] if __import__("os").name == "nt" else ["-fsanitize=address,undefined"]
            run([cc, "-std=c11", "-DMESHCORE_TINF_IMPLEMENTATION", "-g", "-O1", *sanitizer,
                 "-c", str(ROOT / "src/helpers/ota/tinf/tinflate.c"), "-o", str(directory / "tinf.o")])
            executable = directory / "world_map"
            run([cxx, "-std=c++17", "-DPOCKET_WORLD_MAP_TEST", "-I" + str(ROOT / "src"),
                 "-g", "-O1", *sanitizer, str(ROOT / "test/fixtures/pocket_world_map/test_world_map.cpp"),
                 str(ROOT / "src/helpers/ui/PocketWorldMap.cpp"), str(directory / "tinf.o"), "-o", str(executable)])
            self.assertIn("checks passed", run([str(executable)]))

    def test_arm_decode_stack_fits_companion_loop(self):
        tool = shutil.which("arm-none-eabi-g++")
        if not tool:
            candidate = Path.home() / ".platformio/packages/toolchain-gccarmnoneeabi/bin/arm-none-eabi-g++"
            if candidate.is_file():
                tool = str(candidate)
        if not tool:
            self.skipTest("ARM compiler unavailable")
        cc = str(Path(tool).with_name("arm-none-eabi-gcc"))
        with tempfile.TemporaryDirectory(prefix="mesh-pocket-map-stack-") as temporary:
            directory = Path(temporary)
            flags = ["-mcpu=cortex-m4", "-mthumb", "-Oz", "-fno-inline-small-functions", "-fstack-usage"]
            run([tool, "-std=gnu++17", *flags, "-fno-exceptions", "-fno-rtti", "-DPOCKET_WORLD_MAP_TEST",
                 "-I" + str(ROOT / "src"), "-c", str(ROOT / "src/helpers/ui/PocketWorldMap.cpp"),
                 "-o", str(directory / "map.o")])
            run([cc, "-std=gnu11", *flags, "-DMESHCORE_TINF_IMPLEMENTATION", "-c",
                 str(ROOT / "src/helpers/ota/tinf/tinflate.c"), "-o", str(directory / "tinf.o")])

            def frames(name):
                rows = {}
                for line in (directory / (name + ".su")).read_text().splitlines():
                    function, size, kind = line.rsplit("\t", 2)
                    self.assertEqual(kind, "static", line)
                    rows[function] = int(size)
                return rows

            renderer, decoder = frames("map"), frames("tinf")
            entry = next(size for name, size in renderer.items() if "::renderWorldMap(" in name)
            # Decoder helper sum overbounds mutually exclusive branches.
            decode = sum(size for name, size in decoder.items()
                         if not name.endswith(":tinf_init") and not name.endswith(":tinf_uncompress"))
            draw = sum(size for name, size in renderer.items()
                       if any(signature in name for signature in ("::drawChunk(", "::project(", "::readDelta(")))
            peak = entry + max(decode, draw)
            self.assertLessEqual(peak + 1536, 8192)
            print(f"ARM Pocket map local stack: {peak} bytes + 1536 caller reserve <= 8192")


if __name__ == "__main__":
    unittest.main()
