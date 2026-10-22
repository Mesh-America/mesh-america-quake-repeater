"""Execute bounded trace state and the real checked IRQ/activity hooks."""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest

from cpp_source import body

ROOT = Path(__file__).resolve().parents[1]


def compile_cpp(folder, source, name="trace", flags=()):
    cpp, binary = Path(folder) / (name + ".cpp"), Path(folder) / name
    cpp.write_text(source, encoding="ascii")
    command = [os.environ.get("CXX", "g++"), "-std=c++17", "-O1", "-g",
               "-Wall", "-Wextra", "-Werror", "-fsanitize=address,undefined",
               "-fno-sanitize-recover=all", "-fno-omit-frame-pointer", "-no-pie",
               "-I", str(ROOT / "src"), *flags, str(cpp), "-o", str(binary)]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode:
        raise AssertionError(result.stdout + result.stderr)
    return binary


class RadioTraceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory(prefix="mc-radio-trace-")
        cls.binary = compile_cpp(cls.folder.name,
            (ROOT / "test/fixtures/esp32_radio_trace.cpp").read_text(),
            flags=("-DESP32_PLATFORM", "-DMESH_HIL_RADIO_TRACE=1"))

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def run_case(self, name):
        result = subprocess.run([str(self.binary), name], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_capture_lifetime_and_rearm(self): self.run_case("lifetime")
    def test_conservative_holds_receipts_and_blackout(self): self.run_case("holds")
    def test_checked_tx_event_bounds_and_first_positive(self): self.run_case("tx")
    def test_failed_spi_zero_is_never_a_lower_bound(self): self.run_case("spi")
    def test_clipping_and_frozen_immutability(self): self.run_case("freeze")
    def test_overflow_never_overwrites_and_wrong_phy_fails_closed(self): self.run_case("overflow")
    def test_scan_gap_has_an_exact_interval_and_separate_deadline(self): self.run_case("scan")
    def test_capture_and_launch_epochs_cannot_reuse_old_bounds(self): self.run_case("epochs")

    def test_disabled_object_has_no_buffer_clock_hash_or_sdk_dependencies(self):
        # This compiles without ESP32 SDK include paths. Both absence of the
        # flag and an explicit zero must remove all implementation/dependencies.
        with tempfile.TemporaryDirectory(prefix="mc-radio-trace-off-") as folder:
            for index, flags in enumerate(((), ("-DESP32_PLATFORM",),
                    ("-DESP32_PLATFORM", "-DMESH_HIL_RADIO_TRACE=0"),
                    ("-DNRF52_PLATFORM", "-DMESH_HIL_RADIO_TRACE=1"))):
                obj = Path(folder) / (str(index) + ".o")
                result = subprocess.run([os.environ.get("CXX", "g++"), "-std=c++11",
                    *flags, "-c", str(ROOT / "src/helpers/radiolib/ESP32RadioTrace.cpp"),
                    "-o", str(obj)], capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                symbols = subprocess.check_output(["nm", "-C", str(obj)], text=True)
                self.assertNotIn("radiotrace", symbols)
                self.assertNotIn("esp_timer", symbols)
                self.assertNotIn("sha256", symbols)
                self.assertNotIn(" U ", symbols)

    def test_tx_only_mode_has_no_receiver_capture_and_keeps_the_ram_reserve(self):
        source = r'''
#include <cassert>
#include <helpers/radiolib/ESP32RadioTrace.h>
using namespace mesh::radiotrace;
int main() {
  static_assert(SpanCapacity == 0 && RxCapacity == 0 && BucketCapacity == 0, "sender storage");
  static_assert(sizeof(Trace) <= 2048, "sender reserve");
  Trace t;int radio=0;t.context(&radio,0,1);assert(t.arm(100,0,1000));
  t.activity(&radio,110,111,true,false,None);
  assert(t.receiveRead(&radio,120)==NoIndex);
  t.scan(&radio,130,100,20);
  assert(!t.span_count && !t.rx_count && !t.bucket_count);
  for(unsigned i=0;i<40;++i) {
    t.context(&radio,0,i+2); // physical primary is retuned to each planned tuple
    t.transmitPrepare(&radio,200+i*10,i,101,100);
    t.transmitLaunch(&radio,200+i*10,200+i*10,200+i*10,0);
    t.dio(&radio,201+i*10,202+i*10,false);
    t.irq(&radio,203+i*10,204+i*10,0,1);
    t.transmitFinish(&radio,205+i*10,true);
    assert(!t.tx[i].flags);
  }
  assert(t.tx_count==40 && !t.tx_dropped && !t.flags);
  Trace interrupted;interrupted.context(&radio,0,1);assert(interrupted.arm(100,0,1000));
  interrupted.transmitPrepare(&radio,200,1,101,100);
  interrupted.transmitLaunch(&radio,200,201,202,0);
  interrupted.dio(&radio,203,204,false);
  interrupted.context(&radio,0,2); // a live TX may never survive a tuple replacement
  interrupted.irq(&radio,205,206,0,1);
  interrupted.transmitFinish(&radio,207,true);
  assert((interrupted.tx[0].flags&(Invalid|Interrupted|MissingBound))==(Invalid|Interrupted|MissingBound));
}
'''
        with tempfile.TemporaryDirectory(prefix="mc-radio-trace-tx-") as folder:
            binary = compile_cpp(folder, source, flags=("-DESP32_PLATFORM",
                "-DMESH_HIL_RADIO_TRACE=1", "-DMESH_HIL_RADIO_TRACE_TX_ONLY=1"))
            result = subprocess.run([str(binary)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_actual_irq_and_activity_hooks_preserve_transactions_and_returns(self):
        chip = (ROOT / "src/helpers/radiolib/CustomSX1262.h").read_text()
        irq = body(chip, "uint32_t getIrqFlags() override")
        activity = body(chip, "bool isReceiving()")
        source = r'''
#include <cassert>
#include <cstdint>
#include <helpers/radiolib/ESP32RadioTrace.h>
#define MESH_DEBUG_PRINTLN(...) ((void)0)
#define RADIOLIB_SX126X_CMD_GET_IRQ_STATUS 0x12
#define RADIOLIB_SX126X_IRQ_PREAMBLE_DETECTED 4U
#define RADIOLIB_SX126X_IRQ_HEADER_VALID 16U
#define RADIOLIB_SX126X_IRQ_HEADER_ERR 32U
#define RADIOLIB_SX126X_IRQ_SYNC_WORD_VALID 8U
static uint64_t clock_us=1000000;
static unsigned clock_reads=0;
uint32_t millis(){return clock_us/1000;}
namespace mesh {namespace radiotrace {
Trace& trace(){static Trace t;return t;}
uint64_t nowUs(){++clock_reads;return clock_us;}
}}
struct Module {
  uint32_t irq=0;unsigned reads=0,clears=0;int16_t status=0;
  int16_t SPIreadStream(uint8_t command,uint8_t* data,size_t length) {
    assert(command==0x12 && length==2);++reads;
    // A failing transfer may have returned either zero or partial bytes.
    data[0]=uint8_t(irq>>8);data[1]=uint8_t(irq);return status;
  }
};
struct PhysicalLayer {virtual uint32_t getIrqFlags()=0;virtual ~PhysicalLayer()=default;};
struct Chip : PhysicalLayer {
  Module module;Module* mod=&module;
  uint32_t _activityAt=0,_preambleMillis=99,_maxPayloadMillis=1456;
  bool _headerSeen=false,busy=false;
  bool isChipBusy(){return busy;}
  void clearIrqFlags(uint32_t bits){++module.clears;module.irq&=~bits;}
  @IRQ@
  @ACTIVITY@
};
int main() {
  using namespace mesh::radiotrace;
  Chip c;trace().context(static_cast<PhysicalLayer*>(&c),0,1);
  c.module.irq=4;assert(c.isReceiving());
  c.module.irq=0;assert(!c.isReceiving());
  assert(c.module.reads==2 && !clock_reads); // runtime-off evaluates no timer args
  assert(trace().arm(clock_us,0,10000));
  clock_us+=1000;c.module.irq=4;assert(c.isReceiving());
  assert(trace().span_count==1);
  clock_us+=99000;assert(c.isReceiving());
  clock_us+=1000;assert(!c.isReceiving());
  assert(trace().spans[0].reason==PreambleExpired);
  assert(c.module.reads==5 && c.module.clears==1);
  clock_us+=1000;c.module.irq=4;assert(c.isReceiving());
  clock_us+=1000;c.module.irq=4|16;assert(c.isReceiving());
  clock_us+=1457000;assert(!c.isReceiving());
  assert(trace().spans[1].reason==PayloadExpired && c.module.clears==2);
  clock_us+=1000;c.module.irq=4;assert(c.isReceiving());
  clock_us+=1000;c.module.irq=4|32;assert(!c.isReceiving());
  assert(trace().spans[2].reason==HeaderError && c.module.clears==3);
  // Exactly one read occurs for the checked override, including failures,
  // and its returned bytes remain the same as the legacy implementation.
  auto before=c.module.reads;c.module.status=-707;c.module.irq=0x1234;
  assert(c.getIrqFlags()==0x1234 && c.module.reads==before+1);
  assert(trace().spi_errors==1 && (trace().flags&Invalid));
}
'''.replace("@IRQ@", irq).replace("@ACTIVITY@", activity)
        with tempfile.TemporaryDirectory(prefix="mc-radio-trace-hooks-") as folder:
            binary = compile_cpp(folder, source, flags=("-DESP32_PLATFORM", "-DMESH_HIL_RADIO_TRACE=1"))
            result = subprocess.run([str(binary)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_actual_launch_success_failure_timeout_and_compiled_out_side_effects(self):
        chip = (ROOT / "src/helpers/radiolib/CustomSX1262.h").read_text()
        launch = body(chip, "int16_t launchMode() override")
        source = r'''
#include <cassert>
#include <cstdint>
#include <helpers/radiolib/ESP32RadioTrace.h>
#define RADIOLIB_RADIO_MODE_TX 3
#define RADIOLIB_RADIO_MODE_NONE 0
#define RADIOLIB_SX126X_TX_TIMEOUT_NONE 0
#define RADIOLIB_ERR_NONE 0
#define RADIOLIB_ERR_SPI_CMD_TIMEOUT -707
#define SX126X_TX_BUSY_TIMEOUT_MS 3
using RadioLibTime_t=uint32_t;
static uint64_t clock_us=1000000;
static unsigned clock_reads=0;
#if MESH_RADIO_TRACE_ENABLED
namespace mesh {namespace radiotrace {
Trace& trace(){static Trace t;return t;}
uint64_t nowUs(){++clock_reads;return clock_us;}
}}
#endif
struct Hal {
  unsigned yields=0;
  uint32_t millis(){return clock_us/1000;}
  void yield(){++yields;clock_us+=1000;}
};
struct Module {
  Hal hal_value;Hal* hal=&hal_value;unsigned rf_calls=0;
  void setRfSwitchState(int){++rf_calls;}
};
struct PhysicalLayer {virtual int16_t launchMode()=0;virtual ~PhysicalLayer()=default;};
struct SX1262 : PhysicalLayer {
  unsigned base_calls=0;
  int16_t launchMode()override{++base_calls;return 91;}
};
struct Chip : SX1262 {
  Module module;Module* mod=&module;
  int stagedMode=3,txMode=2;int16_t set_result=0;
  unsigned set_calls=0,busy_reads=0,busy_loops=2;
  int16_t setTx(int){++set_calls;clock_us+=37;return set_result;}
  bool isChipBusy(){return ++busy_reads<=busy_loops;}
  @LAUNCH@
};
int main() {
  Chip off;assert(off.launchMode()==0);
  assert(off.set_calls==1 && off.busy_reads==3 && off.module.rf_calls==1);
  assert(off.module.hal->yields==2 && off.stagedMode==0 && !clock_reads);
  Chip base;base.stagedMode=1;assert(base.launchMode()==91);
  assert(base.base_calls==1 && !base.set_calls && !clock_reads);
#if MESH_RADIO_TRACE_ENABLED
  using namespace mesh::radiotrace;
  for (int test=0;test<3;++test) {
    Chip c;if(test==1)c.set_result=-20;if(test==2)c.busy_loops=100;
    trace().context(static_cast<PhysicalLayer*>(&c),0,1);
    assert(trace().arm(clock_us,0,1000));
    trace().transmitPrepare(static_cast<PhysicalLayer*>(&c),clock_us,1,101,100);
    const auto expected=clock_us;
    const int16_t result=c.launchMode();
    auto& r=trace().tx[0];
    assert(r.launch_lo_us==expected-trace().epoch_us && r.launch_hi_us-r.launch_lo_us==37);
    assert(c.set_calls==1 && c.module.rf_calls==1 && c.stagedMode==0);
    if(test==0) {
      assert(result==0 && r.busy_low_us-r.launch_lo_us==2037);
      assert(c.busy_reads==3 && c.module.hal->yields==2);
      trace().dio(static_cast<PhysicalLayer*>(&c),clock_us+1,clock_us+2,false);
      trace().irq(static_cast<PhysicalLayer*>(&c),clock_us+3,clock_us+4,0,1);
      trace().transmitFinish(static_cast<PhysicalLayer*>(&c),clock_us+5,true);
      assert(!r.flags);
    } else {
      assert(result==(test==1?-20:-707) && r.busy_low_us==NoTime);
      assert(c.busy_reads==unsigned(test==1?0:3));
      assert(c.module.hal->yields==unsigned(test==1?0:3));
      trace().transmitFinish(static_cast<PhysicalLayer*>(&c),clock_us+5,false);
      assert((r.flags&(Invalid|Interrupted|MissingBound))==(Invalid|Interrupted|MissingBound));
    }
    trace().stop(clock_us+6);clock_us+=10000;
  }
#endif
}
'''.replace("@LAUNCH@", launch)
        with tempfile.TemporaryDirectory(prefix="mc-radio-trace-launch-") as folder:
            for value in (0, 1):
                binary = compile_cpp(folder, source, name="launch" + str(value),
                    flags=("-DESP32_PLATFORM", "-DMESH_HIL_RADIO_TRACE=" + str(value)))
                result = subprocess.run([str(binary)], capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                if value == 0:
                    symbols = subprocess.check_output(["nm", "-C", str(binary)], text=True)
                    self.assertNotIn("radiotrace", symbols)


if __name__ == "__main__": unittest.main()
