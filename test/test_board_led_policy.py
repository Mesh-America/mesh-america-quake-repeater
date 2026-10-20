"""Exercise production board LED callbacks without touching hardware."""
from pathlib import Path
import os
import re
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


def body(path, name, index=0):
    source = (ROOT / path).read_text()
    matches = list(re.finditer(
        rf"\bvoid\s+(?:\w+::)?{name}\([^)]*\)(?:\s+override)?\s*\{{", source))
    start = matches[index].end()
    end, depth = start, 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[start:end - 1]


STUBS = r"""
#include <cassert>
#include <helpers/LedPolicy.h>
#define HIGH 1
#define LOW 0
#define P_LORA_TX_LED 1
#define LED_PIN 1
#define LED_BUILTIN 1
#define LED_RED 1
#define EXP_PIN_LED 1
#define EXP_PIN_USER_LED 1
#define LED_STATE_ON LOW
int levels[8], tx, rx, fan_calls, fan_state;
void digitalWrite(int pin, int value) { levels[pin] = value; }
struct Expander { void digitalWrite(int p, int v) { ::digitalWrite(p, v); } } expander;
void expWritePin(int p, int v) { digitalWrite(p, v); }
struct NRF52Board { static void applyLedPolicy() {} };
struct Fem {
  void setTxModeEnable() { ++tx; }
  void setRxModeEnable() { ++rx; }
} loRaFEMControl;
void reset() {
  for (auto &v : levels) v = -1;
  tx = rx = fan_calls = fan_state = 0;
  mesh::leds::setEnabled(false);
}
"""


class BoardLedPolicyTests(unittest.TestCase):
    def run_cpp(self, source):
        compiler = os.environ.get("CXX") or shutil.which("g++") or shutil.which("clang++")
        if not compiler:
            self.skipTest("C++ compiler unavailable")
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            cpp = directory / "led_policy.cpp"
            exe = directory / ("led_policy.exe" if os.name == "nt" else "led_policy")
            cpp.write_text(source)
            result = subprocess.run(
                [compiler, "-std=c++17", "-I", str(ROOT / "src"), str(cpp), "-o", str(exe)],
                capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            result = subprocess.run([str(exe)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_gpio_polarity_and_fem_callbacks(self):
        # Exercise active-low, active-high, LED_STATE_ON and expander boards.
        cases = [
            ("variants/lilygo_tdeck/TDeckBoard.h", 0, False, None),
            ("variants/thinknode_m7/ThinkNodeM7Board.h", 0, False, None),
            ("variants/thinknode_m5/ThinknodeM5Board.h", 1, False, None),
            ("variants/xiao_nrf52/XiaoNrf52Board.h", 0, False, None),
            ("variants/rak11310/RAK11310Board.h", 1, False, None),
            ("variants/xiao_rp2040/XiaoRP2040Board.h", 1, False, None),
            ("variants/rpi_picow/PicoWBoard.h", 1, False, None),
            ("variants/sensecap_solar/SenseCapSolarBoard.h", 1, False, None),
            ("variants/heltec_t096/T096Board.cpp", 1, True, None),
            ("variants/heltec_tower_v2/HeltecTowerV2Board.cpp", 0, True, None),
            ("variants/heltec_v4/HeltecV4Board.cpp", 1, True, "src/helpers/ESP32Board.h"),
            ("variants/heltec_v4_r8/HeltecV4R8Board.cpp", 1, True, "src/helpers/ESP32Board.h"),
            ("src/helpers/stm32/STM32Board.h", 0, False, None),
        ]
        source = STUBS
        for index, (path, on, fem, policy_path) in enumerate(cases):
            source += f"""
namespace test{index} {{
void before() {{ {body(path, "onBeforeTransmit")} }}
void after() {{ {body(path, "onAfterTransmit")} }}
void apply() {{ {body(policy_path or path, "applyLedPolicy")} }}
void run() {{
  reset();
  levels[1] = {on};
  apply();
  assert(levels[1] == {1 - on});
  assert(tx == 0 && rx == 0);
  before();
  assert(levels[1] == {1 - on});
  assert(tx == {int(fem)} && rx == 0);
  after();
  assert(levels[1] == {1 - on});
  assert(rx == {int(fem)});
  mesh::leds::setEnabled(true);
  before();
  assert(levels[1] == {on});
  after();
  assert(levels[1] == {1 - on});
}}
}}
"""
        source += "int main() {" + "".join(f"test{i}::run();" for i in range(len(cases))) + "}"
        self.run_cpp(source)

    def test_wio_expander_preserves_gnss_wake_level(self):
        path = "variants/wio-tracker-l2/WioTrackerL2Board.h"
        self.run_cpp(STUBS + f"""
bool expander_ok = true;
void setLed(bool on) {{ {body("variants/wio-tracker-l2/WioTrackerL2Board.cpp", "setLed")} }}
void before() {{ {body(path, "onBeforeTransmit")} }}
void after() {{ {body(path, "onAfterTransmit")} }}
void apply() {{ {body(path, "applyLedPolicy")} }}
int main() {{
  reset();
  apply(); assert(levels[1] == HIGH);
  before(); assert(levels[1] == HIGH);
  after(); assert(levels[1] == HIGH);
  mesh::leds::setEnabled(true);
  before(); assert(levels[1] == LOW);
  after(); assert(levels[1] == HIGH);
  expander_ok = false; levels[1] = -1;
  apply(); before(); after(); assert(levels[1] == -1);
}}
""")

    def test_tbeam_fan_runs_with_leds_disabled(self):
        path = "variants/lilygo_tbeam_1w/TBeam1WBoard.cpp"
        self.run_cpp(STUBS + r"""
constexpr int FAN_AUTO = 2, FAN_TX_COOLDOWN_MS = 1000;
int _fan_mux = 0, _mode = FAN_AUTO;
bool _tx_active = false, _stopped = false, _tx_cooldown_active = false;
unsigned _tx_until_ms = 0;
void portENTER_CRITICAL(int*) {}
void portEXIT_CRITICAL(int*) {}
unsigned millis() { return 23; }
void setFanOutputLocked(bool on) { ++fan_calls; fan_state = on; }
""" + f"""
void before() {{ {body(path, "onBeforeTransmit")} }}
void after() {{ {body(path, "onAfterTransmit")} }}
void apply() {{ {body(path, "applyLedPolicy")} }}
int main() {{
  reset(); apply();
  before();
  assert(levels[1] == LOW && _tx_active && fan_calls == 1 && fan_state);
  apply(); assert(_tx_active && fan_calls == 1 && !_tx_cooldown_active);
  after();
  assert(!_tx_active && _tx_cooldown_active && _tx_until_ms == 1023);
}}
""")

    def test_rgb_tx_does_not_change_torch(self):
        path = "variants/lilygo_techo_card/TechoCardBoard.cpp"
        self.run_cpp(STUBS + r"""
struct Pixel {
  int value = 0, shows = 0;
  void setPixelColor(int, int r, int g, int b) { value = r + g + b; }
  void show() { ++shows; }
} Led_A, Led_C;
""" + f"""
void before() {{ {body(path, "onBeforeTransmit")} }}
void after() {{ {body(path, "onAfterTransmit")} }}
void apply() {{ {body(path, "applyLedPolicy")} }}
int main() {{
  reset(); Led_A.value = 60; Led_C.value = 765;
  apply(); before();
  assert(Led_A.value == 0 && Led_C.value == 765 && Led_C.shows == 0);
  mesh::leds::setEnabled(true); before(); assert(Led_A.value == 60);
  after(); assert(Led_A.value == 0 && Led_C.value == 765);
}}
""")


if __name__ == "__main__":
    unittest.main()
