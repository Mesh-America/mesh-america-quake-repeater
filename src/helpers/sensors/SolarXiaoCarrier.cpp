#include "SolarXiaoCarrier.h"
#if defined(MESH_SOLARXIAO_POWER) && MESH_SOLARXIAO_POWER
#include <math.h>
#include <stdio.h>
#include <string.h>

namespace mesh { namespace solar {
namespace {
// Complete canonical records detect bad version, length, value or complement.
// The filesystem adapter also verifies atomic publication and public readback.
const uint8_t images[4][CarrierSelection::IMAGE_SIZE] = {
  {'S','X','B',1,0,0xff,0xa5,0x5a},
  {'S','X','B',1,1,0xfe,0xa5,0x5a},
  {'S','X','B',1,2,0xfd,0xa5,0x5a},
  {'S','X','B',1,3,0xfc,0xa5,0x5a}
};
}

void CarrierSelection::begin() {
  type=Auto; saved=false; healthy=store.available();
  verified_mppt=false; probed=false; next_probe=0;
  if (!healthy || !store.exists()) return;
  uint8_t image[IMAGE_SIZE];
  if (!store.load(image,sizeof(image)) || image[4]>Base
      || memcmp(image,images[image[4]],sizeof(image))) {
    healthy=false;
    return;
  }
  type=static_cast<Type>(image[4]); saved=true;
}

void CarrierSelection::service(Bus& bus,uint32_t now) {
  if (!isAuto() || verified_mppt || (probed && static_cast<int32_t>(now-next_probe)<0)) return;
  probed=true; next_probe=now+5000;
  uint16_t manufacturer,device;
  // These read-only identity registers do not configure the INA260 or charger.
  // A simple address ACK could be a different device (including an INA219).
  verified_mppt=bus.read(0x40,0xfe,manufacturer) && manufacturer==0x5449
      && bus.read(0x40,0xff,device) && (device&0xfff0)==0x2270;
  // Latch a positive identity for this boot; transient loss must not relabel it.
}

bool CarrierSelection::select(Type requested) {
  if (!store.available() || !store.save(images[requested],IMAGE_SIZE)) {
    // A failed publication/readback may leave either record live on disk.
    // Block native I2C/replay until an explicit selection succeeds or reloads.
    healthy=false;
    return false;
  }
  type=requested; saved=true; healthy=true;
  verified_mppt=false; probed=false; next_probe=0;
  return true;
}

bool CarrierSelection::handle(const char* command,char* reply,size_t capacity,
                              float battery_v,float mcu_c,bool history_available) {
  if (!command || !reply || !capacity) return false;
  if (!strcmp(command,"get solar.board")) {
    if (!healthy) snprintf(reply,capacity,"Err - carrier selection unconfirmed; set solar.board auto|advanced|base|mppt");
    else if (type==Auto) snprintf(reply,capacity,"> auto source=%s result=%s",saved?"saved":"default",
        verified_mppt?"mppt (INA260 ID verified)":"self-only (MPPT unconfirmed; Base/Advanced indistinguishable)");
    else snprintf(reply,capacity,"> %s source=%s (manual override)",
                  type==Advanced?"advanced":type==Base?"base":"mppt",saved?"saved":"default");
    return true;
  }
  if (!strncmp(command,"set solar.board",15) && (!command[15] || command[15]==' ')) {
    const char* value=command+15;
    while (*value==' ') ++value;
    Type requested=Auto;
    bool valid=true;
    if (!strcmp(value,"auto")) requested=Auto;
    else if (!strcmp(value,"advanced")) requested=Advanced;
    else if (!strcmp(value,"base")) requested=Base;
    else if (!strcmp(value,"mppt")) requested=Mppt;
    else valid=false;
    if (!valid) {
      snprintf(reply,capacity,"Err - use set solar.board auto|advanced|base|mppt");
    } else if (!select(requested)) {
      snprintf(reply,capacity,"Err - carrier save unconfirmed; native access blocked; repeat selection");
    } else if (type==Auto) {
      snprintf(reply,capacity,"OK - auto saved; verifying INA260; self ADC/MCU retained; verified MPPT reloads retained charger overrides");
    } else if (type==Advanced || type==Base) {
      snprintf(reply,capacity,"OK - %s saved; native LTC/INA access disabled; self ADC/MCU telemetry retained",type==Base?"Base":"Advanced");
    } else {
      snprintf(reply,capacity,"OK - MPPT saved; native access and retained charger overrides re-enabled");
    }
    return true;
  }
  if (strncmp(command,"get solar",9) || (command[9] && command[9]!=' ')) return false;
  const char* key=command+9; if (*key==' ') ++key;
  if (!strcmp(key,"readings") || !strcmp(key,"battery")) {
    char battery[24],temperature[24];
    if (isfinite(battery_v) && battery_v>0) snprintf(battery,sizeof(battery),"%.3fV",double(battery_v));
    else snprintf(battery,sizeof(battery),"unavailable");
    if (isfinite(mcu_c)) snprintf(temperature,sizeof(temperature),"%.2fC",double(mcu_c));
    else snprintf(temperature,sizeof(temperature),"unavailable");
    snprintf(reply,capacity,"> XIAO battery=%s MCU=%s (processor); self channel=1",battery,temperature);
  } else if (!strcmp(key,"history")) {
    snprintf(reply,capacity,history_available
        ? "> get telemetry.volt [1-7]; get telemetry.temp [1-7]; 30min samples, 7d RAM history; voltage trend does not measure charge current"
        : "Err - telemetry history is not included in this build");
  } else if (!healthy) {
    snprintf(reply,capacity,"Err - carrier selection unconfirmed; self readings available; set solar.board auto|advanced|base|mppt");
  } else if (!*key || !strcmp(key,"info")) {
    if (type==Auto) snprintf(reply,capacity,"> mode=auto source=%s %s",saved?"saved":"default",
        verified_mppt?"carrier=mppt (INA260 verified); use get mppt for LTC4162 identity/readings"
                     :"result=self-only; INA260 not verified; Base/Advanced cannot be distinguished");
    else snprintf(reply,capacity,"> carrier=%s source=%s charger=%s; %s",
             type==Advanced?"advanced":type==Base?"base":"mppt",saved?"configured":"default",
             type==Advanced?"BQ24650":type==Base?"CN3791":"LTC4162",
             type==Mppt?"use get mppt for live chip identity/readings":"ADC/MCU only; charger settings hardware-only");
  } else if (!strcmp(key,"capabilities")) {
    const char* capabilities=type==Advanced
        ? "> Advanced: battery ADC + MCU temp; solar V/I, battery I/W, NTC and charger flags unwired; settings hardware-only"
        : type==Base
        ? "> Base: battery ADC + MCU temp; CN3791 analog charger has no digital readings/settings; other power signals unwired"
        : nativeAllowed()
        ? "> MPPT: self ADC/MCU + INA260 V/A/W + LTC4162 readings/settings when reachable; use get mppt fields 0"
        : "> Auto: self ADC/MCU only until INA260 ID verifies MPPT; Base/Advanced have no digital identity; retrying detection";
    snprintf(reply,capacity,"%s",capabilities);
  } else {
    snprintf(reply,capacity,"Err - use get solar info|readings|capabilities|history; get/set solar.board");
  }
  return true;
}
}} // namespace mesh::solar
#endif
