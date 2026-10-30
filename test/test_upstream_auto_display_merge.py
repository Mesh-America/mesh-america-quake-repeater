"""Keep upstream's display name on the existing single-buffer OLED backend."""
from pathlib import Path
import tempfile
import unittest

import test_oled_display_probe as probe
from test_upstream_power_policy_merge import Recipes

DRAWING = r'''
  uint8_t rotation = 0;
  void setRotation(uint8_t value) { rotation = last_rotation = value; }
  int16_t width() const { return rotation & 1 ? HEIGHT : WIDTH; }
  int16_t height() const { return rotation & 1 ? WIDTH : HEIGHT; }
  void setTextColor(uint16_t) {}
  void setTextSize(int) {}
  void setTextWrap(bool) {}
  void cp437(bool) {}
  void setCursor(int, int) {}
  void print(const char*) {}
  void fillRect(int, int, int, int, uint16_t) {}
  void drawRect(int, int, int, int, uint16_t) {}
  void drawBitmap(int, int, const uint8_t*, int, int, uint16_t) {}
  void getTextBounds(const char* text, int, int, int16_t* x, int16_t* y,
                     uint16_t* width, uint16_t* height) {
    *x = *y = 0; *width = std::strlen(text) * 6; *height = 8;
  }
'''

HARNESS = r'''
#include <cassert>
#include <cstdlib>
#include <stdlib.h>
#include <type_traits>
#include <Adafruit_SSD1306.h>
static unsigned allocations = 0, active = 0;
void* test_malloc(size_t size) {
  assert(size == 1024); ++allocations; ++active; return std::malloc(size);
}
void test_free(void* p) { if (p) { assert(active == 1); --active; std::free(p); } }
#define malloc test_malloc
#include <helpers/ui/AutoDetectDisplay.h>
#include <helpers/ui/SSD1306Display.cpp>
#undef malloc
static_assert(std::is_same<AutoDetectDisplay, SSD1306Display>::value,
              "compatibility must preserve the single driver and framebuffer");
namespace mesh { namespace ui {
static OLEDControllerMode saved = OLEDControllerMode::Auto;
OLEDControllerMode oledControllerMode() { return saved; }
}}
using mesh::ui::OLEDControllerMode;
int main() {
  for (auto mode : {OLEDControllerMode::Auto, OLEDControllerMode::SSD1306,
                    OLEDControllerMode::SH1106}) {
    for (int status : {0, 8}) {
      Wire = TwoWire{}; Wire.status[0x3C] = {status, status};
      mesh::ui::saved = mode;
      const unsigned before = allocations;
      {
        AutoDetectDisplay panel;
        DisplayDriver* ui = &panel;
        assert(ui->supportsRotation() && panel.begin() && ui->isOn());
        assert(allocations == before + 1 && active == 1);
        const bool sh = mode == OLEDControllerMode::SH1106 ||
            (mode == OLEDControllerMode::Auto && status == 8);
        // SSD1306 init has no payload in this vendor double. SH1106 performs
        // its real init and eight page writes through the actual backend.
        bool saw_page = false;
        for (const auto& tx : Wire.transactions)
          if (tx.data.size() == 4 && tx.data[1] == 0xB0) saw_page = true;
        assert(saw_page == sh);
        for (unsigned degrees : {0, 90, 180, 270}) {
          assert(ui->setRotationDegrees(degrees));
          assert(ui->width() == (degrees % 180 ? 64 : 128));
          assert(ui->height() == (degrees % 180 ? 128 : 64));
          ui->setFlipped(true); assert(last_rotation == ((degrees / 90 + 2) & 3));
          ui->setFlipped(false); assert(last_rotation == degrees / 90);
        }
        assert(!ui->setRotationDegrees(45));
        ui->setTextSize(2); assert(ui->textLineHeight() == 16);
        ui->startFrame(); assert(ui->textLineHeight() == 8);
        ui->turnOff(); assert(!ui->isOn()); ui->turnOn(); assert(ui->isOn());
        Wire.requests.clear();
        assert(panel.begin() && allocations == before + 1);
      }
      assert(active == 0);
    }
  }
  Wire = TwoWire{}; Wire.present[0x3C] = false;
  mesh::ui::saved = OLEDControllerMode::Auto;
  AutoDetectDisplay absent;
  const unsigned before = allocations;
  assert(!absent.begin() && !absent.isOn());
  absent.turnOn(); assert(!absent.isOn() && allocations == before);
}
'''


class UpstreamAutoDisplayMergeTests(unittest.TestCase):
    def test_real_compatibility_driver_detection_settings_rotation_and_memory(self):
        vendor = probe.VENDOR.replace("class Adafruit_SSD1306 {",
                                "inline unsigned last_rotation = 0;\nclass Adafruit_SSD1306 {")
        vendor = vendor.replace("public:\n", "public:\n" + DRAWING)
        vendor += "\n#define SSD1306_BLACK 0\n#define SSD1306_WHITE 1\n"
        vendor += "#define SSD1306_DISPLAYON 0xAF\n#define SSD1306_DISPLAYOFF 0xAE\n"
        mocks = {
            "Arduino.h": probe.ARDUINO + "\ninline int digitalRead(unsigned) { return 0; }\n",
            "Wire.h": probe.WIRE, "Adafruit_SSD1306.h": vendor, "Adafruit_GFX.h": "",
            "helpers/IdentityStore.h": "#pragma once\nstruct FakeFS;\n#define FILESYSTEM FakeFS\n",
        }
        # Existing helper writes only direct children; provide the one nested
        # header through a separate include directory in the same test scope.
        identity = mocks.pop("helpers/IdentityStore.h")
        with tempfile.TemporaryDirectory() as directory:
            include = Path(directory)
            (include / "helpers").mkdir()
            (include / "helpers/IdentityStore.h").write_text(identity)
            probe.OledDisplayProbeTests.compile_run(
                self, HARNESS, ("-DOLED_AUTO_DETECT=1", "-DPIN_OLED_RESET=-1",
                               "-Wno-unused-parameter", "-I", str(include)), mocks)

    def test_every_rak_display_role_keeps_existing_detection_and_source_budget(self):
        recipes = Recipes()
        count = 0
        for section in recipes.config.sections():
            if not section.startswith("env:RAK_4631_"):
                continue
            flags = recipes.value(section, "build_flags")
            if "DISPLAY_CLASS=" not in flags:
                continue
            with self.subTest(role=section):
                self.assertIn("OLED_AUTO_DETECT=1", flags)
                self.assertIn("DISPLAY_CLASS=SSD1306Display", flags)
                sources = recipes.value(section, "build_src_filter")
                self.assertIn("helpers/ui/SSD1306Display.cpp", sources)
                self.assertNotIn("helpers/ui/SH1106Display.cpp", sources)
                self.assertNotIn("Adafruit SH110X", recipes.value(section, "lib_deps"))
            count += 1
        self.assertGreater(count, 15)


if __name__ == "__main__":
    unittest.main()
