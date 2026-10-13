#pragma once

#include <RadioLib.h>

// Native beginGFSK resets the LR11xx's DIO switch registers. Cache the same
// seven mode masks used by RadioLib, then restore them with a checked command
// before entering RX (its public setRfSwitchTable otherwise discards errors).
class LR11x0MorseRfSwitch {
  uint8_t enable_ = 0;
  uint8_t modes_[7] = {};
  bool configured_ = false;
public:
  void capture(Module* module,
               const uint32_t (&pins)[Module::RFSWITCH_MAX_PINS],
               const Module::RfSwitchMode_t table[]) {
    enable_ = 0;
    for (auto& mode : modes_) mode = 0;
    configured_ = table != nullptr;
    if (!configured_) return;
    for (size_t i = 0; i < Module::RFSWITCH_MAX_PINS; ++i) {
      if (pins[i] == RADIOLIB_NC || !(pins[i] & RFSWITCH_PIN_FLAG)) continue;
      enable_ |= 1UL << RADIOLIB_LRXXXX_DIOx_VAL(pins[i]);
    }
    for (size_t i = 0; i < 7 && table[i].mode != LR11x0::MODE_END_OF_TABLE; ++i) {
      const uint8_t index = table[i].mode - LR11x0::MODE_STBY;
      if (index >= 7) continue;
      for (size_t j = 0; j < Module::RFSWITCH_MAX_PINS; ++j) {
        if (pins[j] == RADIOLIB_NC || !(pins[j] & RFSWITCH_PIN_FLAG)) continue;
        if (table[i].values[j] == module->hal->GpioLevelHigh) modes_[index] |= 1UL << j;
      }
    }
  }
  template <typename Apply>
  int16_t restore(Apply apply) const {
    return !configured_ ? RADIOLIB_ERR_NONE : apply(enable_, modes_);
  }
};
