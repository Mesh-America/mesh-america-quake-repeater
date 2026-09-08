#pragma once

namespace mesh {
namespace nrf52 {

// The pinned Bluefruit core does not check xTaskCreate's return value for its
// BLE and SOC workers. Nrf52LoopStack.cpp observes those calls through the
// existing linker wrapper so a nominally successful begin cannot hide OOM.
void resetBleTaskStartup();
bool bleTasksStarted();

}  // namespace nrf52
}  // namespace mesh
