#pragma once

#include <stdint.h>

namespace mesh {
namespace tbeam_charge {

enum : uint8_t { AXP192 = 0x03, AXP2101 = 0x4A };

struct Setting {
  uint8_t reg;
  uint8_t mask;
  uint8_t bits;
};

// These are the discrete hardware targets, not a voltage range. In particular,
// neither PMU supports the 3.65 V termination voltage used by LiFePO4 cells.
inline bool encode(uint8_t model, uint16_t millivolts, Setting& setting) {
  if (model == AXP192) {
    setting.reg = 0x33;
    setting.mask = 0x60;
    switch (millivolts) {
      case 4100: setting.bits = 0x00; return true;
      case 4150: setting.bits = 0x20; return true;
      case 4200: setting.bits = 0x40; return true;
      case 4360: setting.bits = 0x60; return true;
      default: return false;
    }
  }
  if (model == AXP2101) {
    setting.reg = 0x64;
    setting.mask = 0x07;
    switch (millivolts) {
      case 4000: setting.bits = 1; return true;
      case 4100: setting.bits = 2; return true;
      case 4200: setting.bits = 3; return true;
      case 4350: setting.bits = 4; return true;
      case 4400: setting.bits = 5; return true;
      default: return false;
    }
  }
  return false;
}

inline bool supports(uint8_t model, uint16_t millivolts) {
  Setting setting;
  return encode(model, millivolts, setting);
}

inline const char* options(uint8_t model) {
  if (model == AXP192) return "4.10,4.15,4.20,4.36";
  if (model == AXP2101) return "4.00,4.10,4.20,4.35,4.40";
  return nullptr;
}

inline const char* storeNamespace(uint8_t model) {
  if (model == AXP192) return "tbeam192_chg";
  if (model == AXP2101) return "tbeam2101_chg";
  return nullptr;
}

inline bool decode(uint8_t model, uint8_t value, uint16_t& millivolts) {
  if (model == AXP192) {
    static const uint16_t targets[] = {4100, 4150, 4200, 4360};
    millivolts = targets[(value & 0x60) >> 5];
    return true;
  }
  if (model == AXP2101) {
    static const uint16_t targets[] = {4000, 4100, 4200, 4350, 4400};
    const uint8_t code = value & 0x07;
    if (code < 1 || code > 5) return false;
    millivolts = targets[code - 1];
    return true;
  }
  return false;
}

template<typename IO>
bool read(IO& io, uint8_t model, uint16_t& millivolts) {
  Setting setting;
  if (!encode(model, 4200, setting)) return false;
  uint8_t detected, value;
  if (!io.read(0x03, detected) || detected != model ||
      !io.read(setting.reg, value)) return false;
  return decode(model, value, millivolts);
}

template<typename IO>
bool write(IO& io, uint8_t model, uint16_t millivolts) {
  Setting setting;
  if (!encode(model, millivolts, setting)) return false;
  uint8_t detected, previous;
  if (!io.read(0x03, detected) || detected != model ||
      !io.read(setting.reg, previous)) return false;
  const uint8_t value = (previous & ~setting.mask) | setting.bits;
  if (value != previous && !io.write(setting.reg, value)) return false;
  uint8_t actual;
  return io.read(setting.reg, actual) && actual == value;
}

// Store reads distinguish an absent key from an I/O failure; writes include
// commit and readback. The caller must keep the store open for the transaction.
template<typename IO, typename Store>
bool setPersistent(IO& io, Store& store, uint8_t model, uint16_t millivolts) {
  if (!supports(model, millivolts)) return false;
  uint16_t previousHardware, previousStored = 0;
  bool existed = false;
  if (!read(io, model, previousHardware) ||
      !store.read(previousStored, existed)) return false;

  if (!write(io, model, millivolts)) {
    // A failed readback may follow a successful physical write.
    write(io, model, previousHardware);
    return false;
  }
  if (existed && previousStored == millivolts) return true;
  if (store.write(millivolts)) return true;

  // Restore persistence before restoring hardware, so a successful rollback
  // cannot leave the requested target to be silently reapplied on next boot.
  const bool restoredStore = existed ? store.write(previousStored) : store.erase();
  if (restoredStore) {
    write(io, model, previousHardware);
  } else {
    // A failed commit has an uncertain durable result. Match a readable saved
    // setting where possible; otherwise keep the last verified requested
    // hardware target and report failure, never pretend the state is unchanged.
    uint16_t stored = 0;
    bool present = false;
    if (store.read(stored, present)) {
      if (!present) write(io, model, previousHardware);
      else if (supports(model, stored)) write(io, model, stored);
    }
  }
  return false;
}

template<typename IO, typename Store>
bool configureBoot(IO& io, Store& store, uint8_t model, bool apply_fresh_default) {
  uint16_t stored = 0;
  bool present = false;
  if (!store.read(stored, present)) return false;
  // A missing preference is the only condition that permits the existing full
  // driver's 4.2 V default. Unreadable/invalid saved settings must never raise
  // the charger target; preserve the PMU state and surface a boot failure.
  if (!present) return !apply_fresh_default || write(io, model, 4200);
  return supports(model, stored) && write(io, model, stored);
}

} // namespace tbeam_charge
} // namespace mesh
