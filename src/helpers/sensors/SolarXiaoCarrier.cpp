#include "SolarXiaoCarrier.h"
#if defined(MESH_SOLARXIAO_POWER) && MESH_SOLARXIAO_POWER
#include <math.h>
#include <stdio.h>
#include <string.h>

namespace mesh { namespace solar {
namespace {
// Complete canonical records detect bad version, length, value or complement.
// The filesystem adapter also verifies atomic publication and public readback.
const uint8_t images[2][CarrierSelection::IMAGE_SIZE] = {
  {'S','X','B',1,0,0xff,0xa5,0x5a},
  {'S','X','B',1,1,0xfe,0xa5,0x5a}
};
}

void CarrierSelection::begin() {
  type=Mppt; saved=false; healthy=store.available();
  if (!healthy || !store.exists()) return;
  uint8_t image[IMAGE_SIZE];
  if (!store.load(image,sizeof(image)) || image[4]>1
      || memcmp(image,images[image[4]],sizeof(image))) {
    healthy=false;
    return;
  }
  type=static_cast<Type>(image[4]); saved=true;
}

bool CarrierSelection::select(Type requested) {
  if (!store.available() || !store.save(images[requested],IMAGE_SIZE)) {
    // A failed publication/readback may leave either record live on disk.
    // Block native I2C/replay until an explicit selection succeeds or reloads.
    healthy=false;
    return false;
  }
  type=requested; saved=true; healthy=true;
  return true;
}

bool CarrierSelection::handle(const char* command,char* reply,size_t capacity,
                              float battery_v,float mcu_c,bool history_available) {
  if (!command || !reply || !capacity) return false;
  if (!strcmp(command,"get solar.board")) {
    if (!healthy) snprintf(reply,capacity,"Err - carrier selection unconfirmed; set solar.board advanced|mppt");
    else snprintf(reply,capacity,"> %s source=%s (configured, not autodetected)",
                  type==Advanced?"advanced":"mppt",saved?"saved":"default");
    return true;
  }
  if (!strncmp(command,"set solar.board",15) && (!command[15] || command[15]==' ')) {
    const char* value=command+15;
    while (*value==' ') ++value;
    if (strcmp(value,"advanced") && strcmp(value,"mppt")) {
      snprintf(reply,capacity,"Err - use set solar.board advanced|mppt");
    } else if (!select(!strcmp(value,"advanced")?Advanced:Mppt)) {
      snprintf(reply,capacity,"Err - carrier save unconfirmed; native access blocked; repeat selection");
    } else if (type==Advanced) {
      snprintf(reply,capacity,"OK - Advanced saved; native LTC/INA access disabled; self ADC/MCU telemetry retained");
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
    snprintf(reply,capacity,"Err - carrier selection unconfirmed; self readings available; set solar.board advanced|mppt");
  } else if (!*key || !strcmp(key,"info")) {
    snprintf(reply,capacity,"> carrier=%s source=%s charger=%s; %s",
             type==Advanced?"advanced":"mppt",saved?"configured":"default",
             type==Advanced?"BQ24650":"LTC4162",
             type==Advanced?"ADC/MCU only; charger settings hardware-only":"use get mppt for live chip identity/readings");
  } else if (!strcmp(key,"capabilities")) {
    snprintf(reply,capacity,type==Advanced
        ? "> Advanced: battery ADC + MCU temp; solar V/I, battery I/W, NTC and charger flags unwired; settings hardware-only"
        : "> MPPT: self ADC/MCU + INA260 V/A/W + LTC4162 readings/settings when reachable; use get mppt fields 0");
  } else {
    snprintf(reply,capacity,"Err - use get solar info|readings|capabilities|history; get/set solar.board");
  }
  return true;
}
}} // namespace mesh::solar
#endif
