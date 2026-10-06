#!/usr/bin/env python3
"""Run the production charger CLI with hardware/storage failure fixtures."""

from pathlib import Path
import os
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SANITIZER_FLAGS = [] if os.name == "nt" else [
    "-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-fno-pie", "-no-pie"]


class BatteryChargeCliTest(unittest.TestCase):
    def test_charger_api_is_scoped_to_supported_boards(self):
        # Unused virtual hooks still consume flash in small Companion images.
        # Compile the actual MainBoard interface for every supported macro and
        # representative unrelated platforms, not only the capability macro.
        source = r'''
#include <MeshCore.h>
#include <type_traits>
template<class Board> class HasChargeControl {
  template<class B> static std::true_type probe(decltype(&B::getBatteryChargeTarget));
  template<class> static std::false_type probe(...);
public:
  static constexpr bool value = decltype(probe<Board>(nullptr))::value;
};
static_assert(MESH_BATTERY_CHARGE_CONTROL == EXPECT_CHARGE_CONTROL, "capability scope");
static_assert(HasChargeControl<mesh::MainBoard>::value == bool(EXPECT_CHARGE_CONTROL),
              "charger virtual hooks must not consume unrelated board flash");
'''
        supported = ("TBEAM_SX1262", "TBEAM_SX1276", "TBEAM_SUPREME_SX1262",
                     "HELTEC_MESH_SOLAR")
        unrelated = (None, "STM32", "NRF52", "ESP32", "HELTEC_V4")
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "test.cpp"
            path.write_text(source, encoding="ascii")
            for macro in supported + unrelated:
                with self.subTest(board=macro):
                    expected = int(macro in supported)
                    flags = [f"-D{macro}"] if macro else []
                    subprocess.run(["c++", "-std=c++11", "-fsyntax-only",
                                    f"-DEXPECT_CHARGE_CONTROL={expected}", *flags,
                                    "-I", str(ROOT / "src"), str(path)],
                                   check=True, capture_output=True)

    def test_commands_failures_precision_and_bounded_replies(self):
        source = r'''
#include <MeshCore.h>
#include <helpers/BatteryChargeCLI.h>
#include <cassert>
#include <cstring>
#include <string>
struct Board : mesh::MainBoard {
  bool capable = true, read_ok = true, save_ok = true, restore_failed = false;
  unsigned reads = 0, writes = 0;
  uint16_t target = 4200;
  uint16_t getBattMilliVolts() override { return 3700; }
  const char* getManufacturerName() const override { return "fixture"; }
  void reboot() override {}
  uint8_t getStartupReason() const override { return 0; }
  const char* getBatteryChargeTargetOptions() const override {
    return capable ? "4.10,4.15,4.20,4.36" : nullptr;
  }
  bool getBatteryChargeTarget(uint16_t& result) override {
    ++reads;
    if (!read_ok) return false;
    result = target;
    return true;
  }
  bool batteryChargeTargetRestoreFailed() const override { return restore_failed; }
  bool supportsBatteryChargeTarget(uint16_t mv) override {
    return mv == 4100 || mv == 4150 || mv == 4200 || mv == 4360;
  }
  bool setBatteryChargeTarget(uint16_t mv) override {
    ++writes;
    if (!save_ok) return false;
    target = mv;
    return true;
  }
};
int main() {
  using mesh::power::handleBatteryChargeCommand;
  using mesh::power::parseChargeVolts;
  Board board;
  char reply[160];
  assert(handleBatteryChargeCommand(board, "get charge.voltage", reply, sizeof(reply)));
  assert(std::string(reply) == "> 4.200 V" && board.reads == 1);
  board.restore_failed = true;
  assert(handleBatteryChargeCommand(board, "get charge.voltage", reply, sizeof(reply)));
  assert(std::string(reply) == "> 4.200 V (boot restore failed)");
  board.restore_failed = false;
  assert(handleBatteryChargeCommand(board, "get charge.voltage.options", reply, sizeof(reply)));
  assert(std::string(reply) == "> 4.10,4.15,4.20,4.36 V");
  for (const char* value : {"4.1", "4.10", "4.100", "04.100", "4.10 \t"}) {
    std::string command = "set charge.voltage "; command += value;
    assert(handleBatteryChargeCommand(board, command.c_str(), reply, sizeof(reply)));
    assert(std::string(reply) == "OK - charge.voltage 4.100 V (saved)");
    assert(board.target == 4100);
  }
  for (const char* value : {"", "4.", ".1", "4.1000", "4.1garbage", "+4.1", "-4.1",
       "nan", "inf", "4e0", "65536", "65.536", "999999999999999999999", "4 1"}) {
    const unsigned writes = board.writes;
    std::string command = "set charge.voltage "; command += value;
    assert(handleBatteryChargeCommand(board, command.c_str(), reply, sizeof(reply)));
    assert(std::string(reply).find("Error: usage") == 0 && board.writes == writes);
  }
  for (const char* value : {"3.65", "3.650", "4", "4.099", "4.101", "0", "65.535"}) {
    const unsigned writes = board.writes;
    std::string command = "set charge.voltage "; command += value;
    assert(handleBatteryChargeCommand(board, command.c_str(), reply, sizeof(reply)));
    assert(std::string(reply).find("Error: unsupported target") == 0);
    assert(board.writes == writes && board.target == 4100);
  }
  uint16_t parsed = 123;
  assert(parseChargeVolts("3.65", parsed) && parsed == 3650);
  assert(parseChargeVolts("65.535", parsed) && parsed == 65535);
  assert(!parseChargeVolts("65.536", parsed) && parsed == 65535);
  board.read_ok = false;
  assert(handleBatteryChargeCommand(board, "get charge.voltage", reply, sizeof(reply)));
  assert(std::string(reply) == "Error: charger read failed");
  board.save_ok = false;
  assert(handleBatteryChargeCommand(board, "set charge.voltage 4.2", reply, sizeof(reply)));
  assert(std::string(reply).find("Error: charge target not confirmed saved") == 0);
  assert(board.target == 4100);
  board.capable = false;
  unsigned writes = board.writes, reads = board.reads;
  assert(handleBatteryChargeCommand(board, "set charge.voltage 3.65", reply, sizeof(reply)));
  assert(std::string(reply).find("not supported on this board") != std::string::npos);
  assert(board.writes == writes && board.reads == reads);
  board.capable = true;
  for (const char* command : {"get charge.voltage.bad", "set charge.voltage.options", "charge.voltage",
       "get battery.full", "set radio 910,62.5,7,5"}) {
    assert(!handleBatteryChargeCommand(board, command, reply, sizeof(reply)));
  }
  assert(handleBatteryChargeCommand(board, "get charge.voltage extra", reply, sizeof(reply)));
  assert(std::string(reply).find("Error: usage") == 0);
  // Companion prefixes reserve three bytes; callers also use smaller buffers.
  for (size_t capacity = 1; capacity <= 157; ++capacity) {
    char bounded[164]; memset(bounded, '#', sizeof(bounded));
    memcpy(bounded, "ab|", 3);
    assert(handleBatteryChargeCommand(board, "set charge.voltage 3.65", bounded + 3, capacity));
    assert(memcmp(bounded, "ab|", 3) == 0);
    assert(bounded[3 + capacity] == '#' && memchr(bounded + 3, 0, capacity));
  }
  assert(!handleBatteryChargeCommand(board, nullptr, reply, sizeof(reply)));
  assert(!handleBatteryChargeCommand(board, "get charge.voltage", nullptr, sizeof(reply)));
  assert(!handleBatteryChargeCommand(board, "get charge.voltage", reply, 0));
}
'''
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)
            (path / "test.cpp").write_text(source, encoding="ascii")
            binary = path / "test"
            subprocess.run(["c++", "-std=c++11", "-Wall", "-Wextra", "-DTBEAM_SX1262",
                            *SANITIZER_FLAGS,
                            "-I", str(ROOT / "src"), str(path / "test.cpp"),
                            "-o", str(binary)], check=True, capture_output=True)
            subprocess.run([str(binary)], check=True)

    def test_shared_role_dispatch_and_meshsolar_hardware_limit(self):
        # Pin independent role entry points so a parser tested here cannot be
        # omitted from the Companion/BLE path while working on serial repeaters.
        for name in ("src/helpers/CommonCLI.cpp", "examples/companion_radio/MyMesh.cpp",
                     "examples/simple_secure_chat/main.cpp"):
            source = (ROOT / name).read_text()
            self.assertIn("#include <helpers/BatteryChargeCLI.h>", source)
            self.assertIn("mesh::power::handleBatteryChargeCommand(", source)
        source = r'''
#include <MeshCore.h>
#include <helpers/BatteryChargeCLI.h>
#include "MeshSolarBoard.h"
#include <cassert>
#include <string>
int main() {
  MeshSolarBoard board;
  char reply[160];
  assert(!board.supportsBatteryChargeTarget(3650));
  assert(!board.setBatteryChargeTarget(3650));
  for (const char* cmd : {"get charge.voltage", "get charge.voltage.options", "set charge.voltage 3.65"}) {
    assert(mesh::power::handleBatteryChargeCommand(board, cmd, reply, sizeof(reply)));
    assert(std::string(reply).find("CN3795") != std::string::npos);
    assert(std::string(reply).find("hardware") != std::string::npos);
  }
}
'''
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)
            (path / "helpers").mkdir()
            (path / "Arduino.h").write_text(
                "#pragma once\n#include <stdint.h>\ninline uint16_t meshSolarGetBattVoltage() {return 7400;}\n",
                encoding="ascii")
            (path / "meshSolarApp.h").write_text('#include "Arduino.h"\n', encoding="ascii")
            (path / "helpers/NRF52Board.h").write_text(r'''
#pragma once
#include <MeshCore.h>
class NRF52Board : public mesh::MainBoard {
public:
  explicit NRF52Board(const char*) {}
  void reboot() override {}
  uint8_t getStartupReason() const override { return 0; }
};
using NRF52BoardDCDC = NRF52Board;
''', encoding="ascii")
            (path / "test.cpp").write_text(source, encoding="ascii")
            binary = path / "test"
            subprocess.run(["c++", "-std=c++11", "-DHELTEC_MESH_SOLAR", "-I", temp, "-I", str(ROOT / "src"),
                            "-I", str(ROOT / "variants/heltec_mesh_solar"),
                            str(path / "test.cpp"), "-o", str(binary)],
                           check=True, capture_output=True)
            subprocess.run([str(binary)], check=True)


if __name__ == "__main__":
    unittest.main()
