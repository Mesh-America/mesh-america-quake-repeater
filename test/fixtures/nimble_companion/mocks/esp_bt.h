#pragma once
#include <NimBLEDevice.h>
using esp_err_t = int;
constexpr esp_err_t ESP_OK = 0;
enum esp_bt_controller_status_t {
  ESP_BT_CONTROLLER_STATUS_IDLE,
  ESP_BT_CONTROLLER_STATUS_INITED,
  ESP_BT_CONTROLLER_STATUS_ENABLED
};
inline esp_bt_controller_status_t esp_bt_controller_get_status() {
  return static_cast<esp_bt_controller_status_t>(fake_nimble::controller_state);
}
inline esp_err_t esp_bt_controller_disable() {
  if (fake_nimble::failure == "stop-controller") return 1;
  fake_nimble::controller_state = ESP_BT_CONTROLLER_STATUS_INITED;
  return ESP_OK;
}
inline esp_err_t esp_bt_controller_deinit() {
  if (fake_nimble::failure == "deinit-controller") return 1;
  fake_nimble::controller_state = ESP_BT_CONTROLLER_STATUS_IDLE;
  return ESP_OK;
}
