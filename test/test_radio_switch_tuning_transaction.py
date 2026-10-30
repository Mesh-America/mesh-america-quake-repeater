"""Run the actual tuning transaction with radio ownership and RX/save faults."""
from pathlib import Path
import unittest
from test_radio_receive_contract import method
from test_radio_interrupt_recovery import compile_run

ROOT = Path(__file__).resolve().parents[1]


class RadioSwitchTransactionTest(unittest.TestCase):
    def test_admission_restore_and_commit_order(self):
        source = (ROOT / 'src/helpers/radiolib/RadioLibWrappers.cpp').read_text()
        transaction = method(source, 'mesh::RadioParamApplyResult RadioLibWrapper::trySetSwitchTuning(')
        compile_run(r'''
#include <cassert>
#include <initializer_list>
#include <helpers/RadioSwitchTuning.h>
namespace mesh { enum class RadioParamApplyResult { APPLIED, BUSY, FAILED }; }
using Result=mesh::RadioParamApplyResult;
struct RadioLibWrapper {
  mesh::RadioSwitchTuning policy;
  struct { unsigned resets=0; void resetSwitchTest(){++resets;} } _profiles;
  uint8_t admission=1;
  bool receiving=true, fail_rx=false, inject_packet=false, pending_packet=false;
  unsigned admissions=0, resumes=0, mutations=0;
  mesh::RadioSwitchCapabilities switchTuningCapabilities()const {
    mesh::RadioSwitchCapabilities caps; caps.flags=63; return caps;
  }
  mesh::RadioSwitchTuning switchTuning()const{return policy;}
  uint8_t beginReconfigure(){++admissions;return pending_packet?2:admission;}
  void setDriverSwitchFeatures(uint8_t value){++mutations;policy.flags=value;}
  bool configureBootSwitchTuning(const mesh::RadioSwitchTuning& value){
    setDriverSwitchFeatures(value.flags);return true;
  }
  void endReconfigure(bool resume) {
    if(resume){++resumes;receiving=!fail_rx;if(inject_packet)pending_packet=true;}
  }
  bool isInRecvMode()const{return receiving;}
  Result trySetSwitchTuning(const mesh::RadioSwitchTuning&,
      bool(*)(void*,const mesh::RadioSwitchTuning&)=nullptr,void*=nullptr);
};
struct Commit {
  RadioLibWrapper* radio;
  bool fail=false;
  unsigned calls=0;
  static bool save(void* context,const mesh::RadioSwitchTuning& value){
    auto& self=*static_cast<Commit*>(context);
    ++self.calls;
    assert(self.radio->receiving && self.radio->policy==value);
    return !self.fail;
  }
};
'''.replace('void*=nullptr', 'void* = nullptr') + transaction + r'''
int main(){
  mesh::RadioSwitchTuning requested;requested.flags=63;
  for(uint8_t rejected:{uint8_t(2),uint8_t(3)}){
    RadioLibWrapper radio;radio.admission=rejected;Commit store{&radio};
    auto result=radio.trySetSwitchTuning(requested,Commit::save,&store);
    assert(result==(rejected==2?Result::BUSY:Result::FAILED));
    assert(!radio.policy.flags && !radio.mutations && !store.calls && !radio._profiles.resets);
  }
  {
    RadioLibWrapper radio;radio.pending_packet=true;Commit store{&radio};
    assert(radio.trySetSwitchTuning(requested,Commit::save,&store)==Result::BUSY);
    assert(radio.pending_packet && !radio.mutations && !radio.resumes && !store.calls);
  }
  {
    RadioLibWrapper radio;Commit store{&radio};
    auto invalid=requested;invalid.flags|=64;
    assert(radio.trySetSwitchTuning(invalid,Commit::save,&store)==Result::FAILED);
    assert(!radio.admissions && !radio.mutations && !store.calls);
    assert(radio.trySetSwitchTuning(requested,Commit::save,&store)==Result::APPLIED);
    assert(radio.policy==requested && radio._profiles.resets==1 && store.calls==1);
  }
  {
    RadioLibWrapper radio;radio.fail_rx=true;Commit store{&radio};
    assert(radio.trySetSwitchTuning(requested,Commit::save,&store)==Result::FAILED);
    assert(!radio.policy.flags && !store.calls && radio.mutations==2);
  }
  {
    RadioLibWrapper radio;radio.inject_packet=true;Commit store{&radio};store.fail=true;
    assert(radio.trySetSwitchTuning(requested,Commit::save,&store)==Result::FAILED);
    assert(!radio.policy.flags && store.calls==1 && radio.pending_packet);
    assert(radio.receiving && radio.resumes==1 && radio.mutations==2);
  }
}
''')


if __name__ == '__main__':
    unittest.main()
