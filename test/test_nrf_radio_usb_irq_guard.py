"""Execute the HIL-only USB IRQ guard, including its independent deadline ISR."""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest

from test_rak3401_buffered_radio_hal import MOCK_HAL

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'src/helpers/radiolib/NrfRadioUsbIrqGuard.cpp'

ARDUINO = r'''
#pragma once
#include <cassert>
#include <cstdint>
struct TaskMock { unsigned priority; const char* name; };
using TaskHandle_t=TaskMock*;
enum { TASK_PRIO_LOW=1 };
enum IRQn_Type { GPIOTE_IRQn=6,RTC2_IRQn=36,USBD_IRQn=39 };
struct RtcMock {
  uint32_t COUNTER=0,PRESCALER=0,INTENSET=0,EVTEN=0;
  uint32_t EVENTS_COMPARE[4]{},CC[4]{};
};
extern RtcMock rtc;
#define NRF_RTC2 (&rtc)
struct NvicState { unsigned __cr_flag=0; };
extern NvicState nrf_nvic_state;
extern TaskMock loopTask,otherTask;
extern TaskHandle_t currentTask;
extern unsigned primask,basepri,faultmask;
extern bool inIsr,irqEnabled[64],irqPending[64],fireBeforeUsbMask;
extern unsigned irqPriority[64],nvicChanges,sdkCalls,sdkFailures,taskYields;
extern int failOperation;
extern bool failTransfer;
extern "C" void RTC2_IRQHandler();
void expire();
inline bool isInISR() { return inIsr; }
inline TaskHandle_t xTaskGetCurrentTaskHandle() { return currentTask; }
inline const char* pcTaskGetName(TaskHandle_t task) { return task->name; }
inline unsigned uxTaskPriorityGet(TaskHandle_t task) { return task->priority; }
inline unsigned __get_PRIMASK() { return primask; }
inline unsigned __get_BASEPRI() { return basepri; }
inline unsigned __get_FAULTMASK() { return faultmask; }
inline void taskYIELD() { ++taskYields; }
inline bool NVIC_GetEnableIRQ(IRQn_Type irq) { return irqEnabled[irq]; }
inline bool NVIC_GetPendingIRQ(IRQn_Type irq) { return irqPending[irq]; }
inline unsigned NVIC_GetPriority(IRQn_Type irq) { return irqPriority[irq]; }
inline void permitted(IRQn_Type irq) {
  assert(irq==USBD_IRQn || irq==RTC2_IRQn);++nvicChanges;
}
inline void NVIC_SetPriority(IRQn_Type irq,unsigned priority) {
  permitted(irq);irqPriority[irq]=priority;
}
inline void NVIC_EnableIRQ(IRQn_Type irq) { permitted(irq);irqEnabled[irq]=true; }
inline void NVIC_DisableIRQ(IRQn_Type irq) {
  permitted(irq);
  if(irq==USBD_IRQn && fireBeforeUsbMask) { fireBeforeUsbMask=false;expire(); }
  irqEnabled[irq]=false;
}
inline void NVIC_ClearPendingIRQ(IRQn_Type irq) { permitted(irq);irqPending[irq]=false; }
'''

SDM = r'''
#pragma once
#include <Arduino.h>
constexpr unsigned NRF_SUCCESS=0;
extern unsigned sdkQueryResult,sdkQueryEnabled,sdkQueries;
inline unsigned sd_softdevice_is_enabled(uint8_t* enabled) {
  ++sdkQueries;*enabled=sdkQueryEnabled;return sdkQueryResult;
}
'''

NVIC = r'''
#pragma once
#include <nrf_sdm.h>
inline bool sdkFail(int operation) {
  ++sdkCalls;
  if(operation==failOperation) { failOperation=0;++sdkFailures;return true; }
  return false;
}
inline bool legal(unsigned priority) { return priority<8 && priority!=0 && priority!=1 && priority!=4; }
inline unsigned sd_nvic_SetPriority(IRQn_Type irq,unsigned priority) {
  if(sdkFail(1)) return 91;
  assert(legal(priority));NVIC_SetPriority(irq,priority);return 0;
}
inline unsigned sd_nvic_EnableIRQ(IRQn_Type irq) {
  if(sdkFail(2)) return 92;
  assert(legal(irqPriority[irq]));NVIC_EnableIRQ(irq);return 0;
}
inline unsigned sd_nvic_DisableIRQ(IRQn_Type irq) {
  if(sdkFail(3)) return 93;
  NVIC_DisableIRQ(irq);return 0;
}
inline unsigned sd_nvic_ClearPendingIRQ(IRQn_Type irq) {
  if(sdkFail(4)) return 94;
  NVIC_ClearPendingIRQ(irq);return 0;
}
'''

RTC = r'''
#pragma once
#include <Arduino.h>
constexpr unsigned RTC_INTENSET_COMPARE0_Msk=1u<<16;
enum nrf_rtc_event_t { NRF_RTC_EVENT_COMPARE_0=0 };
inline void nrf_rtc_int_enable(RtcMock* p,unsigned mask) { p->INTENSET|=mask; }
inline void nrf_rtc_int_disable(RtcMock* p,unsigned mask) { p->INTENSET&=~mask; }
inline void nrf_rtc_event_clear(RtcMock* p,nrf_rtc_event_t) { p->EVENTS_COMPARE[0]=0; }
inline bool nrf_rtc_event_check(RtcMock* p,nrf_rtc_event_t) { return p->EVENTS_COMPARE[0]!=0; }
inline void nrf_rtc_cc_set(RtcMock* p,unsigned ch,unsigned value) { p->CC[ch]=value; }
inline unsigned nrf_rtc_cc_get(RtcMock* p,unsigned ch) { return p->CC[ch]; }
'''

MOCK = MOCK_HAL.replace('#include <cassert>', '#include <Arduino.h>\n#include <cassert>')
MOCK = MOCK.replace('    ++bursts;', '''
    if(failTransfer) { expire();assert(irqEnabled[USBD_IRQn]); }
    ++bursts;''')
MOCK = MOCK.replace('virtual ~ArduinoHal() = default;', r'''
  unsigned yields=0,transactions=0;
  bool transactionUsb=false;
  virtual ~ArduinoHal() = default;
  virtual void yield() { assert(irqEnabled[USBD_IRQn]);++yields; }
  virtual void spiBeginTransaction() { ++transactions;transactionUsb=irqEnabled[USBD_IRQn]; }
''')

FIXTURE = r'''
#include <initializer_list>
#include <helpers/radiolib/Nrf52BufferedRadioHal.h>
RtcMock rtc;
TaskMock loopTask{1,"loop"},otherTask{3,"usbd"};
TaskHandle_t currentTask=&loopTask;
NvicState nrf_nvic_state;
unsigned primask=0,basepri=0,faultmask=0;
bool inIsr=false,irqEnabled[64]{},irqPending[64]{},fireBeforeUsbMask=false;
unsigned irqPriority[64]{},nvicChanges=0,sdkCalls=0,sdkFailures=0,taskYields=0;
unsigned sdkQueryResult=0,sdkQueryEnabled=0,sdkQueries=0;
int failOperation=0;
bool failTransfer=false;
void expire() {
  rtc.COUNTER=rtc.CC[0];rtc.EVENTS_COMPARE[0]=1;irqPending[RTC2_IRQn]=true;
  assert(irqEnabled[RTC2_IRQn]);
  const bool was=inIsr;inIsr=true;RTC2_IRQHandler();inIsr=was;
}
void resetHardware(bool sd=false) {
  using namespace mesh::radiousb;
  assert(!work.active.load());
  rtc=RtcMock{};rtc.COUNTER=100;rtc.CC[0]=9876;
  primask=basepri=faultmask=0;inIsr=false;nrf_nvic_state.__cr_flag=0;
  currentTask=&loopTask;loopTask.priority=1;
  sdkQueryResult=0;sdkQueryEnabled=sd;sdkQueries=0;failOperation=0;
  for(unsigned i=0;i<64;++i) { irqEnabled[i]=false;irqPending[i]=false;irqPriority[i]=0; }
  irqEnabled[USBD_IRQn]=true;irqPriority[USBD_IRQn]=6;
  irqEnabled[GPIOTE_IRQn]=true;irqPriority[GPIOTE_IRQn]=6;
  if(sd) irqPriority[RTC2_IRQn]=7;
  nvicChanges=sdkCalls=sdkFailures=taskYields=0;
}
void restoredHardware(bool sd=false) {
  using namespace mesh::radiousb;
  assert(!work.active.load() && mesh_hil_radio_usb_irq.active==0);
  assert(irqEnabled[USBD_IRQn] && !irqEnabled[RTC2_IRQn]);
  assert(irqPriority[RTC2_IRQn]==unsigned(sd?7:0) && irqPriority[USBD_IRQn]==6);
  assert(!irqPending[RTC2_IRQn] && rtc.INTENSET==0 && rtc.EVTEN==0 && rtc.CC[0]==9876);
  assert(rtc.PRESCALER==0 && rtc.EVENTS_COMPARE[0]==0);
  assert(irqEnabled[GPIOTE_IRQn] && irqPriority[GPIOTE_IRQn]==6);
  assert(primask==0 && basepri==0 && faultmask==0);
}
int earlyFailure() { mesh::radiousb::Guard guard(true);assert(!irqEnabled[USBD_IRQn]);return -1; }
int main() {
  using namespace mesh::radiousb;
  auto& capture=mesh_hil_radio_usb_irq;
  assert(capture.magic==0x4d435255 && capture.version==1 && capture.size_bytes==96);
  SPIClass bus;Nrf52BufferedRadioHal concrete(bus,8000000);ArduinoHal& hal=concrete;
  // All admission exclusions make no NVIC writes and preserve other owners.
  for(unsigned gate=0;gate<18;++gate) {
    resetHardware();bool owned=true;
    switch(gate) {
      case 0: owned=false;break;
      case 1: inIsr=true;break;
      case 2: currentTask=&otherTask;break;
      case 3: loopTask.priority=3;break;
      case 4: primask=1;break;
      case 5: basepri=1;break;
      case 6: faultmask=1;break;
      case 7: nrf_nvic_state.__cr_flag=1;break;
      case 8: irqEnabled[USBD_IRQn]=false;break;
      case 9: irqEnabled[RTC2_IRQn]=true;break;
      case 10: irqPending[RTC2_IRQn]=true;break;
      case 11: rtc.INTENSET=1;break;
      case 12: rtc.EVTEN=1u<<17;break;
      case 13: rtc.EVENTS_COMPARE[1]=1;break;
      case 14: rtc.PRESCALER=31;break;
      case 15: sdkQueryResult=123;break;
      case 16: sdkQueryEnabled=1;irqPriority[RTC2_IRQn]=0;break;
      case 17: sdkQueryEnabled=1;irqPriority[USBD_IRQn]=4;break;
    }
    { Guard guard(owned);assert(!work.active.load()); }
    assert(nvicChanges==0);
  }
  resetHardware();
  irqPending[USBD_IRQn]=true;
  { Guard outer(true);
    assert(work.active.load() && !irqEnabled[USBD_IRQn] && irqEnabled[RTC2_IRQn]);
    assert(irqPending[USBD_IRQn] && irqPriority[RTC2_IRQn]==2 && rtc.CC[0]==132);
    { Guard inner(true); }assert(work.active.load() && !irqEnabled[USBD_IRQn]);
    const unsigned before=hal.yields;
    hal.yield();assert(hal.yields==before && taskYields==1);
    hal.spiBeginTransaction();assert(!hal.transactionUsb);
    outer.release();outer.release();
    assert(irqPending[USBD_IRQn]);
  }
  restoredHardware();assert(sdkCalls==0 && sdkQueries==1);
  // The timer ISR restores USB without another HAL poll/frame returning.
  resetHardware();
  { Guard guard(true);expire();restoredHardware(); }
  restoredHardware();
  // Real buffered transfer can trigger the simulated deadline independently.
  resetHardware();failTransfer=true;
  { Guard guard(true);uint8_t tx[3]={0x86,1,2},rx[3]{};hal.spiTransfer(tx,3,rx);
    assert(rx[0]==uint8_t(tx[0]^0xa5) && bus.bursts==1);
  }
  failTransfer=false;restoredHardware();
  // Cooperative checks also restore before CS or normal TinyUSB flush.
  for(bool frame:{false,true}) {
    resetHardware();rtc.COUNTER=0xfffff0;
    { Guard guard(true);assert(rtc.CC[0]==0x10);rtc.COUNTER=0x10;
      if(frame) { hal.spiBeginTransaction();assert(hal.transactionUsb); }
      else { const unsigned before=hal.yields;hal.yield();assert(hal.yields==before+1); }
    }
    restoredHardware();
  }
  // Expiry racing immediately before USB masking cannot leave USB disabled.
  resetHardware();fireBeforeUsbMask=true;
  { Guard guard(true);restoredHardware(); }restoredHardware();
  // An unrelated/spurious timer IRQ does not clear another source/event.
  resetHardware();rtc.EVENTS_COMPARE[2]=1;RTC2_IRQHandler();
  assert(rtc.EVENTS_COMPARE[2]==1 && nvicChanges==0);
  resetHardware();assert(earlyFailure()==-1);restoredHardware();
  // A separate USB owner cannot silently invalidate the isolation experiment.
  resetHardware();
  { Guard guard(true);const unsigned before=capture.usb_reenabled;
    irqEnabled[USBD_IRQn]=true;hal.yield();
    assert(capture.usb_reenabled==before+1);restoredHardware();
  }
  // SD-on path uses checked inline app-NVIC helpers, including deadline ISR.
  resetHardware(true);
  { Guard guard(true);assert(capture.last_sdk_enabled==1 && capture.last_sdk_result==0);
    expire();restoredHardware(true); }
  assert(sdkCalls>0 && sdkFailures==0 && sdkQueries==1);
  // Fail each admission API before USB can remain masked; restore exact state.
  for(int operation:{1,2,3}) {
    resetHardware(true);failOperation=operation;
    { Guard guard(true); }restoredHardware(true);
    assert(sdkFailures==1);
  }
  resetHardware();
  const unsigned before=hal.yields;
  for(unsigned i=0;i<1000;++i) hal.yield();
  assert(hal.yields==before+1000 && taskYields==0 && nvicChanges==0);
  assert(capture.entries==capture.releases && capture.active==0 && capture.expired>=5);
}
'''


class NrfRadioUsbIrqGuardTests(unittest.TestCase):
    def test_real_guard_hal_and_deadline_isr_preserve_irq_ownership(self):
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory)
            (folder/'hal/Arduino').mkdir(parents=True)
            for name,content in (('Arduino.h',ARDUINO),('nrf_sdm.h',SDM),
                                 ('nrf_nvic.h',NVIC),('nrf_rtc.h',RTC),
                                 ('hal/Arduino/ArduinoHal.h',MOCK),('test.cpp',FIXTURE)):
                (folder/name).write_text(content,encoding='ascii')
            binary=folder/'test.exe'
            built=subprocess.run([os.environ.get('CXX','g++'),'-std=c++17','-Wall',
                '-Wextra','-Werror','-DNRF52_PLATFORM','-DMESH_HIL_PROFILE_TIMING=1',
                '-DMC_NRF_RADIO_PROFILE_USB_IRQ_GUARD=1','-I',str(folder),'-I',str(ROOT/'src'),
                str(folder/'test.cpp'),str(SOURCE),'-o',str(binary)],capture_output=True,text=True,
                env={**os.environ,'TMPDIR':str(folder)})
            self.assertEqual(built.returncode,0,built.stderr)
            ran=subprocess.run([str(binary)],capture_output=True,text=True)
            self.assertEqual(ran.returncode,0,ran.stderr)

    def test_default_off_has_no_code_types_ram_or_sdk_dependencies(self):
        for source in ('#include <helpers/radiolib/NrfRadioUsbIrqGuard.h>\n',SOURCE.read_text()):
            result=subprocess.run([os.environ.get('CXX','g++'),'-E','-P','-x','c++',
                '-I',str(ROOT/'src'),'-I',str(SOURCE.parent),'-'],input=source,
                capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertFalse(result.stdout.strip())

    def test_experiment_requires_hil_nrf_and_separate_priority_measurement(self):
        for flags,diagnostic in (([], 'requires nRF52 HIL profile timing'),
                (['-DNRF52_PLATFORM'],'requires nRF52 HIL profile timing'),
                (['-DMESH_HIL_PROFILE_TIMING=1'],'requires nRF52 HIL profile timing'),
                (['-DNRF52_PLATFORM','-DMESH_HIL_PROFILE_TIMING=1',
                  '-DMC_NRF_RADIO_PROFILE_PRIORITY=1'],'experiments separately')):
            result=subprocess.run([os.environ.get('CXX','g++'),'-E','-x','c++',
                '-DMC_NRF_RADIO_PROFILE_USB_IRQ_GUARD=1',*flags,'-I',str(ROOT/'src'),'-'],
                input='#include <helpers/radiolib/NrfRadioUsbIrqGuard.h>\n',
                capture_output=True,text=True)
            self.assertNotEqual(result.returncode,0)
            self.assertIn(diagnostic,result.stderr)


if __name__=='__main__':
    unittest.main()
