"""Execute optional RAM timing aggregation without radio hardware."""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest

from test_radio_receive_contract import method
import test_radio_profile_scan as scan

ROOT = Path(__file__).resolve().parents[1]


class ProfileSwitchTimingTest(unittest.TestCase):
    def compile_run(self, source):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / "Arduino.h").write_text(
                "#pragma once\n#include <cstdint>\n#include <cmath>\n")
            cpp, binary = folder / "test.cpp", folder / "test.exe"
            cpp.write_text(source, encoding="ascii")
            built = subprocess.run([os.environ.get("CXX", "g++"), "-std=c++17",
                "-Wall", "-Wextra", "-I", str(folder), "-I", str(ROOT / "src"),
                str(cpp), "-o", str(binary)], capture_output=True, text=True)
            self.assertEqual(built.returncode, 0, built.stderr)
            ran = subprocess.run([str(binary)], capture_output=True, text=True)
            self.assertEqual(ran.returncode, 0, ran.stderr)

    @staticmethod
    def production_globals():
        source = (ROOT / "src/helpers/radiolib/RadioLibWrappers.cpp").read_text()
        return source.split("#if MESH_HIL_PROFILE_TIMING\n", 1)[1].split("#endif", 1)[0]

    def test_direction_histogram_clock_wrap_failures_and_split_sum(self):
        self.compile_run(r'''
#include <cassert>
#include <cstdint>
#define MESH_HIL_PROFILE_TIMING 1
#define NRF52_PLATFORM 1
struct FakeDwt { uint32_t CYCCNT=0; } fakeDwt;
#define DWT (&fakeDwt)
static bool clockEnabled=false;
static unsigned enableCalls=0;
bool dwt_enabled() { return clockEnabled; }
void dwt_enable() { clockEnabled=true; ++enableCalls; }
#include <helpers/radiolib/ProfileSwitchTiming.h>
@GLOBALS@
int main() {
  using namespace mesh::profiletiming;
  auto& capture=mesh_hil_profile_timing;
  assert(capture.magic==Magic && capture.version==2 && capture.size_bytes==1808);
  assert(capture.clock_hz==64000000 && capture.sequence==0);
  initializeClock();
  assert(enableCalls==1 && capture.clock_state==2);
  initializeClock();
  assert(enableCalls==1 && capture.clock_state==3 && capture.clock_initializations==2);
  fakeDwt.CYCCNT=1234; assert(readClock()==1234);

  // Raw counter wrap inside an awake hop is handled before /64 conversion.
  uint32_t ticks=0xfffff000U;
  begin(0,1,ticks);
  for(uint32_t stage=0;stage<Whole;++stage) {
    ticks+=(40+10*stage)*64;
    mark(static_cast<Stage>(stage),ticks);
  }
  finish(Success,ticks);
  assert(capture.sequence==2 && !(capture.sequence&1));
  const auto& forward=capture.direction[0];
  assert(forward.successes==1 && forward.busy==0 && forward.failures==0);
  assert(forward.last_mask==511 && forward.last_us[Whole]==600);
  assert(forward.worst_us[Whole]==600 && forward.worst_us[Frequency]==50);
  assert(forward.stage[Whole].sum_low_us==600 && forward.stage[Whole].sum_high_us==0);
  assert(forward.stage[Whole].min_us==600 && forward.stage[Whole].max_us==600);
  assert(forward.stage[Whole].histogram[9]==1);
  for(uint32_t stage=0;stage<Whole;++stage)
    assert(forward.stage[stage].last_us==40+10*stage);

  // Aborts keep partial evidence but never inflate successful timing stats.
  begin(1,0,100); mark(BeginReconfigure,100+1000*64); finish(Busy,100+1000*64);
  assert(capture.direction[1].busy==1 && capture.direction[1].successes==0);
  assert(capture.direction[1].stage[Whole].count==0);
  assert(capture.direction[1].last_us[Whole]==1000);
  begin(1,0,100); mark(Frequency,100+1100*64); finish(Failure,100+1100*64);
  assert(capture.direction[1].failures==1 && capture.direction[1].stage[Frequency].count==0);
  const uint32_t sequence=capture.sequence;
  // Marks after failure, rollback, same-profile refresh, or malformed profile
  // values cannot append samples to the old transaction.
  mark(Frequency,0); finish(Success,0);
  begin(0,0,0); mark(Frequency,100); finish(Success,100);
  begin(2,0,0); finish(Success,100);
  assert(capture.sequence==sequence);

  auto& sum=capture.direction[0].stage[Frequency];
  sum.sum_low_us=0xfffffff5U; sum.sum_high_us=3;
  begin(0,1,0); mark(Frequency,20*64); finish(Success,20*64);
  assert(sum.sum_low_us==9 && sum.sum_high_us==4);
  assert(sum.min_us==20 && sum.max_us==50 && sum.count==2);
  assert(forward.worst_us[Whole]==600 && forward.worst_us[Frequency]==50);
  begin(1,0,0); mark(Frequency,960*64); finish(Success,960*64);
  assert(capture.direction[1].stage[Frequency].histogram[15]==1);
  begin(1,0,0); mark(Frequency,10000*64); finish(Success,10000*64);
  assert(capture.direction[1].stage[Frequency].histogram[15]==2);
  assert(capture.direction[1].worst_us[Whole]==10000);
  assert(capture.direction[1].worst_us[Frequency]==10000);
}
'''.replace("@GLOBALS@", self.production_globals()))

    def test_real_profile_transaction_retains_success_busy_and_rollback(self):
        source = (ROOT / "src/helpers/radiolib/RadioLibWrappers.cpp").read_text()
        names = [('uint8_t', 'beginReconfigure'), ('void', 'endReconfigure'),
                 ('void', 'serviceProfileScan')] + [
            ('mesh::RadioParamApplyResult', name) for name in [
                'tuneProfile', 'prepareTransmitProfile', 'tryRestoreCodingRate',
                'trySetParams', 'trySetPrimaryParams']]
        methods = '\n'.join(method(source, f'{kind} RadioLibWrapper::{name}(')
                            for kind, name in names)
        methods += '\n' + method(source,
            'mesh::RadioParamApplyResult RadioLibWrapper::prepareTransmitProfile(uint8_t profile, bool')
        wrapper = (ROOT / 'src/helpers/radiolib/CustomSX1262Wrapper.h').read_text()
        methods += '\n' + method(wrapper, 'void setProfileStandbyWarm(').replace(
            'void setProfileStandbyWarm(bool enabled) override',
            'void RadioLibWrapper::setProfileStandbyWarm(bool enabled)')
        prefix = '#include <helpers/radiolib/ProfileSwitchTiming.h>\n' + self.production_globals()
        fixture = scan.HARNESS.replace('@METHODS@', prefix + methods)
        self.compile_run('#define MESH_HIL_PROFILE_TIMING 1\n' + fixture)

    def test_disabled_header_has_no_instrumentation_or_ram_definition(self):
        source = '#include <helpers/radiolib/ProfileSwitchTiming.h>\nint main() {}\n'
        preprocessed = subprocess.run([os.environ.get('CXX', 'g++'), '-E', '-P',
            '-x', 'c++', '-I', str(ROOT / 'src'), '-'], input=source,
            capture_output=True, text=True)
        self.assertEqual(preprocessed.returncode, 0, preprocessed.stderr)
        self.assertEqual(preprocessed.stdout.strip(), 'int main() {}')


if __name__ == '__main__':
    unittest.main()
