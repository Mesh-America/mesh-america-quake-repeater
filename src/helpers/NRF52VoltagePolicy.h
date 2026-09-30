#pragma once

#include <stddef.h>
#include <stdint.h>

#include "NRF52VoltageRules.h"

#if defined(NRF52_PLATFORM) && defined(NRF52_POWER_MANAGEMENT)
namespace mesh {
namespace power {

// Called by checkBootVoltage(). Uses a single non-formatting mount to read the
// policy, then releases the FS so the application can mount it normally later.
void loadVoltagePolicyAtBoot(uint16_t board_default_mv);
bool voltagePolicySupported();
bool bootlockOffAllowed();
uint16_t configuredBootlock();
uint16_t configuredCutoff();
uint16_t configuredEmpty();
uint16_t configuredFull();
uint16_t configuredAdcPermille();
uint8_t configuredBatteryPercent(uint16_t mv);
bool setConfiguredBootlock(uint16_t mv);
bool setConfiguredCutoff(uint16_t mv);
bool isVoltagePolicyCommand(const char* command);
bool handleVoltagePolicyCommand(const char* command, char* reply,
                                size_t reply_capacity);

} // namespace power
} // namespace mesh
#endif
