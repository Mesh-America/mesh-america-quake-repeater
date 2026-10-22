#include "GxEPDDisplay.h"

using panel::Call;

static void paint(GxEPDDisplay& display, const char* text) {
  display.setTextSize(1);
  display.setCursor(2, 20);
  display.print(text);
}

static void frame(GxEPDDisplay& display, const char* text) {
  display.startFrame();
  paint(display, text);
  display.endFrame();
}

static void cleanBaseline(GxEPDDisplay& display, int interval = 2) {
  assert(display.begin());
  assert(display.width() == 250 && display.height() == 122);
  display.setMaxPartialRefresh(interval);
  display.forceFullRefresh();
  frame(display, "Network");
  assert(panel::updates(Call::Full) == 1 && panel::updates(Call::Partial) == 0);
  assert(panel::images.back() == "Network");
}

int main(int argc, char** argv) {
  assert(argc == 2);
  const std::string scenario = argv[1];
  GxEPDDisplay display;
  if (scenario == "boot") {
    display.turnOff();
    assert(panel::calls.empty() && "an uninitialized display must not access hardware");
    assert(display.begin());
    display.startFrame();
    display.setMaxPartialRefresh(30);
    paint(display, "First image");
    display.endFrame();
    assert(panel::updates(Call::Full) == 1 && panel::updates(Call::Partial) == 0);
    frame(display, "Clock 13:44");
    assert(panel::updates(Call::Partial) == 1);
    return 0;
  }
  cleanBaseline(display);

  if (scenario == "manual") {
    // Requesting a clean once rendering has started must clean this frame,
    // including when it has exactly the same drawing commands as before.
    display.startFrame();
    paint(display, "Network");
    display.forceFullRefresh();
    display.endFrame();
    assert(panel::updates(Call::Full) == 2 && panel::updates(Call::Partial) == 0);
    const auto calls = panel::calls.size();
    frame(display, "Network");
    assert(panel::calls.size() == calls && "identical clean image needs no repeat SPI update");
    display.forceFullRefresh();
    frame(display, "Network");
    assert(panel::updates(Call::Full) == 3);
  } else if (scenario == "periodic") {
    const auto calls = panel::calls.size();
    frame(display, "Network");
    assert(panel::calls.size() == calls);
    frame(display, "Clock 13:44");
    assert(panel::updates(Call::Partial) == 1 && panel::updates(Call::Full) == 1);
    const auto after_first = panel::calls.size();
    for (unsigned i = 0; i < 8; ++i) frame(display, "Clock 13:44");
    assert(panel::calls.size() == after_first && "unchanged frames must not exhaust the clean interval");
    frame(display, "Clock 13:45");
    assert(panel::updates(Call::Partial) == 2 && panel::updates(Call::Full) == 1);
    frame(display, "Clock 13:46");
    assert(panel::updates(Call::Full) == 2 && panel::updates(Call::Partial) == 2);
    frame(display, "Clock 13:47");
    assert(panel::updates(Call::Partial) == 3 && "a clean resets the partial-update allowance");
    assert(panel::images.back() == "Clock 13:47");
  } else if (scenario == "interval") {
    // A settings change must preserve a clean requested before drawing starts.
    display.forceFullRefresh();
    display.setMaxPartialRefresh(60);
    frame(display, "Network");
    assert(panel::updates(Call::Full) == 2 && panel::updates(Call::Partial) == 0);
    // Settings may also be applied by the GUI after startFrame(). Neither
    // increasing the allowance nor manual cleanup may cancel a requested clean.
    for (int interval : {30, -1, 1}) {
      const auto full = panel::updates(Call::Full);
      display.forceFullRefresh();
      display.startFrame();
      display.setMaxPartialRefresh(interval);
      paint(display, "Network");
      display.endFrame();
      assert(panel::updates(Call::Full) == full + 1);
    }
    display.setMaxPartialRefresh(-1);
    const auto full = panel::updates(Call::Full);
    for (unsigned i = 0; i < 70; ++i) {
      const std::string value = "tick " + std::to_string(i);
      frame(display, value.c_str());
    }
    assert(panel::updates(Call::Full) == full && "manual mode allows partial updates until explicitly cleaned");
    assert(panel::updates(Call::Partial) == 70);
  } else if (scenario == "wake") {
    display.turnOff();
    assert(!display.isOn() && panel::updates(Call::Hibernate) == 1);
    const auto full = panel::updates(Call::Full);
    const auto partial = panel::updates(Call::Partial);
    display.turnOn();
    assert(display.isOn());
    frame(display, "Network");
    assert(panel::updates(Call::Full) == full + 1);
    assert(panel::updates(Call::Partial) == partial);
    // An already-awake turnOn() should not force a clean or discard history.
    display.turnOn();
    frame(display, "Clock 13:45");
    assert(panel::updates(Call::Full) == full + 1);
    assert(panel::updates(Call::Partial) == partial + 1);
  } else if (scenario == "rotation") {
    display.startFrame();
    display.setNativeRotation(1);
    paint(display, "Flipped");
    display.endFrame();
    assert(display.width() == 250 && display.height() == 122);
    assert(panel::updates(Call::Full) == 2 && panel::updates(Call::Partial) == 0);
    display.setNativeRotation(1);
    frame(display, "Flipped");
    assert(panel::updates(Call::Full) == 2 && panel::updates(Call::Partial) == 0);
    frame(display, "Flipped clock");
    assert(panel::updates(Call::Partial) == 1);
  } else {
    assert(false && "unknown scenario");
  }
}
