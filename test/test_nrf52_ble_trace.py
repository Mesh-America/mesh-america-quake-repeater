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
void meshBleTraceIdentity(char* reply, size_t capacity) {
  snprintf(reply,capacity,"> identity");
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
  for (const char* command : {"get bluetooth.trace.identity", "get ble.trace.identity"}) {
    assert(meshBleTraceCommand(command,reply,sizeof(reply)));
    assert(!strcmp(reply,"> identity"));
  }
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

    def test_real_identity_query_bounds_sdk_outputs_and_reports_failures(self):
        source = (ROOT / "src/helpers/nrf52/SerialBLEInterface.cpp").read_text()
        start = source.index("void meshBleTraceIdentity(")
        implementation = source[start:source.index("\n}\n", start) + 3]
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            cpp = work / "identity.cpp"
            cpp.write_text(r'''
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstring>
static constexpr uint32_t NRF_SUCCESS = 0;
struct ble_gap_addr_t { uint8_t addr_type; uint8_t addr[6]; };
static bool initialized;
static void* instance;
static unsigned calls;
static uint32_t address_result, name_result;
static uint16_t actual_length;
struct Data { uint8_t count() { return 255; } };
static struct { Data Advertising, ScanResponse; } Bluefruit;
static uint32_t sd_ble_gap_addr_get(ble_gap_addr_t* address) {
  assert(initialized); ++calls;
  *address = {1, {0xc6, 0xbb, 0xcd, 0x86, 0xa0, 0xd1}};
  return address_result;
}
static uint32_t sd_ble_gap_device_name_get(uint8_t* name, uint16_t* length) {
  assert(initialized && *length == 32); ++calls;
  const uint8_t bytes[] = {0x41, 0x00, 0xc3, 0xa9};
  const size_t copied = actual_length < *length ? actual_length : *length;
  for (size_t i = 0; i < copied; ++i) name[i] = bytes[i % sizeof(bytes)];
  *length = actual_length;
  return name_result;
}
@IMPLEMENTATION@
int main() {
  char reply[172];
  meshBleTraceIdentity(reply, sizeof(reply));
  assert(!strcmp(reply, "> Bluetooth not initialized") && calls == 0);
  initialized = true; instance = &initialized; actual_length = 4;
  meshBleTraceIdentity(reply, sizeof(reply));
  assert(!strcmp(reply, "> a=0,t=1,mac=d1a086cdbbc6,n=0,len=4,hex=4100c3a9,adv=255,scan=255"));
  actual_length = 65535;
  meshBleTraceIdentity(reply, sizeof(reply));
  assert(strstr(reply, ",len=65535,hex="));
  assert(strstr(reply, ",adv=255,scan=255"));
  assert(strlen(reply) < sizeof(reply) - 1);
  const char* begin = strstr(reply, "hex=") + 4;
  assert(strchr(begin, ',') - begin == 64);
  address_result = name_result = UINT32_MAX;
  meshBleTraceIdentity(reply, sizeof(reply));
  assert(!strcmp(reply, "> a=4294967295,t=255,mac=,n=4294967295,len=65535,hex=,adv=255,scan=255"));
  char tiny[5] = {};
  meshBleTraceIdentity(tiny, sizeof(tiny));
  assert(tiny[4] == 0);
}
'''.replace("@IMPLEMENTATION@", implementation))
            binary = work / "identity"
            compiled = subprocess.run([
                "c++", "-std=c++17", "-O2", "-flto", "-Wall", "-Wextra", "-Werror",
                "-fsanitize=address,undefined", "-fno-omit-frame-pointer",
                "-fno-pie", "-no-pie", str(cpp), "-o", str(binary),
            ], capture_output=True, text=True)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            result = subprocess.run([str(binary)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

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
