"""Execute diagnostic task-priority admission, restoration and RTC deadline."""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest

from test_rak3401_buffered_radio_hal import MOCK_HAL

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'src/helpers/radiolib/NrfRadioPriorityLease.cpp'

ARDUINO=r'''
#pragma once
#include <cassert>
#include <cstdint>
using UBaseType_t=unsigned;
struct TaskMock { unsigned priority; const char* name; };
using TaskHandle_t=TaskMock*;
enum { TASK_PRIO_LOW=1,TASK_PRIO_HIGH=3 };
#define configMAX_PRIORITIES 5
struct RtcMock { uint32_t COUNTER; };
extern RtcMock rtc;
#define NRF_RTC2 (&rtc)
extern TaskMock loopTask,otherTask;
extern TaskHandle_t currentTask;
extern bool inIsr;
extern unsigned prioritySets;
inline bool isInISR() { return inIsr; }
inline TaskHandle_t xTaskGetCurrentTaskHandle() { return currentTask; }
inline const char* pcTaskGetName(TaskHandle_t task) { return task->name; }
inline unsigned uxTaskPriorityGet(TaskHandle_t task) { return task->priority; }
inline void vTaskPrioritySet(TaskHandle_t task,unsigned priority) {
  assert(!inIsr && task==&loopTask && priority<5);
  task->priority=priority;++prioritySets;
}
'''

MOCK=MOCK_HAL.replace('#include <cassert>','#include <Arduino.h>\n#include <cassert>')
MOCK=MOCK.replace('virtual ~ArduinoHal() = default;',r'''
  unsigned yields=0,transactions=0,lastTransactionPriority=0;
  virtual ~ArduinoHal() = default;
  virtual void yield() { ++yields; }
  virtual void spiBeginTransaction() {
    ++transactions;lastTransactionPriority=currentTask->priority;
  }
''')

FIXTURE=r'''
#include <helpers/radiolib/Nrf52BufferedRadioHal.h>
RtcMock rtc{};
TaskMock loopTask{1,"loop"},otherTask{3,"usbd"};
TaskHandle_t currentTask=&loopTask;
bool inIsr=false;
unsigned prioritySets=0;
int failEarly(bool fail) {
  mesh::radiopriority::Lease lease(true);
  assert(loopTask.priority==4);
  if(fail) return -1;
  lease.release();
  assert(loopTask.priority==1);
  return 0;
}
int main() {
  using namespace mesh::radiopriority;
  auto& capture=mesh_hil_radio_priority;
  assert(capture.magic==0x4d435250 && capture.size_bytes==60);
  SPIClass bus;Nrf52BufferedRadioHal concrete(bus,8000000);
  ArduinoHal& hal=concrete;
  { Lease lease(false);assert(loopTask.priority==1); }
  inIsr=true;{ Lease lease(true); }inIsr=false;
  currentTask=&otherTask;{ Lease lease(true); }currentTask=&loopTask;
  loopTask.priority=3;{ Lease lease(true); }loopTask.priority=1;
  assert(prioritySets==0 && capture.entries==0);
  assert(capture.skipped_not_owned==1 && capture.skipped_isr==1);
  assert(capture.skipped_task==1 && capture.skipped_priority==1);

  // Nested rejection must not release its outer caller's admitted lease.
  rtc.COUNTER=100;
  { Lease outer(true);assert(loopTask.priority==4 && capture.active==1);
    { Lease inner(true); }assert(loopTask.priority==4 && capture.active==1);
    hal.yield();assert(hal.yields==0 && capture.suppressed_yields==1);
    hal.spiBeginTransaction();
    assert(hal.transactions==1 && hal.lastTransactionPriority==4);
    currentTask=&otherTask;hal.yield();assert(hal.yields==1);
    currentTask=&loopTask;
    outer.release();assert(loopTask.priority==1 && capture.active==0);
    outer.release();
  }
  assert(capture.skipped_nested==1 && capture.entries==1 && capture.releases==1);
  assert(prioritySets==2);

  // The RTC is 24-bit. Expiry drops priority BEFORE normal USB-flushing yield.
  rtc.COUNTER=0x00fffff0;
  { Lease lease(true);
    rtc.COUNTER=(0x00fffff0+31)&RtcMask;
    hal.yield();assert(loopTask.priority==4 && hal.yields==1);
    rtc.COUNTER=(0x00fffff0+32)&RtcMask;
    hal.yield();assert(loopTask.priority==1 && hal.yields==2);
    assert(capture.active==0 && capture.expired==1);
  }
  assert(capture.entries==2 && capture.releases==2 && prioritySets==4);
  for(unsigned i=0;i<10000;++i) hal.yield();
  assert(hal.yields==10002); // No lease means no suppressed normal yields.

  // Frame checks expire before the base transaction can lower radio CS.
  rtc.COUNTER=100;
  { Lease lease(true);rtc.COUNTER=132;hal.spiBeginTransaction();
    assert(hal.transactions==2 && hal.lastTransactionPriority==1);
    assert(loopTask.priority==1 && capture.expired==2);
  }
  uint8_t tx[]={0x86,0x12,0x34},rx[3]={};
  hal.spiTransfer(tx,3,rx);hal.spiTransfer(nullptr,0,nullptr);
  assert(bus.bursts==1 && bus.bytes==0 && rx[1]==uint8_t(tx[1]^0xa5));

  // Both early failure and explicit successful release restore exactly once.
  rtc.COUNTER=200;
  assert(failEarly(true)==-1 && loopTask.priority==1);
  assert(failEarly(false)==0 && loopTask.priority==1);
  assert(capture.entries==5 && capture.releases==5 && prioritySets==10);
  assert(capture.active==0 && capture.frame_checks==2);
}
'''


class NrfRadioPriorityLeaseTest(unittest.TestCase):
    def test_real_lease_and_hal_preserve_yields_and_restore_on_every_exit(self):
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory)
            (folder/'hal/Arduino').mkdir(parents=True)
            (folder/'Arduino.h').write_text(ARDUINO,encoding='ascii')
            (folder/'hal/Arduino/ArduinoHal.h').write_text(MOCK,encoding='ascii')
            cpp,binary=folder/'test.cpp',folder/'test.exe'
            cpp.write_text(FIXTURE,encoding='ascii')
            built=subprocess.run([os.environ.get('CXX','g++'),'-std=c++17',
                '-Wall','-Wextra','-Werror','-DNRF52_PLATFORM',
                '-DMESH_HIL_PROFILE_TIMING=1','-DMC_NRF_RADIO_PROFILE_PRIORITY=1',
                '-I',str(folder),'-I',str(ROOT/'src'),str(cpp),str(SOURCE),
                '-o',str(binary)],capture_output=True,text=True)
            self.assertEqual(built.returncode,0,built.stderr)
            ran=subprocess.run([str(binary)],capture_output=True,text=True)
            self.assertEqual(ran.returncode,0,ran.stderr)

    def test_default_off_has_no_code_types_ram_or_sdk_dependencies(self):
        preprocessed=subprocess.run([os.environ.get('CXX','g++'),'-std=c++17',
            '-E','-P','-x','c++','-I',str(ROOT/'src'),'-'],
            input='#include <helpers/radiolib/NrfRadioPriorityLease.h>\nint main() {}\n',
            capture_output=True,text=True)
        self.assertEqual(preprocessed.returncode,0,preprocessed.stderr)
        self.assertEqual(preprocessed.stdout.strip(),'int main() {}')
        implementation=subprocess.run([os.environ.get('CXX','g++'),'-std=c++17',
            '-E','-P',str(SOURCE)],capture_output=True,text=True)
        self.assertEqual(implementation.returncode,0,implementation.stderr)
        self.assertFalse(implementation.stdout.strip())

    def test_experiment_rejects_missing_nrf_or_timing(self):
        for flags in (['-DMC_NRF_RADIO_PROFILE_PRIORITY=1'],
                      ['-DMC_NRF_RADIO_PROFILE_PRIORITY=1','-DNRF52_PLATFORM'],
                      ['-DMC_NRF_RADIO_PROFILE_PRIORITY=1','-DMESH_HIL_PROFILE_TIMING=1']):
            with self.subTest(flags=flags):
                result=subprocess.run([os.environ.get('CXX','g++'),'-E','-x','c++',
                    *flags,'-I',str(ROOT/'src'),'-'],
                    input='#include <helpers/radiolib/NrfRadioPriorityLease.h>\n',
                    capture_output=True,text=True)
                self.assertNotEqual(result.returncode,0)
                self.assertIn('requires nRF52 HIL profile timing',result.stderr)


if __name__=='__main__':
    unittest.main()
