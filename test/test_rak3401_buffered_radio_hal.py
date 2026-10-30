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
struct MockSpim {
  uint32_t ENABLE = 0;
  struct { uint32_t RXDELAY = 2; } IFTIMING;
};
inline MockSpim mockSpim3;
inline MockSpim* NRF_SPIM3 = &mockSpim3;
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
struct RadioLibHal { virtual ~RadioLibHal()=default; };
struct ArduinoHal : RadioLibHal {
  bool initInterface = false;
  SPIClass* spi;
  SPISettings spiSettings;
  explicit ArduinoHal(SPIClass& bus, SPISettings settings)
      : spi(&bus), spiSettings(settings) {}
  virtual ~ArduinoHal() = default;
  virtual void spiBeginTransaction() {}
  virtual void spiTransfer(uint8_t* out, size_t length, uint8_t* in) {
    for (size_t i = 0; i < length; ++i) in[i] = spi->transfer(out[i]);
  }
};
'''


HARNESS = r'''
#include <array>
#include <initializer_list>
#include <helpers/radiolib/Nrf52BufferedRadioHal.h>
#include <helpers/radiolib/NrfRadioSpiStartupDiagHal.h>
@CLOCK_POLICY@
SPIClass SPI, SPI1;
constexpr unsigned P_LORA_NSS=1, P_LORA_DIO_1=2, P_LORA_RESET=3, P_LORA_BUSY=4;
struct Module {
  ArduinoHal* hal;
  Module(ArduinoHal* adapter, unsigned cs, unsigned irq, unsigned rst, unsigned busy)
      : hal(adapter) {
    assert(cs==1 && irq==2 && rst==3 && busy==4);
    assert(hal->spi == &SPI1 && hal->spiSettings.hz == MC_RAK3401_SPI_HZ);
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


def construction_from_target(target):
    start=target.index("#if MESH_HIL_SPI_STARTUP_DIAG",target.index("RAK3401Board board;"))
    end=target.index("RADIO_CLASS radio = new Module(",start)
    return target[start:target.index(";",end)+1]


class Rak3401BufferedRadioHalTests(unittest.TestCase):
    def test_actual_target_uses_one_transfer_per_command_on_same_spi1_at_8mhz(self):
        target = (ROOT / "variants/rak3401/target.cpp").read_text(encoding="ascii")
        clock_policy = target[target.index("#ifndef MC_RAK3401_SPI_HZ"):
                              target.index("\nnamespace {")]
        construction = construction_from_target(target)
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
            cpp.write_text(HARNESS.replace("@CONSTRUCTION@", construction)
                           .replace("@CLOCK_POLICY@", clock_policy), encoding="ascii")
            for name, implementation, succeeds in (("buffered", helper, True),
                                                   ("per-byte", legacy, False)):
                with self.subTest(implementation=name):
                    (base / "helpers/radiolib/Nrf52BufferedRadioHal.h").write_text(
                        implementation, encoding="ascii")
                    built = subprocess.run([compiler, "-std=c++17", "-Wall", "-Wextra",
                        "-Werror", "-I", str(base), "-I", str(ROOT / "src"),
                        "-I",str(ROOT / "src/helpers/radiolib"),str(cpp), "-o", str(executable)],
                        capture_output=True, text=True, timeout=60)
                    self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
                    ran = subprocess.run([str(executable)], capture_output=True,
                                         text=True, timeout=10)
                    if succeeds:
                        self.assertEqual(ran.returncode, 0, ran.stdout + ran.stderr)
                    else:
                        self.assertNotEqual(ran.returncode, 0,
                                            "per-byte negative control did not fail")

    def test_clock_dial_rejects_unqualified_spim3_speeds_and_workaround(self):
        target = (ROOT / "variants/rak3401/target.cpp").read_text(encoding="ascii")
        policy = target[target.index("#ifndef MC_RAK3401_SPI_HZ"):
                        target.index("\nnamespace {")]
        construction = construction_from_target(target)
        fixture = HARNESS.replace("@CLOCK_POLICY@", policy).replace("@CONSTRUCTION@", construction)
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / "hal/Arduino").mkdir(parents=True)
            (folder / "hal/Arduino/ArduinoHal.h").write_text(MOCK_HAL, encoding="ascii")
            (folder / "nrf_sdm.h").write_text(
                "#pragma once\n#include <cstdint>\ninline uint32_t sd_softdevice_is_enabled(uint8_t* enabled)"
                "{*enabled=0;return 0;}\n",encoding="ascii")
            cpp, binary = folder / "test.cpp", folder / "test.exe"
            cpp.write_text(fixture, encoding="ascii")
            cases = [([], True)] + [
                ([f"MC_RAK3401_SPI_HZ={clock}"], True)
                for clock in (2000000, 4000000, 8000000)] + [
                (["MC_RAK3401_SPI_HZ=16000000", "SPI_32MHZ_INTERFACE=1",
                  "NRFX_SPIM3_NRF52840_ANOMALY_198_WORKAROUND_ENABLED=1"], False),
                (["MC_RAK3401_SPI_HZ=16000000"], False),
                (["MC_RAK3401_SPI_HZ=16000000", "SPI_32MHZ_INTERFACE=1"], False),
                (["MC_RAK3401_SPI_HZ=16000000", "SPI_32MHZ_INTERFACE=0",
                  "NRFX_SPIM3_NRF52840_ANOMALY_198_WORKAROUND_ENABLED=1"], False),
                (["MC_RAK3401_SPI_HZ=16000000", "SPI_32MHZ_INTERFACE=1",
                  "NRFX_SPIM3_NRF52840_ANOMALY_198_WORKAROUND_ENABLED=0"], False),
                (["MC_RAK3401_SPI_HZ=12000000"], False),
                (["MC_RAK3401_SPI_HZ=32000000"], False)]
            diagnostic=["MC_RAK3401_SPI_HZ=16000000","MESH_HIL_SPI_STARTUP_DIAG=1",
                "MESH_HIL_PROFILE_TIMING=1","SPI_32MHZ_INTERFACE=1",
                "NRFX_SPIM3_NRF52840_ANOMALY_198_WORKAROUND_ENABLED=1","NRF52_PLATFORM=1"]
            cases.append((diagnostic,True))
            for required in diagnostic[1:-1]:
                cases.append(([flag for flag in diagnostic if flag!=required],False))
            cases.append(([flag if flag!="MESH_HIL_PROFILE_TIMING=1" else "MESH_HIL_PROFILE_TIMING=0"
                           for flag in diagnostic],False))
            cases.append(([flag if flag!="MC_RAK3401_SPI_HZ=16000000" else "MC_RAK3401_SPI_HZ=32000000"
                           for flag in diagnostic],False))
            for flags, valid in cases:
                with self.subTest(flags=flags):
                    built = subprocess.run([os.environ.get("CXX", "g++"), "-std=c++17",
                        "-Wall", "-Wextra", "-Werror", *["-D" + flag for flag in flags],
                        "-I", str(folder), "-I", str(ROOT / "src"), str(cpp),
                        str(ROOT/"src/helpers/radiolib/NrfRadioSpiStartupDiagHal.cpp"),
                        "-o", str(binary)], capture_output=True, text=True)
                    if valid:
                        self.assertEqual(built.returncode, 0, built.stderr)
                        ran = subprocess.run([str(binary)], capture_output=True, text=True)
                        self.assertEqual(ran.returncode, 0, ran.stderr)
                    else:
                        self.assertNotEqual(built.returncode, 0)
                        self.assertIn("RAK3401", built.stderr)


if __name__ == "__main__":
    unittest.main()
