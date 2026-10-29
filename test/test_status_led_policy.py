"""Run the common LED policy and Xiao S3 LED initialization with fake GPIO."""

from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

from test_replay_reset_integration import extract_braced

ROOT = Path(__file__).resolve().parents[1]

ARDUINO = r'''
#pragma once
#include <cassert>
#include <vector>
#define LOW 0
#define HIGH 1
#define INPUT 0
#define OUTPUT 1
struct Event { int kind, pin, value; };
extern std::vector<Event> events;
inline void digitalWrite(int pin, int value) { events.push_back({0, pin, value}); }
inline void pinMode(int pin, int mode) { events.push_back({1, pin, mode}); }
inline void analogWrite(int pin, int value) { events.push_back({2, pin, value}); }
'''

HARNESS = r'''
#include <Arduino.h>
#include <target.h>
#include <helpers/LedPolicy.h>
std::vector<Event> events;
int main() {
  // Enabling permits the existing heartbeat owner to run; it does not light
  // an idle LED or change its output mode as a side effect of the command.
  assert(mesh::leds::enabled());
  mesh::leds::applyStatusPolicy();
  assert(events.empty());
  mesh::leds::setEnabled(false);
  mesh::leds::applyStatusPolicy();
  assert(!mesh::leds::enabled());
  assert(events.size() == EXPECT_EVENTS);
#if EXPECT_EVENTS == 2
  assert(events[0].kind == 0 && events[0].pin == PIN_STATUS_LED);
  assert(events[0].value == EXPECT_OFF);
  assert(events[1].kind == 1 && events[1].pin == PIN_STATUS_LED);
  assert(events[1].value == OUTPUT); // Set the off latch before enabling output.
#elif EXPECT_EVENTS == 3
  const int pins[] = {PIN_STATUS_LED_R, PIN_STATUS_LED_G, PIN_STATUS_LED_B};
  for (unsigned i = 0; i < 3; ++i)
    assert(events[i].kind == 2 && events[i].pin == pins[i] && events[i].value == 0);
#endif
  events.clear();
  mesh::leds::setEnabled(true);
  mesh::leds::applyStatusPolicy();
  assert(mesh::leds::enabled() && events.empty());
}
'''


def compile_run(case, source, defines):
    compiler = shutil.which("c++") or shutil.which("g++")
    case.assertIsNotNone(compiler, "run this host suite where c++ is available")
    with tempfile.TemporaryDirectory(prefix="mesh-status-led-") as folder:
        folder = Path(folder)
        (folder / "Arduino.h").write_text(ARDUINO)
        (folder / "target.h").write_text("#pragma once\n" + "\n".join(
            "#define " + define.replace("=", " ", 1) for define in defines))
        (folder / "case.cpp").write_text(source)
        binary = folder / "case"
        built = subprocess.run([
            compiler, "-std=c++11", "-Wall", "-Wextra", "-Werror",
            "-I", str(folder), "-I", str(ROOT / "src"),
            str(ROOT / "src/helpers/LedPolicy.cpp"), str(folder / "case.cpp"),
            "-o", str(binary)], text=True, capture_output=True, timeout=30)
        case.assertEqual(built.returncode, 0, built.stderr)
        ran = subprocess.run([str(binary)], text=True, capture_output=True, timeout=10)
        case.assertEqual(ran.returncode, 0, ran.stdout + ran.stderr)


class StatusLedPolicyTests(unittest.TestCase):
    def test_off_is_immediate_and_on_leaves_heartbeat_in_control(self):
        cases = (
            ("active-high", ["PIN_STATUS_LED=12", "LED_STATE_ON=HIGH",
                             "EXPECT_OFF=LOW", "EXPECT_EVENTS=2"]),
            ("active-low", ["PIN_STATUS_LED=12", "LED_STATE_ON=LOW",
                            "EXPECT_OFF=HIGH", "EXPECT_EVENTS=2"]),
            ("default-polarity", ["PIN_STATUS_LED=12", "EXPECT_OFF=LOW",
                                 "EXPECT_EVENTS=2"]),
            ("absent", ["EXPECT_EVENTS=0"]),
            ("negative-pin", ["PIN_STATUS_LED=-1", "EXPECT_EVENTS=0"]),
            ("rgb", ["PIN_STATUS_LED_R=3", "PIN_STATUS_LED_G=24",
                     "PIN_STATUS_LED_B=28", "PIN_STATUS_LED=24", "EXPECT_EVENTS=3"]),
        )
        for name, defines in cases:
            with self.subTest(board=name):
                compile_run(self, HARNESS, defines)

    def test_xiao_s3_uses_active_low_output_during_radio_init(self):
        ini = (ROOT / "variants/xiao_s3/platformio.ini").read_text()
        names = ("PIN_STATUS_LED", "LED_STATE_ON", "P_LORA_SCLK",
                 "P_LORA_MISO", "P_LORA_MOSI")
        definitions = {name: re.findall(r"-D\s+" + name + r"=([^\s;]+)", ini)
                       for name in names}
        self.assertEqual(definitions["PIN_STATUS_LED"], ["21"])
        self.assertEqual(definitions["LED_STATE_ON"], ["LOW"])
        for name in names:
            self.assertEqual(len(definitions[name]), 1, name)
        method = extract_braced((ROOT / "variants/xiao_s3/target.cpp").read_text(),
                                "bool radio_init()")
        source = r'''
#include <Arduino.h>
#include <target.h>
std::vector<Event> events;
struct Clock { template<class... T> void begin(T...) {} } fallback_clock, rtc_clock;
struct Spi { void begin(int, int, int) {} } spi;
struct Radio { bool std_init(Spi*) { return true; } } radio;
int Wire = 0;
@METHOD@
int main() {
  assert(radio_init());
  assert(events.size() == 3);
  assert(events[0].kind == 0 && events[0].pin == 21 && events[0].value == HIGH);
  assert(events[1].kind == 1 && events[1].pin == 21 && events[1].value == OUTPUT);
  assert(events[2].kind == 1 && events[2].pin == 48 && events[2].value == OUTPUT);
}
'''
        compile_run(self, source.replace("@METHOD@", method),
                    [name + "=" + definitions[name][0] for name in names])


if __name__ == "__main__":
    unittest.main()
