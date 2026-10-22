#pragma once

#include <epd/GxEPD2_213_B74.h>

// MeshPocket's SSD1680 glass needs its own refresh/power sequence. Register
// values and settling times are documented by the LCMEN2R13ECC1 profile in
// https://github.com/meshtastic/firmware/tree/develop/src/graphics/niche/Drivers/EInk
// Keep GxEPD2's tested bitmap transfer and 128 x 250 RAM / 122-pixel geometry.
class MeshPocketEinkPanel : public GxEPD2_213_B74 {
public:
  MeshPocketEinkPanel(int16_t cs, int16_t dc, int16_t rst, int16_t busy)
      : GxEPD2_213_B74(cs, dc, rst, busy) {}

  void prepareRefresh(bool partial) {
    // Reset only the controller. BW::init() would also erase the drawn canvas.
    // initial=false preserves the previous image RAM instead of writing white.
    GxEPD2_EPD::init(0, false, 10, false);
    _waitWhileBusy(nullptr, 1000);
    _using_partial_mode = partial;
  }

  void refresh(bool partial = false) override {
    _writeCommand(0x3C); // Border waveform
    _writeData(partial ? 0x85 : 0x05);
    _writeCommand(0x22); // Load OTP waveform, update, then disable panel power
    _writeData(partial ? 0xFF : 0xF7);
    _writeCommand(0x20);
    // BUSY can initially read low. Do not overwrite image history or sleep
    // until the panel has had its minimum settling time, then honor BUSY.
    delay(partial ? 800 : 2500);
    _waitWhileBusy(nullptr, partial ? 800 : 2500);
    _initial_refresh = false;
    _power_is_on = false;
  }

  void refresh(int16_t, int16_t, int16_t w, int16_t h) override {
    // The Pocket uses a full-screen canvas, including for differential updates.
    if (w > 0 && h > 0) refresh(true);
  }

  void powerOff() override {
    // 0xFF / 0xF7 already disable panel power. An extra 0x83 / 0x20 sequence
    // between the refresh and image-history synchronization is unnecessary.
    _power_is_on = false;
  }

  void hibernate() override {
    if (_rst < 0) return;
    _writeCommand(0x10);
    _writeData(0x01); // Deep sleep mode 1 retains current / previous image RAM.
    _hibernating = true;
    _init_display_done = false;
  }

  void finishRefresh() {
    // Call after BW::display() has synchronized both image RAM banks.
    _writeCommand(0x7F); // Terminate image write without another update.
    _waitWhileBusy(nullptr, 1000);
    hibernate();
  }
};
