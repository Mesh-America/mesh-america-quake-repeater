#if defined(NRF52_PLATFORM)

#include <Arduino.h>
#include <FreeRTOS.h>
#include <task.h>
#include <string.h>
#include <helpers/nrf52/BleTaskStartup.h>

namespace mesh {
namespace nrf52 {
static uint8_t ble_task_mask;

void resetBleTaskStartup() { ble_task_mask = 0; }
bool bleTasksStarted() { return ble_task_mask == 3; }
}  // namespace nrf52
}  // namespace mesh

#ifndef MESH_NRF52_LOOP_STACK_WORDS
  #define MESH_NRF52_LOOP_STACK_WORDS 2048
#endif

static_assert(MESH_NRF52_LOOP_STACK_WORDS >= 1024,
              "The nRF52 loop task stack must not be smaller than the framework default");

extern "C" BaseType_t __real_xTaskCreate(
    TaskFunction_t task_code, const char* const task_name,
    const configSTACK_DEPTH_TYPE stack_depth, void* const parameters,
    UBaseType_t priority, TaskHandle_t* const created_task);

// The Adafruit nRF52 core hard-codes the Arduino loop task to 1024 32-bit
// words (4 KiB). Mesh packet verification and authenticated remote commands
// can legitimately enter Ed25519 routines whose stack peaks do not fit there.
// Wrap task creation so only the framework's "loop" task receives 8 KiB; all
// BLE, timer, callback, and application-created tasks retain their requested
// sizes.
extern "C" BaseType_t __wrap_xTaskCreate(
    TaskFunction_t task_code, const char* const task_name,
    const configSTACK_DEPTH_TYPE stack_depth, void* const parameters,
    UBaseType_t priority, TaskHandle_t* const created_task) {
  configSTACK_DEPTH_TYPE adjusted_depth = stack_depth;
  if (task_name != NULL && strcmp(task_name, "loop") == 0
      && stack_depth == 1024) {
    adjusted_depth = MESH_NRF52_LOOP_STACK_WORDS;
  }
  const BaseType_t result = __real_xTaskCreate(
      task_code, task_name, adjusted_depth, parameters, priority, created_task);
  if (task_name != NULL) {
    const uint8_t mask = strcmp(task_name, "BLE") == 0 ? 1
        : strcmp(task_name, "SOC") == 0 ? 2 : 0;
    if (result == pdPASS) {
      mesh::nrf52::ble_task_mask |= mask;
    } else {
      mesh::nrf52::ble_task_mask &= ~mask;
    }
  }
  return result;
}

#endif
