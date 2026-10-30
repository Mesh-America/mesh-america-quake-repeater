"""Execute default-off IRQ body observation and correlated worst-hop deltas."""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest

import test_profile_switch_timing as timing

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'src/helpers/radiolib/NrfRadioIrqObserver.cpp'

ARDUINO=r'''
#pragma once
#include <cstdint>
struct DwtMock { uint32_t CYCCNT=0; };
extern DwtMock dwt;
#define DWT (&dwt)
inline bool dwt_enabled() { return true; }
inline void dwt_enable() {}
const char* pcTaskGetName(void* task);
'''

FIXTURE=r'''
#include <cassert>
#include <Arduino.h>
#include <helpers/radiolib/ProfileSwitchTiming.h>
@TIMING_GLOBALS@
DwtMock dwt;
unsigned real_calls[8]{},durations[8]={640,128,192,256,320,384,448,512};
bool nested=false;
const char* selected_task_name="loop";
const char* pcTaskGetName(void* task) { assert(task==nullptr);return selected_task_name; }
extern "C" void __wrap_RTC1_IRQHandler();
extern "C" void __wrap_GPIOTE_IRQHandler();
extern "C" void __wrap_UARTE0_UART0_IRQHandler();
extern "C" void __wrap_UARTE1_IRQHandler();
extern "C" void __wrap_POWER_CLOCK_IRQHandler();
extern "C" void __wrap_USBD_IRQHandler();
extern "C" void __wrap_vTaskSwitchContext();
extern "C" void __wrap_SPIM0_SPIS0_TWIM0_TWIS0_SPI0_TWI0_IRQHandler();
extern "C" void __real_RTC1_IRQHandler() {
  ++real_calls[0];dwt.CYCCNT+=durations[0];
  if(nested) __wrap_GPIOTE_IRQHandler();
}
#define REAL_HANDLER(symbol,index) extern "C" void __real_##symbol() { ++real_calls[index];dwt.CYCCNT+=durations[index]; }
REAL_HANDLER(GPIOTE_IRQHandler,1)
REAL_HANDLER(UARTE0_UART0_IRQHandler,2)
REAL_HANDLER(UARTE1_IRQHandler,3)
REAL_HANDLER(POWER_CLOCK_IRQHandler,4)
REAL_HANDLER(USBD_IRQHandler,5)
REAL_HANDLER(vTaskSwitchContext,6)
REAL_HANDLER(SPIM0_SPIS0_TWIM0_TWIS0_SPI0_TWI0_IRQHandler,7)
int main() {
  namespace obs=mesh::irqobserver;
  namespace timing=mesh::profiletiming;
  auto& capture=obs::mesh_hil_radio_irqs;
  assert(capture.magic==0x4d434952 && capture.version==2 && capture.size_bytes==424 && capture.source_count==8);
  static_assert(obs::Scheduler==6 && obs::Twim0Spim0==7,"Original indices must remain stable");
  static_assert(sizeof(obs::mesh_hil_irq_counters)==96,"IRQ counter bank size changed");
  // Actual wrappers forward every source exactly once, with no active hop.
  __wrap_UARTE0_UART0_IRQHandler();__wrap_UARTE1_IRQHandler();
  __wrap_POWER_CLOCK_IRQHandler();__wrap_USBD_IRQHandler();__wrap_vTaskSwitchContext();
  __wrap_SPIM0_SPIS0_TWIM0_TWIS0_SPI0_TWI0_IRQHandler();
  for(unsigned i=2;i<8;++i) assert(real_calls[i]==1);
  // Nested source time is explicitly inclusive in its parent; deltas remain
  // per source and are attached to the same worst successful physical hop.
  dwt.CYCCNT=100;durations[0]=640;durations[1]=128;nested=true;
  timing::begin(0,1,timing::readClock());
  __wrap_RTC1_IRQHandler();
  const auto endpoint=timing::readEndpointClock();
  assert(endpoint==868);
  __wrap_USBD_IRQHandler(); // Scheduling after endpoint must not enter deltas.
  timing::finish(timing::Success,endpoint);
  auto& direction=capture.direction[0];
  assert(direction.last_valid && direction.worst_valid && direction.last_ticks==768);
  assert(direction.last.calls[obs::Rtc1]==1 && direction.last.cycles[obs::Rtc1]==768);
  assert(direction.last.calls[obs::Gpiote]==1 && direction.last.cycles[obs::Gpiote]==128);
  assert(direction.last.calls[obs::Usb]==0 && direction.last.cycles[obs::Usb]==0);
  assert(direction.worst.cycles[obs::Rtc1]==768);
  assert(timing::mesh_hil_profile_timing.direction[0].stage[timing::Whole].max_us==12);
  // A smaller successful hop updates last but preserves correlated worst.
  nested=false;durations[0]=64;
  timing::begin(0,1,timing::readClock());__wrap_RTC1_IRQHandler();
  timing::finish(timing::Success,timing::readEndpointClock());
  assert(direction.last.cycles[obs::Rtc1]==64 && direction.worst.cycles[obs::Rtc1]==768);
  assert(direction.worst_ticks==768);
  // Failure records its own IRQ evidence without replacing successful worst.
  selected_task_name="Tmr Svc";
  timing::begin(0,1,timing::readClock());__wrap_vTaskSwitchContext();
  timing::finish(timing::Failure,timing::readEndpointClock());
  assert(capture.last_result==timing::Failure && direction.last.calls[obs::Scheduler]==1);
  assert(direction.last.selected[obs::TimerTask]==1 && direction.last.selected[obs::LoopTask]==0);
  assert(direction.last.selected_name[0]==0x20726d54 && direction.last.selected_name[1]==0x00637653);
  assert(direction.worst.cycles[obs::Rtc1]==768 && direction.worst.calls[obs::Scheduler]==0);
  assert(direction.worst.selected_name[0]==0);
  // Both DWT and per-source 32-bit counters use modular hop deltas.
  obs::mesh_hil_irq_counters[obs::Uart1].calls=UINT32_MAX;
  obs::mesh_hil_irq_counters[obs::Uart1].cycles=UINT32_MAX-10;
  dwt.CYCCNT=UINT32_MAX-31;durations[3]=64;
  timing::begin(1,0,timing::readClock());__wrap_UARTE1_IRQHandler();
  __wrap_SPIM0_SPIS0_TWIM0_TWIS0_SPI0_TWI0_IRQHandler();
  timing::finish(timing::Success,timing::readEndpointClock());
  assert(capture.direction[1].last_ticks==576 && capture.direction[1].last.calls[obs::Uart1]==1);
  assert(capture.direction[1].last.cycles[obs::Uart1]==64);
  assert(capture.direction[1].last.calls[obs::Twim0Spim0]==1 && capture.direction[1].last.cycles[obs::Twim0Spim0]==512);
  assert(capture.direction[1].worst.calls[obs::Twim0Spim0]==1 && capture.direction[1].worst.cycles[obs::Twim0Spim0]==512);
  // A permanently odd writer sequence cannot hang the application or publish
  // stale counter data as valid attribution. Timing itself remains available.
  obs::mesh_hil_irq_counters[obs::Gpiote].sequence=1;
  const auto failures=capture.snapshot_failures;
  timing::begin(1,0,timing::readClock());
  obs::mesh_hil_irq_counters[obs::Gpiote].sequence=2;
  dwt.CYCCNT+=128;
  timing::finish(timing::Success,timing::readEndpointClock());
  assert(capture.snapshot_failures==failures+1 && !capture.direction[1].last_valid);
  for(unsigned i=0;i<8;++i) {
    assert(capture.direction[1].last.calls[i]==0 && capture.direction[1].last.cycles[i]==0);
  }
  assert(capture.sequence%2==0 && capture.snapshots==10 && capture.retries>=8);
}
'''


class NrfRadioIrqObserverTests(unittest.TestCase):
    def test_actual_wrappers_and_profile_timing_keep_correlated_stable_irq_deltas(self):
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory)
            (folder/'Arduino.h').write_text(ARDUINO,encoding='ascii')
            source=folder/'test.cpp'
            source.write_text(FIXTURE.replace('@TIMING_GLOBALS@',
                timing.ProfileSwitchTimingTest.production_globals()),encoding='ascii')
            binary=folder/'test'
            built=subprocess.run([os.environ.get('CXX','c++'),'-std=c++17','-Wall','-Wextra','-Werror',
                '-fsanitize=address,undefined','-fno-sanitize-recover=all','-fno-pie','-no-pie',
                '-DNRF52_PLATFORM','-DMESH_HIL_PROFILE_TIMING=1','-DMESH_HIL_IRQ_TIMING=1',
                '-I',str(folder),'-I',str(ROOT/'src'),str(source),str(SOURCE),'-o',str(binary)],
                capture_output=True,text=True,env={**os.environ,'TMPDIR':str(folder)})
            self.assertEqual(built.returncode,0,built.stderr)
            ran=subprocess.run([str(binary)],capture_output=True,text=True)
            self.assertEqual(ran.returncode,0,ran.stdout+ran.stderr)

    def test_disabled_observer_has_no_code_ram_or_sdk_dependency(self):
        result=subprocess.run([os.environ.get('CXX','c++'),'-E','-P',str(SOURCE)],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertFalse(result.stdout.strip())

    def test_observer_requires_hil_nrf(self):
        for flags in ([],['-DNRF52_PLATFORM'],['-DMESH_HIL_PROFILE_TIMING=1']):
            result=subprocess.run([os.environ.get('CXX','c++'),'-E','-x','c++',
                '-DMESH_HIL_IRQ_TIMING=1',*flags,'-I',str(ROOT/'src'),'-'],
                input='#include <helpers/radiolib/NrfRadioIrqObserver.h>\n',capture_output=True,text=True)
            self.assertNotEqual(result.returncode,0)
            self.assertIn('requires nRF52 HIL profile timing',result.stderr)


if __name__=='__main__':unittest.main()
