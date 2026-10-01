#!/usr/bin/env python3
"""Check the debug reader's bounds and its disabled production behavior."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]

class BleTraceTest(unittest.TestCase):
    def test_debug_records_are_bounded_and_disabled_calls_have_no_effect(self):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            (work / 'Arduino.h').write_text(
                '#include <stdint.h>\n#include <stddef.h>\n'
                'inline uint32_t millis() { return 1234; }\ninline uint32_t micros() { return 4567; }\n')
            source = work / 'trace.cpp'
            source.write_text(r'''
#include <cassert>
#include <cstring>
#include <helpers/nrf52/BleDebugTrace.h>
#if MESH_NRF52_BLE_TRACE
extern "C" { MeshBleTraceBuffer mesh_ble_trace; }
void meshBleTraceState(char* reply, size_t capacity) {
  snprintf(reply,capacity,"> state");
}
int main() {
  char reply[160];
  assert(!meshBleTraceCommand("get radio",reply,sizeof(reply)));
  meshBleTrace(0xf002,0,0x16);
  assert(meshBleTraceCommand("get bluetooth.trace 1",reply,sizeof(reply)));
  assert(!strcmp(reply,"> 1,1234,0xf002,0,22,0"));
  for(const char* command:{"get bluetooth.trace 0", "get bluetooth.trace -1",
      "get bluetooth.trace 1 extra", "get bluetooth.trace 4294967296"}) {
    assert(meshBleTraceCommand(command,reply,sizeof(reply)));
    assert(!strncmp(reply,"Error:",6));
  }
  for(int i=0;i<256;++i)meshBleTrace(0x10);
  assert(meshBleTraceCommand("get bluetooth.trace 1",reply,sizeof(reply)));
  assert(!strcmp(reply,"Error: trace record unavailable"));
  assert(meshBleTraceCommand("get bluetooth.trace 257",reply,sizeof(reply)));
  assert(!strcmp(reply,"> 257,1234,0x0010,65535,0,0"));
  assert(meshBleTraceCommand("get bluetooth.trace.state",reply,sizeof(reply)));
  assert(!strcmp(reply,"> state"));
  meshBleTraceDispatchEnter(0x10,0);
  assert(mesh_ble_trace.dispatch_event.load()==0x10);
  meshBleTraceDispatchExit(0x10,0);
  assert(mesh_ble_trace.dispatch_event.load()==0);
  mesh_ble_trace.writer.test_and_set();
  meshBleTrace(0x10);
  mesh_ble_trace.writer.clear();
  assert(mesh_ble_trace.dropped.load()==1);
  assert(mesh_ble_trace.next.load()==259);
  assert(meshBleTraceCommand("get bluetooth.trace.timing",reply,sizeof(reply)));
  assert(strstr(reply,"dispatch_event=0"));
  char tiny[5] = {};
  assert(meshBleTraceCommand("get bluetooth.trace",tiny,sizeof(tiny)));
  assert(tiny[4]==0);
}
#else
int main() {
  int side_effect = 0;
  meshBleTrace(++side_effect);
  meshBleTraceMax(++side_effect,++side_effect);
  meshBleTraceDispatchEnter(++side_effect,++side_effect);
  meshBleTraceDispatchExit(++side_effect,++side_effect);
  assert(side_effect==0);
}
#endif
''')
            for enabled in (0, 1):
                binary = work / f'trace-{enabled}'
                subprocess.run(['c++','-std=c++17','-include','initializer_list',
                    f'-DMESH_NRF52_BLE_TRACE={enabled}', '-I'+str(work),
                    '-I'+str(ROOT/'src'), str(source), '-o', str(binary)],
                    check=True, capture_output=True)
                subprocess.run([str(binary)],check=True,capture_output=True)

    def test_concurrent_reader_never_accepts_mixed_records(self):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            (work / 'Arduino.h').write_text(
                '#include <stdint.h>\n#include <stddef.h>\n'
                'inline uint32_t millis(){return 1234;}\n'
                'inline uint32_t micros(){return 4567;}\n')
            source = work / 'race.cpp'
            source.write_text(r'''
#include <cassert>
#include <thread>
#include <helpers/nrf52/BleDebugTrace.h>
extern "C" { MeshBleTraceBuffer mesh_ble_trace; }
void meshBleTraceState(char*,size_t) {}
int main() {
  std::atomic<bool> done{false};
  std::thread writer([&]{
    for(uint32_t i=1;i<100000;++i)meshBleTrace(i,i^0x12345678,i*3,i*7);
    done.store(true);
  });
  do {
    uint32_t next=mesh_ble_trace.next.load();
    MeshBleTraceRecord r;
    for(uint32_t i=(next>256?next-255:1);i<=next;++i) {
      if(meshBleTraceRead(i,r)) {
        assert(r.handle==(r.event^0x12345678));
        assert(r.detail==r.event*3 && r.extra==r.event*7);
      }
    }
  } while(!done.load());
  writer.join();
}
''')
            binary = work / 'race'
            subprocess.run(['c++','-std=c++17','-O2','-pthread',
                '-DMESH_NRF52_BLE_TRACE=1', '-I'+str(work),
                '-I'+str(ROOT/'src'), str(source), '-o', str(binary)],
                check=True,capture_output=True)
            subprocess.run([str(binary)],check=True,capture_output=True)

if __name__ == '__main__':
    unittest.main()
