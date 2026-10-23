"""Execute bytewise ESP32 radio constructors and their saved clock selection."""
from pathlib import Path
import os
import re
import shutil
import subprocess
import tempfile
import unittest

from test_sx126x_buffered_radio_hal import MOCK, ROOT


TARGETS = (
    "geprc_linkflow_900", "heltec_v2", "lilygo_t3s3_sx1276",
    "lilygo_tbeam_SX1276", "lilygo_tlora_v2_1", "meshnology_w12",
    "waveshare_esp32s3_lr1121",
)
SX1276 = set(TARGETS[:5])

PRELUDE = r'''
#include <helpers/radiolib/TunableRadioHal.h>
struct InertBoard {};
struct DacPaLevel { int dbm, dac; };
SPIClass SPI;
struct Module {
  ArduinoHal* hal;
  Module(ArduinoHal* adapter,unsigned cs,unsigned irq,unsigned reset,unsigned busy)
      : hal(adapter) { assert(cs==1 && irq==2 && reset==3 && busy==4); }
};
struct Radio {
  Module* mod;
  Radio(Module* value) : mod(value) {}
  ~Radio() { delete mod; }
};
#define RADIO_CLASS Radio
'''


class Esp32TunableTargetConstructors(unittest.TestCase):
    def test_actual_constructors_preserve_2mhz_byte_path_bus_and_pins(self):
        compiler = shutil.which(os.environ.get("CXX", "g++"))
        self.assertIsNotNone(compiler)
        cases = []
        for target in TARGETS:
            text = (ROOT / "variants" / target / "target.cpp").read_text(encoding="ascii")
            self.assertIn("#include <helpers/radiolib/TunableRadioHal.h>", text)
            prefix = text[:text.index("WRAPPER_CLASS radio_driver")]
            prefix = re.sub(r"^\s*#include[^\n]*\n", "", prefix, flags=re.MULTILINE)
            board = re.search(r"^(\w+) board;", prefix, re.MULTILINE).group(1)
            conditional_bus = "#if defined(P_LORA_SCLK)" in prefix
            for local in ((True, False) if conditional_bus else (True,)):
                name = f"case_{len(cases)}"
                select = "spi" if local else "::SPI"
                definitions = "#define P_LORA_SCLK 5\n" if local else ""
                unused_pa = "(void)POWER_LEVELS;" if target == "geprc_linkflow_900" else ""
                # Compile the production conditional block and constructors,
                # including each default-SPI fallback, without rewriting them.
                cases.append(f'''
{definitions}
namespace {name} {{
using {board}=InertBoard;
constexpr unsigned P_LORA_NSS=1,P_LORA_RESET=3,P_LORA_BUSY=4;
constexpr unsigned P_LORA_DIO_0=2,P_LORA_DIO_1={4 if target in SX1276 else 2};
{prefix}
void check() {{
  {unused_pa}
  auto& bus={select};auto& hal=radio_hal;
  assert(radio.mod->hal==&hal && TunableRadioHal::find(radio.mod->hal)==&hal);
  assert(hal.spi==&bus && hal.defaultHz()==2000000 && hal.effectiveHz()==2000000);
  assert(hal.spiSettings.hz==2000000 && hal.spiSettings.order==MSBFIRST);
  assert(hal.spiSettings.mode==SPI_MODE0 && hal.getTuning().flags==0);
  assert(hal.initInterface=={str(not local).lower()});
  assert(hal.capabilities().flags==0);
  assert(hal.capabilities().spi_clocks==(2|4|8|mesh::RadioSwitchCapabilities::Spi9));
  bus.begins=bus.ends=bus.bytes=bus.bursts=0;
  hal.init();hal.term();
  assert(bus.begins=={int(not local)} && bus.ends=={int(not local)});
  mesh::RadioSwitchTuning tuning;
  tuning.spi_mhz=9;
  assert(hal.setTuning(tuning) && hal.getTuning().spi_mhz==9);
  assert(hal.effectiveHz()==8888888 && hal.spiSettings.hz==8888888);
  uint8_t tx[]={{1,0x7f,0xff}},rx[3]={{}};
  radio.mod->hal->spiTransfer(tx,3,rx);
  assert(bus.bytes==3 && bus.bursts==0);
  for(unsigned i=0;i<3;++i) assert(rx[i]==uint8_t(tx[i]^0xa5));
  const auto previous=hal.getTuning();
  tuning.spi_mhz=16;
  assert(!hal.setTuning(tuning) && hal.getTuning()==previous);
  tuning.spi_mhz=9;tuning.flags=mesh::RadioSwitchTuning::Buffer;
  assert(!hal.setTuning(tuning) && hal.getTuning()==previous);
  tuning.spi_mhz=0;tuning.flags=0;
  assert(hal.setTuning(tuning) && hal.effectiveHz()==2000000);
  assert(hal.spiSettings.hz==2000000 && hal.spi==&bus);
  assert(bus.begins=={int(not local)} && bus.ends=={int(not local)});
}}
}}
#undef P_LORA_SCLK
''')
        self.assertEqual(len(cases), 11)
        fixture = PRELUDE + "\n".join(cases)
        fixture += "\nint main(){" + "".join(
            f"case_{index}::check();" for index in range(len(cases))) + "}\n"
        with tempfile.TemporaryDirectory(prefix="esp32-tunable-targets-") as folder:
            work = Path(folder)
            (work / "hal/Arduino").mkdir(parents=True)
            (work / "hal/Arduino/ArduinoHal.h").write_text(MOCK, encoding="ascii")
            cpp, executable = work / "test.cpp", work / "test"
            cpp.write_text(fixture, encoding="ascii")
            flags = [] if os.name == "nt" else [
                "-fsanitize=address,undefined", "-fno-pie", "-no-pie"]
            built = subprocess.run([
                compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror", *flags,
                "-DESP32_PLATFORM", "-I", str(work), "-I", str(ROOT / "src"),
                str(cpp), "-o", str(executable)],
                capture_output=True, text=True, timeout=60)
            self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
            ran = subprocess.run([str(executable)], capture_output=True,
                                 text=True, timeout=10)
            self.assertEqual(ran.returncode, 0, ran.stdout + ran.stderr)


if __name__ == "__main__":
    unittest.main()
