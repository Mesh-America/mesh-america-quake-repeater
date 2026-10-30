"""Execute the actual bounded HIL read probe and its production HAL setter."""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest

from test_rak3401_buffered_radio_hal import MOCK_HAL


ROOT=Path(__file__).resolve().parents[1]
HELPER=ROOT/"src/helpers/radiolib/NrfRadioSpiReadProbe.cpp"
FLAGS=["-DNRF52_PLATFORM=1","-DMESH_HIL_SPI_STARTUP_DIAG=1",
       "-DMESH_HIL_PROFILE_TIMING=1","-DSPI_32MHZ_INTERFACE=1",
       "-DNRFX_SPIM3_NRF52840_ANOMALY_198_WORKAROUND_ENABLED=1",
       "-DMC_RAK3401_SPI_HZ=8000000","-DMESH_HIL_SPI_READ_PROBE=1"]

SDK=r'''
#pragma once
#include <cstdint>
extern bool sd_enabled;
inline uint32_t sd_softdevice_is_enabled(uint8_t* enabled){*enabled=sd_enabled;return 0;}
'''

MOCK=MOCK_HAL.replace("#include <cassert>","#include <cassert>\n#include <nrf_sdm.h>")
MOCK=MOCK.replace("  uint32_t ENABLE = 0;","  uint32_t ENABLE = 0, FREQUENCY = 0;")
MOCK=MOCK.replace("  virtual void spiBeginTransaction() {}",r'''
  unsigned transactions=0,ends=0;
  virtual void spiBeginTransaction(){++transactions;mockSpim3.FREQUENCY=spiSettings.hz==8000000?0x80000000:0x0a000000;}
  virtual void spiEndTransaction(){++ends;}
''')
MOCK=MOCK.replace("for (size_t i = 0; i < length; ++i) rx[i] = tx[i] ^ 0xa5;",r'''
    assert(tx && tx[0]==0x11);
    for(size_t i=0;i<length;++i)rx[i]=i<2?0xa2:(mockSpim3.FREQUENCY==0x0a000000?0x16:1);
''')

FIXTURE=r'''
#include <cassert>
#include <helpers/radiolib/NrfRadioSpiStartupDiagHal.h>
bool sd_enabled=false;
using namespace mesh;
using namespace mesh::spireadprobe;
struct ModuleMock {
 NrfRadioSpiStartupDiagHal& hal;
 struct {uint32_t timeout=5000;} spiConfig;
 unsigned calls=0,fast_reads=0;
 bool refuse_fast=false,fail_final=false;
 explicit ModuleMock(NrfRadioSpiStartupDiagHal& adapter):hal(adapter){}
 int16_t SPIreadStream(uint16_t command,uint8_t* type,size_t length,bool wait,bool verify){
   assert(command==0x11&&length==1&&wait&&!verify);
   assert(spiConfig.timeout==20);
   ++calls;
   if(fail_final&&calls>32)return -705; // Failure before any SPI access.
   hal.spiBeginTransaction();
   uint8_t tx[3]={0x11,0,0},rx[3]{};
   const bool fast=mockSpim3.FREQUENCY==0x0a000000;
   sd_enabled=refuse_fast&&fast;
   hal.spiTransfer(tx,3,rx);
   sd_enabled=false;
   hal.spiEndTransaction();
   // Copy real mock-wire RX as Module does after its completed transfer.
   if(fast)++fast_reads;
   *type=rx[2];
   return fast?(refuse_fast?-707:-20):0;
 }
};
int main(){
 SPIClass bus;NrfRadioSpiStartupDiagHal hal(bus,8000000);
 ModuleMock module(hal);
#if TEST_REFUSE_FAST
 module.refuse_fast=true;
#endif
#if TEST_FAIL_FINAL
 module.fail_final=true;
#endif
 assert(!hal.setDiagnosticSpiFrequency(32000000));
 run(hal,module,spistartup::mesh_hil_spi_startup);
 const auto& capture=mesh_hil_spi_read_probe;
 assert(capture.magic==0x4d435352&&capture.version==1&&capture.size_bytes==296);
 assert(capture.runs==1&&capture.complete==1&&capture.active_phase==UINT32_MAX);
 assert(module.spiConfig.timeout==5000);
 assert(module.calls==48&&module.fast_reads==16);
 for(unsigned phase=0;phase<3;++phase){
   const auto& sample=capture.phases[phase];
   assert(sample.reads==16);
   assert(sample.requested_hz==(phase==1?16000000:8000000));
   if(phase==1){
     assert(sample.api_errors==16&&sample.api_ok==0&&sample.other_types==16&&sample.lora_types==0);
     assert(sample.first_frequency==0x0a000000&&sample.last_frequency==0x0a000000);
#if TEST_REFUSE_FAST
     assert(sample.first_result==-707&&sample.last_result==-707);
     assert(sample.first_type==0x2a&&sample.last_type==0x2a);
     assert(sample.refusals_after-sample.refusals_before==16);
     assert(sample.first_rx[0]==UINT32_MAX&&sample.last_rx[2]==UINT32_MAX);
#else
     assert(sample.first_result==-20&&sample.last_result==-20);
     assert(sample.first_type==0x16&&sample.last_type==0x16);
     assert(sample.refusals_after==sample.refusals_before);
     assert(sample.first_rx[0]==0xa2&&sample.last_rx[2]==0x16);
#endif
   }else if(TEST_FAIL_FINAL&&phase==2){
     assert(sample.api_errors==16&&sample.api_ok==0&&sample.other_types==16);
     assert(sample.first_result==-705&&sample.last_result==-705&&sample.last_type==0xff);
     assert(sample.first_rx[0]==UINT32_MAX&&sample.last_rx[2]==UINT32_MAX);
     assert(sample.queries_after==sample.queries_before);
   }else{
     assert(sample.api_ok==16&&sample.api_errors==0&&sample.lora_types==16&&sample.other_types==0);
     assert(sample.first_result==0&&sample.last_result==0&&sample.first_type==1&&sample.last_type==1);
     assert(sample.first_rx[0]==0xa2&&sample.last_rx[2]==1);
     assert(sample.first_frequency==0x80000000&&sample.last_frequency==0x80000000);
     assert(sample.queries_after-sample.queries_before==16);
   }
 }
 // Final no-transfer transaction restores physical8MHz even if all final
 // Module reads returned early. A second recovery-init call cannot rerun it.
 assert(capture.restored_hz==8000000&&capture.restored_frequency==0x80000000);
 assert(mockSpim3.FREQUENCY==0x80000000&&hal.spiSettings.hz==8000000);
 assert(trailingBaselineHealthy()==!TEST_FAIL_FINAL);
 // Even an otherwise healthy trailing baseline is invalid if SD refused
 // a frame. Incomplete captures must never authorize normal handoff either.
 ++mesh_hil_spi_read_probe.phases[2].refusals_after;
 assert(!trailingBaselineHealthy());
 --mesh_hil_spi_read_probe.phases[2].refusals_after;
 mesh_hil_spi_read_probe.complete=0;assert(!trailingBaselineHealthy());
 mesh_hil_spi_read_probe.complete=1;
 const unsigned calls=module.calls,transactions=hal.transactions;
 run(hal,module,spistartup::mesh_hil_spi_startup);
 assert(module.calls==calls&&hal.transactions==transactions&&capture.runs==1);
}
'''


class NrfRadioSpiReadProbeTests(unittest.TestCase):
    def test_real_probe_restores_8mhz_after_fast_failure_refusal_and_early_return(self):
        with tempfile.TemporaryDirectory(prefix="nrf-spi-read-probe-") as directory:
            folder=Path(directory);(folder/"hal/Arduino").mkdir(parents=True)
            (folder/"nrf_sdm.h").write_text(SDK,encoding="ascii")
            (folder/"hal/Arduino/ArduinoHal.h").write_text(MOCK,encoding="ascii")
            source=folder/"test.cpp";source.write_text(FIXTURE,encoding="ascii")
            binary=folder/"test"
            for refuse,fail_final in ((0,0),(1,0),(0,1)):
                built=subprocess.run([os.environ.get("CXX","c++"),"-std=c++17","-Wall","-Wextra","-Werror",
                    "-fsanitize=address,undefined","-fno-sanitize-recover=all","-fno-pie","-no-pie",
                    f"-DTEST_REFUSE_FAST={refuse}",f"-DTEST_FAIL_FINAL={fail_final}",*FLAGS,
                    "-I",str(folder),"-I",str(ROOT/"src"),str(source),
                    str(HELPER),str(ROOT/"src/helpers/radiolib/NrfRadioSpiStartupDiagHal.cpp"),"-o",str(binary)],
                    capture_output=True,text=True,env={**os.environ,"TMPDIR":str(folder)})
                self.assertEqual(built.returncode,0,built.stderr)
                ran=subprocess.run([str(binary)],capture_output=True,text=True)
                self.assertEqual(ran.returncode,0,ran.stdout+ran.stderr)

    def test_default_off_has_no_code_ram_or_sdk_dependencies(self):
        with tempfile.TemporaryDirectory(prefix="nrf-spi-read-probe-off-") as directory:
            output=Path(directory)/"probe.o"
            for flags in ([],["-DMESH_HIL_SPI_READ_PROBE=0"]):
                built=subprocess.run([os.environ.get("CXX","c++"),"-std=c++17",*flags,
                    "-I",str(ROOT/"src"),"-c",str(HELPER),"-o",str(output)],capture_output=True,text=True)
                self.assertEqual(built.returncode,0,built.stderr)
                symbols=subprocess.run(["nm","--defined-only",str(output)],capture_output=True,text=True)
                self.assertEqual(symbols.returncode,0,symbols.stderr)
                self.assertEqual(symbols.stdout.strip(),"")

    def test_probe_requires_all_hil_controller_workaround_and_boot_clock_guards(self):
        for required in FLAGS[:-1]:
            flags=[flag for flag in FLAGS if flag!=required]
            if required=="-DMC_RAK3401_SPI_HZ=8000000":
                flags.append("-DMC_RAK3401_SPI_HZ=16000000")
            result=subprocess.run([os.environ.get("CXX","c++"),"-E","-x","c++",*flags,
                "-I",str(ROOT/"src"),"-"],input="#include <helpers/radiolib/NrfRadioSpiReadProbe.h>\n",
                capture_output=True,text=True)
            self.assertNotEqual(result.returncode,0,required)
            self.assertIn("SPI read probe",result.stderr)

    def test_target_runs_probe_only_after_success_and_default_does_not_call_it(self):
        source=(ROOT/"variants/rak3401/target.cpp").read_text()
        init=source[source.index("bool radio_init() {"):source.index("uint32_t radio_fallback_rng_seed()")]
        calls="mesh::spireadprobe::run(radioHal, *radio.getMod(), mesh::spistartup::mesh_hil_spi_startup);"
        helper=source[source.index("static bool finishSpiReadProbe() {"):source.index("bool radio_init() {")]
        self.assertEqual(helper.count(calls),1)
        self.assertLess(helper.index(".runs) return true;"),helper.index(calls))
        self.assertIn("return board.recoverRadio() && radio.std_init(&SPI1);",helper)
        self.assertIn("if (radio.std_init(&SPI1)\n#if MESH_HIL_SPI_READ_PROBE\n      && finishSpiReadProbe()",init)
        self.assertIn("if (!radio.std_init(&SPI1)\n#if MESH_HIL_SPI_READ_PROBE\n      || !finishSpiReadProbe()",init)
        self.assertEqual(init.count("target_radio_available = true;"),2)
        self.assertEqual(init.count("board.enableRadioFrontend();"),2)


if __name__=="__main__":unittest.main(verbosity=2)
