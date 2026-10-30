#pragma once
#include <cstddef>
#include <helpers/CLICommandUtils.h>

// These dispatch fixtures exercise another command family. Calibration and
// its checked persistence have their own production-code test suites.
namespace mesh { namespace power {
template <typename Board>
bool handleStoredBatteryCalibrationCommand(Board&, const char*, char*, size_t) {
  return false;
}
}}
