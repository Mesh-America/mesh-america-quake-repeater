#pragma once

#include "SolarXiaoPowerCore.h"

namespace mesh { namespace solar {

// Carrier identity is selected by the operator. A missing/unpowered I2C
// peripheral cannot distinguish the Advanced board from the MPPT board.
class CarrierSelection {
public:
  enum Type : uint8_t { Mppt = 0, Advanced = 1 };
  static constexpr size_t IMAGE_SIZE = 8;

private:
  Store& store;
  Type type = Mppt;
  bool healthy = false;
  bool saved = false;
  bool select(Type requested);

public:
  explicit CarrierSelection(Store& persistence) : store(persistence) {}
  void begin();
  bool nativeAllowed() const { return healthy && type == Mppt; }
  bool isAdvanced() const { return healthy && type == Advanced; }
  bool settingsHealthy() const { return healthy; }
  bool handle(const char* command, char* reply, size_t capacity,
              float xiao_battery_v, float mcu_c, bool history_available);
};

}} // namespace mesh::solar
