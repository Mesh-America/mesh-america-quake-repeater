#!/usr/bin/env python3
"""Execute the production Companion UART setup and bounded frame queue."""

from pathlib import Path
import configparser
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

from test_replay_reset_integration import extract_braced


ROOT = Path(__file__).resolve().parents[1]
SANITIZERS = (["-fsanitize=address,undefined", "-fno-sanitize-recover=all",
               "-fno-pie", "-no-pie"] if sys.platform.startswith("linux") else [])


def conditional_block(source, marker):
    """Keep nested compile-time conditions from the actual setup intact."""
    start = source.index(marker)
    depth = 0
    for line in source[start:].splitlines(keepends=True):
        if re.match(r"\s*#\s*(?:if|ifdef|ifndef)\b", line):
            depth += 1
        elif re.match(r"\s*#\s*endif\b", line):
            depth -= 1
            if depth == 0:
                end = start + len(line)
                return source[source.index(marker):end]
        start += len(line)
    raise AssertionError(f"unterminated setup condition: {marker}")


HARNESS = r'''
#include <cassert>
#include <algorithm>
#include <cstdio>
#include <deque>
#include <limits>
#include <string>
#include <vector>
#include "helpers/ArduinoSerialInterface.h"
#include "helpers/MultiSerialInterface.h"
@STREAM@
class HardwareSerial : public BufferStream {
public:
  unsigned port;
  int rx = -1, tx = -1;
  unsigned baud = 0;
  explicit HardwareSerial(unsigned selected) : port(selected) {}
  void setPins(int receive, int transmit) { rx = receive; tx = transmit; }
  void begin(unsigned speed) { baud = speed; }
};
@DECLARATION@
static MultiSerialInterface interface_manager;
static void setupHardwareSerial() {
@SETUP@
}

int main() {
  setupHardwareSerial();
#if defined(SERIAL_RX)
  assert(companion_serial.rx == SERIAL_RX);
  assert(companion_serial.tx == SERIAL_TX);
  assert(companion_serial.baud == 115200);
  interface_manager.enable();
  assert(interface_manager.isInterfaceConnected(InterfaceType::HardwareSerial));
  const uint8_t request[] = {'<', 1, 0, 0x01};
  companion_serial.push(request, sizeof(request));
  uint8_t received[MAX_FRAME_SIZE] = {};
  assert(interface_manager.checkRecvFrame(received) == 1);
  assert(interface_manager.captureReplyRoute() == &hardware_serial_interface);

  // The UART setup must actually opt into admission, not just directly call
  // write(). A zero-capacity port must retain the complete required response.
  companion_serial.write_capacity = 0;
  const uint8_t response[] = {0x00};
  assert(hardware_serial_interface.writeFrame(response, sizeof(response))
      == sizeof(response));
  assert(companion_serial.output.empty());
  assert(hardware_serial_interface.hasPendingIO());
  assert(hardware_serial_interface.isWriteBusy());
  for (unsigned i = 1; i < 4; ++i) {
    assert(hardware_serial_interface.writeFrame(response, sizeof(response))
        == sizeof(response));
  }
  assert(hardware_serial_interface.writeFrame(response, sizeof(response)) == 0);
  companion_serial.write_capacity = 4096;
  hardware_serial_interface.loop();
  std::vector<uint8_t> expected;
  for (unsigned i = 0; i < 4; ++i) {
    expected.insert(expected.end(), {'>', 1, 0, 0x00});
  }
  assert(companion_serial.output == expected);
  assert(!hardware_serial_interface.hasPendingIO());

  // An ESP32-S3 UART FIFO is only 128 bytes, smaller than a maximum frame.
  // Each poll must retain the suffix, including when a Stream unexpectedly
  // accepts fewer bytes than it reported as writable.
  companion_serial.output.clear();
  companion_serial.write_capacity = 128;
  std::vector<uint8_t> payload(MAX_FRAME_SIZE);
  payload[0] = 0x05;
  for (size_t i = 1; i < payload.size(); ++i) payload[i] = uint8_t(i);
  assert(hardware_serial_interface.writeFrame(payload.data(), payload.size())
      == payload.size());
  assert(companion_serial.output.size() == 128);
  assert(hardware_serial_interface.hasPendingIO());
  assert(hardware_serial_interface.writeFrame(response, sizeof(response))
      == sizeof(response));
  assert(companion_serial.output.size() == 128);
  companion_serial.write_capacity = 128;
  companion_serial.max_write = 2;
  hardware_serial_interface.loop();
  assert(companion_serial.output.size() == 130);
  companion_serial.max_write = 0;
  hardware_serial_interface.loop();
  assert(companion_serial.output.size() == 130);
  companion_serial.max_write = std::numeric_limits<size_t>::max();
  hardware_serial_interface.loop();
  expected = {'>', uint8_t(MAX_FRAME_SIZE), 0};
  expected.insert(expected.end(), payload.begin(), payload.end());
  expected.insert(expected.end(), {'>', 1, 0, 0x00});
  assert(companion_serial.output == expected);
  assert(!hardware_serial_interface.hasPendingIO());
#else
  interface_manager.enable();
  assert(!interface_manager.isConnected());
#endif
  std::puts("PASS: actual Companion UART setup and bounded transmission");
}
'''


class CompanionHardwareSerialTest(unittest.TestCase):
    def test_actual_setup_uses_bounded_frame_queue(self):
        compiler = os.environ.get("CXX") or shutil.which("g++") or shutil.which("clang++")
        if compiler is None:
            self.skipTest("a host C++17 compiler is required")
        main = (ROOT / "examples/companion_radio/main.cpp").read_text()
        native = (ROOT / "test/test_serial_mode_switch/test_serial_mode_switch.cpp").read_text()
        declaration = conditional_block(main, "// include hardware serial interface")
        setup = conditional_block(main, "// add hardware serial interface")
        source = HARNESS.replace("@STREAM@", extract_braced(native, "class BufferStream") + ";")
        source = source.replace("@DECLARATION@", declaration).replace("@SETUP@", setup)

        # Keep the test's supported mapping list tied to actual board profiles,
        # without asking PlatformIO to resolve configuration or start a build.
        mappings = []
        for board, rx, tx in (("ThinkNode_M2", "44", "43"),
                              ("ThinkNode_M5", "44", "43"),
                              ("Xiao_S3_WIO", "D7", "D6")):
            folder = {"ThinkNode_M2": "thinknode_m2", "ThinkNode_M5": "thinknode_m5",
                      "Xiao_S3_WIO": "xiao_s3_wio"}[board]
            config = configparser.ConfigParser(interpolation=None)
            config.read(ROOT / "variants" / folder / "platformio.ini")
            self.assertEqual(config[board]["extends"], "esp32_base")
            for profile in ("serial", "full"):
                flags = config[f"env:{board}_companion_radio_{profile}"]["build_flags"]
                self.assertEqual(re.findall(r"-D\s+SERIAL_RX=(\S+)", flags), [rx])
                self.assertEqual(re.findall(r"-D\s+SERIAL_TX=(\S+)", flags), [tx])
            mappings.append((board, [f"SERIAL_RX={rx}", f"SERIAL_TX={tx}"]))
        mappings.append(("no-hardware-uart", []))

        with tempfile.TemporaryDirectory(prefix="meshcore-companion-uart-") as directory:
            work = Path(directory)
            cpp = work / "test.cpp"
            cpp.write_text(source, encoding="ascii")
            for name, defines in mappings:
                with self.subTest(board=name):
                    binary = work / f"{name}.exe"
                    built = subprocess.run([
                        compiler, "-std=c++17", "-Werror", *SANITIZERS,
                        "-DD6=43", "-DD7=44", *[f"-D{define}" for define in defines],
                        f"-I{ROOT / 'test/mocks'}", f"-I{ROOT / 'src'}",
                        str(cpp), str(ROOT / "src/helpers/ArduinoSerialInterface.cpp"),
                        "-o", str(binary),
                    ], capture_output=True, text=True, timeout=60)
                    self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
                    checked = subprocess.run([str(binary)], capture_output=True,
                                             text=True, timeout=10)
                    self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
                    self.assertIn("PASS: actual Companion UART setup", checked.stdout)


if __name__ == "__main__":
    unittest.main()
