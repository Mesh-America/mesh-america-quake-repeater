"""Execute the real profile transaction's optional priority-lease boundaries."""
from pathlib import Path
import unittest

from test_radio_receive_contract import method
import test_profile_switch_timing as timing
import test_radio_profile_scan as scan


ROOT=Path(__file__).resolve().parents[1]


class NrfRadioPriorityIntegrationTests(unittest.TestCase):
    compile_run=timing.ProfileSwitchTimingTest.compile_run

    def test_real_transaction_includes_entry_cost_and_releases_before_stats_or_rollback(self):
        self.exercise_real_transaction('MC_NRF_RADIO_PROFILE_PRIORITY', 'radiopriority', 'Lease')

    def test_usb_irq_guard_uses_same_measured_endpoint_and_failure_release_contract(self):
        self.exercise_real_transaction('MC_NRF_RADIO_PROFILE_USB_IRQ_GUARD', 'radiousb', 'Guard')

    def exercise_real_transaction(self, flag, namespace, guard_type):
        source=(ROOT/"src/helpers/radiolib/RadioLibWrappers.cpp").read_text()
        methods="\n".join(method(source,signature) for signature in (
            "uint8_t RadioLibWrapper::beginReconfigure(",
            "void RadioLibWrapper::endReconfigure(",
            "mesh::RadioParamApplyResult RadioLibWrapper::tuneProfile("))
        fixture=scan.HARNESS.split("int main() {",1)[0]
        fixture=fixture.replace("static uint64_t elapsed_us;",r'''
static uint64_t elapsed_us;
static bool priority_active=false,expected_owned=false,applied_priority[8]={};
static unsigned entries=0,releases=0;
static uint32_t sequence_at_start=0;
''')
        fixture=fixture.replace("  void beginProfileRetune(bool) {}",r'''
  bool warm_allowed=true,retune_owned=false;
  void beginProfileRetune(bool continuous) { retune_owned=continuous && warm_allowed; }
  bool ownsWarmProfileRetune() const { return retune_owned; }
''').replace("  void endProfileRetune(bool) {}",
             "  void endProfileRetune(bool) { retune_owned=false; }")
        fixture=fixture.replace("{ ++applies; elapsed_us+=switch_apply_us;",
            "{ applied_priority[applies]=priority_active; ++applies; elapsed_us+=switch_apply_us;")
        globals_source=timing.ProfileSwitchTimingTest.production_globals()
        lease=r'''
#include <helpers/radiolib/ProfileSwitchTiming.h>
@GLOBALS@
namespace mesh { namespace @NAMESPACE@ {
class @GUARD_TYPE@ {
  bool admitted=false;
 public:
  explicit @GUARD_TYPE@(bool owned) {
    assert(owned==expected_owned);
    if(!owned) return;
    assert(!priority_active);
    admitted=priority_active=true;++entries;
    elapsed_us+=11; // Raising priority must be charged to the hop.
  }
  void release() {
    if(!admitted) return;
    assert(priority_active);
    // Timing publication must happen after normal priority is restored.
    assert(profiletiming::mesh_hil_profile_timing.sequence==sequence_at_start);
    admitted=priority_active=false;++releases;
    elapsed_us+=1000; // Model immediate USB scheduling during restoration.
  }
  ~@GUARD_TYPE@() { release(); }
};
} }
'''.replace("@GLOBALS@",globals_source).replace('@NAMESPACE@',namespace).replace('@GUARD_TYPE@',guard_type)
        fixture=fixture.replace("@METHODS@",lease+methods)
        fixture=r'''#define MESH_HIL_PROFILE_TIMING 1
#define @FLAG@ 1
'''.replace('@FLAG@',flag)+fixture+r'''
int main() {
  using Result=mesh::RadioParamApplyResult;
  for(unsigned scenario=0;scenario<8;++scenario) {
    RadioLibWrapper radio;
    mesh::RadioProfileConfig second;
    second.params=radio._profiles.primary;second.params.freq+=1;
    second.mode=mesh::RadioProfileMode::RxTx;
    radio._profiles.setSecondary(second,false);
    radio._rx_ps_enabled=radio._rx_ps_armed=false;
    radio._profile_refresh_required=true;
    entries=releases=0;priority_active=false;
    for(bool& value:applied_priority) value=false;
    uint8_t target=1;
    switch(scenario) {
      case 1: radio.busy=true;break;
      case 2: radio.fail=true;break;
      case 3: radio.failRxStarts=1;break;
      case 4: radio.warm_allowed=false;break;
      case 5: radio._rx_ps_enabled=true;break;
      case 6: radio._rx_ps_armed=true;break;
      case 7: target=0;break;
    }
    expected_owned=scenario<4;
    auto& capture=mesh::profiletiming::mesh_hil_profile_timing;
    sequence_at_start=capture.sequence;
    const auto result=radio.tuneProfile(target);
    assert(!priority_active && entries==unsigned(expected_owned) && releases==entries);
    if(scenario==1) {
      assert(result==Result::BUSY && radio.applies==0);
      assert(capture.direction[0].last_us[mesh::profiletiming::Whole]==11);
    } else if(scenario==2 || scenario==3) {
      assert(result==Result::FAILED && radio.applies==2);
      assert(applied_priority[0] && !applied_priority[1]);
      assert(capture.direction[0].last_result==mesh::profiletiming::Failure);
      assert(capture.direction[0].last_us[mesh::profiletiming::Whole]==1211);
    } else {
      assert(result==Result::APPLIED);
      if(scenario==0) {
        assert(applied_priority[0]);
        assert(radio._profiles.longest_switch_us==1211);
        assert(radio._profiles.switch_test_max_us[0]==1211);
        assert(capture.direction[0].last_us[mesh::profiletiming::Whole]==1211);
        assert(elapsed_us-radio._profile_visit_stamp==1000);
      } else assert(!applied_priority[0]);
    }
  }
}
'''
        self.compile_run(fixture)

    def test_chip_capability_requires_live_owned_warm_receive_state(self):
        source=(ROOT/"src/helpers/radiolib/CustomSX1262.h").read_text()
        accessor=method(source,"bool hilOwnsWarmProfileRetune(")
        self.compile_run(r'''
#include <cassert>
#include <helpers/radiolib/SX1262ProfileSwitchState.h>
struct Radio {
  SX1262ProfileSwitchState _profileSwitch{true};
  bool _coldStandby=false;
  @ACCESSOR@
};
int main() {
  for(unsigned gate=0;gate<7;++gate) {
    Radio radio;
    radio._profileSwitch.rxResult(0,true);
    radio._profileSwitch.begin(true,true);
    assert(radio.hilOwnsWarmProfileRetune());
    switch(gate) {
      case 0: radio._profileSwitch.end(true);break;
      case 1: radio._profileSwitch.begin(false,true);break;
      case 2: radio._profileSwitch.begin(true,false);break;
      case 3: radio._profileSwitch.rxResult(-1,true);break;
      case 4: radio._profileSwitch.standbyResult(-1);break;
      case 5: radio._profileSwitch.invalidate();break;
      case 6: radio._coldStandby=true;break;
    }
    assert(!radio.hilOwnsWarmProfileRetune());
  }
}
'''.replace("@ACCESSOR@",accessor))


if __name__=="__main__":
    unittest.main()
