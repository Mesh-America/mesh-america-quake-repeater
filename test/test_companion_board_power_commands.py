"""Execute real Companion power formatting and the nRF52 hardware-state reader."""
from pathlib import Path
import os
import re
import subprocess
import tempfile
import unittest
from cpp_source import body

ROOT = Path(__file__).resolve().parents[1]


class CompanionPowerDiagnostics(unittest.TestCase):
    def compile(self, source, flags=()):
        with tempfile.TemporaryDirectory(prefix="companion-power-diagnostics-") as folder:
            cpp, exe = Path(folder) / "test.cpp", Path(folder) / "test"
            cpp.write_text(source, encoding="ascii")
            result = subprocess.run([os.environ.get("CXX", "c++"), "-std=c++17",
                "-Wall", "-Wextra", "-Werror", "-fsanitize=address,undefined",
                "-fno-omit-frame-pointer", "-no-pie", "-I", str(ROOT / "src"),
                *["-D" + flag for flag in flags], str(cpp), "-o", str(exe)],
                capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            run = subprocess.run([str(exe)], capture_output=True, text=True, timeout=10)
            self.assertEqual(run.returncode, 0, run.stderr)

    def test_actual_common_power_format_and_capability_gates(self):
        source = (ROOT / "src/helpers/CommonCLI.cpp").read_text()
        common = body(source, '} else if (strcmp(command, "power") == 0)')
        common = common[common.index("{") :]
        fixture = r'''
#include <helpers/CompanionPowerDiagnostics.h>
#include <cassert>
struct Board {
  bool pm=false, usb_cap=false, solar_cap=false;
  bool usb=false, solar=false, external=false, charger=false;
  bool watchdog_supported=true, watchdog_running=true;
  unsigned batt_reads=0, boot_reads=0, source_reads=0, usb_reads=0, solar_reads=0;
  bool supportsPowerManagement() const { return pm; }
  bool hasUsbPowerDetect() const { return usb_cap; }
  bool hasSolarChargerDetect() const { return solar_cap; }
  bool isUsbPowered() { ++usb_reads; return usb; }
  bool isSolarChargerActive() { ++solar_reads; return solar; }
  bool isExternalPowered() { ++source_reads; return external; }
  bool isChargerActive() { return charger; }
  unsigned getBattMilliVolts() { ++batt_reads; return 4102; }
  unsigned getBootVoltage() { ++boot_reads; return 3991; }
  bool getSystemWatchdogRunning(bool& running) const {
    running=watchdog_running; return watchdog_supported;
  }
};
void commonPower(Board& board, char* reply) {
  auto* _board=&board;
  @COMMON@
}
void expect(Board& board,const char* command,const char* expected) {
  char reply[160];
  assert(mesh::companion::handlePowerDiagnosticsCommand(board,command,reply,sizeof(reply)));
  assert(strcmp(reply,expected)==0);
}
int main() {
  Board board;
  expect(board,"get pwrmgt.support","> unsupported");
  expect(board,"get pwrmgt.source","ERROR: Power management not supported");
  expect(board,"get pwrmgt.bootmv","ERROR: Power management not supported");
  assert(board.source_reads==0 && board.boot_reads==0);
  board.pm=true;
  expect(board,"get pwrmgt.support","> supported");
  expect(board,"get pwrmgt.source","> battery");
  board.external=true;
  expect(board,"get pwrmgt.source","> external");
  expect(board,"get pwrmgt.bootmv","> 3991 mV");
  assert(board.boot_reads==1 && board.batt_reads==0);
  for(unsigned bits=0;bits<64;++bits) {
    board.usb_cap=bits&1;board.solar_cap=bits&2;board.usb=bits&4;
    board.solar=bits&8;board.external=bits&16;board.charger=bits&32;
    board.usb_reads=board.solar_reads=0;
    char actual[160],expected[160];
    assert(mesh::companion::handlePowerDiagnosticsCommand(board,"power",actual,sizeof(actual)));
    assert(board.usb_reads==unsigned(board.usb_cap));
    assert(board.solar_reads==unsigned(board.solar_cap));
    commonPower(board,expected);
    assert(strcmp(actual,expected)==0);
  }
  board.watchdog_supported=true;board.watchdog_running=false;
  expect(board,"get system.watchdog","> off");
  board.watchdog_running=true;expect(board,"get system.watchdog","> on");
  board.watchdog_supported=false;
  expect(board,"get system.watchdog","Error: unsupported on this platform");
  for(const char* command:{"set system.watchdog on","set system.watchdog off","set system.watchdog","set system.watchdog invalid"}) {
    expect(board,command,"Error: system watchdog control is unavailable in Companion");
    assert(board.watchdog_running); // A setter must never pretend to stop it.
  }
}
'''.replace("@COMMON@", common)
        fixture = "#include <initializer_list>\n" + fixture
        self.compile(fixture)

    def test_actual_nrf_reader_reports_hardware_even_with_feeding_disabled(self):
        source = (ROOT / "src/helpers/NRF52Board.cpp").read_text()
        reader = body(source, "bool NRF52Board::getSystemWatchdogRunning(bool& running) const")
        self.assertNotRegex(reader, r"feedWatchdog|serviceWatchdog|TASKS_START|RR\[")
        fixture = r'''
#include <cassert>
#include <cstdint>
struct { volatile uint32_t RUNSTATUS=0; uint32_t untouched=0x1234; } registers;
#define NRF_WDT (&registers)
struct NRF52Board { bool getSystemWatchdogRunning(bool& running) const; };
@READER@
int main() {
  const NRF52Board board;
  bool running=true;
  assert(board.getSystemWatchdogRunning(running) && !running);
  registers.RUNSTATUS=1;
  assert(board.getSystemWatchdogRunning(running) && running);
  registers.RUNSTATUS=2;
  assert(board.getSystemWatchdogRunning(running) && running);
  assert(registers.RUNSTATUS==2 && registers.untouched==0x1234);
}
'''.replace("@READER@", reader)
        self.compile(fixture, ["NRF52_WATCHDOG_TIMEOUT_SECONDS=0"])
        self.compile(fixture, ["NRF52_WATCHDOG_TIMEOUT_SECONDS=60"])

    def test_real_base_defaults_and_nrf_support_scope(self):
        source = (ROOT / "src/MeshCore.h").read_text()
        default_reader = body(source, "virtual bool getSystemWatchdogRunning(bool& running) const")
        default_power = body(source, "virtual bool supportsPowerManagement() const")
        nrf = (ROOT / "src/helpers/NRF52Board.h").read_text()
        nrf_power = body(nrf, "bool supportsPowerManagement() const override")
        preceding = nrf[:nrf.index("bool supportsPowerManagement() const override")]
        active = []
        for directive in re.findall(r"^\s*#\s*(if[^\n]*|endif)\s*$", preceding, re.MULTILINE):
            if directive == "endif": active.pop()
            else: active.append(directive)
        self.assertIn("ifdef NRF52_POWER_MANAGEMENT", active)
        fixture = r'''
#include <cassert>
struct MainBoard {
  @READER@
  @POWER@
};
struct ManagedBoard:MainBoard {
  @NRF_POWER@
};
int main() {
  MainBoard base;ManagedBoard managed;
  bool running=true;
  assert(!base.getSystemWatchdogRunning(running) && running);
  assert(!base.supportsPowerManagement() && managed.supportsPowerManagement());
}
'''.replace("@READER@", default_reader).replace("@POWER@", default_power).replace("@NRF_POWER@", nrf_power)
        self.compile(fixture)

    def test_small_output_buffers_and_unknown_commands(self):
        fixture = r'''
#include <helpers/CompanionPowerDiagnostics.h>
#include <cassert>
#include <initializer_list>
struct Board {
  bool supportsPowerManagement()const{return true;}
  bool hasUsbPowerDetect()const{return true;}
  bool hasSolarChargerDetect()const{return true;}
  bool isUsbPowered(){return true;}
  bool isSolarChargerActive(){return true;}
  bool isExternalPowered(){return true;}
  bool isChargerActive(){return true;}
  unsigned getBattMilliVolts(){return 12345;}
  unsigned getBootVoltage(){return 54321;}
  bool getSystemWatchdogRunning(bool& v)const{v=true;return true;}
};
int main() {
  Board board;
  for(const char* command:{"power","get pwrmgt.support","get pwrmgt.source","get pwrmgt.bootmv","get system.watchdog","set system.watchdog off"}) {
    for(unsigned length=1;length<160;++length) {
      char data[162];memset(data,'z',sizeof(data));
      assert(mesh::companion::handlePowerDiagnosticsCommand(board,command,data+1,length));
      assert(data[0]=='z' && data[length+1]=='z');
      assert(memchr(data+1,0,length)!=nullptr);
    }
  }
  char untouched[8]="stable";
  for(const char* command:{"","get pwrmgt.support.extra","power extra","get system.watchdog off","set system.watchdog.extra off"}) {
    assert(!mesh::companion::handlePowerDiagnosticsCommand(board,command,untouched,sizeof(untouched)));
    assert(strcmp(untouched,"stable")==0);
  }
  assert(!mesh::companion::handlePowerDiagnosticsCommand(board,nullptr,untouched,sizeof(untouched)));
  assert(!mesh::companion::handlePowerDiagnosticsCommand(board,"power",nullptr,sizeof(untouched)));
  assert(!mesh::companion::handlePowerDiagnosticsCommand(board,"power",untouched,0));
}
'''
        self.compile(fixture)


if __name__ == "__main__":unittest.main()
