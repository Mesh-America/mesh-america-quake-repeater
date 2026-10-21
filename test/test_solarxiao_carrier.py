"""Exercise the real carrier selector and adapter with persistence/bus faults."""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import unittest

from test_regulator_settings import FILESYSTEM

ROOT = Path(__file__).resolve().parents[1]
SENSORS = ROOT / "src/helpers/sensors"

# Compile the production NRF52 FilePresence boundary, including the distinction
# between an absent record and failed filesystem metadata. Other file operations
# keep using the shared mock so metadata and full-read faults are independent.
FILESYSTEM_WITH_METADATA = FILESYSTEM.replace(
    "struct MockFS;", "struct MockFS;\nstruct lfs_info {};\nconstexpr int LFS_ERR_NOENT=-2;\n"
    "int lfs_stat(MockFS*,const char*,lfs_info*);"
).replace(
    "unsigned writes=0,renames=0;",
    "unsigned writes=0,renames=0;bool fail_stat=false;\n"
    "  void _lockFS() {}\n  void _unlockFS() {}\n  MockFS* _getFS() {return this;}"
) + r'''
inline int lfs_stat(MockFS* fs,const char* path,lfs_info*) {
  return fs->fail_stat ? -5 : fs->files.count(path) ? 0 : LFS_ERR_NOENT;
}
'''

SELECTOR_HARNESS = r'''
#include "SolarXiaoCarrier.h"
#include <cassert>
#include <cmath>
#include <cstring>
#include <string>
#include <vector>
using namespace mesh::solar;
struct MemoryStore : Store {
  std::vector<uint8_t> bytes;
  bool present=false, available_now=true, fail_load=false;
  bool fail_save=false, publish_before_failure=false;
  unsigned loads=0,saves=0;
  bool available() const override { return available_now; }
  bool exists() const override { return present; }
  bool load(uint8_t* out,size_t n) override {
    ++loads;
    if(fail_load || bytes.size()!=n)return false;
    memcpy(out,bytes.data(),n);return true;
  }
  bool save(const uint8_t* data,size_t n) override {
    ++saves;
    if(!fail_save || publish_before_failure) {bytes.assign(data,data+n);present=true;}
    return !fail_save;
  }
};
std::string cli(CarrierSelection& c,const char* cmd,float mv=3.876f,
                float temp=27.25f,bool history=true) {
  char reply[157]={};
  assert(c.handle(cmd,reply,sizeof(reply),mv,temp,history));return reply;
}
void has(const std::string& text,const char* wanted) {
  assert(text.find(wanted)!=std::string::npos);
}
void blocked(CarrierSelection& c) {
  assert(!c.nativeAllowed() && !c.settingsHealthy() && !c.isAdvanced());
  has(cli(c,"get solar.board"),"unconfirmed");
}
int main(int argc,char** argv) {
  assert(argc==2);const std::string scenario=argv[1];
  if(scenario=="persistence") {
    MemoryStore store;CarrierSelection c(store);
    assert(!c.nativeAllowed());c.begin();
    assert(c.settingsHealthy() && c.nativeAllowed() && !c.isAdvanced());
    assert(!store.loads && !store.saves && !store.present);
    has(cli(c,"get solar.board"),"source=default");
    has(cli(c,"get solar.board"),"not autodetected");
    has(cli(c,"get solar capabilities"),"INA260");assert(!store.saves);
    has(cli(c,"set solar.board advanced"),"OK");
    assert(c.isAdvanced() && !c.nativeAllowed() && store.saves==1);
    assert(store.bytes.size()==CarrierSelection::IMAGE_SIZE);
    CarrierSelection restarted(store);restarted.begin();
    assert(restarted.isAdvanced() && !restarted.nativeAllowed());
    has(cli(restarted,"get solar.board"),"source=saved");
    has(cli(restarted,"get solar info"),"BQ24650");
    has(cli(restarted,"get solar capabilities"),"unwired");
    assert(store.saves==1);
    has(cli(restarted,"set solar.board mppt"),"retained charger overrides");
    CarrierSelection mppt(store);mppt.begin();
    assert(mppt.nativeAllowed() && !mppt.isAdvanced());
    has(cli(mppt,"get solar.board"),"mppt source=saved");
  } else if(scenario=="invalid-records") {
    MemoryStore reference;CarrierSelection baseline(reference);baseline.begin();
    cli(baseline,"set solar.board advanced");const auto valid=reference.bytes;
    for(size_t byte=0;byte<valid.size();++byte) {
      MemoryStore store;store.present=true;store.bytes=valid;store.bytes[byte]^=0x40;
      CarrierSelection c(store);c.begin();blocked(c);assert(!store.saves);
    }
    for(size_t size=0;size<=10;++size) {
      if(size==valid.size())continue;
      MemoryStore store;store.present=true;store.bytes=valid;store.bytes.resize(size);
      CarrierSelection c(store);c.begin();blocked(c);assert(!store.saves);
    }
    MemoryStore store;store.present=true;store.bytes=valid;store.fail_load=true;
    CarrierSelection c(store);c.begin();blocked(c);
    store.fail_load=false;cli(c,"set solar.board advanced");assert(c.isAdvanced());
    store.available_now=false;c.begin();blocked(c);
    const unsigned saves=store.saves;has(cli(c,"set solar.board mppt"),"unconfirmed");
    assert(store.saves==saves);blocked(c);
    store.available_now=true;c.begin();assert(c.isAdvanced());
  } else if(scenario=="save-failures") {
    for(bool published:{false,true}) {
      MemoryStore store;CarrierSelection c(store);c.begin();
      store.fail_save=true;store.publish_before_failure=published;
      has(cli(c,"set solar.board advanced"),"native access blocked");blocked(c);
      assert(store.present==published);
      store.fail_save=false;
      has(cli(c,"set solar.board advanced"),"OK");assert(c.isAdvanced());
      store.fail_save=true;store.publish_before_failure=published;
      has(cli(c,"set solar.board mppt"),"unconfirmed");blocked(c);
      assert(store.bytes[4]==(published?0:1));
      store.fail_save=false;
      cli(c,"set solar.board mppt");assert(c.nativeAllowed());
    }
  } else if(scenario=="readings-history") {
    MemoryStore store;CarrierSelection c(store);c.begin();cli(c,"set solar.board advanced");
    has(cli(c,"get solar readings"),"battery=3.876V MCU=27.25C");
    has(cli(c,"get solar battery"),"processor");
    has(cli(c,"get solar readings"),"self channel=1");
    for(float value:{NAN,INFINITY,-INFINITY}) {
      has(cli(c,"get solar readings",value,value),"battery=unavailable MCU=unavailable");
    }
    for(float value:{0.0f,-1.0f})
      has(cli(c,"get solar battery",value,-15.5f),"battery=unavailable MCU=-15.50C");
    has(cli(c,"get solar history"),"get telemetry.volt [1-7]");
    has(cli(c,"get solar history"),"30min samples, 7d RAM history");
    has(cli(c,"get solar history",3.8f,25,false),"not included");
    store.fail_load=true;c.begin();blocked(c);
    has(cli(c,"get solar readings"),"3.876V");
    has(cli(c,"get solar history",3.8f,25,false),"not included");
  } else if(scenario=="parser-bounds") {
    MemoryStore store;CarrierSelection c(store);c.begin();char reply[157]={};
    for(const char* unrelated:{"", "get solarpanel", "get solar.boardextra",
        "set solar.boardextra advanced", "get mppt", "get SOLAR", "solar"}) {
      assert(!c.handle(unrelated,reply,sizeof(reply),3.8f,25,true));
    }
    for(const char* invalid:{"set solar.board", "set solar.board auto",
        "set solar.board ADVANCED", "set solar.board advanced extra",
        "set solar.board advanced ", "get solar unknown"}) {
      has(cli(c,invalid),"Err");assert(!store.saves && c.nativeAllowed());
    }
    assert(!c.handle(nullptr,reply,sizeof(reply),3.8f,25,true));
    assert(!c.handle("get solar",nullptr,sizeof(reply),3.8f,25,true));
    assert(!c.handle("get solar",reply,0,3.8f,25,true));
    for(const char* cmd:{"get solar", "get solar info", "get solar.board",
        "get solar capabilities", "get solar readings", "get solar battery",
        "get solar history", "set solar.board advanced", "set solar.board mppt"}) {
      for(size_t capacity=1;capacity<=157;++capacity) {
        std::vector<char> guarded(capacity+16,'~');
        char* out=guarded.data()+8;
        assert(c.handle(cmd,out,capacity,NAN,NAN,true));
        for(size_t i=0;i<8;++i)assert(guarded[i]=='~' && guarded[8+capacity+i]=='~');
        assert(memchr(out,0,capacity)!=nullptr);
      }
    }
  } else assert(false);
}
'''

SENSOR_MANAGER = r'''
#pragma once
#include <cstdint>
#include <vector>
#include <cmath>
struct CayenneLPP {
  std::vector<uint8_t> channels;
  void addVoltage(uint8_t c,float) {channels.push_back(c);}
  void addCurrent(uint8_t c,float) {channels.push_back(c);}
  void addPower(uint8_t c,float) {channels.push_back(c);}
  void addTemperature(uint8_t c,float) {channels.push_back(c);}
  void addGenericSensor(uint8_t c,float) {channels.push_back(c);}
};
namespace mesh {
struct MainBoard {
  uint16_t battery_mv=3850;float mcu_c=26.75f;
  unsigned battery_reads=0,temperature_reads=0;
  uint16_t getBattMilliVolts() {++battery_reads;return battery_mv;}
  float getMCUTemperature() {++temperature_reads;return mcu_c;}
};
struct SensorManager {
  struct VoltageSensorReading {uint8_t channel;float voltage;bool valid;};
};
}
'''

WIRE = r'''
#pragma once
#include <cassert>
#include <cstdint>
#include <vector>
struct FakeWire {
  uint16_t charger[256]={},ina[256]={};
  unsigned calls=0,reads=0,writes=0;
  uint8_t address=0,reg=0;size_t cursor=0;
  std::vector<uint8_t> tx,rx;
  FakeWire() {
    charger[0x43]=0x46b4;charger[0x14]=2;charger[0x29]=1;
    charger[0x4a]=1;charger[0x39]=7;charger[0x34]=256;
    charger[0x3a]=17152;charger[0x3b]=8000;charger[0x3c]=7985;
    charger[0x3d]=uint16_t(-100);charger[0x3e]=200;
    charger[0x3f]=14000;charger[0x40]=10914;
    ina[0xfe]=0x5449;ina[0xff]=0x2270;
    ina[2]=10560;ina[1]=uint16_t(-8);ina[3]=13;
  }
  void beginTransmission(uint8_t a) {assert(a==0x68 || a==0x40);address=a;++calls;tx.clear();}
  void write(uint8_t b) {tx.push_back(b);}
  int endTransmission(bool stop=true) {
    assert(!tx.empty());reg=tx[0];
    if(stop && tx.size()==3) {
      assert(address==0x68);++writes;charger[reg]=tx[1]|(uint16_t(tx[2])<<8);
    }
    return 0;
  }
  int requestFrom(uint8_t a,uint8_t n) {
    assert(a==address && n==2);++reads;cursor=0;
    const uint16_t value=(a==0x68?charger:ina)[reg];
    rx={uint8_t(a==0x68?value:value>>8),uint8_t(a==0x68?value>>8:value)};
    return 2;
  }
  int available() {return int(rx.size()-cursor);}
  int read() {return cursor<rx.size()?rx[cursor++]:-1;}
};
extern FakeWire Wire;
'''

ADAPTER_HARNESS = r'''
#include <cassert>
#include <cmath>
#include <cstring>
#include <string>
#include <algorithm>
#include <helpers/IdentityStore.h>
#include <helpers/SensorManager.h>
#include <Wire.h>
#define ATOMIC_FILE_WRITER_IMPLEMENTATION
static uint32_t now_ms=100;
uint32_t millis() {return now_ms;}
int digitalRead(int pin) {assert(pin==30 || pin==31);return 1;}
FakeWire Wire;
#include "@ADAPTER@"
using namespace mesh;
using namespace mesh::solar;
std::string cli(const char* command) {
  char reply[157]={};assert(handleCommand(command,reply,sizeof(reply),false));return reply;
}
void has(const std::string& text,const char* wanted) {
  assert(text.find(wanted)!=std::string::npos);
}
void nativeSilent() {
  const auto calls=Wire.calls,reads=Wire.reads,writes=Wire.writes;
  for(const char* command:{"get mppt", "get mppt info", "get mppt battery",
      "get mppt raw 0x43", "get mppt fields 0", "set mppt mppt.enabled off",
      "mppt reload", "mppt reset", "mppt bsr run", "mppt ship arm",
      "mppt alerts clear limits 65535"}) has(cli(command),"Err");
  service();now_ms+=10000;service();
  CayenneLPP lpp;addTelemetry(lpp);assert(lpp.channels.empty());
  uint8_t channels[]={99,99,99,99,99};
  SensorManager::VoltageSensorReading values[5];
  for(auto& value:values)value={99,99,true};
  assert(!voltageChannels(channels,5));assert(!queryVoltages(values,5));
  assert(!voltageChannels(nullptr,0));assert(!queryVoltages(nullptr,0));
  for(auto c:channels)assert(c==99);
  for(auto value:values)assert(value.channel==99 && value.voltage==99 && value.valid);
  assert(calls==Wire.calls && reads==Wire.reads && writes==Wire.writes);
}
int main(int argc,char** argv) {
  assert(argc==2);const std::string scenario=argv[1];MockFS fs;MainBoard board;
  if(scenario=="advanced-runtime") {
    beginSettings(board,&fs,MESH_ENABLE_TELEMETRY_HISTORY);assert(!Wire.calls);
    has(cli("set solar.board advanced"),"OK");nativeSilent();
    assert(fs.exists("/solar_board") && !fs.exists("/solar_power"));
    const auto calls=Wire.calls;
    has(cli("get solar readings"),"battery=3.850V MCU=26.75C");
    assert(board.battery_reads==1 && board.temperature_reads==1);
    board.battery_mv=3991;board.mcu_c=-12.5f;
    has(cli("get solar battery"),"battery=3.991V MCU=-12.50C");
    assert(board.battery_reads==2 && board.temperature_reads==2);
    has(cli("get solar info"),"BQ24650");has(cli("get solar capabilities"),"unwired");
    has(cli("get solar history"),MESH_ENABLE_TELEMETRY_HISTORY?"30min":"not included");
    assert(board.battery_reads==2 && board.temperature_reads==2 && calls==Wire.calls);
    beginSettings(board,&fs,MESH_ENABLE_TELEMETRY_HISTORY);has(cli("get solar.board"),"advanced source=saved");nativeSilent();
    board.battery_mv=0;board.mcu_c=NAN;
    has(cli("get solar readings"),"battery=unavailable MCU=unavailable");
  } else if(scenario=="invalid-runtime") {
    fs.files["/solar_board"]={'b','a','d'};beginSettings(board,&fs,MESH_ENABLE_TELEMETRY_HISTORY);assert(!Wire.calls);
    nativeSilent();has(cli("get solar.board"),"unconfirmed");
    has(cli("get solar readings"),"3.850V");assert(board.battery_reads==1);
    has(cli("set solar.board advanced"),"OK");nativeSilent();
    beginSettings(board,nullptr,MESH_ENABLE_TELEMETRY_HISTORY);nativeSilent();has(cli("get solar.board"),"unconfirmed");
    has(cli("set solar.board mppt"),"unconfirmed");nativeSilent();
    has(cli("get solar battery"),"3.850V");
  } else if(scenario=="reenable-reload") {
    beginSettings(board,&fs,MESH_ENABLE_TELEMETRY_HISTORY);has(cli("set solar.board advanced"),"OK");nativeSilent();
    Settings overrides;overrides.defaults();overrides.masks[0x14]=2;overrides.values[0x14]=0;
    uint8_t image[Settings::IMAGE_SIZE];overrides.encode(image);
    fs.files["/solar_power"]=std::vector<uint8_t>(image,image+sizeof(image));
    const auto calls=Wire.calls;
    has(cli("set solar.board mppt"),"retained charger overrides");
    assert(Wire.calls==calls && !Wire.writes);
    service();assert(Wire.calls>calls && Wire.writes==1 && !(Wire.charger[0x14]&2));
    has(cli("get mppt info"),"FST");
    CayenneLPP lpp;addTelemetry(lpp);assert(!lpp.channels.empty());
    assert(std::find(lpp.channels.begin(),lpp.channels.end(),2)!=lpp.channels.end());
    assert(std::find(lpp.channels.begin(),lpp.channels.end(),13)!=lpp.channels.end());
    uint8_t channels[5]={99,99,99,99,99};
    SensorManager::VoltageSensorReading values[5];values[4].channel=99;
    assert(voltageChannels(channels,5)==4 && queryVoltages(values,5)==4);
    for(unsigned i=0;i<4;++i)assert(channels[i]==i+2 && values[i].channel==i+2);
    assert(values[0].valid && fabs(values[0].voltage-13.2f)<0.001f);
    assert(channels[4]==99 && values[4].channel==99);
    has(cli("set solar.board advanced"),"OK");nativeSilent();
    assert(fs.files["/solar_power"]==std::vector<uint8_t>(image,image+sizeof(image)));
  } else if(scenario=="selection-store-faults") {
    beginSettings(board,&fs,MESH_ENABLE_TELEMETRY_HISTORY);has(cli("set solar.board advanced"),"OK");
    const auto advanced=fs.files["/solar_board"];
    fs.fail_write=true;has(cli("set solar.board mppt"),"unconfirmed");nativeSilent();
    assert(fs.files["/solar_board"]==advanced);fs.fail_write=false;
    cli("set solar.board advanced");
    fs.fail_rename_from="/solar_board.tmp";
    has(cli("set solar.board mppt"),"unconfirmed");nativeSilent();
    assert(fs.files["/solar_board"]==advanced);fs.fail_rename_from.clear();
    cli("set solar.board advanced");fs.corrupt_write=true;
    has(cli("set solar.board mppt"),"unconfirmed");nativeSilent();
    assert(fs.files["/solar_board"]==advanced);fs.corrupt_write=false;
    cli("set solar.board advanced");fs.fail_read_path="/solar_board";
    has(cli("set solar.board mppt"),"unconfirmed");nativeSilent();
    assert(fs.files["/solar_board"]!=advanced);fs.fail_read_path.clear();
    has(cli("set solar.board advanced"),"OK");nativeSilent();
    beginSettings(board,&fs,MESH_ENABLE_TELEMETRY_HISTORY);assert(selection.isAdvanced());nativeSilent();
  } else if(scenario=="metadata-faults") {
    fs.fail_stat=true;
    beginSettings(board,&fs,MESH_ENABLE_TELEMETRY_HISTORY);
    has(cli("get solar.board"),"unconfirmed");nativeSilent();
    has(cli("set solar.board advanced"),"OK");nativeSilent();
    beginSettings(board,&fs,MESH_ENABLE_TELEMETRY_HISTORY);
    has(cli("get solar.board"),"advanced source=saved");nativeSilent();
    fs.fail_read_path="/solar_board";
    beginSettings(board,&fs,MESH_ENABLE_TELEMETRY_HISTORY);
    has(cli("get solar.board"),"unconfirmed");nativeSilent();
    fs.fail_read_path.clear();
    has(cli("set solar.board advanced"),"OK");nativeSilent();
    fs.files["/solar_board"][0]^=1;
    beginSettings(board,&fs,MESH_ENABLE_TELEMETRY_HISTORY);
    has(cli("get solar.board"),"unconfirmed");nativeSilent();
  } else assert(false);
}
'''


class SolarXiaoCarrierTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.compiler = os.environ.get("CXX") or shutil.which("g++") or shutil.which("clang++")
        if not cls.compiler:
            raise unittest.SkipTest("host C++11 compiler unavailable")
        cls.temp = tempfile.TemporaryDirectory(prefix="solarxiao-carrier-test-")
        cls.addClassCleanup(cls.temp.cleanup)
        directory = Path(cls.temp.name)
        (directory / "helpers").mkdir()
        (directory / "helpers/IdentityStore.h").write_text(FILESYSTEM_WITH_METADATA, encoding="ascii")
        (directory / "helpers/SensorManager.h").write_text(SENSOR_MANAGER, encoding="ascii")
        (directory / "Wire.h").write_text(WIRE, encoding="ascii")
        cls.binaries = {}
        for name, harness, flags, extra in (
            ("selector", SELECTOR_HARNESS, [], []),
            ("adapter-history", ADAPTER_HARNESS, ["-DNRF52_PLATFORM", "-DMESH_ENABLE_TELEMETRY_HISTORY=1",
                "-DHIGH=1", "-DPIN_BOARD_SDA=30", "-DPIN_BOARD_SCL=31"],
                [str(SENSORS / "SolarXiaoPowerCore.cpp")]),
            ("adapter-no-history", ADAPTER_HARNESS, ["-DNRF52_PLATFORM", "-DMESH_ENABLE_TELEMETRY_HISTORY=0",
                "-DHIGH=1", "-DPIN_BOARD_SDA=30", "-DPIN_BOARD_SCL=31"],
                [str(SENSORS / "SolarXiaoPowerCore.cpp")]),
        ):
            cpp = directory / (name + ".cpp")
            cpp.write_text(harness.replace("@ADAPTER@", str(SENSORS / "SolarXiaoPower.cpp")), encoding="ascii")
            binary = directory / name
            built = subprocess.run([cls.compiler, "-std=c++11", "-Wall", "-Wextra", "-Werror",
                "-fsanitize=address,undefined", "-fno-sanitize-recover=all", "-fno-pie", "-no-pie",
                "-DMESH_SOLARXIAO_POWER=1", *flags, "-I" + str(directory),
                "-I" + str(ROOT / "src"), "-I" + str(SENSORS), str(cpp),
                str(SENSORS / "SolarXiaoCarrier.cpp"), *extra, "-o", str(binary)],
                text=True, capture_output=True, timeout=45)
            if built.returncode:
                raise AssertionError(built.stdout + built.stderr)
            cls.binaries[name] = binary

    def run_scenario(self, binary, scenario):
        result = subprocess.run([str(self.binaries[binary]), scenario], capture_output=True,
                                text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_explicit_selection_and_restart_persistence(self):
        self.run_scenario("selector", "persistence")

    def test_corrupt_missing_and_unreadable_records_fail_closed(self):
        self.run_scenario("selector", "invalid-records")

    def test_ambiguous_publication_requires_explicit_recovery(self):
        self.run_scenario("selector", "save-failures")

    def test_unavailable_measurements_and_history_build_capability(self):
        self.run_scenario("selector", "readings-history")

    def test_command_boundaries_and_every_reply_capacity(self):
        self.run_scenario("selector", "parser-bounds")

    def test_actual_advanced_adapter_has_no_native_io_and_live_self_readings(self):
        for binary in ("adapter-history", "adapter-no-history"):
            with self.subTest(binary=binary):
                self.run_scenario(binary, "advanced-runtime")

    def test_actual_adapter_blocks_native_io_with_unconfirmed_selection(self):
        self.run_scenario("adapter-history", "invalid-runtime")

    def test_mppt_reenable_reloads_retained_policy_and_restores_telemetry(self):
        self.run_scenario("adapter-history", "reenable-reload")

    def test_actual_selection_store_write_rename_checksum_and_public_read_faults(self):
        self.run_scenario("adapter-history", "selection-store-faults")

    def test_history_capability_is_passed_from_the_role_translation_unit(self):
        adapter = (SENSORS / "SolarXiaoPower.cpp").read_text(encoding="ascii")
        self.assertNotRegex(adapter, r"(?m)^\s*#\s*(?:if|ifdef|ifndef)\b[^\n]*MESH_ENABLE_TELEMETRY_HISTORY")
        role = (ROOT / "examples/simple_repeater/main.cpp").read_text(encoding="ascii")
        self.assertRegex(role, r"mesh::solar::beginSettings\(board,\s*regulator_prefs_fs,\s*MESH_ENABLE_TELEMETRY_HISTORY")

    def test_metadata_errors_require_a_valid_full_record_or_block_native_access(self):
        self.run_scenario("adapter-history", "metadata-faults")


if __name__ == "__main__":
    unittest.main()
