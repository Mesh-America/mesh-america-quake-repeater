"""Exercise the shipping charger core with fault-injected I2C and persistence."""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import unittest

from test_replay_reset_integration import extract_braced

ROOT = Path(__file__).resolve().parents[1]
HARNESS = r'''
#include "SolarXiaoPowerCore.h"
#include <cassert>
#include <cmath>
#include <cstring>
#include <string>
#include <vector>
using namespace mesh::solar;
struct FakeBus : Bus {
  uint16_t r[256]={}, ina[256]={};
  bool online=true, fail_write=false, ignore_write=false;
  int read_fail=-1;
  struct Write {unsigned reg, value;};
  std::vector<Write> writes;
  FakeBus() {
    r[0x43]=0x46b4; r[0x14]=2; r[0x29]=1;
    r[16]=16019; r[17]=17414; r[0x1a]=31; r[0x1b]=15;
    r[0x4a]=1; r[0x39]=7; r[0x34]=256;
    r[0x3a]=17152; r[0x3b]=8000; r[0x3c]=7985;
    r[0x3d]=uint16_t(-100); r[0x3e]=200; r[0x3f]=14000;
    r[0x40]=10914; r[0x41]=10;
    ina[0xfe]=0x5449; ina[0xff]=0x2270;
    ina[2]=10560; ina[1]=uint16_t(-8); ina[3]=13;
  }
  bool read(uint8_t addr,uint8_t reg,uint16_t& word) override {
    assert(addr==0x68 || addr==0x40);
    if (!online || int(reg)==read_fail) return false;
    word=(addr==0x68?r:ina)[reg]; return true;
  }
  bool write(uint8_t addr,uint8_t reg,uint16_t word) override {
    assert(addr==0x68); writes.push_back({reg,word});
    if (fail_write) return false;
    if (ignore_write) return true;
    if(reg>=0x36 && reg<=0x38) r[reg]&=word;
    else r[reg]=word;
    return true;
  }
};
struct FakeStore : Store {
  std::vector<uint8_t> bytes;
  bool writable=true, failed=false;
  int saves=0;
  bool available() const override {return writable;}
  bool exists() const override {return !bytes.empty();}
  bool load(uint8_t* data,size_t n) override {
    if(bytes.size()!=n) return false;
    memcpy(data,bytes.data(),n);return true;
  }
  bool save(const uint8_t* data,size_t n) override {
    ++saves; if(failed)return false;
    bytes.assign(data,data+n);return true;
  }
};
std::string cli(Controller& c,const char* cmd,bool local=true) {
  struct Guard {char a[3]; char reply[157]; char z[3];} g;
  memset(&g,0x5a,sizeof(g));
  assert(c.handle(cmd,g.reply,sizeof(g.reply),local));
  assert(g.a[0]==0x5a && g.a[2]==0x5a && g.z[0]==0x5a && g.z[2]==0x5a);
  assert(memchr(g.reply,0,sizeof(g.reply)));
  return g.reply;
}
void has(const std::string& s,const char* part) {assert(s.find(part)!=std::string::npos);}
void close(double got,double expected) {assert(fabs(got-expected)<0.0002);}
int main(int argc,char** argv) {
  assert(argc==2); std::string test=argv[1];
  FakeBus bus;FakeStore store;Controller c(bus,store);c.begin();
  if(test=="readings") {
    Snapshot s;assert(c.snapshot(s)); assert(s.charger && s.monitor && s.adc_active);
    close(s.battery_v,13.2);close(s.battery_a,-0.01);close(s.battery_w,0.13);
    close(s.vin_v,13.192);close(s.charger_vbat_v,13.2001792);
    close(s.ibat_a,-0.01466);close(s.iin_a,0.02932);close(s.die_c,36.6);
    assert(fabs(s.ntc_c-25)<0.02);close(s.bsr_ohm,0.0008);
    bus.r[0x4a]=3;c.snapshot(s);assert(std::isnan(s.bsr_ohm));
    bus.r[0x43]=0x06b0;c.snapshot(s);assert(s.cells==0 && c.lastCellCount()==4);
    assert(std::isnan(s.charger_vbat_v));has(cli(c,"get mppt battery.mv"),"unknown cells");
    bus.r[0x39]=0;c.snapshot(s);assert(!s.adc_active && std::isnan(s.vin_v));
    has(cli(c,"get mppt input.mv"),"ADC inactive");
    bus.r[0x14]|=4;c.snapshot(s);assert(s.adc_active);
    bus.r[0x40]=21684;c.snapshot(s);assert(std::isnan(s.ntc_c));
    bus.ina[0xff]=0x227f;c.snapshot(s);assert(s.monitor);
    bus.ina[0xff]=0x2260;c.snapshot(s);assert(!s.monitor);
    assert(bus.writes.empty() && store.saves==0);
  } else if(test=="defaults-identity") {
    c.service(0);c.service(5000);assert(bus.writes.empty());
    for(unsigned id: {0x0101u,0x0404u,0x0603u,0x0704u,0x0f04u}) {
      bus.r[0x43]=id;has(cli(c,"set mppt telemetry.fast on"),"Err -");
      c.service(10000+id);assert(bus.writes.empty());
    }
    bus.r[0x43]=0x06b0;has(cli(c,"set mppt telemetry.fast on"),"OK -");
    assert(bus.r[0x14]==10);
    bus.online=false;has(cli(c,"set mppt telemetry.fast off"),"unavailable");
  } else if(test=="locks-ranges") {
    for(const char* cmd: {"set mppt cells 3","set mppt chemistry 4",
      "set mppt jeita.t1_raw 123","set mppt jeita.voltages_432 123",
      "set mppt absorb.seconds 500","set mppt recharge.mv 13000",
      "set mppt input.limit_ma nan","set mppt input.limit_ma inf",
      "set mppt input.limit_ma -1","set mppt input.limit_ma 10",
      "set mppt input.limit_ma 3201","set mppt charge.cell_mv 3650",
      "set mppt charge.current_ma 2000","set mppt charge.cell_mv 3550",
      "set mppt input.minimum_mv 14000","set mppt telemetry.fast 1",
      "set mppt thermal.start_c 126","set mppt thermal.start_c 120",
      "set mppt thermal.end_c 70","set mppt termination.current_ma -1",
      "set mppt alert.limits_mask 0x1000","set mppt state 0",
      "set mppt telemetry.fast on extra"}) {
      has(cli(c,cmd),"Err -");assert(bus.writes.empty());
    }
    bus.r[0x43]=0x0600;
    has(cli(c,"set mppt alert.battery_low_mv 12000"),"unknown");assert(bus.writes.empty());
    assert(store.saves==0);
  } else if(test=="rounding-rmw") {
    bus.r[0x14]=0x8052;
    has(cli(c,"set mppt telemetry.fast on"),"readback verified");
    assert(bus.r[0x14]==0x804a); // preserve other bits; never replay run_bsr.
    has(cli(c,"set mppt input.limit_ma 1234"),"1200");assert(bus.r[0x15]==23);
    has(cli(c,"set mppt mppt.enabled off"),"OK -");
    has(cli(c,"set mppt input.minimum_mv 13000"),"13078.1");assert(bus.r[0x16]==92);
    has(cli(c,"set mppt jeita.enabled off"),"OK -");
    has(cli(c,"set mppt charge.current_ma 1540"),"1500");assert(bus.r[0x1a]==14);
    has(cli(c,"set mppt charge.cell_mv 3558"),"3550");assert(bus.r[0x1b]==11);
    has(cli(c,"set mppt thermal.start_c 80"),"OK -");
    has(cli(c,"set mppt thermal.end_c 115"),"OK -");
    has(cli(c,"set mppt termination.current_ma 200"),"OK -");
  } else if(test=="persistence-order") {
    has(cli(c,"set mppt telemetry.force on"),"OK -");
    has(cli(c,"set mppt jeita.enabled off"),"OK -");
    has(cli(c,"set mppt charge.current_ma 1000"),"OK -");
    has(cli(c,"set mppt thermal.end_c 125"),"OK -");
    has(cli(c,"set mppt thermal.start_c 115"),"OK -");
    has(cli(c,"set mppt charge.enabled off"),"OK -");
    bus.r[0x14]=2;bus.r[0x29]=1;bus.r[0x1a]=31;bus.r[16]=16019;bus.r[17]=17414;
    bus.writes.clear();Controller fresh(bus,store);fresh.begin();fresh.service(0xfffffff0);
    assert(bus.writes[0].reg==0x14 && (bus.writes[0].value&0x20));
    assert(bus.writes[1].reg==17 && bus.writes[2].reg==16);
    assert(bus.r[0x29]==0 && bus.r[0x1a]==9 && bus.r[0x14]==38);
    assert(fresh.settingsApplied());size_t count=bus.writes.size();fresh.service(20);
    assert(bus.writes.size()==count);fresh.service(5000);assert(bus.writes.size()==count);
    has(cli(fresh,"set mppt jeita.enabled on"),"OK -");
    bus.r[0x1a]=31;count=bus.writes.size();fresh.service(10000);assert(bus.writes.size()==count);
    has(cli(fresh,"mppt forget"),"live charger unchanged");
    bus.r[0x14]=2;fresh.service(15000);assert(bus.r[0x14]==2);
  } else if(test=="faults") {
    bus.ignore_write=true;has(cli(c,"set mppt telemetry.fast on"),"write/readback failed");
    assert(store.saves==0 && bus.r[0x14]==2);
    bus.ignore_write=false;store.failed=true;
    has(cli(c,"set mppt telemetry.fast on"),"rollback=verified");
    assert(bus.r[0x14]==2 && !c.settingsHealthy());
    size_t count=bus.writes.size();c.service(0);assert(bus.writes.size()==count);
    has(cli(c,"set mppt telemetry.fast on"),"storage unavailable");
    store.failed=false;has(cli(c,"mppt reload"),"OK -");
    has(cli(c,"set mppt telemetry.fast on"),"OK -");
    bus.read_fail=0x14;has(cli(c,"set mppt telemetry.fast off"),"read failed");
    bus.read_fail=-1;bus.fail_write=true;
    has(cli(c,"set mppt telemetry.fast off"),"rollback=verified");
  } else if(test=="record-validation") {
    Settings s;s.defaults();uint8_t image[Settings::IMAGE_SIZE];s.encode(image);
    Settings got;assert(got.decode(image));image[23]^=1;assert(!got.decode(image));
    for(int type=0;type<6;++type) {
      s.defaults();
      if(type==0){s.masks[0x43%Settings::REG_COUNT]=1;} // reserved/non-writable
      if(type==1){s.masks[0x14]=16;s.values[0x14]=16;}
      if(type==2){s.masks[16]=0xffff;s.values[16]=1;}
      if(type==3){s.rsnsb_mohm=NAN;}
      if(type==4){s.masks[0x1c]=0xffff;s.values[0x1c]=0xffff;}
      if(type==5){s.masks[0x1b]=31;s.values[0x1b]=31;}
      s.encode(image);assert(!got.decode(image));
    }
    store.bytes.assign(10,0);Controller bad(bus,store);bad.begin();bad.service(0);
    assert(!bad.settingsHealthy() && bus.writes.empty());
    has(cli(bad,"set mppt telemetry.force on"),"storage unavailable");
    has(cli(bad,"mppt reset",false),"local USB");
    has(cli(bad,"mppt reset"),"OK -");assert(bad.settingsHealthy());
    has(cli(bad,"set mppt cal.rsnsb_mohm 20"),"saved");
    has(cli(bad,"get mppt cal.rsnsb_mohm"),"source=user");
    Controller after(bus,store);after.begin();close(after.configuration().rsnsb_mohm,20);
  } else if(test=="actions-parser") {
    assert(!c.handle("get mpptish",nullptr,0,true));
    for(int i=0;i<40;++i) {std::string cmd="get mppt fields "+std::to_string(i);cli(c,cmd.c_str());}
    has(cli(c,"get mppt fields -1"),"Err -");
    has(cli(c,"get mppt raw 0x43"),"46B4");has(cli(c,"get mppt raw 0x12"),"Err -");
    has(cli(c,"mppt ship arm",false),"local USB");assert(bus.writes.empty());
    has(cli(c,"mppt bsr run"),"not saved");assert(bus.writes.back().value==18);
    has(cli(c,"mppt ship arm"),"not saved");assert(bus.writes.back().value==21325);
    has(cli(c,"mppt ship disarm"),"not saved");assert(bus.writes.back().value==0);
    bus.r[0x36]=0xcfff;has(cli(c,"mppt alerts clear limits 0x20"),"OK -");
    assert(bus.writes.back().value==0xffdf && bus.r[0x36]==0xcfdf);
    has(cli(c,"mppt alerts clear limits 0x1000"),"Err -");assert(store.saves==0);
  } else return 2;
}
'''


class SolarXiaoPowerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="solarxiao-power-test-")
        cls.addClassCleanup(cls.temp.cleanup)
        directory = Path(cls.temp.name)
        cpp = directory / "test.cpp"
        cpp.write_text(HARNESS, encoding="ascii")
        cls.binary = directory / "test"
        compiler = os.environ.get("CXX") or shutil.which("g++")
        assert compiler, "host C++11 compiler required"
        subprocess.run([compiler, "-std=c++11", "-Wall", "-Wextra", "-Werror",
            "-fsanitize=address,undefined", "-fno-sanitize-recover=all", "-fno-pie", "-no-pie",
            "-DMESH_SOLARXIAO_POWER=1", "-I" + str(ROOT / "src/helpers/sensors"),
            str(cpp), str(ROOT / "src/helpers/sensors/SolarXiaoPowerCore.cpp"),
            "-o", str(cls.binary)], check=True, capture_output=True, text=True, timeout=30)

    def test_shipping_core(self):
        for scenario in ("readings", "defaults-identity", "locks-ranges", "rounding-rmw",
                         "persistence-order", "faults", "record-validation", "actions-parser"):
            with self.subTest(scenario=scenario):
                result = subprocess.run([str(self.binary), scenario], capture_output=True,
                                        text=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


class SolarXiaoTelemetryIntegrationTests(unittest.TestCase):
    def test_permissions_and_stable_voltage_channels(self):
        source = (ROOT / "src/helpers/sensors/EnvironmentSensorManager.cpp").read_text()
        methods = "\n".join(extract_braced(source, prefix) for prefix in (
            "bool EnvironmentSensorManager::querySensors(",
            "uint8_t EnvironmentSensorManager::getVoltageSensorChannels(",
            "uint8_t EnvironmentSensorManager::queryVoltageSensors("))
        harness = r'''#include <cassert>
#include <cstdint>
#include <cmath>
using std::isfinite;
#define TELEM_CHANNEL_SELF 1
#define TELEM_PERM_ENVIRONMENT 4
struct CayenneLPP {};
struct SensorManager { struct VoltageSensorReading {uint8_t channel;float voltage;bool valid;}; };
int native_queries=0, optional_queries=0;
namespace mesh { namespace solar {
constexpr uint8_t FIRST_OPTIONAL_CHANNEL=14;
void addTelemetry(CayenneLPP&) {++native_queries;}
uint8_t voltageChannels(uint8_t* ch,uint8_t cap) {
  const uint8_t n=cap<4?cap:4;for(uint8_t i=0;ch && i<n;++i)ch[i]=2+i;return n;
}
uint8_t queryVoltages(SensorManager::VoltageSensorReading* r,uint8_t cap) {
  const uint8_t n=cap<4?cap:4;
  for(uint8_t i=0;i<n;++i)r[i]={uint8_t(2+i),13.2f,i==0};return n;
}
}}
void optional(uint8_t ch,uint8_t,CayenneLPP&) {
  ++optional_queries;assert(ch==(MESH_SOLARXIAO_POWER?14:2));
}
bool optional_voltage(uint8_t,float& voltage) {voltage=5;return true;}
class EnvironmentSensorManager:public SensorManager {
  struct ActiveSensor {void(*query)(uint8_t,uint8_t,CayenneLPP&);bool(*query_voltage)(uint8_t,float&);uint8_t sub_channel;};
  ActiveSensor _active_sensors[1]={{optional,optional_voltage,0}};
  int _active_sensor_count=1;uint8_t next_available_channel=2;
public:
 bool querySensors(uint8_t,CayenneLPP&);
 uint8_t getVoltageSensorChannels(uint8_t*,uint8_t) const;
 uint8_t queryVoltageSensors(VoltageSensorReading*,uint8_t);
};
@METHODS@
int main() {
 EnvironmentSensorManager env;CayenneLPP lpp;
 env.querySensors(0,lpp);assert(!native_queries && !optional_queries);
 env.querySensors(4,lpp);assert(native_queries==MESH_SOLARXIAO_POWER && optional_queries==1);
 const int all=MESH_SOLARXIAO_POWER?5:1;
 for(int cap=0;cap<7;++cap) {
  uint8_t ch[8];for(auto& c:ch)c=255;
  SensorManager::VoltageSensorReading r[8];for(auto& item:r)item.channel=255;
  int n=cap<all?cap:all;
  assert(env.getVoltageSensorChannels(ch,cap)==n);
  assert(env.queryVoltageSensors(r,cap)==n);
  for(int i=0;i<n;++i) {
   int expected=MESH_SOLARXIAO_POWER && i<4?2+i:MESH_SOLARXIAO_POWER?14:2;
   assert(ch[i]==expected && r[i].channel==expected);
   assert(r[i].valid==(MESH_SOLARXIAO_POWER?i==0 || i==4:true));
  }
  assert(ch[n]==255 && r[n].channel==255);
 }
}
'''.replace("@METHODS@", methods)
        with tempfile.TemporaryDirectory(prefix="solarxiao-telemetry-test-") as temp:
            cpp = Path(temp) / "test.cpp"
            binary = Path(temp) / "test"
            cpp.write_text(harness, encoding="ascii")
            for enabled in (0, 1):
                build = subprocess.run([shutil.which("g++"), "-std=c++11",
                    "-DMESH_SOLARXIAO_POWER=" + str(enabled), "-fsanitize=address,undefined",
                    "-fno-pie", "-no-pie", str(cpp), "-o", str(binary)],
                    capture_output=True, text=True, timeout=30)
                self.assertEqual(build.returncode, 0, build.stdout + build.stderr)
                run = subprocess.run([str(binary)], capture_output=True, text=True, timeout=10)
                self.assertEqual(run.returncode, 0, run.stdout + run.stderr)


if __name__ == "__main__":
    unittest.main()
