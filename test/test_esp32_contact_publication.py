#!/usr/bin/env python3
from pathlib import Path
import json,subprocess,tempfile,unittest
ROOT=Path(__file__).resolve().parents[1]
FIXTURE=ROOT/"test/fixtures/contact_publication/test.cpp"
class Publication(unittest.TestCase):
 def run_native(self,mode,platform='ESP32_PLATFORM',negative=None):
  source=(ROOT/'src/helpers/ContactFileTransaction.h').read_text().replace('#include "IdentityStore.h"','// native supplied File').replace('#include "PersistentStoreFormat.h"','#include <helpers/PersistentStoreFormat.h>')
  if negative=='cleanup':
   a='if (!defer_backup_cleanup)';self.assertEqual(source.count(a),1);source=source.replace(a,'if (true)')
  elif negative=='retirement':
   a='ok = _fs->remove(_backup);';self.assertEqual(source.count(a),2);source=source.replace(a,'ok = true; // negative: leave previous backup',1)
  with tempfile.TemporaryDirectory(prefix='mesh-publication-') as folder:
   p=Path(folder);(p/'transaction_under_test.h').write_text(source);binary=p/'test'
   result=subprocess.run(['c++','-std=c++17','-O1','-g','-Wall','-Wextra','-fsanitize=address,undefined','-fno-omit-frame-pointer','-D'+platform+'=1','-I',str(p),'-I',str(ROOT/'src'),'-I',str(ROOT/'test/fixtures/contact_cache'),'-I',str(ROOT/'test/fixtures/contact_cache/mocks'),str(FIXTURE),'-o',str(binary)],text=True,capture_output=True)
   self.assertEqual(result.returncode,0,result.stderr)
   result=subprocess.run([str(binary),mode],text=True,capture_output=True)
   if negative:
    self.assertNotEqual(result.returncode,0,result.stdout)
    self.assertIn('SPIFFS.',result.stderr)
   else:self.assertEqual(result.returncode,0,result.stdout+result.stderr)
 def test_default_and_deferred_success_contracts(self):self.run_native('contracts')
 def test_retirement_and_recovery_failure_before_temp_ownership(self):self.run_native('retire')
 def test_repeated_transaction_all_begin_cancellation_boundaries(self):self.run_native('cancel')
 def test_publish_failures_and_every_rename_crash(self):self.run_native('faults')
 def test_251_502_counts_and_unchanged_commit_cadence(self):self.run_native('counts')
 def test_other_platform_retains_cleanup_despite_true_arg(self):self.run_native('contracts','RP2040_PLATFORM')
 def test_removed_defer_guard_is_detected(self):self.run_native('contracts',negative='cleanup')
 def test_omitted_retirement_is_detected(self):self.run_native('retire',negative='retirement')
if __name__=='__main__':unittest.main()
