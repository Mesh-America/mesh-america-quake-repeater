"""Execute XIAO's default and HIL-only SPIM2 radio constructor/recovery paths."""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest

from test_radio_receive_contract import method
from test_sx126x_buffered_radio_hal import MOCK


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "variants/xiao_nrf52/target.cpp"
CONFIG = ROOT / "variants/xiao_nrf52/XiaoRadioSpiConfig.h"
SDK = Path.home() / ".platformio/packages/framework-arduinoadafruitnrf52/libraries/SPI/SPI.cpp"
BASE_FLAGS = ["-DNRF52_PLATFORM", "-DNRF52840_XXAA", "-DXIAO_NRF52"]
FAST_FLAGS = BASE_FLAGS + ["-DMC_XIAO_NRF52_HIL_FAST_SPI=1", "-DSPI_32MHZ_INTERFACE=1"]

# Exact global bus selection from the pinned core. When the package exists,
# compare this fixture against its real source before executing either branch.
SDK_MAPPING = """#ifndef SPI_32MHZ_INTERFACE
#define SPI_32MHZ_INTERFACE 0
#endif

#if SPI_32MHZ_INTERFACE == 0
  #define _SPI_DEV    NRF_SPIM3 // 32 Mhz
  #define _SPI1_DEV   NRF_SPIM2

#elif SPI_32MHZ_INTERFACE == 1
  #define _SPI_DEV    NRF_SPIM2
  #define _SPI1_DEV   NRF_SPIM3 // 32 Mhz

#else
  #error "not supported yet"
#endif

#if SPI_INTERFACES_COUNT >= 1
// use SPIM3 for highspeed 32Mhz
SPIClass SPI(_SPI_DEV,  PIN_SPI_MISO,  PIN_SPI_SCK,  PIN_SPI_MOSI);
#endif

#if SPI_INTERFACES_COUNT >= 2
SPIClass SPI1(_SPI1_DEV, PIN_SPI1_MISO, PIN_SPI1_SCK, PIN_SPI1_MOSI);
#endif
"""
HAL_MOCK = MOCK.replace("struct SPIClass {", """
struct MockSpim { unsigned number; };
inline MockSpim spim2{2},spim3{3};
inline MockSpim* NRF_SPIM2=&spim2;
inline MockSpim* NRF_SPIM3=&spim3;
struct SPIClass {
  MockSpim* device;
  unsigned miso,sck,mosi;
  SPIClass(MockSpim* port,unsigned input,unsigned clock,unsigned output)
      : device(port),miso(input),sck(clock),mosi(output) {}
  void setPins(unsigned input,unsigned clock,unsigned output) {
    miso=input;sck=clock;mosi=output;
  }
""")


class XiaoNrf52BufferedSpiTests(unittest.TestCase):
    def test_actual_default_and_candidate_preserve_global_bus_and_reinitialization(self):
        text = TARGET.read_text()
        start = text.index("#if MC_XIAO_NRF52_HIL_FAST_SPI\n")
        constructor = text[start:text.index("#endif", start) + len("#endif")]
        initialization = method(text, "bool radio_init()")
        if SDK.exists():
            actual = SDK.read_text()
            self.assertIn(SDK_MAPPING, actual)
        fixture = r'''
#include <cassert>
#include <cstdint>
#include <hal/Arduino/ArduinoHal.h>
#include "XiaoRadioSpiConfig.h"
#include <helpers/radiolib/TunableRadioHal.h>
#define SPI_INTERFACES_COUNT 2
#define PIN_SPI_MISO 9
#define PIN_SPI_MOSI 10
#define PIN_SPI_SCK 8
#define PIN_SPI1_MISO 25
#define PIN_SPI1_MOSI 26
#define PIN_SPI1_SCK 29
#define P_LORA_MISO PIN_SPI_MISO
#define P_LORA_MOSI PIN_SPI_MOSI
#define P_LORA_SCLK PIN_SPI_SCK
constexpr unsigned P_LORA_NSS=4,P_LORA_DIO_1=1,P_LORA_RESET=2,P_LORA_BUSY=3;
@SDK_MAPPING@
struct Module {
  ArduinoHal* hal;
  bool owns;
  Module(ArduinoHal* adapter,unsigned cs,unsigned irq,unsigned reset,unsigned busy)
      : hal(adapter),owns(false) { assert(cs==4 && irq==1 && reset==2 && busy==3); }
  Module(unsigned cs,unsigned irq,unsigned reset,unsigned busy,SPIClass& bus)
      : Module(new ArduinoHal(bus,SPISettings(2000000,MSBFIRST,SPI_MODE0)),cs,irq,reset,busy) {
    owns=true;
  }
  ~Module() { if(owns) delete hal; }
};
struct Radio {
  Module* module;
  bool next=true;
  unsigned starts=0;
  Radio(Module* value):module(value) {}
  ~Radio() { delete module; }
  bool std_init(SPIClass* bus) {
    assert(bus==&SPI && module->hal->spi==bus);
    bus->setPins(P_LORA_MISO,P_LORA_SCLK,P_LORA_MOSI);bus->begin();++starts;
    return next;
  }
};
#define RADIO_CLASS Radio
@CONSTRUCTOR@
static bool target_radio_available=false;
unsigned Wire=0;
struct Rtc { unsigned begins=0; void begin(unsigned) { ++begins; } } rtc_clock;
@INITIALIZATION@
int main() {
  assert(radio.module->hal->spi==&SPI);
  assert(SPI.device->number==(MC_XIAO_NRF52_HIL_FAST_SPI?2:3));
  assert(SPI1.device->number==(MC_XIAO_NRF52_HIL_FAST_SPI?3:2));
  assert(radio.module->hal->spiSettings.hz==8000000);
  assert(!radio.module->hal->initInterface && SPI.begins==0 && SPI1.begins==0);
  radio.module->hal->init();radio.module->hal->term();
  assert(SPI.begins==0 && SPI.ends==0); // The board still owns bus lifetime.
  assert(radio_init() && target_radio_available && radio.starts==1 && SPI.begins==1);
  assert(SPI.miso==9 && SPI.sck==8 && SPI.mosi==10);
  uint8_t tx[]={0x86,0x12,0x34,0x56},rx[4]{};
  radio.module->hal->spiTransfer(tx,4,rx);
  assert(SPI.bursts==unsigned(MC_XIAO_NRF52_HIL_FAST_SPI));
  assert(SPI.bytes==unsigned(MC_XIAO_NRF52_HIL_FAST_SPI?0:4));
  assert(rx[0]==uint8_t(tx[0]^0xa5) && rx[3]==uint8_t(tx[3]^0xa5));
  const unsigned bursts=SPI.bursts,bytes=SPI.bytes;
  radio.module->hal->spiTransfer(nullptr,0,nullptr);
  assert(SPI.bursts==bursts && SPI.bytes==bytes);
  // Existing shutdown/recovery can restart the same global object. Neither
  // the HAL nor a failed radio initialization changes its bus or ownership.
  SPI.end();SPI.setPins(P_LORA_MISO,P_LORA_SCLK,P_LORA_MOSI);SPI.begin();
  radio.next=false;assert(!radio_init() && !target_radio_available);
  radio.next=true;assert(radio_init() && target_radio_available);
  assert(radio.module->hal->spi==&SPI && radio.starts==3 && SPI.begins==4);
  assert(SPI1.begins==0 && SPI1.ends==0 && SPI1.bursts==0 && SPI1.bytes==0);
#ifdef DISABLE_I2C_RTC_SCAN
  assert(rtc_clock.begins==0);
#else
  assert(rtc_clock.begins==3);
#endif
}
'''.replace("@SDK_MAPPING@", SDK_MAPPING).replace("@CONSTRUCTOR@", constructor).replace(
            "@INITIALIZATION@", initialization)
        with tempfile.TemporaryDirectory(prefix="mesh-xiao-spi-", dir="/var/tmp") as directory:
            directory = Path(directory)
            (directory / "hal/Arduino").mkdir(parents=True)
            (directory / "hal/Arduino/ArduinoHal.h").write_text(HAL_MOCK, encoding="ascii")
            cpp, binary = directory / "test.cpp", directory / "test.exe"
            cpp.write_text(fixture, encoding="ascii")
            for fast, solar in ((False, False), (True, False), (False, True), (True, True)):
                with self.subTest(fast=fast, solar=solar):
                    flags = FAST_FLAGS if fast else BASE_FLAGS
                    if solar:
                        flags = flags + ["-DDISABLE_I2C_RTC_SCAN"]
                    built = subprocess.run([
                        os.environ.get("CXX", "g++"), "-std=c++17", "-Wall", "-Wextra", "-Werror",
                        "-fsanitize=address,undefined", "-fno-sanitize-recover=all", "-fno-pie", "-no-pie",
                        *flags, "-I", str(directory), "-I", str(ROOT / "src"),
                        "-I", str(CONFIG.parent), str(cpp), "-o", str(binary),
                    ], capture_output=True, text=True, env={**os.environ, "TMPDIR": str(directory)})
                    self.assertEqual(built.returncode, 0, built.stderr)
                    ran = subprocess.run([str(binary)], capture_output=True, text=True)
                    self.assertEqual(ran.returncode, 0, ran.stderr)

    def test_candidate_fails_closed_without_exact_board_bus_or_safe_peripheral_policy(self):
        cases = [
            (["-DMC_XIAO_NRF52_HIL_FAST_SPI=2"], "must be 0 or 1"),
            (["-DMC_XIAO_NRF52_HIL_FAST_SPI=1"], "requires the nRF52840 XIAO target"),
            (BASE_FLAGS + ["-DMC_XIAO_NRF52_HIL_FAST_SPI=1"], "mapped to SPIM2"),
            (BASE_FLAGS + ["-DMC_XIAO_NRF52_HIL_FAST_SPI=1", "-DSPI_32MHZ_INTERFACE=0"], "mapped to SPIM2"),
            (FAST_FLAGS + ["-DNRFX_SPIM3_NRF52840_ANOMALY_198_WORKAROUND_ENABLED=1"], "SoftDevice-conflicting"),
            (FAST_FLAGS + ["-DOTA_SD_STORE=1"], "additional SD or Ethernet"),
            (FAST_FLAGS + ["-DETHERNET_ENABLED=1"], "additional SD or Ethernet"),
        ]
        for flags, diagnostic in cases:
            with self.subTest(flags=flags):
                result = subprocess.run([os.environ.get("CXX", "g++"), "-E", "-x", "c++",
                                         *flags, "-I", str(ROOT / "src"), str(CONFIG)],
                                        capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(diagnostic, result.stderr)

    def test_default_candidate_has_no_code_or_sdk_dependency_and_recipes_do_not_enable_it(self):
        result = subprocess.run([os.environ.get("CXX", "g++"), "-E", "-P", "-x", "c++", "-I", str(ROOT / "src"), str(CONFIG)],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(result.stdout.strip())
        config = CONFIG.with_name("platformio.ini").read_text()
        active = "\n".join(line for line in config.splitlines() if not line.lstrip().startswith(";"))
        self.assertNotIn("MC_XIAO_NRF52_HIL_FAST_SPI", active)
        self.assertNotIn("SPI_32MHZ_INTERFACE", active)


if __name__ == "__main__":
    unittest.main()
