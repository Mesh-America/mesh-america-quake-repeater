#include "SolarXiaoPower.h"
#if defined(MESH_SOLARXIAO_POWER) && MESH_SOLARXIAO_POWER
#include "SolarXiaoPowerCore.h"
#include <helpers/CheckedSettingsFile.h>
#include <Wire.h>
#include <math.h>

namespace mesh { namespace solar {
extern const char meshcore_capability_solarxiao_power[] = "MESHCORE_CAPABILITY:solarxiao_power:v1";
namespace {
class CarrierBus : public Bus {
  bool ready(uint8_t address) {
    return (address==0x68 || address==0x40)
        && digitalRead(PIN_BOARD_SDA)==HIGH && digitalRead(PIN_BOARD_SCL)==HIGH;
  }
public:
  bool read(uint8_t address, uint8_t reg, uint16_t& value) override {
    if (!ready(address)) return false;
    Wire.beginTransmission(address);
    Wire.write(reg);
    if (Wire.endTransmission(false)!=0) return false;
    if (Wire.requestFrom(address,uint8_t(2))!=2) {
      while (Wire.available()) Wire.read();
      return false;
    }
    const uint8_t first=Wire.read(), second=Wire.read();
    // LTC4162 SMBus words are little endian; INA260 registers are big endian.
    value=address==0x68 ? uint16_t(first)|(uint16_t(second)<<8)
                        : (uint16_t(first)<<8)|second;
    return true;
  }
  bool write(uint8_t address,uint8_t reg,uint16_t value) override {
    if (address!=0x68 || !ready(address)) return false;
    Wire.beginTransmission(address);
    Wire.write(reg); Wire.write(uint8_t(value)); Wire.write(uint8_t(value>>8));
    return Wire.endTransmission()==0;
  }
};
class CarrierStore : public Store {
public:
  FILESYSTEM* fs=nullptr;
  static constexpr const char* path="/solar_power";
  bool available() const override { return fs!=nullptr; }
  bool exists() const override { return fs && fs->exists(path); }
  bool load(uint8_t* data,size_t size) override {
    return storage::readFixedSettingsFile(fs,path,data,size);
  }
  bool save(const uint8_t* data,size_t size) override {
    if (!fs || size!=Settings::IMAGE_SIZE) return false;
    AtomicFileWriter writer(fs,path);
    if (!writer || writer.write(data,size)!=size || !writer.commit()) return false;
    uint8_t checked[Settings::IMAGE_SIZE];
    return load(checked,size) && !memcmp(checked,data,size);
  }
};
constexpr const char* CarrierStore::path;
CarrierBus transport;
CarrierStore persistence;
Controller controller(transport,persistence);
}

void beginSettings(FILESYSTEM* fs) {
  const volatile char* marker=meshcore_capability_solarxiao_power;
  (void)*marker;
  persistence.fs=fs; controller.begin();
}
void service() { controller.service(millis()); }
bool handleCommand(const char* command,char* reply,size_t capacity,bool local) {
  return controller.handle(command,reply,capacity,local);
}
void addTelemetry(CayenneLPP& lpp) {
  Snapshot s; controller.snapshot(s);
  if (s.monitor) {
    lpp.addVoltage(2,s.battery_v); lpp.addCurrent(2,s.battery_a); lpp.addPower(2,s.battery_w);
  }
  if (!s.charger) return;
  if (isfinite(s.vin_v)) {
    lpp.addVoltage(3,s.vin_v); lpp.addCurrent(3,s.iin_a);
    lpp.addPower(3,fmaxf(0,s.vin_v*s.iin_a));
  }
  if (isfinite(s.vout_v)) lpp.addVoltage(4,s.vout_v);
  if (isfinite(s.charger_vbat_v)) lpp.addVoltage(5,s.charger_vbat_v);
  if (isfinite(s.ibat_a)) lpp.addCurrent(5,s.ibat_a);
  if (isfinite(s.die_c)) lpp.addTemperature(6,s.die_c);
  if (isfinite(s.ntc_c)) lpp.addTemperature(7,s.ntc_c);
  lpp.addGenericSensor(8,s.state); lpp.addGenericSensor(9,s.status);
  lpp.addGenericSensor(10,s.system);
  for (unsigned i=0;i<3;++i) lpp.addGenericSensor(11+i,s.alerts[i]);
}
uint8_t voltageChannels(uint8_t* channels,uint8_t capacity) {
  const uint8_t count=capacity<4 ? capacity : 4;
  for (uint8_t i=0;channels && i<count;++i) channels[i]=2+i;
  return count;
}
uint8_t queryVoltages(SensorManager::VoltageSensorReading* readings,uint8_t capacity) {
  if (!readings || !capacity) return 0;
  Snapshot s; controller.snapshot(s);
  const float volts[]={s.battery_v,s.vin_v,s.vout_v,s.charger_vbat_v};
  const uint8_t count=capacity<4 ? capacity : 4;
  for (uint8_t i=0;i<count;++i) {
    readings[i].channel=2+i;
    readings[i].valid=(i==0?s.monitor:s.charger) && isfinite(volts[i]);
    readings[i].voltage=readings[i].valid ? volts[i] : 0;
  }
  return count;
}
}} // namespace mesh::solar
#endif
