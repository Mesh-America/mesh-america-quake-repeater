#include <helpers/ui/SSD1306Display.h>
#include <assert.h>
#include <initializer_list>
#include <stdio.h>

static constexpr uint8_t RAIL_PIN = 7;

static void resetBoundary() {
  panel_state = PanelState();
  Wire = TwoWire();
  for (unsigned i = 0; i < 64; ++i) pin_levels[i] = pin_modes[i] = 0;
}

static void fail(bool allocation) {
  panel_state.allocation_ok = !allocation;
  Wire.result = allocation ? 0 : 2;
}

static void repair() { panel_state.allocation_ok = true; Wire.result = 0; }

static void expectNotReady(SSD1306Display& panel) {
  assert(!panel.isOn());
  const unsigned before = panel_state.rotations;
  panel.setFlipped(true);
  assert(panel.setRotationDegrees(90));
  panel.setFlipped(false);
  assert(panel.setRotationDegrees(0));
  assert(panel_state.rotations == before);
}

static void failedBoot(bool allocation, bool other_owner, bool shared) {
  resetBoundary();
  RefCountedDigitalPin rail(RAIL_PIN);
  rail.begin();
  if (other_owner) rail.claim();
  SSD1306Display panel(shared ? &rail : nullptr);
  fail(allocation);
  for (unsigned attempt = 0; attempt < 3; ++attempt) {
    // This is the caller's real admission contract: failed panels never get a
    // UI task which could later turn them off and release a phantom claim.
    DisplayDriver* ui = panel.begin() ? &panel : nullptr;
    assert(ui == nullptr);
    expectNotReady(panel);
    assert(digitalRead(RAIL_PIN) == (other_owner ? HIGH : LOW));
    if (shared && PIN_OLED_RESET >= 0) assert(digitalRead(PIN_OLED_RESET) == LOW);
  }
  assert(panel_state.begins == 3);
  assert(Wire.probes == (allocation ? 0U : 3U));
  // A failed panel owns nothing: repeated off may not steal another owner's
  // claim. Once that independent owner stops, the rail must really turn off.
  for (unsigned i = 0; i < 3; ++i) panel.turnOff();
  assert(digitalRead(RAIL_PIN) == (other_owner ? HIGH : LOW));
  if (other_owner) rail.release();
  assert(digitalRead(RAIL_PIN) == LOW);
  repair();
  assert(panel.begin() && panel.isOn());
  assert(digitalRead(RAIL_PIN) == (shared ? HIGH : LOW));
  assert(panel.begin());  // Already on: do not acquire a second display claim.
  panel.turnOff();
  assert(!panel.isOn() && digitalRead(RAIL_PIN) == LOW);
  // Claim/release after all failures proves the counter has not underflowed.
  rail.claim(); assert(digitalRead(RAIL_PIN) == HIGH);
  rail.release(); assert(digitalRead(RAIL_PIN) == LOW);
}

static void failedReinitialization(bool allocation, bool other_owner, bool shared) {
  resetBoundary();
  RefCountedDigitalPin rail(RAIL_PIN);
  rail.begin();
  if (other_owner) rail.claim();
  SSD1306Display panel(shared ? &rail : nullptr);
  assert(panel.begin());
  const unsigned rotations = panel_state.rotations;
  fail(allocation);
  assert(!panel.begin());  // Already-on begin has exactly one claim to roll back.
  expectNotReady(panel);
  assert(panel_state.rotations == rotations);
  assert(digitalRead(RAIL_PIN) == (other_owner ? HIGH : LOW));
  if (other_owner) rail.release();
  assert(digitalRead(RAIL_PIN) == LOW);
  repair();
  assert(panel.begin());
  panel.turnOff();
  assert(digitalRead(RAIL_PIN) == LOW);
}

static void failedWake(bool allocation, bool other_owner, bool shared) {
  resetBoundary();
  RefCountedDigitalPin rail(RAIL_PIN);
  rail.begin();
  if (other_owner) rail.claim();
  SSD1306Display panel(shared ? &rail : nullptr);
  assert(panel.begin());
  if (shared) panel.turnOff();
  else {
    // A continuously powered panel normally needs no reinit after turnOff.
    // Mark it unready through a real failed begin before testing failed wake.
    fail(allocation);
    assert(!panel.begin());
  }
  fail(allocation);
  const unsigned commands = panel_state.on_commands, begins = panel_state.begins;
  for (unsigned attempt = 0; attempt < 3; ++attempt) {
    panel.turnOn();
    expectNotReady(panel);
    assert(panel_state.on_commands == commands);
    assert(panel_state.begins == begins + attempt + 1);
    assert(digitalRead(RAIL_PIN) == (other_owner ? HIGH : LOW));
  }
  repair();
  panel.turnOn();
  assert(panel.isOn() && panel_state.on_commands == commands + 1);
  assert(digitalRead(RAIL_PIN) == ((shared || other_owner) ? HIGH : LOW));
  panel.turnOff();
  if (other_owner) {
    assert(digitalRead(RAIL_PIN) == HIGH);
    rail.release();
  }
  assert(digitalRead(RAIL_PIN) == LOW);
}

static void ordinarySuccess(bool shared) {
  resetBoundary();
  RefCountedDigitalPin rail(RAIL_PIN);
  rail.begin();
  SSD1306Display panel(shared ? &rail : nullptr);
  assert(panel.begin());
  assert(panel.isOn() && panel_state.begins == 1 && panel_state.rotations == 1);
  panel.turnOn();
  assert(panel_state.begins == 1 && panel_state.on_commands == 1);
  panel.turnOff();
  assert(!panel.isOn() && digitalRead(RAIL_PIN) == LOW);
  panel.turnOn();
  assert(panel.isOn() && panel_state.begins == (shared ? 2U : 1U));
  assert(panel_state.on_commands == 2);
  panel.turnOff();
  mesh::ui::displayPowerPrefs() = mesh::ui::DisplayPowerPrefs();
  mesh::ui::displayPowerPrefs().battery.mode = mesh::ui::DisplayMode::On;
  assert(panel.servicePower(false) && panel.isOn());
  mesh::ui::displayPowerPrefs().battery.mode = mesh::ui::DisplayMode::Off;
  assert(panel.servicePower(false) && !panel.isOn());
  assert(digitalRead(RAIL_PIN) == LOW);
}

int main() {
  unsigned checks = 0;
  for (bool allocation : {false, true}) for (bool other_owner : {false, true})
  for (bool shared : {false, true}) {
    failedBoot(allocation, other_owner, shared); ++checks;
    failedReinitialization(allocation, other_owner, shared); ++checks;
    failedWake(allocation, other_owner, shared); ++checks;
  }
  for (bool shared : {false, true}) { ordinarySuccess(shared); ++checks; }
  printf("PASS: actual SSD1306 power ownership (%u scenarios)\n", checks);
}
