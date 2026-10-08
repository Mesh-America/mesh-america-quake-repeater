#!/usr/bin/env python3
"""Execute background502/default251 admission bounds on the real CFT."""
from pathlib import Path
import json,os,subprocess,tempfile,unittest
ROOT=Path(os.environ.get("CONTACT_WRITER_ROOT",Path(__file__).resolve().parents[1]))
HEADER=Path(os.environ.get("CONTACT_WRITER_HEADER",ROOT/"src/helpers/ContactFileTransaction.h"))
DATASTORE=Path(os.environ.get("CONTACT_WRITER_DATASTORE",ROOT/"examples/companion_radio/DataStore.cpp"))
FIXTURE=Path(__file__).resolve().parent/"fixtures/contact_writer_batch/test.cpp"
class WriterBatch(unittest.TestCase):
    def run_native(self,mode,negative=None):
        source=HEADER.read_text().replace('#include "IdentityStore.h"','// native supplied FILESYSTEM').replace(
            '#include "PersistentStoreFormat.h"','#include <helpers/PersistentStoreFormat.h>')
        if negative=="default":
            anchor='while (serviceBegin() == BeginProgress::Pending) {}'
            self.assertEqual(source.count(anchor),1)
            source=source.replace(anchor,'while (serviceBegin(true) == BeginProgress::Pending) {}')
        if negative=="large":
            anchor='ESP_BACKGROUND_WRITE_BUFFER_SIZE = 502;'
            self.assertEqual(source.count(anchor),1);source=source.replace(anchor,'ESP_BACKGROUND_WRITE_BUFFER_SIZE = 4096;')
        # Reuse the existing immediate-full-newlib stdio model unchanged.
        with tempfile.TemporaryDirectory(prefix='mesh-writer-batch-') as directory:
            tmp=Path(directory);(tmp/'transaction_under_test.h').write_text(source)
            binary=tmp/'fixture'
            cmd=['c++','-std=c++17','-O1','-g','-Wall','-Wextra','-fsanitize=address,undefined',
                 '-fno-omit-frame-pointer','-DESP32_PLATFORM=1','-I',str(tmp),'-I',str(ROOT/'src'),
                 '-I',str(ROOT/'test/fixtures/contact_cache'),'-I',str(ROOT/'test/fixtures/contact_cache/mocks'),
                 str(FIXTURE),'-o',str(binary)]
            compiled=subprocess.run(cmd,text=True,capture_output=True)
            self.assertEqual(compiled.returncode,0,compiled.stderr)
            result=subprocess.run([str(binary),mode],text=True,capture_output=True)
            if negative:
                self.assertNotEqual(result.returncode,0,result.stdout)
                self.assertIn('largest_backend_write <= cap',result.stderr)
                return
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            return [json.loads(line) for line in result.stdout.splitlines()]
    def test_counts_admissions_and_exact_committed_bytes(self):
        rows=self.run_native('measure');self.assertEqual(len(rows),6)
        for row in rows:
            n=row['records'];cap=502 if row['background'] else 251
            self.assertEqual(row['logical_writes'],n)
            self.assertEqual(row['bytes'],n*152)
            self.assertEqual(row['backend_writes'],(n*152+cap-1)//cap)
            self.assertEqual(row['largest_backend_write'],cap)
        self.assertEqual([(r['backend_writes']) for r in rows],[211,106,212,106,212,106])
    def test_synchronous_constructor_keeps_default251(self):self.run_native('default')
    def test_configure_time_selection_is_latched(self):self.run_native('configure')
    def test_cancellation_tail_and_old_target(self):self.run_native('cancel')
    def test_fail_closed_config_short_write_corruption_and_crash(self):self.run_native('faults')
    def test_old_default_contract_regression_is_detected(self):self.run_native('default','default')
    def test_4096_burst_is_detected(self):self.run_native('measure','large')
if __name__=='__main__':unittest.main()
