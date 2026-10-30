#!/usr/bin/env python3
"""Compile and execute the production USB formatter with bridge-only flags."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class BridgeDebugFormatterTests(unittest.TestCase):
    def test_bridge_only_native_usb_has_bounded_runtime_gated_output(self):
        compiler = shutil.which("g++") or shutil.which("clang++")
        self.assertIsNotNone(compiler)
        header = (ROOT / "src/MeshCore.h").read_text(encoding="ascii")
        start = header.index("#if defined(ARDUINO) && \\\n    (defined(NRF52_PLATFORM)")
        formatter = header[start:header.index("#if MESH_DEBUG && ARDUINO", start)]
        harness = r'''
#include <cassert>
#include <cstdint>
#include <cstring>
#include <string>
struct Stream {
  unsigned calls = 0;
  size_t capacity = 256;
  std::string output;
  size_t write(const uint8_t* bytes, size_t length) {
    ++calls;
    if (length > capacity) return 0;
    output.append(reinterpret_cast<const char*>(bytes), length);
    capacity -= length;
    return length;
  }
} port;
namespace mesh {
bool master = false, verbose = false;
bool isUsbDebugLoggingEnabled() { return master && verbose; }
Stream& usbLoggingPort() { return port; }
}
@FORMATTER@
int main() {
  using mesh::nrf52DebugPrintf;
  assert(nrf52DebugPrintf("quiet") == 0 && port.calls == 0);
  mesh::verbose = true;
  assert(nrf52DebugPrintf("quiet") == 0 && port.calls == 0);
  mesh::master = true;
  mesh::verbose = false;
  assert(nrf52DebugPrintf("quiet") == 0 && port.calls == 0);
  mesh::verbose = true;
  assert(nrf52DebugPrintf("RS232: ready\n") == 13);
  assert(port.output == "RS232: ready\n");
  port.output.clear(); port.capacity = 256;
  const std::string large(1024, 'x');
  assert(nrf52DebugPrintf("%s\n", large.c_str()) == 255);
  assert(port.output.size() == 255);
  assert(port.output.substr(251) == "...\n");
  port.output.clear(); port.capacity = 0;
  assert(nrf52DebugPrintf("blocked\n") == 0 && port.output.empty());
  assert(nrf52DebugPrintf(nullptr) == 0);
}
'''.replace("@FORMATTER@", formatter)
        with tempfile.TemporaryDirectory(prefix="bridge-debug-formatter-") as temporary:
            work = Path(temporary)
            (work / "helpers").mkdir()
            (work / "Arduino.h").write_text("#pragma once\n", encoding="ascii")
            (work / "helpers/NonBlockingWriteStream.h").write_text("#pragma once\n", encoding="ascii")
            source = work / "main.cpp"
            source.write_text(harness, encoding="ascii")
            for name, flags in (
                ("nrf52-rs232", ["-DNRF52_PLATFORM=1", "-DWITH_RS232_BRIDGE=1"]),
                ("esp32-rs232", ["-DMESH_ESP32_USB_CONSOLE_COOPERATIVE=1", "-DWITH_RS232_BRIDGE=1"]),
                ("esp32-udp", ["-DMESH_ESP32_USB_CONSOLE_COOPERATIVE=1", "-DWITH_UDP_BRIDGE=1"]),
            ):
                with self.subTest(platform=name):
                    binary = work / name
                    built = subprocess.run([
                        compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
                        "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
                        "-fno-pie", "-no-pie", "-DARDUINO=1",
                        "-DMESH_DEBUG=0", "-DBRIDGE_DEBUG=0", "-DPOWERSAVING_DEBUG=0",
                        *flags, "-I" + str(work), str(source), "-o", str(binary),
                    ], capture_output=True, text=True, timeout=30)
                    self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
                    checked = subprocess.run([str(binary)], capture_output=True,
                                             text=True, timeout=10)
                    self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)


if __name__ == "__main__":
    unittest.main()
