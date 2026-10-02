// Opt-in V4 OLED instrumentation. Not linked into any production image.
// Keep USB logging enabled while collecting this ASCII-only test stream.
#if defined(COMPANION_PAIRING_UI_HIL)
#include <Arduino.h>
#include <helpers/UsbLogging.h>
#include "../../examples/companion_radio/MyMesh.h"
#include "../../examples/companion_radio/ui-new/UITask.h"
#include <target.h>

extern MyMesh the_mesh;
extern UITask ui_task;
static uint8_t startup_phases = 0;

void companionStartupUiHilFrame(const char* status) {
  if (strcmp(status, "Starting...") == 0) startup_phases |= 1;
  if (strcmp(status, "Loading identity") == 0) startup_phases |= 2;
  if (strcmp(status, "Generating key") == 0) startup_phases |= 4;
  if (strcmp(status, "Saving identity") == 0) startup_phases |= 8;
}

void companionPairingUiHilProbe() {
  if (!mesh::isUsbLoggingEnabled()) return;
  const bool pairing = ui_task.isPairingPromptActive();
  const bool on = display.isOn();
  const bool ble = ui_task.hasBluetoothConnection();
  const bool usb = board.isUsbHostConnected();
  const uint32_t state = on | (pairing << 1) | (ble << 2) | (usb << 3)
      | (uint32_t(startup_phases) << 4);
  static uint32_t previous = UINT32_MAX;
  if (state == previous) return;
  const bool capture = pairing && on && (previous == UINT32_MAX || !(previous & 2));
  previous = state;
  char public_key[65];
  mesh::Utils::toHex(public_key, the_mesh.self_id.pub_key, 32);
  mesh::usbLoggingPort().printf(
      "UIHIL ms=%lu on=%u pairing=%u ble=%u usb=%u startup=%u pin=%lu key=%s\n",
      (unsigned long)millis(), on, pairing, ble, usb, startup_phases,
      (unsigned long)the_mesh.getBLEPin(), public_key);
  if (capture) {
    const uint8_t* pixels = display.hilFramebuffer();
    // One bounded diagnostic write; never read private key material.
    char record[2070];
    memcpy(record, "UIHIL pixels=", 13);
    static const char hex[] = "0123456789abcdef";
    for (size_t i = 0; i < 1024; ++i) {
      record[13 + i * 2] = hex[pixels[i] >> 4];
      record[14 + i * 2] = hex[pixels[i] & 15];
    }
    record[2061] = '\n';
    mesh::usbLoggingPort().write(reinterpret_cast<uint8_t*>(record), 2062);
  }
}
#endif
