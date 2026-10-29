"""Exercise the production profile clock on and off both nRF52 and other boards."""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "src/helpers/radiolib/RadioLibWrappers.cpp").read_text()
CLOCK = SOURCE[SOURCE.index("// Extend the 24-bit RTC counter"):].split(
    "\nstatic\n#if defined(ESP8266)", 1)[0]

HARNESS = r'''
#include <cassert>
#include <cstdint>
struct FakeRtc {
  uint32_t TASKS_STOP = 0, PRESCALER = 9, TASKS_CLEAR = 0, TASKS_START = 0;
  uint32_t COUNTER = 0;
} rtc;
#define NRF_RTC2 (&rtc)
uint32_t micros() { return 1234; }
static uint64_t esp_elapsed_us=1234;
int64_t esp_timer_get_time() { return static_cast<int64_t>(esp_elapsed_us); }
@CLOCK@
int main() {
  assert(profileTimestamp(false) == 1234);
  assert(rtc.TASKS_START == 0 && rtc.TASKS_STOP == 0);
  assert(profileElapsedUs(12, 42, false) == 30);
#if defined(NRF52_PLATFORM)
  rtc.COUNTER = 100;
  assert(profileTimestamp(true) == 0);
  assert(rtc.TASKS_STOP == 1 && rtc.PRESCALER == 0);
  assert(rtc.TASKS_CLEAR == 0 && rtc.TASKS_START == 1);
  rtc.TASKS_CLEAR = rtc.TASKS_START = rtc.TASKS_STOP = 0;
  assert(profileTimestamp(true) == 0);
  assert(rtc.TASKS_CLEAR == 0 && rtc.TASKS_START == 0 && rtc.TASKS_STOP == 0);
  assert(profileElapsedUs(0, 32768, true) == 1000000);
  assert(profileElapsedUs(0xfffffff0, 0x10, true) == 977);
  uint32_t stamp=0;
  for(unsigned second=1;second<=532;++second) {
    rtc.COUNTER=(rtc.COUNTER+32768)&0x00ffffffUL;
    stamp=profileTimestamp(true);
    assert(stamp==second*32768UL);
    assert(profileElapsedUs(0,stamp,true)==second*1000000UL);
  }
  assert(stamp>0x00ffffffUL); // A valid visit can exceed the hardware period.
  assert(profileElapsedUs(0,UINT32_MAX,true)==UINT32_MAX);
  syncProfileClock(false);
  assert(rtc.TASKS_STOP == 1 && profileTimestamp(false) == 1234);
  rtc.TASKS_CLEAR = rtc.TASKS_START = rtc.TASKS_STOP = 0;
  syncProfileClock(false);
  assert(rtc.TASKS_CLEAR == 0 && rtc.TASKS_START == 0 && rtc.TASKS_STOP == 0);
  rtc.COUNTER = 200;
  assert(profileTimestamp(true) == 0);
  assert(rtc.TASKS_CLEAR == 0 && rtc.TASKS_START == 1);
  for(unsigned chunk=0;chunk<511;++chunk) {
    rtc.COUNTER=(rtc.COUNTER+256UL*32768)&0x00ffffffUL;
    profileTimestamp(true);
  }
  rtc.COUNTER=(rtc.COUNTER+255UL*32768)&0x00ffffffUL;
  const auto before=profileTimestamp(true);assert(before==0xffff8000UL);
  rtc.COUNTER=(rtc.COUNTER+32768)&0x00ffffffUL;
  const auto wrapped=profileTimestamp(true);assert(wrapped==0);
  assert(profileElapsedUs(before,wrapped,true)==1000000UL);
#elif defined(ESP32_PLATFORM)
  assert(profileTimestamp(true) == 1234);
  // The ESP Timer is the light-sleep-adjusted clock; a frozen cycle/micros
  // source must not extend a radio visit while the MCU was asleep.
  esp_elapsed_us+=10000;
  assert(micros()==1234 && profileTimestamp(true)==11234);
  assert(profileTimestamp(false)==11234);
  esp_elapsed_us=0x100000010ULL;
  assert(profileTimestamp(true)==0x10);
  assert(profileElapsedUs(0xfffffff0,profileTimestamp(true),true)==32);
  assert(rtc.TASKS_START == 0 && rtc.TASKS_STOP == 0);
#else
  assert(profileTimestamp(true) == 1234);
  assert(profileElapsedUs(12, 42, true) == 30);
  assert(rtc.TASKS_START == 0 && rtc.TASKS_STOP == 0);
#endif
}
'''


class ProfileClockTest(unittest.TestCase):
    def test_clock_selection_and_lifecycle(self):
        with tempfile.TemporaryDirectory() as folder:
            cpp = Path(folder) / "test.cpp"
            exe = Path(folder) / "test.exe"
            cpp.write_text(HARNESS.replace("@CLOCK@", CLOCK))
            for defines in ([], ["-DNRF52_PLATFORM=1"], ["-DESP32_PLATFORM=1"]):
                result = subprocess.run(
                    [os.environ.get("CXX", "g++"), "-std=c++17", "-Wall", "-Wextra",
                     "-Werror", *defines, str(cpp), "-o", str(exe)],
                    capture_output=True, text=True,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                result = subprocess.run([str(exe)], capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
