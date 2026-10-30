"""Exercise the opt-in combined HIL priority and USB IRQ experiment."""

from pathlib import Path
import os
import subprocess
import tempfile
import unittest

from test_radio_receive_contract import method
import test_nrf_radio_usb_irq_guard as usb
import test_profile_switch_timing as timing
import test_radio_profile_scan as scan


ROOT = Path(__file__).resolve().parents[1]
FLAGS = ["-DNRF52_PLATFORM", "-DMESH_HIL_PROFILE_TIMING=1",
         "-DMC_NRF_RADIO_PROFILE_PRIORITY=1", "-DMC_NRF_RADIO_PROFILE_USB_IRQ_GUARD=1",
         "-DMC_NRF_RADIO_PROFILE_COMBINED=1"]
ARDUINO = usb.ARDUINO.replace("enum { TASK_PRIO_LOW=1 };", """
enum { TASK_PRIO_LOW=1,TASK_PRIO_HIGH=3 };
#define configMAX_PRIORITIES 5
extern unsigned prioritySets;
extern bool requireUsbBeforeDrop;
inline void vTaskPrioritySet(TaskHandle_t task,unsigned priority) {
  assert(!inIsr && task==&loopTask && priority<5);
  if(priority==TASK_PRIO_LOW && requireUsbBeforeDrop) assert(irqEnabled[USBD_IRQn]);
  task->priority=priority;++prioritySets;
}
""")
# Declarations used by the inserted RTOS function must precede its body.
ARDUINO = ARDUINO.replace("inline void vTaskPrioritySet", """
extern TaskMock loopTask;
extern bool inIsr,irqEnabled[64];
inline void vTaskPrioritySet""").replace(
    "assert(irqEnabled[USBD_IRQn]);", "assert(irqEnabled[39]);")
FIXTURE = usb.FIXTURE.split("int earlyFailure()", 1)[0] + r'''
unsigned prioritySets=0;
bool requireUsbBeforeDrop=false;
@CLEANUP@
void resetBoth() {
  assert(!mesh::radiopriority::work.active);
  resetHardware();prioritySets=0;requireUsbBeforeDrop=false;failTransfer=false;
}
int fallbackReturn() {
  mesh::radiousb::Guard profile_usb_irq(true);
  mesh::radiopriority::Lease profile_priority(true);
  OrderedProfileRelease ordered_profile_release{profile_usb_irq,profile_priority};
  assert(!irqEnabled[USBD_IRQn] && loopTask.priority==4);
  requireUsbBeforeDrop=true;
  return -1; // The production fallback scope must release IRQ before priority.
}
int main() {
  using mesh::radiousb::Guard;
  using mesh::radiopriority::Lease;
  auto& usbCapture=mesh::radiousb::mesh_hil_radio_usb_irq;
  auto& priorityCapture=mesh::radiopriority::mesh_hil_radio_priority;
  SPIClass bus;Nrf52BufferedRadioHal concrete(bus,8000000);ArduinoHal& hal=concrete;
  resetBoth();
  const unsigned usbEntries=usbCapture.entries,priorityEntries=priorityCapture.entries;
  { Guard irq(true);assert(!irqEnabled[USBD_IRQn] && loopTask.priority==1);
    Lease priority(true);assert(loopTask.priority==4);
    assert(usbCapture.entries==usbEntries+1 && priorityCapture.entries==priorityEntries+1);
    for(unsigned i=0;i<32;++i) hal.yield();
    assert(taskYields==0 && hal.yields==0); // Suppress precedes USB's taskYIELD.
    { Guard nestedIrq(true);Lease nestedPriority(true); }
    assert(mesh::radiousb::work.active.load() && mesh::radiopriority::work.active);
    requireUsbBeforeDrop=true;irq.release();priority.release();
  }
  restoredHardware();assert(loopTask.priority==1 && prioritySets==2);

  // Negative control: raising priority first makes USB guard admission fail.
  resetBoth();const unsigned skipped=usbCapture.skipped_task;
  { Lease priority(true);Guard irq(true);
    assert(!mesh::radiousb::work.active.load());
    assert(usbCapture.skipped_task==skipped+1 && irqEnabled[USBD_IRQn]);
  }
  restoredHardware();assert(loopTask.priority==1);
  resetBoth();assert(fallbackReturn()==-1);restoredHardware();assert(loopTask.priority==1);

  // Independent RTC deadline restores the IRQ even while priority remains
  // elevated. It does not promise to schedule USB worker tasks at that time.
  resetBoth();
  { Guard irq(true);rtc.COUNTER+=2;Lease priority(true);
    expire();assert(irqEnabled[USBD_IRQn] && loopTask.priority==4);
    const unsigned before=priorityCapture.suppressed_yields;hal.yield();
    assert(priorityCapture.suppressed_yields==before+1 && taskYields==0);
    requireUsbBeforeDrop=true;irq.release();priority.release();
  }
  restoredHardware();
  // Timer expiry immediately before priority admission cannot leave USB off.
  resetBoth();
  { Guard irq(true);expire();Lease priority(true);
    assert(irqEnabled[USBD_IRQn] && loopTask.priority==4);
    requireUsbBeforeDrop=true;irq.release();priority.release();
  }
  restoredHardware();

  // Force an earlier cooperative priority deadline to exercise Expired while
  // the independent USB guard still owns its IRQ. A normal CDC flush is unsafe.
  resetBoth();
  { Guard irq(true);Lease priority(true);
    mesh::radiopriority::work.started_ticks-=10;rtc.COUNTER=122;
    const unsigned before=hal.yields;hal.yield();
    assert(loopTask.priority==1 && !irqEnabled[USBD_IRQn]);
    assert(taskYields==1 && hal.yields==before);
    rtc.COUNTER=132;hal.yield();assert(irqEnabled[USBD_IRQn] && hal.yields==before+1);
  }
  restoredHardware();

  // Both deadlines must be checked before selecting a new radio command.
  resetBoth();
  { Guard irq(true);Lease priority(true);rtc.COUNTER=132;requireUsbBeforeDrop=true;
    hal.spiBeginTransaction();assert(hal.transactionUsb && loopTask.priority==1);
  }
  restoredHardware();
  // A simulated blocked transfer's timer can restore USB without any HAL
  // yield. Priority remains cooperative and falls at the next returning poll.
  resetBoth();failTransfer=true;
  { Guard irq(true);Lease priority(true);uint8_t tx[3]={0x86,1,2},rx[3]{};
    hal.spiTransfer(tx,3,rx);assert(irqEnabled[USBD_IRQn] && loopTask.priority==4);
    requireUsbBeforeDrop=true;hal.yield();assert(loopTask.priority==1);
  }
  restoredHardware();

  // Admission failures stay distinguishable in the existing independent
  // captures and neither can release the other experiment's ownership.
  resetBoth();sdkQueryResult=123;
  { Guard irq(true);Lease priority(true);
    assert(!mesh::radiousb::work.active.load() && mesh::radiopriority::work.active);
    assert(irqEnabled[USBD_IRQn]);requireUsbBeforeDrop=true;irq.release();priority.release();
  }
  restoredHardware();
  resetBoth();
  { Guard irq(true);loopTask.priority=3;Lease priority(true);loopTask.priority=1;
    assert(mesh::radiousb::work.active.load() && !mesh::radiopriority::work.active);
    irq.release();priority.release();
  }
  restoredHardware();
  resetBoth();
  { Guard irq(false);Lease priority(false);hal.yield(); }
  restoredHardware();assert(prioritySets==0 && taskYields==0);
  assert(usbCapture.entries==usbCapture.releases && priorityCapture.entries==priorityCapture.releases);
}
'''


class NrfRadioCombinedExperimentTests(unittest.TestCase):
    compile_run = timing.ProfileSwitchTimingTest.compile_run

    def test_real_hal_combines_admission_yield_deadlines_and_ordered_restoration(self):
        production = (ROOT / "src/helpers/radiolib/RadioLibWrappers.cpp").read_text()
        cleanup = method(production, "  struct OrderedProfileRelease {") + ";"
        with tempfile.TemporaryDirectory(prefix="mesh-radio-combined-", dir="/var/tmp") as directory:
            folder = Path(directory)
            (folder / "hal/Arduino").mkdir(parents=True)
            for name, content in (("Arduino.h", ARDUINO), ("nrf_sdm.h", usb.SDM),
                                  ("nrf_nvic.h", usb.NVIC), ("nrf_rtc.h", usb.RTC),
                                  ("hal/Arduino/ArduinoHal.h", usb.MOCK),
                                  ("test.cpp", FIXTURE.replace("@CLEANUP@", cleanup))):
                (folder / name).write_text(content, encoding="ascii")
            binary = folder / "test.exe"
            built = subprocess.run([
                os.environ.get("CXX", "g++"), "-std=c++17", "-Wall", "-Wextra", "-Werror",
                "-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-fno-pie", "-no-pie",
                *FLAGS, "-I", str(folder), "-I", str(ROOT / "src"), str(folder / "test.cpp"),
                str(ROOT / "src/helpers/radiolib/NrfRadioPriorityLease.cpp"),
                str(ROOT / "src/helpers/radiolib/NrfRadioUsbIrqGuard.cpp"), "-o", str(binary),
            ], capture_output=True, text=True, env={**os.environ, "TMPDIR": str(folder)})
            self.assertEqual(built.returncode, 0, built.stderr)
            ran = subprocess.run([str(binary)], capture_output=True, text=True)
            self.assertEqual(ran.returncode, 0, ran.stderr)

    def test_real_transaction_admits_usb_first_and_releases_before_publication(self):
        source = (ROOT / "src/helpers/radiolib/RadioLibWrappers.cpp").read_text()
        methods = "\n".join(method(source, signature) for signature in (
            "uint8_t RadioLibWrapper::beginReconfigure(", "void RadioLibWrapper::endReconfigure(",
            "mesh::RadioParamApplyResult RadioLibWrapper::tuneProfile("))
        fixture = scan.HARNESS.split("int main() {", 1)[0]
        fixture = fixture.replace("static uint64_t elapsed_us;", """
static uint64_t elapsed_us;
static bool usb_active=false,priority_active=false,expected_owned=false;
static unsigned usb_entries=0,priority_entries=0,usb_releases=0,priority_releases=0;
static uint32_t sequence_at_start=0;
""")
        fixture = fixture.replace("  void beginProfileRetune(bool) {}", """
  void beginProfileRetune(bool) {}
  bool ownsWarmProfileRetune() const { return true; }
""")
        fixture = fixture.replace("{ ++applies; elapsed_us+=switch_apply_us;", """{
  if(applies==0) assert(usb_active && priority_active);
  else assert(!usb_active && !priority_active);
  ++applies; elapsed_us+=switch_apply_us;""")
        guards = r'''
#include <helpers/radiolib/ProfileSwitchTiming.h>
@GLOBALS@
namespace mesh { namespace radiousb {
struct Guard {
  bool owns=false;
  explicit Guard(bool owned) {
    assert(owned==expected_owned && !priority_active);
    if(owned) { owns=usb_active=true;++usb_entries;elapsed_us+=7; }
  }
  void release() {
    if(!owns) return;
    assert(usb_active && priority_active);
    assert(profiletiming::mesh_hil_profile_timing.sequence==sequence_at_start);
    owns=usb_active=false;++usb_releases;elapsed_us+=3;
  }
  ~Guard() { release(); }
};
} namespace radiopriority {
struct Lease {
  bool owns=false;
  explicit Lease(bool owned) {
    assert(owned==expected_owned);
    if(owned) { assert(usb_active);owns=priority_active=true;++priority_entries;elapsed_us+=11; }
  }
  void release() {
    if(!owns) return;
    assert(!usb_active && priority_active);
    assert(profiletiming::mesh_hil_profile_timing.sequence==sequence_at_start);
    owns=priority_active=false;++priority_releases;elapsed_us+=1000;
  }
  ~Lease() { release(); }
};
} }
'''.replace("@GLOBALS@", timing.ProfileSwitchTimingTest.production_globals())
        fixture = fixture.replace("@METHODS@", guards + methods)
        fixture = "\n".join(flag.replace("-D", "#define ", 1).replace("=", " ") for flag in FLAGS[1:]) + "\n" + fixture
        fixture += r'''
int main() {
  using Result=mesh::RadioParamApplyResult;
  for(unsigned scenario=0;scenario<4;++scenario) {
    RadioLibWrapper radio;
    mesh::RadioProfileConfig second;
    second.params=radio._profiles.primary;second.params.freq+=1;
    second.mode=mesh::RadioProfileMode::RxTx;radio._profiles.setSecondary(second,false);
    radio._rx_ps_enabled=radio._rx_ps_armed=false;radio._profile_refresh_required=true;
    usb_active=priority_active=false;usb_entries=priority_entries=usb_releases=priority_releases=0;
    expected_owned=true;
    if(scenario==1) radio.busy=true;
    if(scenario==2) radio.fail=true;
    if(scenario==3) radio.failRxStarts=1;
    auto& capture=mesh::profiletiming::mesh_hil_profile_timing;
    sequence_at_start=capture.sequence;
    const auto result=radio.tuneProfile(1);
    assert(!usb_active && !priority_active);
    assert(usb_entries==1 && priority_entries==1 && usb_releases==1 && priority_releases==1);
    assert(capture.direction[0].last_us[mesh::profiletiming::Whole]==(scenario==1?18:1218));
    if(scenario==0) {
      assert(result==Result::APPLIED && radio._profiles.longest_switch_us==1218);
      assert(elapsed_us-radio._profile_visit_stamp==1003);
    } else if(scenario==1) assert(result==Result::BUSY && radio.applies==0);
    else assert(result==Result::FAILED && radio.applies==2);
  }
}
'''
        self.compile_run(fixture)

    def test_opt_in_is_required_and_never_enables_missing_experiments(self):
        config = ROOT / "src/helpers/radiolib/NrfRadioProfileExperimentConfig.h"
        for flags, succeeds, diagnostic in (
            ([], True, ""),
            (["-DMC_NRF_RADIO_PROFILE_COMBINED=0"], True, ""),
            (["-DMC_NRF_RADIO_PROFILE_PRIORITY=1", "-DMC_NRF_RADIO_PROFILE_USB_IRQ_GUARD=1"],
             False, "experiments separately"),
            (["-DMC_NRF_RADIO_PROFILE_COMBINED=1"], False, "requires both"),
            (["-DMC_NRF_RADIO_PROFILE_COMBINED=1", "-DMC_NRF_RADIO_PROFILE_PRIORITY=1"], False, "requires both"),
            (["-DMC_NRF_RADIO_PROFILE_COMBINED=1", "-DMC_NRF_RADIO_PROFILE_USB_IRQ_GUARD=1"], False, "requires both"),
            (["-DMC_NRF_RADIO_PROFILE_COMBINED=2"], False, "must be 0 or 1"),
            (FLAGS[2:], True, ""),
        ):
            with self.subTest(flags=flags):
                result = subprocess.run([os.environ.get("CXX", "g++"), "-E", "-P", "-x", "c++",
                                         *flags, str(config)], capture_output=True, text=True)
                self.assertEqual(result.returncode == 0, succeeds, result.stderr)
                if diagnostic:
                    self.assertIn(diagnostic, result.stderr)
                else:
                    self.assertFalse(result.stdout.strip())


if __name__ == "__main__":
    unittest.main()
