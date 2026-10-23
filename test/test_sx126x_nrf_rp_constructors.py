"""Compile actual conservative nRF52 and buffered RP2040 radio constructors."""
from pathlib import Path
import os
import re
import shutil
import subprocess
import tempfile
import unittest

from test_sx126x_buffered_radio_hal import MOCK, RADIO, ROOT


PREFIX = r'''
#include <helpers/radiolib/SX126xBufferedRadioHal.h>
constexpr unsigned P_LORA_NSS=1,P_LORA_DIO_1=2,P_LORA_RESET=3,P_LORA_BUSY=4;
SPIClass* testDefaultBus=nullptr;
struct Module {
  ArduinoHal* hal; bool owned=false;
  Module(ArduinoHal* adapter,unsigned cs,unsigned irq,unsigned reset,unsigned busy)
      : hal(adapter) { assert(cs==1 && irq==2 && reset==3 && busy==4); }
  Module(unsigned cs,unsigned irq,unsigned reset,unsigned busy,SPIClass& bus)
      : hal(new ArduinoHal(bus,SPISettings(2000000,MSBFIRST,SPI_MODE0))),owned(true) {
    assert(cs==1 && irq==2 && reset==3 && busy==4);
  }
  Module(unsigned cs,unsigned irq,unsigned reset,unsigned busy)
      : Module(cs,irq,reset,busy,*testDefaultBus) { hal->initInterface=true; }
  ~Module() { if (owned) delete hal; }
};
struct Radio {
  Module* mod;
  Radio(Module* value) : mod(value) {}
  ~Radio() { delete mod; }
};
#define RADIO_CLASS Radio
'''


def target_sources(architecture):
    sources=set()
    for config in sorted((ROOT/"variants").glob("*/platformio.ini")):
        text=config.read_text()
        if not re.search(r"^\s*-D\s+RADIO_CLASS=CustomSX1262\s*$",text,re.MULTILINE):
            continue
        base=re.search(r"^extends\s*=\s*(\S+)",text,re.MULTILINE)
        if not base or base.group(1) not in architecture:
            continue
        if config.parent.name=="rak3401":
            continue # Dedicated physical-board test pins its qualified SPI1 setup.
        source=config.with_name("target.cpp")
        if config.parent.name=="wio-tracker-l1-eink":
            source=ROOT/"variants/wio-tracker-l1/target.cpp"
        sources.add(source)
    return sorted(sources)


class SX126xTargetConstructors(unittest.TestCase):
    def compile_run(self,architecture,source,*,defines=()):
        compiler=shutil.which(os.environ.get("CXX","g++"))
        self.assertIsNotNone(compiler)
        with tempfile.TemporaryDirectory(prefix="sx126x-target-constructors-") as folder:
            base=Path(folder)
            (base/"hal/Arduino").mkdir(parents=True)
            (base/"hal/Arduino/ArduinoHal.h").write_text(MOCK,encoding="ascii")
            cpp,executable=base/"test.cpp",base/"test"
            cpp.write_text(source,encoding="ascii")
            built=subprocess.run([compiler,"-std=c++17","-Wall","-Wextra","-Werror",
                f"-D{architecture}",*[f"-D{item}" for item in defines],"-I",str(base),
                "-I",str(ROOT/"src"),str(cpp),"-o",str(executable)],
                capture_output=True,text=True,timeout=60)
            self.assertEqual(built.returncode,0,built.stdout+built.stderr)
            ran=subprocess.run([str(executable)],capture_output=True,text=True,timeout=10)
            self.assertEqual(ran.returncode,0,ran.stdout+ran.stderr)

    def test_actual_rp2040_constructions_keep_buffered_selected_bus(self):
        for arch,bases in (("RP2040_PLATFORM",{"rp2040_base"}),):
            with self.subTest(architecture=arch):
                cases=[]
                sources=target_sources(bases)
                self.assertTrue(sources)
                for source in sources:
                    text=source.read_text()
                    self.assertIn("#include <helpers/radiolib/SX126xBufferedRadioHal.h>",
                                  text,str(source))
                    constructions=re.findall(
                        r"^static SX126xBufferedRadioHal radioHal\(([^;]+)\);\n"
                        r"(RADIO_CLASS radio = new Module\(&radioHal,[^;]+;)",
                        text,re.MULTILINE)
                    self.assertTrue(constructions,str(source))
                    legacy=re.findall(r"new Module\(P_LORA_NSS[^;]+;",text)
                    self.assertEqual(len(legacy),0,str(source))
                    for ordinal,(arguments,module) in enumerate(constructions):
                        bus=arguments.split(",")[0]
                        expected_bus="SPI1" if source.parent.name in {
                            "rak11310","rpi_picow","waveshare_rp2040_lora"} else "SPI"
                        self.assertEqual(bus,expected_bus,str(source))
                        # These are the pre-existing Module() default-bus
                        # branches. Every other constructor passed its bus
                        # explicitly and must leave begin/end board-owned.
                        owns=source.parent.name=="xiao_rp2040" or (
                            source.parent.name in {"heltec_t096","heltec_t1","heltec_t114"}
                            and ordinal==1)
                        name=f"case_{len(cases)}"
                        cases.append((name,f'''
namespace {name} {{
SPIClass SPI,SPI1;
static SX126xBufferedRadioHal radioHal({arguments});
{module}
void check() {{
  assert(radio.mod->hal==&radioHal && radioHal.spi==&{bus});
  assert(radioHal.spiSettings.hz==8000000);
  assert(radioHal.initInterface=={str(owns).lower()});
  radio.mod->hal->init();radio.mod->hal->term();
  assert({bus}.begins=={int(owns)} && {bus}.ends=={int(owns)});
}}
}}
'''))
                fixture=PREFIX+"\n".join(code for _,code in cases)
                fixture+="\nint main() {"+"".join(f"{name}::check();" for name,_ in cases)+"}\n"
                self.compile_run(arch,fixture)

    def test_all_new_nrf52_spim3_defaults_keep_prior_2mhz_byte_path(self):
        cases=[]
        sources=target_sources({"nrf52_base","rak4631_hw"})
        self.assertEqual(len(sources),32)
        for source in sources:
            text=source.read_text()
            self.assertNotIn("BufferedRadioHal",text,str(source))
            constructions=re.findall(r"^RADIO_CLASS radio = new Module\(P_LORA_NSS[^;]+;",text,re.MULTILINE)
            fallback=source.parent.name in {"heltec_t096","heltec_t1","heltec_t114"}
            self.assertEqual(len(constructions),2 if fallback else 1,str(source))
            for ordinal,construction in enumerate(constructions):
                owns=fallback and ordinal==1
                self.assertEqual(construction.endswith(", SPI);"),not owns,str(source))
                name=f"case_{len(cases)}"
                cases.append((name,f'''
namespace {name} {{
SPIClass SPI;
struct BindDefaultBus {{ BindDefaultBus() {{testDefaultBus=&SPI;}} }} bindDefaultBus;
{construction}
void check() {{
  assert(radio.mod->owned && radio.mod->hal->spi==&SPI);
  assert(radio.mod->hal->spiSettings.hz==2000000);
  assert(radio.mod->hal->initInterface=={str(owns).lower()});
  radio.mod->hal->init();radio.mod->hal->term();
  assert(SPI.begins=={int(owns)} && SPI.ends=={int(owns)});
  uint8_t tx[]={{1,0x7f,0xff}},rx[3]={{}};
  radio.mod->hal->spiTransfer(tx,3,rx);
  assert(SPI.bytes==3 && SPI.bursts==0 && rx[0]==(1^0xa5) && rx[2]==(0xff^0xa5));
}}
}}
'''))
        self.assertEqual(len(cases),35)
        fixture=PREFIX+"\n".join(code for _,code in cases)
        fixture+="\nint main() {"+"".join(f"{name}::check();" for name,_ in cases)+"}\n"
        self.compile_run("NRF52_PLATFORM",fixture)

    def test_muzi_uno_and_lr1121_duo_keep_prior_constructor(self):
        text=(ROOT/"variants/muzi_base/target.cpp").read_text()
        constructor=re.search(r"^RADIO_CLASS radio = new Module\(P_LORA_NSS[^;]+;",text,re.MULTILINE)
        self.assertIsNotNone(constructor)
        self.assertNotIn("BufferedRadioHal",text)
        fixture=PREFIX+"\nSPIClass SPI;\n"+constructor.group(0)+r'''
int main() {
  assert(radio.mod->hal->spi==&SPI);
  assert(radio.mod->owned && radio.mod->hal->spiSettings.hz==2000000);
}
'''
        for definitions in ((),("USE_SX1262",)):
            with self.subTest(defines=definitions):
                self.compile_run("NRF52_PLATFORM",fixture,defines=definitions)

    def test_lr1110_m4_keeps_manual_spi_start_and_prior_2mhz_byte_path(self):
        text=(ROOT/"variants/thinknode_m4/target.cpp").read_text()
        construction=re.search(r"^RADIO_CLASS radio = new Module\(P_LORA_NSS[^;]+;",text,re.MULTILINE)
        self.assertIsNotNone(construction)
        self.assertNotIn("BufferedRadioHal",text)
        self.assertIn("SPI.setPins(P_LORA_MISO, P_LORA_SCLK, P_LORA_MOSI);",text)
        self.assertIn("SPI.begin();",text)
        self.assertIn("int status = radio.begin(",text)
        fixture=PREFIX+"\nSPIClass SPI;\n"+construction.group(0)+r'''
int main() {
  assert(radio.mod->owned && radio.mod->hal->spi==&SPI);
  assert(radio.mod->hal->spiSettings.hz==2000000 && !radio.mod->hal->initInterface);
  radio.mod->hal->init();radio.mod->hal->term();
  assert(SPI.begins==0 && SPI.ends==0);
  uint8_t tx[]={1,0x7f,0xff},rx[3]={};
  radio.mod->hal->spiTransfer(tx,3,rx);
  assert(SPI.bursts==0 && SPI.bytes==3 && rx[0]==(1^0xa5));
}
'''
        self.compile_run("NRF52_PLATFORM",fixture)

    def test_existing_lr1110_buffered_constructors_remain_unchanged(self):
        cases=[]
        for name in ("minewsemi_me25ls01","t1000-e","thinknode_m3","wio_wm1110"):
            text=(ROOT/"variants"/name/"target.cpp").read_text()
            construction=re.search(r"^Nrf52BufferedRadioHal radioHal\(SPI\);\n"
                                   r"RADIO_CLASS radio = new Module\([^;]+;",text,re.MULTILINE)
            self.assertIsNotNone(construction,name)
            namespace=f"case_{len(cases)}"
            cases.append((namespace,f'''
namespace {namespace} {{
SPIClass SPI;
{construction.group(0)}
void check() {{
  assert(radio.mod->hal==&radioHal && radioHal.spi==&SPI);
  assert(radioHal.spiSettings.hz==16000000 && !radioHal.initInterface);
  uint8_t tx[]={{0x86,0,1}},rx[3]={{}};
  radio.mod->hal->spiTransfer(tx,3,rx);
  assert(SPI.bursts==1 && SPI.bytes==0 && rx[0]==(0x86^0xa5));
}}
}}
'''))
        fixture=PREFIX+"\n".join(code for _,code in cases)
        fixture+="\nint main() {"+"".join(f"{name}::check();" for name,_ in cases)+"}\n"
        self.compile_run("NRF52_PLATFORM",fixture)


if __name__=="__main__":
    unittest.main()
