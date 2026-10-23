"""Execute the private clock proof and bounded timing snapshot interface."""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest

from test_sx126x_buffered_radio_hal import MOCK


ROOT = Path(__file__).resolve().parents[1]


class Esp32SpiABDiagnosticsTests(unittest.TestCase):
    def test_commands_reach_diagnostics_through_production_cli(self):
        fixture = (ROOT / 'test/fixtures/radio_profiles/switch_tuning_test.cpp').read_text()
        fixture = fixture.rsplit('\nint main() {', 1)[0]
        fixture += r'''
#include <helpers/radiolib/ESP32SpiABDiagnostics.h>
namespace mesh { namespace profiletiming {
extern "C" {
volatile Capture mesh_hil_profile_timing = {
  Magic,Version,sizeof(Capture),0,ClockHz,StageCount,HistogramCount,HistogramWidthUs,0,0,{}};
Work mesh_hil_profile_timing_work = {};
}
} }
int main() {
  TuningFixture f;
  mesh::esp_spiab::recordClock(0x1000,8888888);
  assert(!strcmp(f.cmd("get radio.fast.hw"),"> divider=0x00001000 hz=8888888 changes=1"));
  assert(strstr(f.cmd("get radio.fast.time 1 10"),"d=1 s=10 count=0"));
  assert(strstr(f.cmd("get radio.fast.hist 0 10 1"),"p=1 bins=0,0,0,0,0,0,0,0"));
  assert(strstr(f.cmd("get radio.fast.hil"),"bytes=2192"));
  assert(strstr(f.cmd("set radio.fast.hw 8",false),"read-only"));
  assert(strstr(f.cmd("get radio.fast.time 2 10"),"Error:"));
  assert(!strcmp(f.cmd("get radio.fast.buffer"),"> on"));
  assert(f.radio.attempts==0 && f.fs.files.empty());
}
'''
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            prelude = work / 'prelude.h'
            prelude.write_text('#include <cstdint>\ninline uint32_t micros() { return 0; }\n',
                               encoding='ascii')
            cpp, binary = work / 'cli.cpp', work / 'cli'
            cpp.write_text(fixture, encoding='ascii')
            built = subprocess.run([os.environ.get('CXX', 'g++'), '-std=c++17',
                '-Wall', '-Wextra', '-DESP32_PLATFORM=1', '-DMESH_HIL_PROFILE_TIMING=1',
                '-DMESH_HIL_ESP_SPI_AB=1', '-include', str(prelude),
                '-I', str(ROOT / 'test/fixtures/radio_profiles'),
                '-I', str(ROOT / 'test/fixtures/radio_profiles/mocks'),
                '-I', str(ROOT / 'test/mocks'), '-I', str(ROOT / 'src'),
                str(ROOT / 'src/helpers/RadioProfileCLI.cpp'), str(cpp), '-o', str(binary)],
                capture_output=True, text=True)
            self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
            subprocess.run([str(binary)], check=True)

    def test_live_divider_after_transaction_and_read_only_bounded_snapshots(self):
        fixture = r'''
#include <cassert>
#include <cstring>
#include <cstdint>
#include <helpers/radiolib/ESP32BufferedRadioHal.h>
namespace mesh { namespace profiletiming {
extern "C" {
volatile Capture mesh_hil_profile_timing = {
  Magic,Version,sizeof(Capture),0,ClockHz,StageCount,HistogramCount,HistogramWidthUs,0,0,{}};
Work mesh_hil_profile_timing_work = {};
}
} }
int main() {
  SPIClass bus;
  ESP32BufferedRadioHal hal(bus,8888888);
  auto& clock=mesh::esp_spiab::clockCapture();
  assert(clock.changes==0);
  hal.spiBeginTransaction();
  assert(bus.transactions==1 && clock.changes==1);
  assert(clock.hz==8888888 && clock.divider==9);
  hal.spiBeginTransaction();
  assert(bus.transactions==2 && clock.changes==1);
  mesh::RadioSwitchTuning policy=hal.getTuning();
  policy.spi_mhz=8;
  assert(hal.setTuning(policy));
  hal.spiBeginTransaction();
  assert(clock.hz==8000000 && clock.divider==10 && clock.changes==2);
  assert(bus.bursts==0 && bus.bytes==0);
  // The clock capture and timing statistics are never changed by getters.
  auto& capture=mesh::profiletiming::mesh_hil_profile_timing;
  auto& stats=capture.direction[1].stage[10];
  stats.count=0xffffffffU; stats.sum_high_us=7; stats.sum_low_us=42;
  stats.min_us=199; stats.max_us=612; stats.last_us=201;
  for(unsigned i=0;i<16;++i) stats.histogram[i]=0xffffffffU-i;
  char reply[160];
  auto get=[&](const char* suffix,const char* args="") {
    assert(mesh::esp_spiab::handle(suffix,args,0,reply,sizeof(reply)));
  };
  get("hw"); assert(!strcmp(reply,"> divider=0x0000000A hz=8000000 changes=2"));
  get("hil"); assert(strstr(reply,"magic=0x4D435054 ver=3 bytes=2192 seq=0"));
  get("time","1 10");
  assert(!strcmp(reply,"> d=1 s=10 count=4294967295 sum_hi=7 sum_lo=42 min=199 max=612 last=201"));
  get("hist","1 10 0");
  assert(strstr(reply,"p=0 bins=4294967295,4294967294"));
  get("hist","1 10 1");
  assert(strstr(reply,"p=1 bins=4294967287,4294967286"));
  assert(strstr(reply,"4294967280"));
  for(const char* args:{"", "2 0", "0 11", "-1 0", "0 1 garbage"}) {
    get("time",args); assert(!strncmp(reply,"Error:",6));
  }
  get("hist","0 0 2"); assert(!strncmp(reply,"Error:",6));
  get("hw","extra"); assert(!strncmp(reply,"Error:",6));
  assert(mesh::esp_spiab::handle("hw","8",1,reply,sizeof(reply)));
  assert(strstr(reply,"read-only"));
  assert(!mesh::esp_spiab::handle("warm","",0,reply,sizeof(reply)));
  for(unsigned size=0;size<=160;++size) {
    char guarded[162]; memset(guarded,0x55,sizeof(guarded));
    assert(mesh::esp_spiab::handle("hist","1 10 0",0,guarded+1,size));
    assert(guarded[0]==0x55 && guarded[size+1]==0x55);
    if(size) assert(memchr(guarded+1,0,size));
  }
  assert(clock.changes==2 && stats.count==0xffffffffU && capture.sequence==0);
  assert(bus.bursts==0 && bus.bytes==0);
}
'''
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            (work / 'hal/Arduino').mkdir(parents=True)
            mock = MOCK.replace('  unsigned bursts=0, bytes=0, begins=0, ends=0;',
                '  unsigned bursts=0, bytes=0, begins=0, ends=0, transactions=0, divider=0;\n'
                '  uint32_t getClockDivider() { return divider; }')
            mock = mock.replace('  virtual void init()',
                '  virtual void spiBeginTransaction() { ++spi->transactions; '
                'spi->divider=spiSettings.hz==8888888 ? 9 : 10; }\n'
                '  virtual void init()')
            mock += '\ninline uint32_t spiClockDivToFrequency(uint32_t d) { return 80000000/d; }\n'
            (work / 'hal/Arduino/ArduinoHal.h').write_text(mock, encoding='ascii')
            (work / 'Arduino.h').write_text('#pragma once\n#include <cstdint>\n'
                'inline uint32_t micros() { return 0; }\n', encoding='ascii')
            cpp, binary = work / 'test.cpp', work / 'test'
            cpp.write_text('#include <initializer_list>\n' + fixture, encoding='ascii')
            flags = [os.environ.get('CXX', 'g++'), '-std=c++11', '-Wall', '-Wextra',
                     '-Werror', '-DESP32_PLATFORM=1', '-DMESH_HIL_PROFILE_TIMING=1',
                     '-DMESH_HIL_ESP_SPI_AB=1', '-I', str(work), '-I', str(ROOT / 'src')]
            built = subprocess.run(flags + [str(cpp), '-o', str(binary)],
                                   capture_output=True, text=True)
            self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
            subprocess.run([str(binary)], check=True)

    def test_flag_off_omits_capture_and_invalid_platforms_reject_opt_in(self):
        source = '#include <helpers/radiolib/ESP32SpiABDiagnostics.h>\nint main() {}\n'
        for flags, succeeds in (([], True), (['-DMESH_HIL_ESP_SPI_AB=0'], True),
                (['-DMESH_HIL_ESP_SPI_AB=1'], False),
                (['-DMESH_HIL_ESP_SPI_AB=1', '-DESP32_PLATFORM=1'], False)):
            with self.subTest(flags=flags):
                built = subprocess.run([os.environ.get('CXX', 'g++'), '-std=c++11',
                    '-x', 'c++', '-fsyntax-only', '-I', str(ROOT / 'src'), *flags, '-'],
                    input=source, capture_output=True, text=True)
                self.assertEqual(built.returncode == 0, succeeds, built.stderr)
                if not succeeds:
                    self.assertIn('require ESP32 and profile timing', built.stderr)


if __name__ == '__main__':
    unittest.main()
