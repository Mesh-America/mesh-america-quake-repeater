#pragma once

#if defined(MESH_SOLARXIAO_POWER) && MESH_SOLARXIAO_POWER
#include <helpers/IdentityStore.h>
#include <helpers/SensorManager.h>

namespace mesh { namespace solar {
// Stable carrier channels 2..13 precede optional environmental sensors.
constexpr uint8_t FIRST_OPTIONAL_CHANNEL = 14;
void beginSettings(FILESYSTEM* fs);
void service();
bool handleCommand(const char* command, char* reply, size_t capacity, bool local);
void addTelemetry(CayenneLPP& telemetry);
uint8_t voltageChannels(uint8_t* channels, uint8_t capacity);
uint8_t queryVoltages(SensorManager::VoltageSensorReading* readings, uint8_t capacity);
}}
#endif
