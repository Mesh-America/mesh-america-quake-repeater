#pragma once

#include <MeshCore.h>
#include <helpers/IdentityStore.h>

namespace mesh { namespace power {

// Companion and Terminal Chat keep calibration outside their published
// preference layouts. Infrastructure roles retain their existing ADC field.
bool beginBatteryCalibrationStore(MainBoard& board, FILESYSTEM* fs);
bool setStoredAdcMultiplier(MainBoard& board, float multiplier,
                            char* reply, size_t capacity);
bool handleStoredAdcMultiplierCommand(MainBoard& board, const char* command,
                                      char* reply, size_t capacity);
bool handleStoredBatteryCalibrationCommand(MainBoard& board, const char* command,
                                           char* reply, size_t capacity);

}} // namespace mesh::power
