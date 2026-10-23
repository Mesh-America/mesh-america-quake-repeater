"""Exercise the private Tag/Tower SPI mapping, SDK indices and legacy defaults."""

import importlib.util
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import types
import unittest

from test_radio_receive_contract import method
from test_sx126x_buffered_radio_hal import MOCK


ROOT = Path(__file__).resolve().parents[1]
SDK = Path.home() / ".platformio/packages/framework-arduinoadafruitnrf52"
SPEC = importlib.util.spec_from_file_location("nrf52_hil_spim1", ROOT / "scripts/nrf52_hil_spim1.py")
PATCH = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PATCH)
CONFIG = ROOT / "src/helpers/nrf52/Nrf52HilSpim1Config.h"
OWNER = ROOT / "src/helpers/nrf52/Nrf52HilSpim1Owner.h"
BASE = ["-DNRF52_PLATFORM", "-DNRF52840_XXAA"]
FAST = ["-DMC_NRF52_HIL_SPIM1_RADIO=1", "-DMC_NRF52_HIL_SPIM1_BOUND=1"]


class BuildEnv(dict):
    def __init__(self, directory, flags=(), defines=(), mcu="nrf52840", platform="nordicnrf52"):
        super().__init__(BUILD_FLAGS=flags, CPPDEFINES=list(defines))
        self.directory, self.mcu, self.platform = directory, mcu, platform
        self.middleware = []

    def subst(self, value):
        return value.replace("$PROJECT_DIR", str(ROOT)).replace("$BUILD_DIR", str(self.directory))

    def PioPlatform(self):
        return types.SimpleNamespace(name=self.platform, get_package_dir=lambda name: str(SDK))

    def BoardConfig(self):
        return {"build.mcu": self.mcu}

    def AppendUnique(self, **kwargs):
        for name, values in kwargs.items():
            self.setdefault(name, [])
            self[name].extend(value for value in values if value not in self[name])

    def AddBuildMiddleware(self, callback, pattern):
        self.middleware.append((callback, pattern))

    def File(self, value):
        return Path(value)


@unittest.skipUnless(SDK.is_dir(), "pinned nRF52 framework package unavailable")
class Nrf52HilSpim1Tests(unittest.TestCase):
    def command(self, args, **kwargs):
        result = subprocess.run(args, capture_output=True, text=True, timeout=60, **kwargs)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def test_default_registers_no_hook_or_forced_sdk_configuration(self):
        with tempfile.TemporaryDirectory(dir="/var/tmp") as directory:
            for flags in ((), "-DMC_NRF52_HIL_SPIM1_RADIO=0", "-UMC_NRF52_HIL_SPIM1_RADIO"):
                env = BuildEnv(Path(directory) / "not-created", flags)
                PATCH.install(env)
                self.assertEqual(env.middleware, [])
                self.assertNotIn("CCFLAGS", env)
                self.assertFalse(env.directory.exists())

    def test_scons_entry_and_private_sdk_copy_are_bound_without_editing_sdk(self):
        source = (ROOT / "scripts/nrf52_hil_spim1.py").read_text(encoding="ascii")
        with tempfile.TemporaryDirectory(dir="/var/tmp") as directory:
            directory = Path(directory)
            env = BuildEnv(directory, "-DMC_NRF52_HIL_SPIM1_RADIO=1 -DRAK_WISMESH_TAG")
            scope = {"Import": lambda name: scope.update(env=env)}
            exec(compile(source, "nrf52_hil_spim1.py", "exec"), scope)
            self.assertNotIn("__file__", scope)
            self.assertEqual(len(env.middleware), 1)
            self.assertEqual(env["CCFLAGS"], ["-include" + str(CONFIG)])
            self.assertIn(("MC_NRF52_HIL_SPIM1_BOUND", 1), env["CPPDEFINES"])
            sdk_path = SDK / "libraries/SPI/SPI.cpp"
            original = sdk_path.read_bytes()
            node = types.SimpleNamespace(srcnode=lambda: types.SimpleNamespace(get_abspath=lambda: str(sdk_path)))
            private = PATCH.replace_spi(env, node)
            self.assertTrue(private.is_relative_to(directory))
            self.assertEqual(private.read_text(), PATCH.patched_spi(original.decode("ascii")))
            self.assertEqual(sdk_path.read_bytes(), original)
            stamp = private.stat().st_mtime_ns
            self.assertEqual(PATCH.replace_spi(env, node).stat().st_mtime_ns, stamp)
            with self.assertRaises(RuntimeError):
                PATCH.patched_spi(original.decode("ascii") + "// SDK changed\n")

    def test_build_script_rejects_unsupported_targets_and_new_bus_owners(self):
        with tempfile.TemporaryDirectory(dir="/var/tmp") as directory:
            for flags, extra in (
                ("-DMC_NRF52_HIL_SPIM1_RADIO=2", {}),
                ("-DMC_NRF52_HIL_SPIM1_RADIO=1 -DHELTEC_T096", {}),
                ("-DMC_NRF52_HIL_SPIM1_RADIO=1 -DHELTEC_TOWER_V2 -DRAK_WISMESH_TAG", {}),
                ("-DMC_NRF52_HIL_SPIM1_RADIO=1 -DRAK_WISMESH_TAG -DETHERNET_ENABLED=0", {}),
                ("-DMC_NRF52_HIL_SPIM1_RADIO=1 -DRAK_WISMESH_TAG -DENV_PIN_SDA=4", {}),
                ("-DMC_NRF52_HIL_SPIM1_RADIO=1 -DRAK_WISMESH_TAG", {"mcu": "nrf52832"}),
                ("-DMC_NRF52_HIL_SPIM1_RADIO=1 -DRAK_WISMESH_TAG", {"platform": "espressif32"}),
            ):
                with self.subTest(flags=flags, extra=extra), self.assertRaises(RuntimeError):
                    PATCH.install(BuildEnv(Path(directory), flags, **extra))

    def test_real_sdk_mapping_indices_constructor_recovery_and_second_bus(self):
        compiler = shutil.which(os.environ.get("CXX", "g++"))
        self.assertIsNotNone(compiler)
        sdk_source = (SDK / "libraries/SPI/SPI.cpp").read_text()
        sdk_header = (SDK / "cores/nRF5/nordic/nrfx/drivers/include/nrfx_spim.h").read_text()
        enum = re.search(r"enum \{\n#if NRFX_CHECK\(NRFX_SPIM0_ENABLED\).*?\n\};", sdk_header, re.S).group(0)
        sdk_constructor = sdk_source[sdk_source.index("SPIClass::SPIClass("):sdk_source.index("void SPIClass::begin()")]
        mock = MOCK.replace("struct SPIClass {", r'''
struct MockSpim { unsigned number; };
inline MockSpim dev1{1},dev2{2},dev3{3};
inline MockSpim* NRF_SPIM1=&dev1;
inline MockSpim* NRF_SPIM2=&dev2;
inline MockSpim* NRF_SPIM3=&dev3;
using NRF_SPIM_Type=MockSpim;
inline unsigned g_ADigitalPinMap[48]={};
#define NRF_SPIM_BIT_ORDER_MSB_FIRST 0
struct SPIClass {
  struct { MockSpim* p_reg; unsigned drv_inst_idx; } _spim;
  void* _p_spi=nullptr;
  bool initialized=false;
  unsigned _uc_pinMiso=0,_uc_pinSCK=0,_uc_pinMosi=0,_dataMode=0,_bitOrder=0;
  SPIClass(NRF_SPIM_Type*,uint8_t,uint8_t,uint8_t);
  void setPins(unsigned miso,unsigned sck,unsigned mosi) { _uc_pinMiso=miso;_uc_pinSCK=sck;_uc_pinMosi=mosi; }
''')
        for board, variant in (("RAK_WISMESH_TAG", "rak_wismesh_tag"), ("HELTEC_TOWER_V2", "heltec_tower_v2")):
            text = (ROOT / "variants" / variant / "target.cpp").read_text()
            start = text.index("#if MC_NRF52_HIL_SPIM1_RADIO\nstatic")
            constructor = text[start:text.index("#endif", start) + len("#endif")]
            initialization = method(text, "bool radio_init()")
            for fast in (False, True):
                with self.subTest(board=board, fast=fast), tempfile.TemporaryDirectory(dir="/var/tmp") as directory:
                    directory = Path(directory)
                    (directory / "hal/Arduino").mkdir(parents=True)
                    (directory / "hal/Arduino/ArduinoHal.h").write_text(mock, encoding="ascii")
                    mapping_source = PATCH.patched_spi(sdk_source) if fast else sdk_source
                    mapping = mapping_source[mapping_source.index("#ifndef SPI_32MHZ_INTERFACE"):mapping_source.rindex("#endif // NRF52840_XXAA")]
                    fixture = r'''
#include <cassert>
#include <nrfx_config.h>
#define NRFX_CHECK(value) (value)
@ENUM@
#include <hal/Arduino/ArduinoHal.h>
#define SPI_INTERFACES_COUNT 2
#define WIRE_INTERFACES_COUNT 1
#include <helpers/nrf52/Nrf52HilSpim1Owner.h>
#include <helpers/radiolib/Nrf52BufferedRadioHal.h>
#define PIN_SPI_MISO 9
#define PIN_SPI_MOSI 10
#define PIN_SPI_SCK 8
#define PIN_SPI1_MISO 25
#define PIN_SPI1_MOSI 26
#define PIN_SPI1_SCK 29
constexpr unsigned P_LORA_NSS=4,P_LORA_DIO_1=1,P_LORA_RESET=2,P_LORA_BUSY=3;
@SDK_CONSTRUCTOR@
@MAPPING@
struct Module {
 ArduinoHal* hal; bool owns;
 Module(ArduinoHal* a,unsigned,unsigned,unsigned,unsigned):hal(a),owns(false) {}
 Module(unsigned a,unsigned b,unsigned c,unsigned d,SPIClass& bus)
  :Module(new ArduinoHal(bus,SPISettings(2000000,MSBFIRST,SPI_MODE0)),a,b,c,d) {owns=true;}
 ~Module() {if(owns)delete hal;}
};
struct Radio {
 Module* module; bool next=true; unsigned starts=0;
 Radio(Module* value):module(value) {} ~Radio(){delete module;}
 bool std_init(SPIClass* bus) {assert(bus==&SPI && module->hal->spi==bus);bus->begin();++starts;return next;}
};
#define RADIO_CLASS Radio
@CONSTRUCTOR@
unsigned Wire=0;
struct Rtc {void begin(unsigned){}} rtc_clock;
@INITIALIZATION@
extern "C" unsigned c_indices(void);
int main() {
 assert(SPI._spim.p_reg->number==(MC_NRF52_HIL_SPIM1_RADIO?1:3));
 assert(SPI1._spim.p_reg->number==2);
 assert(SPI._spim.drv_inst_idx==(MC_NRF52_HIL_SPIM1_RADIO?0:1));
 assert(SPI1._spim.drv_inst_idx==unsigned(MC_NRF52_HIL_SPIM1_RADIO));
 assert(c_indices()==(MC_NRF52_HIL_SPIM1_RADIO?0x3210u:0x2100u));
 assert(radio.module->hal->spi==&SPI && !radio.module->hal->initInterface);
 assert(radio.module->hal->spiSettings.hz==8000000);
 assert(radio_init() && SPI.begins==1 && SPI1.begins==0);
 uint8_t tx[]={0x86,1,2,3},rx[4]={};radio.module->hal->spiTransfer(tx,4,rx);
 assert(SPI.bursts==unsigned(MC_NRF52_HIL_SPIM1_RADIO));
 assert(SPI.bytes==unsigned(MC_NRF52_HIL_SPIM1_RADIO?0:4));
 assert(rx[3]==uint8_t(tx[3]^0xa5));
 radio.module->hal->init();radio.module->hal->term();assert(SPI.ends==0);
 SPI.end();radio.next=false;assert(!radio_init());radio.next=true;assert(radio_init());
 assert(SPI.ends==1 && SPI.begins==3 && radio.starts==3 && SPI1.begins==0);
}
'''.replace("@ENUM@", enum).replace("@SDK_CONSTRUCTOR@", sdk_constructor).replace("@MAPPING@", mapping).replace("@CONSTRUCTOR@", constructor).replace("@INITIALIZATION@", initialization)
                    c_source = '#include <nrfx_config.h>\n#define NRFX_CHECK(value) (value)\n' + enum + r'''
unsigned c_indices(void) {
#if MC_NRF52_HIL_SPIM1_RADIO
 return NRFX_SPIM_ENABLED_COUNT*0x1000u+NRFX_SPIM3_INST_IDX*0x100u+NRFX_SPIM2_INST_IDX*0x10u+NRFX_SPIM1_INST_IDX;
#else
 return NRFX_SPIM_ENABLED_COUNT*0x1000u+NRFX_SPIM3_INST_IDX*0x100u+NRFX_SPIM2_INST_IDX*0x10u;
#endif
}
'''
                    cpp, c, obj, executable = [directory / name for name in ("test.cpp", "indices.c", "indices.o", "test")]
                    cpp.write_text(fixture, encoding="ascii")
                    c.write_text(c_source, encoding="ascii")
                    flags = BASE + ["-D" + board, "-I" + str(SDK / "cores/nRF5/nordic"), "-I" + str(ROOT / "src"), "-I" + str(directory)]
                    if fast:
                        flags += FAST + ["-include" + str(CONFIG)]
                    self.command(["gcc", "-std=c11", "-Wall", "-Wextra", "-Werror", *flags, "-c", str(c), "-o", str(obj)])
                    self.command([compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror", *flags, str(cpp), str(obj), "-o", str(executable)])
                    self.command([str(executable)])

    def test_compile_gates_reject_conflicting_or_unbound_candidates(self):
        with tempfile.TemporaryDirectory(dir="/var/tmp") as directory:
            directory = Path(directory)
            source = directory / "gate.cpp"
            source.write_text('#include <helpers/nrf52/Nrf52HilSpim1Owner.h>\n', encoding="ascii")
            valid = BASE + FAST + ["-DRAK_WISMESH_TAG", "-DWIRE_INTERFACES_COUNT=1", "-DSPI_INTERFACES_COUNT=2"]
            for flags in (
                ["-DMC_NRF52_HIL_SPIM1_RADIO=2"],
                FAST,
                BASE + FAST + ["-DHELTEC_T096"],
                [item for item in valid if "_BOUND=" not in item],
                valid + ["-DSPI_32MHZ_INTERFACE=1"],
                valid + ["-DETHERNET_ENABLED=0"],
                valid + ["-DENV_PIN_SCL=4"],
                valid + ["-DNRFX_SPIM3_NRF52840_ANOMALY_198_WORKAROUND_ENABLED=1"],
                valid + ["-DNRFX_H__"],
                [item for item in valid if "WIRE_INTERFACES_COUNT=" not in item] + ["-DWIRE_INTERFACES_COUNT=2"],
            ):
                with self.subTest(flags=flags):
                    result = subprocess.run(["g++", "-E", *flags, "-I" + str(ROOT / "src"), "-I" + str(SDK / "cores/nRF5/nordic"), str(source)], capture_output=True, text=True, timeout=15)
                    self.assertNotEqual(result.returncode, 0, result.stdout)
                    self.assertIn("nRF52 HIL SPIM1", result.stderr)

    def test_actual_sdk_spim1_vector_and_wire1_owner_do_not_collide(self):
        driver = (SDK / "cores/nRF5/nordic/nrfx/drivers/src/nrfx_spim.c").read_text()
        header = (SDK / "cores/nRF5/nordic/nrfx/drivers/include/nrfx_spim.h").read_text()
        aliases = (SDK / "cores/nRF5/nordic/nrfx/soc/nrfx_irqs_nrf52840.h").read_text()
        wire = (SDK / "libraries/Wire/Wire_nRF52.cpp").read_text()
        enum = re.search(r"enum \{\n#if NRFX_CHECK\(NRFX_SPIM0_ENABLED\).*?\n\};", header, re.S).group(0)
        alias = re.search(r"^#define nrfx_spim_1_irq_handler\s+\S+", aliases, re.M).group(0)
        body = re.search(r"#if NRFX_CHECK\(NRFX_SPIM1_ENABLED\)\nvoid nrfx_spim_1_irq_handler\(void\)\n\{.*?\n\}\n#endif", driver, re.S).group(0)
        wire_owner = wire[wire.index("#if WIRE_INTERFACES_COUNT > 1"):wire.rindex("#endif // NRF52_SERIES")]
        source = '#include <cassert>\n#include <helpers/nrf52/Nrf52HilSpim1Owner.h>\n#define NRFX_CHECK(value) (value)\n' + enum + "\n" + alias + r'''
unsigned calls=0, m_cb[NRFX_SPIM_ENABLED_COUNT]={};
constexpr unsigned NRF_SPIM1=1;
void irq_handler(unsigned device,unsigned* control) {
 assert(device==1 && control==&m_cb[NRFX_SPIM1_INST_IDX]);++calls;
}
''' + body + "\n" + wire_owner + r'''
int main() {SPIM1_SPIS1_TWIM1_TWIS1_SPI1_TWI1_IRQHandler();assert(calls==1);}
'''
        with tempfile.TemporaryDirectory(dir="/var/tmp") as directory:
            directory = Path(directory)
            cpp, executable = directory / "irqs.cpp", directory / "irqs"
            cpp.write_text(source, encoding="ascii")
            self.command(["g++", "-std=c++17", "-Wall", "-Wextra", "-Werror", *BASE, *FAST,
                "-DRAK_WISMESH_TAG", "-DWIRE_INTERFACES_COUNT=1", "-DSPI_INTERFACES_COUNT=2",
                "-I" + str(ROOT / "src"), "-I" + str(SDK / "cores/nRF5/nordic"),
                "-include" + str(CONFIG), str(cpp), "-o", str(executable)])
            self.command([str(executable)])

    def test_production_recipes_and_t096_features_are_unchanged(self):
        active = "\n".join(line for path in [ROOT / "platformio.ini", *sorted((ROOT / "variants").glob("*/platformio.ini"))] for line in path.read_text().splitlines() if not line.lstrip().startswith(";"))
        self.assertNotIn("-DMC_NRF52_HIL_SPIM1_RADIO", active)
        self.assertIn("pre:scripts/nrf52_hil_spim1.py", active)
        self.assertNotIn("MC_NRF52_HIL_SPIM1_RADIO", (ROOT / "variants/heltec_t096/target.cpp").read_text())
        self.assertRegex((ROOT / "variants/heltec_t096/variant.h").read_text(), r"#define WIRE_INTERFACES_COUNT\s+\(2\)")


if __name__ == "__main__":
    unittest.main()
