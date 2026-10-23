"""Execute the actual default-off SPI startup capture and refusal gate."""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest

from test_rak3401_buffered_radio_hal import MOCK_HAL


ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "src/helpers/radiolib/NrfRadioSpiStartupDiagHal.cpp"

MOCK_SDM = r'''
#pragma once
#include <cstdint>
extern uint32_t test_sd_result, test_sd_queries;
extern uint8_t test_sd_enabled;
uint32_t sd_softdevice_is_enabled(uint8_t* state);
'''

MOCK_ARDUINO = r'''
#pragma once
#include <cassert>
#include <cstdint>
extern bool spim_disabled;
extern unsigned delay_writes,transaction_starts;
struct EnableRegister {
  uint32_t value=7;
  operator uint32_t() const { return value; }
  EnableRegister& operator=(uint32_t next) { value=next;spim_disabled=next==0;return *this; }
};
struct DelayRegister {
  uint32_t value=2;
  operator uint32_t() const { return value; }
  DelayRegister& operator=(uint32_t next) {
    assert(spim_disabled);++delay_writes;value=next;return *this;
  }
};
struct SpimMock { EnableRegister ENABLE;struct { DelayRegister RXDELAY; } IFTIMING; };
extern SpimMock spim3;
#define NRF_SPIM3 (&spim3)
'''

HARNESS = r'''
#include <array>
#include <cassert>
#include <cstdint>
#include <cstring>
#include <helpers/radiolib/NrfRadioSpiStartupDiagHal.h>
bool spim_disabled=false;
unsigned delay_writes=0,transaction_starts=0;
SpimMock spim3;
uint32_t test_sd_result=0,test_sd_queries=0;
uint8_t test_sd_enabled=0;
using namespace mesh::spistartup;
uint32_t sd_softdevice_is_enabled(uint8_t* state) {
  assert(mesh_hil_spi_startup.phase==Query);
  ++test_sd_queries;*state=test_sd_enabled;return test_sd_result;
}
void before_test_spi_transfer() {
  const auto& capture=mesh_hil_spi_startup;
  assert(capture.phase==Transfer&&capture.begun==capture.completed+1);
  assert(capture.queries==test_sd_queries);
  assert(capture.last_query_result==0&&capture.last_query_enabled==0);
}
int main() {
  SPIClass bus;NrfRadioSpiStartupDiagHal concrete(bus,16000000);
  ArduinoHal& hal=concrete;
  auto& capture=mesh_hil_spi_startup;
  assert(capture.magic==0x4d435353&&capture.version==2&&capture.size_bytes==80);
  assert(capture.phase==Idle&&capture.queries==0&&capture.begun==0&&capture.completed==0&&capture.refused==0);
  assert(capture.first_query_result==UINT32_MAX&&capture.first_query_enabled==UINT32_MAX);
  assert(capture.actual_rx_delay==UINT32_MAX && capture.packet_type_frames==0);
  assert(concrete.spiSettings.hz==16000000&&concrete.spiSettings.order==MSBFIRST&&concrete.spiSettings.mode==SPI_MODE0);
  Capture initial;memcpy(&initial,(const void*)&capture,sizeof(initial));
  // A zero-size call must not touch capture, query the supervisor, or use SPI.
  hal.spiTransfer(nullptr,0,nullptr);
  assert(memcmp(&initial,(const void*)&capture,sizeof(initial))==0&&test_sd_queries==0&&bus.bursts==0);
  hal.spiBeginTransaction();
  assert(transaction_starts==1 && !spim_disabled);
#if defined(SPI_32MHZ_INTERFACE) && SPI_32MHZ_INTERFACE == 1
  const unsigned expected=MESH_HIL_SPI3_RX_DELAY<0?2:MESH_HIL_SPI3_RX_DELAY;
  assert(capture.actual_rx_delay==expected && uint32_t(spim3.IFTIMING.RXDELAY)==expected);
  assert(delay_writes==unsigned(MESH_HIL_SPI3_RX_DELAY>=0));
#else
  assert(capture.actual_rx_delay==UINT32_MAX && delay_writes==0);
#endif
  std::array<uint8_t,4> out={0x83,0x11,0x22,0x33},in{};
  const auto original=out;
  // Positively disabled permits exactly one buffered full-duplex frame.
  hal.spiTransfer(out.data(),out.size(),in.data());
  assert(capture.phase==Completed&&capture.queries==1&&capture.begun==1&&capture.completed==1&&capture.refused==0);
  assert(capture.first_query_result==0&&capture.first_query_enabled==0);
  assert(capture.last_opcode==0x83&&capture.last_length==4&&bus.bursts==1&&bus.bytes==0);
  assert(out==original);
  for(unsigned i=0;i<in.size();++i)assert(in[i]==uint8_t(out[i]^0xa5));
  // Enabled SoftDevice must refuse the nrfx-workaround frame, report command
  // failure throughout the response, and keep the original TX data intact.
  test_sd_enabled=1;in.fill(0x77);out[0]=0xc0;
  hal.spiTransfer(out.data(),2,in.data());
  assert(capture.phase==Refused&&capture.queries==2&&capture.begun==1&&capture.completed==1&&capture.refused==1);
  assert(capture.last_query_result==0&&capture.last_query_enabled==1);
  assert(capture.last_opcode==0xc0&&capture.last_length==2&&bus.bursts==1);
  assert(in[0]==0x2a&&in[1]==0x2a&&in[2]==0x77&&in[3]==0x77&&out[0]==0xc0);
  // A failed query is unsafe even when the returned enabled byte is zero.
  test_sd_enabled=0;test_sd_result=7;in.fill(0x55);
  hal.spiTransfer(out.data(),out.size(),in.data());
  assert(capture.phase==Refused&&capture.queries==3&&capture.begun==1&&capture.completed==1&&capture.refused==2);
  assert(capture.last_query_result==7&&capture.last_query_enabled==0&&bus.bursts==1);
  for(auto byte:in)assert(byte==0x2a);
  // No-RX frames are still refused safely; no null pointer is dereferenced.
  hal.spiTransfer(out.data(),out.size(),nullptr);
  assert(capture.refused==3&&capture.queries==4&&bus.bursts==1);
  // A later positively-disabled query allows transfer and preserves the
  // original first-query evidence while updating the last-query evidence.
  test_sd_result=0;out[0]=0x82;
  hal.spiTransfer(out.data(),out.size(),in.data());
  assert(capture.phase==Completed&&capture.queries==5&&capture.begun==2&&capture.completed==2&&capture.refused==3);
  assert(capture.first_query_result==0&&capture.first_query_enabled==0);
  assert(capture.last_query_result==0&&capture.last_query_enabled==0);
  assert(capture.last_opcode==0x82&&capture.last_length==4&&bus.bursts==2&&bus.bytes==0);
  Capture final;memcpy(&final,(const void*)&capture,sizeof(final));
  hal.spiTransfer(nullptr,0,nullptr);
  assert(memcmp(&final,(const void*)&capture,sizeof(final))==0&&test_sd_queries==5);
  // Record the first three wire bytes only for completed GetPacketType.
  out[0]=0x11;
  hal.spiTransfer(out.data(),3,in.data());
  assert(capture.packet_type_frames==1 && capture.packet_type_length==3);
  for(unsigned i=0;i<3;++i) assert(capture.packet_type_rx[i]==uint8_t(out[i]^0xa5));
  test_sd_enabled=1;hal.spiTransfer(out.data(),3,in.data());
  assert(capture.packet_type_frames==1); // Refused bytes are not wire evidence.
  test_sd_enabled=0;hal.spiTransfer(out.data(),1,in.data());
  assert(capture.packet_type_frames==2 && capture.packet_type_length==1);
  assert(capture.packet_type_rx[0]==uint8_t(0x11^0xa5));
  assert(capture.packet_type_rx[1]==UINT32_MAX && capture.packet_type_rx[2]==UINT32_MAX);
  hal.spiTransfer(out.data(),3,nullptr);
  assert(capture.packet_type_frames==3 && capture.packet_type_length==3);
  for(unsigned i=0;i<3;++i) assert(capture.packet_type_rx[i]==UINT32_MAX);
}
'''


class NrfRadioSpiStartupDiagTests(unittest.TestCase):
    def test_actual_helper_queries_before_frames_and_refuses_unsafe_workaround(self):
        for flags in ([],['-DSPI_32MHZ_INTERFACE=1'],*[['-DSPI_32MHZ_INTERFACE=1',
                       f'-DMESH_HIL_SPI3_RX_DELAY={delay}'] for delay in range(8)]):
            with self.subTest(flags=flags): self.compile_and_run(flags)

    def compile_and_run(self,flags):
        with tempfile.TemporaryDirectory(prefix="nrf-spi-startup-") as directory:
            folder=Path(directory);(folder/"hal/Arduino").mkdir(parents=True)
            mock=MOCK_HAL.replace('#include <cassert>','#include <Arduino.h>\n#include <cassert>')
            # This fixture supplies checked register proxies in Arduino.h;
            # replace the constructor fixture's simpler SPIM mock entirely.
            start=mock.index('struct MockSpim {')
            mock=mock[:start]+mock[mock.index('struct SPISettings {',start):]
            mock=mock.replace("constexpr unsigned MSBFIRST", "void before_test_spi_transfer();\nconstexpr unsigned MSBFIRST")
            mock=mock.replace("    ++bursts;", "    before_test_spi_transfer();\n    ++bursts;")
            mock=mock.replace('rx[i] = tx[i] ^ 0xa5;', 'if(rx) rx[i] = tx[i] ^ 0xa5;')
            mock=mock.replace('virtual void spiBeginTransaction() {}',r'''
  virtual void spiBeginTransaction() { ++transaction_starts;spim3.ENABLE=7; }
''')
            (folder/"hal/Arduino/ArduinoHal.h").write_text(mock,encoding="ascii")
            (folder/"nrf_sdm.h").write_text(MOCK_SDM,encoding="ascii")
            (folder/"Arduino.h").write_text(MOCK_ARDUINO,encoding="ascii")
            source=folder/"test.cpp";source.write_text(HARNESS,encoding="ascii")
            binary=folder/"test"
            command=[os.environ.get("CXX","c++"),"-std=c++17","-Wall","-Wextra","-Werror",
                     "-fsanitize=address,undefined","-fno-sanitize-recover=all","-fno-pie","-no-pie",
                     "-DNRF52_PLATFORM=1","-DMESH_HIL_SPI_STARTUP_DIAG=1",
                     *flags,
                     "-I",str(folder),"-I",str(ROOT/"src"),str(source),str(HELPER),"-o",str(binary)]
            built=subprocess.run(command,capture_output=True,text=True,env={**os.environ,'TMPDIR':str(folder)})
            self.assertEqual(built.returncode,0,built.stderr)
            ran=subprocess.run([str(binary)],capture_output=True,text=True)
            self.assertEqual(ran.returncode,0,ran.stdout+ran.stderr)

    def test_default_off_translation_unit_has_no_code_ram_or_sdk_dependencies(self):
        with tempfile.TemporaryDirectory(prefix="nrf-spi-startup-off-") as directory:
            output=Path(directory)/"diag.o"
            for flags in ([],["-DMESH_HIL_SPI_STARTUP_DIAG=0"]):
                built=subprocess.run([os.environ.get("CXX","c++"),"-std=c++17","-Wall","-Wextra","-Werror",
                    *flags,"-I",str(ROOT/"src"),"-c",str(HELPER),"-o",str(output)],capture_output=True,text=True)
                self.assertEqual(built.returncode,0,built.stderr)
                symbols=subprocess.run(["nm","--defined-only",str(output)],capture_output=True,text=True)
                self.assertEqual(symbols.returncode,0,symbols.stderr)
                self.assertEqual(symbols.stdout.strip(),"")

    def test_delay_dial_rejects_non_hil_or_wrong_controller_and_invalid_range(self):
        for flags,diagnostic in ((['-DMESH_HIL_SPI3_RX_DELAY=0'],'requires the nRF52 SPI startup diagnostic'),
                (['-DMESH_HIL_SPI3_RX_DELAY=1','-DMESH_HIL_SPI_STARTUP_DIAG=1',
                  '-DNRF52_PLATFORM=1'],'requires the diagnostic SPI1/SPIM3 mapping'),
                (['-DMESH_HIL_SPI3_RX_DELAY=2','-DMESH_HIL_SPI_STARTUP_DIAG=1',
                  '-DNRF52_PLATFORM=1','-DSPI_32MHZ_INTERFACE=0'],'requires the diagnostic SPI1/SPIM3 mapping'),
                (['-DMESH_HIL_SPI3_RX_DELAY=-2'],'SPI3 sample delay must be'),
                (['-DMESH_HIL_SPI3_RX_DELAY=8'],'SPI3 sample delay must be')):
            with self.subTest(flags=flags):
                result=subprocess.run([os.environ.get('CXX','c++'),'-E','-x','c++',
                    *flags,'-I',str(ROOT/'src'),'-'],input='#include <helpers/radiolib/NrfRadioSpiStartupDiagHal.h>\n',
                    capture_output=True,text=True)
                self.assertNotEqual(result.returncode,0)
                self.assertIn(diagnostic,result.stderr)


if __name__=="__main__":unittest.main(verbosity=2)
