#pragma once

#include <Arduino.h>
#include <helpers/RefCountedDigitalPin.h>
#include <helpers/ESP32Board.h>

class ThinknodeM2Board : public ESP32Board {

public:
  void begin();
  bool supportsBatteryCalibration() const override { return true; }

  uint16_t getBattMilliVolts() override;
  const char* getManufacturerName() const override ;

};