#include <Arduino.h>
#include <assert.h>
#include <vector>
#include <utility>

static std::vector<std::pair<int, int>> writes;
static int batteryAdc = 2253, temperatureAdc = 2048, lightAdc = 2048;

void digitalWrite(int pin, int level) { writes.emplace_back(pin, level); }
void analogReference(int reference) { assert(reference == AR_INTERNAL_3_0); }
void analogReadResolution(int bits) { assert(bits == 12); }
void delay(unsigned long milliseconds) { assert(milliseconds == 10); }
int analogRead(int pin) {
  if (pin == BATTERY_PIN) return batteryAdc;
  if (pin == TEMP_SENSOR) return temperatureAdc;
  assert(pin == LUX_SENSOR);
  return lightAdc;
}

#include "t1000e_sensors.cpp"

static void checkRailCycle() {
  assert(writes.size() == 2);
  assert(writes[0] == std::make_pair(38, HIGH));
  assert(writes[1] == std::make_pair(38, LOW));
  writes.clear();
}

int main() {
  static_assert(PIN_3V3_EN == 38, "actual sensor rail must remain P1.06");
  static_assert(TEMP_SENSOR == 31 && LUX_SENSOR == 29, "retain real ADC pins");
  assert(isfinite(t1000e_get_temperature()));
  checkRailCycle();
  assert(t1000e_get_light() <= 100);
  checkRailCycle();
  assert(get_heater_temperature(3300, 0) == -30);
  assert(get_heater_temperature(0, 1) == 105);
  assert(get_heater_temperature(3300, 3300) == 105);
  assert(get_heater_temperature(3300, 4000) == 105);
  float previous = -30;
  for (unsigned int sample = 0; sample <= 3300; ++sample) {
    float temperature = get_heater_temperature(3300, sample);
    assert(isfinite(temperature));
    assert(temperature >= -30 && temperature <= 105 && temperature >= previous);
    previous = temperature;
  }
  temperatureAdc = 0;
  assert(t1000e_get_temperature() == -30);
  checkRailCycle();
  lightAdc = 0;
  assert(t1000e_get_light() == 0);
  checkRailCycle();
  lightAdc = 4095;
  assert(t1000e_get_light() == 100);
  checkRailCycle();
}
