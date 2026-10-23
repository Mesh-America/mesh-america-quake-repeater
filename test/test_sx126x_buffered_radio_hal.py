"""Execute portable radio SPI buffering, settings and bus ownership."""
from pathlib import Path
import os
import re
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
RADIO = ROOT / "src/helpers/radiolib"

MOCK = r'''
#pragma once
#include <cassert>
#include <cstddef>
#include <cstdint>
constexpr unsigned MSBFIRST=1, SPI_MODE0=0;
struct SPISettings {
  unsigned hz, order, mode;
  SPISettings(unsigned h, unsigned o, unsigned m) : hz(h), order(o), mode(m) {}
};
struct SPIClass {
  unsigned bursts=0, bytes=0, begins=0, ends=0;
  const void* lastOut=nullptr; void* lastIn=nullptr; size_t lastLength=0;
  void begin() { ++begins; }
  void end() { ++ends; }
  void burst(const void* out, void* in, size_t length) {
    ++bursts; lastOut=out; lastIn=in; lastLength=length;
    const auto* tx=static_cast<const uint8_t*>(out);
    auto* rx=static_cast<uint8_t*>(in);
    for (size_t i=0; i<length; ++i) rx[i]=tx[i]^0xa5;
  }
#if defined(NRF52_PLATFORM) || defined(RP2040_PLATFORM)
  void transfer(const void* out, void* in, size_t length) { burst(out,in,length); }
#else
  void transferBytes(const uint8_t* out, uint8_t* in, size_t length) {
    burst(out,in,length);
  }
#endif
  uint8_t transfer(uint8_t value) { ++bytes; return value^0xa5; }
};
struct ArduinoHal {
  SPIClass* spi; SPISettings spiSettings; bool initInterface=false;
  explicit ArduinoHal(SPIClass& bus,SPISettings settings)
      : spi(&bus),spiSettings(settings) {}
  virtual ~ArduinoHal()=default;
  virtual void init() { if (initInterface) spi->begin(); }
  virtual void term() { if (initInterface) spi->end(); }
  virtual void spiTransfer(uint8_t* out,size_t length,uint8_t* in) {
    for (size_t i=0;i<length;++i) in[i]=spi->transfer(out[i]);
  }
};
'''

FIXTURE = r'''
#include <array>
#include <initializer_list>
#include <helpers/radiolib/SX126xBufferedRadioHal.h>
SPIClass unused, explicitBus, fallbackBus;
int main() {
  SX126xBufferedRadioHal external(explicitBus);
  SX126xBufferedRadioHal fallback(fallbackBus,MC_SX1262_SPI_HZ,true);
  SX126xBufferedRadioHal slower(explicitBus,4000000);
  assert(external.spiSettings.hz == MC_SX1262_SPI_HZ);
  assert(slower.spiSettings.hz == 4000000);
  assert(external.spiSettings.order == MSBFIRST && external.spiSettings.mode == SPI_MODE0);
  assert(!external.initInterface && fallback.initInterface);
  ArduinoHal& hal=external;
  hal.init(); hal.term();
  assert(explicitBus.begins==0 && explicitBus.ends==0);
  fallback.init(); fallback.term();
  assert(fallbackBus.begins==1 && fallbackBus.ends==1);
  // A board/storage handoff can restart this SAME bus without replacing HAL.
  explicitBus.end(); explicitBus.begin();
  assert(hal.spi == &explicitBus);
  std::array<uint8_t,260> tx{}, rx{};
  for (size_t i=0;i<tx.size();++i) tx[i]=uint8_t(i);
  const auto original=tx;
  for (size_t length : {size_t(1),size_t(2),size_t(7),size_t(260)}) {
    rx.fill(0x77);
    const unsigned before=explicitBus.bursts;
    hal.spiTransfer(tx.data(),length,rx.data());
    assert(explicitBus.bursts==before+1 && explicitBus.bytes==0);
    assert(explicitBus.lastOut==tx.data() && explicitBus.lastIn==rx.data());
    assert(explicitBus.lastLength==length && tx==original);
    for (size_t i=0;i<length;++i) assert(rx[i]==uint8_t(tx[i]^0xa5));
    for (size_t i=length;i<rx.size();++i) assert(rx[i]==0x77);
  }
  const unsigned before=explicitBus.bursts;
  hal.spiTransfer(nullptr,0,nullptr);
  assert(explicitBus.bursts==before && explicitBus.bytes==0);
  assert(unused.bursts==0 && fallbackBus.bursts==0);
}
'''


class SX126xBufferedRadioHalTests(unittest.TestCase):
    def test_real_platform_buffers_forward_bytes_without_taking_explicit_bus_ownership(self):
        compiler=shutil.which(os.environ.get("CXX","g++"))
        self.assertIsNotNone(compiler)
        headers={name:(RADIO/name).read_text(encoding="ascii") for name in (
            "SX126xBufferedRadioHal.h","Nrf52BufferedRadioHal.h","ESP32BufferedRadioHal.h")}
        with tempfile.TemporaryDirectory(prefix="sx126x-buffered-radio-") as folder:
            base=Path(folder)
            (base/"hal/Arduino").mkdir(parents=True)
            (base/"helpers/radiolib").mkdir(parents=True)
            (base/"hal/Arduino/ArduinoHal.h").write_text(MOCK,encoding="ascii")
            cpp,executable=base/"test.cpp",base/"test"
            cpp.write_text(FIXTURE,encoding="ascii")
            for arch,header in (("NRF52_PLATFORM","Nrf52BufferedRadioHal.h"),
                                ("ESP32_PLATFORM","ESP32BufferedRadioHal.h"),
                                ("RP2040_PLATFORM","SX126xBufferedRadioHal.h")):
                # Without the real override, byte-for-byte correctness alone
                # still passes; the per-command transfer requirement must fail.
                legacy=re.sub(r"  void spiTransfer\([^}]+\}\n","",headers[header])
                self.assertNotEqual(legacy,headers[header])
                for clock in (8000000,8888888):
                    for name,implementation,succeeds in (("buffered",headers[header],True),
                                                         ("per-byte",legacy,False)):
                        with self.subTest(arch=arch,clock=clock,implementation=name):
                            for file,content in headers.items():
                                (base/"helpers/radiolib"/file).write_text(
                                    implementation if file==header else content,encoding="ascii")
                            built=subprocess.run([compiler,"-std=c++17","-Wall","-Wextra",
                                "-Werror",f"-D{arch}",f"-DMC_SX1262_SPI_HZ={clock}",
                                "-I",str(base),str(cpp),"-o",str(executable)],
                                capture_output=True,text=True,timeout=60)
                            self.assertEqual(built.returncode,0,built.stdout+built.stderr)
                            ran=subprocess.run([str(executable)],capture_output=True,
                                               text=True,timeout=10)
                            if succeeds:
                                self.assertEqual(ran.returncode,0,ran.stdout+ran.stderr)
                            else:
                                self.assertNotEqual(ran.returncode,0,
                                    "per-byte negative control did not fail")

    def test_default_clock_matches_all_capable_spi_controllers(self):
        header=(RADIO/"SX126xBufferedRadioHal.h").read_text(encoding="ascii")
        self.assertIn("#define MC_SX1262_SPI_HZ 8000000",header)


if __name__ == "__main__":
    unittest.main()
