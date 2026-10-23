"""Execute the RAK3401's actual HAL construction and buffered SPI override."""
from pathlib import Path
import os
import re
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


MOCK_HAL = r'''
#pragma once
#include <cassert>
#include <cstddef>
#include <cstdint>
#include <cstring>
constexpr unsigned MSBFIRST = 1, SPI_MODE0 = 0;
struct SPISettings {
  unsigned hz, order, mode;
  SPISettings(unsigned h, unsigned o, unsigned m) : hz(h), order(o), mode(m) {}
};
struct SPIClass {
  unsigned bursts = 0, bytes = 0;
  const void* lastOut = nullptr;
  void* lastIn = nullptr;
  size_t lastLength = 0;
  void transfer(const void* out, void* in, size_t length) {
    ++bursts; lastOut = out; lastIn = in; lastLength = length;
    const auto* tx = static_cast<const uint8_t*>(out);
    auto* rx = static_cast<uint8_t*>(in);
    // Deterministic independent MISO data verifies the full-duplex response.
    for (size_t i = 0; i < length; ++i) rx[i] = tx[i] ^ 0xa5;
  }
  uint8_t transfer(uint8_t value) { ++bytes; return value ^ 0xa5; }
};
struct ArduinoHal {
  SPIClass* spi;
  SPISettings spiSettings;
  explicit ArduinoHal(SPIClass& bus, SPISettings settings)
      : spi(&bus), spiSettings(settings) {}
  virtual ~ArduinoHal() = default;
  virtual void spiTransfer(uint8_t* out, size_t length, uint8_t* in) {
    for (size_t i = 0; i < length; ++i) in[i] = spi->transfer(out[i]);
  }
};
'''


HARNESS = r'''
#include <array>
#include <initializer_list>
#include <helpers/radiolib/Nrf52BufferedRadioHal.h>
SPIClass SPI, SPI1;
constexpr unsigned P_LORA_NSS=1, P_LORA_DIO_1=2, P_LORA_RESET=3, P_LORA_BUSY=4;
struct Module {
  ArduinoHal* hal;
  Module(ArduinoHal* adapter, unsigned cs, unsigned irq, unsigned rst, unsigned busy)
      : hal(adapter) {
    assert(cs==1 && irq==2 && rst==3 && busy==4);
    assert(hal->spi == &SPI1 && hal->spiSettings.hz == 8000000);
  }
};
struct Radio {
  Module* mod;
  Radio(Module* module) : mod(module) {}
  ~Radio() { delete mod; }
};
#define RADIO_CLASS Radio
@CONSTRUCTION@
int main() {
  assert(radio.mod->hal == &radioHal);
  ArduinoHal& hal = *radio.mod->hal; // Exercise the production virtual override.
  assert(hal.spiSettings.order == MSBFIRST && hal.spiSettings.mode == SPI_MODE0);
  std::array<uint8_t, 260> tx{}, rx{};
  for (size_t i = 0; i < tx.size(); ++i) tx[i] = uint8_t(i);
  const auto original = tx;
  // Typical command/status/FIFO lengths, including a complete radio packet.
  for (size_t length : {size_t(1), size_t(2), size_t(7), size_t(260)}) {
    rx.fill(0x77);
    const unsigned before = SPI1.bursts;
    hal.spiTransfer(tx.data(), length, rx.data());
    assert(SPI1.bursts == before+1 && SPI1.bytes == 0);
    assert(SPI1.lastOut == tx.data() && SPI1.lastIn == rx.data());
    assert(SPI1.lastLength == length && tx == original);
    for (size_t i = 0; i < length; ++i) assert(rx[i] == uint8_t(tx[i] ^ 0xa5));
    for (size_t i = length; i < rx.size(); ++i) assert(rx[i] == 0x77);
  }
  const unsigned before = SPI1.bursts;
  hal.spiTransfer(nullptr, 0, nullptr);
  assert(SPI1.bursts == before && SPI1.bytes == 0);
  assert(SPI.bursts == 0 && SPI.bytes == 0); // Never use the private probe bus.
}
'''


class Rak3401BufferedRadioHalTests(unittest.TestCase):
    def test_actual_target_uses_one_transfer_per_command_on_same_spi1_at_8mhz(self):
        target = (ROOT / "variants/rak3401/target.cpp").read_text(encoding="ascii")
        construction = "\n".join(re.findall(
            r"^(?:static Nrf52BufferedRadioHal radioHal\([^;]+;|"
            r"RADIO_CLASS radio = new Module\([^;]+;)$", target, re.MULTILINE))
        self.assertEqual(len(construction.splitlines()), 2)
        helper = (ROOT / "src/helpers/radiolib/Nrf52BufferedRadioHal.h").read_text(
            encoding="ascii")
        # Removing the real override reinstates ArduinoHal's per-byte path.
        # It must fail even though all received bytes would still be correct.
        legacy = re.sub(r"  void spiTransfer\([^}]+\}\n", "", helper)
        self.assertNotEqual(helper, legacy)
        compiler = shutil.which(os.environ.get("CXX", "g++"))
        self.assertIsNotNone(compiler)
        with tempfile.TemporaryDirectory(prefix="rak3401-buffered-radio-") as folder:
            base = Path(folder)
            (base / "hal/Arduino").mkdir(parents=True)
            (base / "helpers/radiolib").mkdir(parents=True)
            (base / "hal/Arduino/ArduinoHal.h").write_text(MOCK_HAL, encoding="ascii")
            cpp, executable = base / "test.cpp", base / "test"
            cpp.write_text(HARNESS.replace("@CONSTRUCTION@", construction), encoding="ascii")
            for name, implementation, succeeds in (("buffered", helper, True),
                                                   ("per-byte", legacy, False)):
                with self.subTest(implementation=name):
                    (base / "helpers/radiolib/Nrf52BufferedRadioHal.h").write_text(
                        implementation, encoding="ascii")
                    built = subprocess.run([compiler, "-std=c++17", "-Wall", "-Wextra",
                        "-Werror", "-I", str(base), str(cpp), "-o", str(executable)],
                        capture_output=True, text=True, timeout=60)
                    self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
                    ran = subprocess.run([str(executable)], capture_output=True,
                                         text=True, timeout=10)
                    if succeeds:
                        self.assertEqual(ran.returncode, 0, ran.stdout + ran.stderr)
                    else:
                        self.assertNotEqual(ran.returncode, 0,
                                            "per-byte negative control did not fail")


if __name__ == "__main__":
    unittest.main()
