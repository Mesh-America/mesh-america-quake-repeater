#pragma once

#include "SolarXiaoPowerCore.h"

namespace mesh { namespace solar {

// Only a verified INA260 identifies the MPPT carrier automatically. Missing
// responses leave self-only telemetry; Base and Advanced have no digital ID.
class CarrierSelection {
public:
  // Preserve the original manual record values for installed selections.
  enum Type : uint8_t { Mppt = 0, Advanced = 1, Auto = 2, Base = 3 };
  static constexpr size_t IMAGE_SIZE = 8;

private:
  Store& store;
  Type type = Auto;
  bool healthy = false;
  bool saved = false;
  bool verified_mppt = false;
  bool probed = false;
  uint32_t next_probe = 0;
  bool select(Type requested);

public:
  explicit CarrierSelection(Store& persistence) : store(persistence) {}
  void begin();
  void service(Bus& bus, uint32_t now);
  bool nativeAllowed() const { return healthy && (type == Mppt || (type == Auto && verified_mppt)); }
  bool isAdvanced() const { return healthy && type == Advanced; }
  bool isBase() const { return healthy && type == Base; }
  bool isAuto() const { return healthy && type == Auto; }
  bool settingsHealthy() const { return healthy; }
  bool handle(const char* command, char* reply, size_t capacity,
              float xiao_battery_v, float mcu_c, bool history_available);
};

}} // namespace mesh::solar
