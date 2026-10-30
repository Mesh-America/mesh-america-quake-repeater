"""Execute failed transaction recovery without erasing fork feature ownership."""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest
from cpp_source import body
from test_radio_profile_scan import HARNESS, ROOT


class ProfileRepairTests(unittest.TestCase):
    def test_failed_apply_rollback_standby_and_trusted_refresh(self):
        source = (ROOT / 'src/helpers/radiolib/RadioLibWrappers.cpp').read_text()
        methods = '\n'.join(body(source, signature) for signature in (
            'uint8_t RadioLibWrapper::beginReconfigure(',
            'void RadioLibWrapper::endReconfigure(',
            'mesh::RadioParamApplyResult RadioLibWrapper::tuneProfile(',
            'mesh::RadioParamApplyResult RadioLibWrapper::trySetParams('))
        harness = HARNESS[:HARNESS.index('int main() {')]
        harness = harness.replace('bool standbyXOSC=false; int standby() { return 0; }',
            'bool standbyXOSC=false; int result=0; int standby() { return result; }')
        harness = harness.replace('  bool _cw_active=false;',
            '  bool _cw_active=false, _beacon_owned=false, _beacon_restoring=false, fail_all=false;')
        harness = harness.replace('return !fail || f==909.5f;', 'return !fail_all && (!fail || f==909.5f);')
        harness = harness.replace('bool restoreAfterDeepInit() { return true; }',
                                  'bool restoreAfterDeepInit() { return false; }')
        harness = harness.replace('  void startRecv() {',
                                  '  void startRecv() { if (_profile_repair_required) return;')
        harness += r'''
int main() {
 using Result=mesh::RadioParamApplyResult;
 RadioLibWrapper w; w._rx_ps_armed=w._rx_ps_enabled=false;
 auto second=w._profiles.primary;second.freq=910.5;
 w._profiles.secondary.params=second;w._profiles.secondary.mode=mesh::RadioProfileMode::RxTx;
 w.fail_all=true;
 assert(w.tuneProfile(1)==Result::FAILED && w._profile_repair_required);
 assert(w._active_profile==0 && w._profile_refresh_required);
 w.fail_all=false;w.packet=true;w.events.record();
 assert(w.tuneProfile(0)==Result::APPLIED); // Untrusted stale activity cannot block repair.
 assert(!w._profile_repair_required && w.state==STATE_RX && !w.hasPendingRadioInterrupt());
 w._profile_refresh_required=true;w.events.record();
 const auto applies=w.applies;
 assert(w.tuneProfile(0)==Result::BUSY && w.applies==applies && w.hasPendingRadioInterrupt());
 w.events.claim();w.packet=false;w._profile_repair_required=true;
 w._beacon_owned=true;assert(w.beginReconfigure()==2);w._beacon_owned=false;
 w._cw_active=true;assert(w.beginReconfigure()==2);w._cw_active=false;
 w.state=STATE_TX_WAIT;assert(w.beginReconfigure()==2);w.state=STATE_IDLE;
 w.busy=true;assert(w.beginReconfigure()==2);w.busy=false;
 w.chip.result=-7;assert(w.tuneProfile(0)==Result::FAILED && w._profile_repair_required);
 w.chip.result=0;assert(w.tuneProfile(0)==Result::APPLIED && w.state==STATE_RX);
 w.fail_all=true;
 assert(w.trySetParams(911.5,125,8,5)==Result::FAILED && w._profile_repair_required);
 w.fail_all=false;assert(w.tuneProfile(0)==Result::APPLIED && !w._profile_repair_required);
}
'''
        harness = harness.replace('@METHODS@', methods)
        with tempfile.TemporaryDirectory(prefix='profile-repair-') as folder:
            cpp, exe = Path(folder)/'test.cpp', Path(folder)/'test.exe'
            (Path(folder)/'Arduino.h').write_text('#pragma once\n#include <cstdint>\n#include <cmath>\n')
            cpp.write_text(harness)
            flags=[] if os.name=='nt' else ['-fsanitize=address,undefined','-fno-pie','-no-pie']
            built=subprocess.run([os.environ.get('CXX','g++'),'-std=c++17',*flags,
                '-DMESH_ENABLE_TX_BEACONS=1','-I',folder,'-I',str(ROOT/'src'),str(cpp),'-o',str(exe)],
                capture_output=True,text=True,timeout=60)
            self.assertEqual(built.returncode,0,built.stderr)
            ran=subprocess.run([str(exe)],capture_output=True,text=True,timeout=10)
            self.assertEqual(ran.returncode,0,ran.stderr)


if __name__=='__main__': unittest.main()
