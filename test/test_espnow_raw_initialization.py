#!/usr/bin/env python3
"""Check cold ESP-NOW storage initialization and unused linker reclamation."""

from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class EspNowRawInitializationTest(unittest.TestCase):
    def test_constexpr_initialization_does_not_root_an_unused_workspace(self):
        with tempfile.TemporaryDirectory(prefix="espnow-unused-init-") as temp:
            workspace = Path(temp) / "workspace.cpp"
            workspace.write_text(r'''
#include <helpers/ESPNowRawFragmentation.h>
constexpr mesh::espnow::ESPNowRawReassembler constant_initialized(1234);
mesh::espnow::ESPNowRawReassembler unused_reassembler;
''')
            main = Path(temp) / "main.cpp"
            main.write_text("int main() { return 0; }\n")
            binary = Path(temp) / "without-espnow"
            # Deliberately disable optimization/LTO: only the linker's real
            # section reclamation may drop this externally visible global.
            result = subprocess.run([
                "c++", "-std=c++11", "-O0", "-fno-lto",
                "-ffunction-sections", "-fdata-sections", "-Wl,--gc-sections",
                "-I", str(ROOT / "src"), str(workspace), str(main),
                "-o", str(binary),
            ], text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            symbols = subprocess.run(["nm", "--defined-only", str(binary)],
                                     text=True, capture_output=True, check=True).stdout
            self.assertNotIn("unused_reassembler", symbols)
            self.assertNotIn("_GLOBAL__sub_I_unused_reassembler", symbols)
            subprocess.run([str(binary)], check=True)

    def test_default_and_custom_timeouts_with_fragmentation_reset_and_rollover(self):
        harness = r'''
#include <helpers/ESPNowRawFragmentation.h>
#include <cassert>
#include <cstdint>
#include <cstring>
#include <new>
using namespace mesh::espnow;
ESPNowRawReassembler default_initialized;
int main() {
  uint8_t packet[255], output[255], mac[6] = {2, 1, 2, 3, 4, 5};
  for (unsigned i = 0; i < sizeof packet; ++i) packet[i] = i;
  ESPNowRawFrames frames;
  assert(encodeEspNowRawFrames(packet, sizeof packet, frames));
  size_t size = 99;
  assert(default_initialized.expire(0) == 0);
  assert(default_initialized.acceptFrame(mac, frames.data[0], frames.lengths[0],
      1, output, sizeof output, size) == ESPNowRawReassemblyResult::FRAGMENT_STORED);
  assert(default_initialized.expire(2000) == 0);
  assert(default_initialized.expire(2001) == 1); // unchanged 2000 ms default
  // A placement-new object must clear arbitrary prior bytes, not depend on
  // global .bss zeroing. Custom initialization preserves its exact timeout.
  alignas(ESPNowRawReassemblerT<1>) uint8_t arena[sizeof(ESPNowRawReassemblerT<1>)];
  memset(arena, 0xCC, sizeof arena);
  auto* reassembler = new (arena) ESPNowRawReassemblerT<1>(20);
  assert(reassembler->expire(1000) == 0);
  assert(reassembler->acceptFrame(mac, frames.data[0], frames.lengths[0],
      0xFFFFFFF0UL, output, sizeof output, size)
      == ESPNowRawReassemblyResult::FRAGMENT_STORED);
  assert(reassembler->expire(3) == 0);
  assert(reassembler->expire(4) == 1);
  assert(reassembler->acceptFrame(mac, frames.data[1], frames.lengths[1],
      5, output, sizeof output, size) == ESPNowRawReassemblyResult::FRAGMENT_STORED);
  assert(reassembler->acceptFrame(mac, frames.data[0], frames.lengths[0],
      6, output, sizeof output, size) == ESPNowRawReassemblyResult::PACKET_COMPLETE);
  assert(size == sizeof packet && !memcmp(output, packet, sizeof packet));
  assert(reassembler->acceptFrame(mac, frames.data[0], frames.lengths[0],
      7, output, sizeof output, size) == ESPNowRawReassemblyResult::DUPLICATE);
  reassembler->reset();
  assert(reassembler->expire(1000) == 0);
  assert(reassembler->acceptFrame(mac, frames.data[0], frames.lengths[0],
      8, output, sizeof output, size) == ESPNowRawReassemblyResult::FRAGMENT_STORED);
  assert(reassembler->acceptFrame(mac, frames.data[1], frames.lengths[1],
      9, output, sizeof output, size) == ESPNowRawReassemblyResult::PACKET_COMPLETE);
  assert(size == sizeof packet && !memcmp(output, packet, sizeof packet));
  reassembler->~ESPNowRawReassemblerT<1>();
}
'''
        with tempfile.TemporaryDirectory(prefix="espnow-live-init-") as temp:
            binary = Path(temp) / "reassembler"
            result = subprocess.run([
                "c++", "-std=c++11", "-Wall", "-Wextra", "-Werror",
                "-fsanitize=address,undefined", "-g", "-I", str(ROOT / "src"),
                "-x", "c++", "-", "-o", str(binary),
            ], input=harness, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            result = subprocess.run([str(binary)], text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
