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
void meshBleTraceAdvertising(char* reply, size_t capacity) {
  snprintf(reply,capacity,"> advertising");
}
void meshBleTraceAdvertiser(char* reply, size_t capacity) {
  snprintf(reply,capacity,"> advertiser");
}
void meshBleTraceStack(char* reply, size_t capacity) {
  snprintf(reply,capacity,"> stack");
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
  for (const char* command : {"get bluetooth.trace.advertising", "get ble.trace.advertising"}) {
    assert(meshBleTraceCommand(command,reply,sizeof(reply)));
    assert(!strcmp(reply,"> advertising"));
  }
  assert(!meshBleTraceCommand("get ble.trace.advertising extra",reply,sizeof(reply)));
  assert(meshBleTraceCommand("get bluetooth.trace.advertiser",reply,sizeof(reply)));
  assert(!strcmp(reply,"> advertiser"));
  for (const char* command : {"get bluetooth.trace.advertiser extra",
      "get bluetooth.trace.advertiserx", "get ble.trace.advertiser"}) {
    assert(!meshBleTraceCommand(command,reply,sizeof(reply)));
  }
  assert(meshBleTraceCommand("get bluetooth.trace.stack",reply,sizeof(reply)));
  assert(!strcmp(reply,"> stack"));
  for (const char* command : {"get bluetooth.trace.stack extra",
      "get bluetooth.trace.stackx", "get bluetooth.trace.stack ",
      "get ble.trace.stack"}) {
    assert(!meshBleTraceCommand(command,reply,sizeof(reply)));
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

    def test_real_advertising_query_reads_public_payloads_with_31_byte_bounds(self):
        source = (ROOT / "src/helpers/nrf52/SerialBLEInterface.cpp").read_text()
        start = source.index("void meshBleTraceAdvertising(")
        implementation = source[start:source.index("\n}\n", start) + 3]
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            cpp = work / "advertising.cpp"
            cpp.write_text(r'''
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstring>
static void* instance;
struct BLEAdvertisingData {
  uint8_t length = 0;
  uint8_t bytes[31] = {};
  uint8_t count() { return length; }
  uint8_t* getData() { return bytes; }
};
static struct { BLEAdvertisingData Advertising, ScanResponse; } Bluefruit;
@IMPLEMENTATION@
int main() {
  char reply[172];
  meshBleTraceAdvertising(reply, sizeof(reply));
  assert(!strcmp(reply, "> Bluetooth not initialized"));
  instance = reply;
  const uint8_t advertising[] = {2, 1, 6, 2, 10, 4};
  memcpy(Bluefruit.Advertising.bytes, advertising, sizeof(advertising));
  Bluefruit.Advertising.length = sizeof(advertising);
  // This is the copied advertising payload, independent of the GAP getter.
  const uint8_t scan[] = {5, 9, 'R', 0, 0xc3, 0xa9};
  memcpy(Bluefruit.ScanResponse.bytes, scan, sizeof(scan));
  Bluefruit.ScanResponse.length = sizeof(scan);
  meshBleTraceAdvertising(reply, sizeof(reply));
  assert(!strcmp(reply, "> adv_len=6,adv_hex=020106020a04,scan_len=6,scan_hex=05095200c3a9"));
  for (unsigned i = 0; i < 31; ++i) {
    Bluefruit.Advertising.bytes[i] = i;
    Bluefruit.ScanResponse.bytes[i] = 255 - i;
  }
  Bluefruit.Advertising.length = Bluefruit.ScanResponse.length = 255;
  meshBleTraceAdvertising(reply, sizeof(reply));
  assert(strlen(reply) < sizeof(reply) - 1);
  const char* adv_hex = strstr(reply, "adv_hex=") + 8;
  const char* scan_hex = strstr(reply, "scan_hex=") + 9;
  assert(strchr(adv_hex, ',') - adv_hex == 62 && strlen(scan_hex) == 62);
  assert(!strncmp(reply, "> adv_len=255,", 14));
  assert(strstr(reply, ",scan_len=255,"));
  char tiny[3] = {};
  meshBleTraceAdvertising(tiny, sizeof(tiny));
  assert(tiny[2] == 0);
  char untouched = 'X';
  meshBleTraceAdvertising(&untouched, 0);
  assert(untouched == 'X');
}
'''.replace("@IMPLEMENTATION@", implementation))
            binary = work / "advertising"
            compiled = subprocess.run([
                "c++", "-std=c++17", "-O2", "-flto", "-Wall", "-Wextra", "-Werror",
                "-fsanitize=address,undefined", "-fno-omit-frame-pointer",
                "-fno-pie", "-no-pie", str(cpp), "-o", str(binary),
            ], capture_output=True, text=True)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            result = subprocess.run([str(binary)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_real_advertiser_query_uses_live_sdk_state_and_bounded_handle_enumeration(self):
        source = (ROOT / "src/helpers/nrf52/SerialBLEInterface.cpp").read_text()
        start = source.index("void meshBleTraceAdvertiser(")
        implementation = source[start:source.index("\n}\n", start) + 3]
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            cpp = work / "advertiser.cpp"
            cpp.write_text(r'''
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstring>
static constexpr uint32_t NRF_SUCCESS = 0;
static constexpr uint32_t NRF_ERROR_INVALID_STATE = 8;
static constexpr uint32_t BLE_ERROR_INVALID_ADV_HANDLE = 0x3004;
static constexpr uint8_t BLE_GAP_ADV_SET_HANDLE_NOT_SET = 255;
struct ble_gap_addr_t { uint8_t addr_type; uint8_t addr[6]; };
struct ble_gap_irk_t { uint8_t irk[16]; };
struct ble_gap_privacy_params_t {
  uint8_t privacy_mode;
  uint8_t private_addr_type;
  uint16_t private_addr_cycle_s;
  ble_gap_irk_t* p_device_irk;
};
static void* instance;
static uint8_t enabled;
static uint32_t enabled_result, privacy_result;
static unsigned enabled_calls, advertiser_calls, privacy_calls;
static uint32_t statuses[255];
static unsigned handle_calls[255];
static ble_gap_privacy_params_t privacy_value;
namespace mesh_nrf52 {
static uint32_t softdeviceIsEnabled(uint8_t& value) {
  ++enabled_calls; value = enabled; return enabled_result;
}
}
static struct {
  struct { bool running; bool isRunning() { return running; } } Advertising;
} Bluefruit;
static uint32_t sd_ble_gap_adv_addr_get(uint8_t handle, ble_gap_addr_t* address) {
  // In particular, never probe the sentinel 255 or wrap the handle loop.
  assert(handle < BLE_GAP_ADV_SET_HANDLE_NOT_SET);
  assert(handle_calls[handle]++ == 0);
  ++advertiser_calls;
  // Failed calls may leave arbitrary bytes; only successful output is usable.
  *address = {1, {0xc6, 0xbb, 0xcd, 0x86, 0xa0, 0xd1}};
  return statuses[handle];
}
static uint32_t sd_ble_gap_privacy_get(ble_gap_privacy_params_t* value) {
  ++privacy_calls;
  // NULL suppresses IRK output; this diagnostic must never request key data.
  assert(value->p_device_irk == nullptr);
  // The SDK's failed output must not become reported privacy settings.
  *value = privacy_result == NRF_SUCCESS
      ? privacy_value : ble_gap_privacy_params_t{255, 255, 65535, nullptr};
  return privacy_result;
}
static void reset() {
  instance = &enabled; enabled = 1;
  enabled_result = privacy_result = NRF_SUCCESS;
  enabled_calls = advertiser_calls = privacy_calls = 0;
  Bluefruit.Advertising.running = false;
  privacy_value = {};
  for (unsigned i = 0; i < 255; ++i) {
    statuses[i] = BLE_ERROR_INVALID_ADV_HANDLE; handle_calls[i] = 0;
  }
}
@IMPLEMENTATION@
int main() {
  char reply[172];
  reset(); instance = nullptr;
  meshBleTraceAdvertiser(reply, sizeof(reply));
  assert(!strcmp(reply, "> Bluetooth not initialized"));
  assert(enabled_calls == 0 && advertiser_calls == 0 && privacy_calls == 0);
  reset(); enabled = 0;
  meshBleTraceAdvertiser(reply, sizeof(reply));
  assert(!strcmp(reply, "> Bluetooth not initialized"));
  assert(enabled_calls == 1 && advertiser_calls == 0 && privacy_calls == 0);
  reset(); enabled_result = UINT32_MAX;
  meshBleTraceAdvertiser(reply, sizeof(reply));
  assert(!strcmp(reply, "> Bluetooth not initialized"));
  assert(enabled_calls == 1 && advertiser_calls == 0 && privacy_calls == 0);

  // A nonzero live handle wins even when the framework cache says stopped.
  reset(); statuses[37] = NRF_SUCCESS; privacy_value = {2, 0, 60, nullptr};
  meshBleTraceAdvertiser(reply, sizeof(reply));
  assert(!strcmp(reply, "> cached=0,active=1,idle=0,invalid=254,error=0,h=37,t=1,mac=d1a086cdbbc6,privacy_status=0,privacy=2,cycle=60"));
  assert(advertiser_calls == 255 && privacy_calls == 1);
  for (unsigned i = 0; i < 255; ++i) assert(handle_calls[i] == 1);

  // An existing inactive set must not be mistaken for cached advertising.
  reset(); statuses[37] = NRF_ERROR_INVALID_STATE; Bluefruit.Advertising.running = true;
  meshBleTraceAdvertiser(reply, sizeof(reply));
  assert(!strcmp(reply, "> cached=1,active=0,idle=1,invalid=254,error=0,h=255,t=0,mac=000000000000,privacy_status=0,privacy=0,cycle=0"));
  assert(advertiser_calls == 255 && privacy_calls == 1);

  // Count all valid states and retain the first ACTIVE handle/address.
  reset(); statuses[2] = NRF_ERROR_INVALID_STATE;
  statuses[37] = statuses[254] = NRF_SUCCESS;
  meshBleTraceAdvertiser(reply, sizeof(reply));
  assert(strstr(reply, "active=2,idle=1,invalid=252,error=0,h=37,t=1,mac=d1a086cdbbc6"));
  assert(advertiser_calls == 255 && handle_calls[254] == 1);

  reset(); statuses[9] = 0xdeadbeef;
  meshBleTraceAdvertiser(reply, sizeof(reply));
  assert(strstr(reply, "active=0,idle=0,invalid=9,error=3735928559,h=255,t=0,mac=000000000000"));
  assert(advertiser_calls == 10 && handle_calls[10] == 0 && privacy_calls == 1);
  reset(); statuses[254] = NRF_SUCCESS; privacy_result = UINT32_MAX;
  meshBleTraceAdvertiser(reply, sizeof(reply));
  assert(strstr(reply, "active=1,idle=0,invalid=254,error=0,h=254,t=1,mac=d1a086cdbbc6"));
  assert(strstr(reply, "privacy_status=4294967295,privacy=0,cycle=0"));
  assert(strlen(reply) < sizeof(reply) - 1);

  // snprintf bounds include tiny buffers, zero capacity and a null/zero sink.
  reset(); char guarded[] = {'A', 'x', 'x', 'x', 'x', 'x', 'B'};
  meshBleTraceAdvertiser(guarded + 1, 5);
  assert(guarded[0] == 'A' && guarded[5] == 0 && guarded[6] == 'B');
  reset(); char single = 'X';
  meshBleTraceAdvertiser(&single, 1);
  assert(single == 0);
  reset(); char untouched = 'X';
  meshBleTraceAdvertiser(&untouched, 0);
  assert(untouched == 'X');
  reset(); meshBleTraceAdvertiser(nullptr, 0);
}
'''.replace("@IMPLEMENTATION@", implementation))
            binary = work / "advertiser"
            compiled = subprocess.run([
                "c++", "-std=c++17", "-O2", "-flto", "-Wall", "-Wextra", "-Werror",
                "-fsanitize=address,undefined", "-fno-omit-frame-pointer",
                "-fno-pie", "-no-pie", str(cpp), "-o", str(binary),
            ], capture_output=True, text=True)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            result = subprocess.run([str(binary)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_real_stack_query_reports_live_version_and_sdk_failures_with_bounds(self):
        source = (ROOT / "src/helpers/nrf52/SerialBLEInterface.cpp").read_text()
        start = source.index("void meshBleTraceStack(")
        implementation = source[start:source.index("\n}\n", start) + 3]
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            cpp = work / "stack.cpp"
            cpp.write_text(r'''
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstring>
static constexpr uint32_t NRF_SUCCESS = 0;
struct ble_version_t {
  uint8_t version_number;
  uint16_t company_id;
  uint16_t subversion_number;
};
static void* instance;
static unsigned calls;
static unsigned enabled_calls;
static uint8_t enabled = 1;
static uint32_t enabled_status;
static uint32_t version_status;
static ble_version_t live_version;
namespace mesh_nrf52 {
static uint32_t softdeviceIsEnabled(uint8_t& value) {
  assert(instance);
  ++enabled_calls;
  value = enabled;
  return enabled_status;
}
}
static uint32_t sd_ble_version_get(ble_version_t* version) {
  assert(instance && enabled_status == NRF_SUCCESS && enabled);
  assert(version->version_number == 0 && version->company_id == 0
      && version->subversion_number == 0);
  ++calls;
  // A failed SDK call can overwrite every output field. Its data is unusable.
  *version = live_version;
  return version_status;
}
@IMPLEMENTATION@
int main() {
  char reply[172];
  meshBleTraceStack(reply, sizeof(reply));
  assert(!strcmp(reply, "> Bluetooth not initialized"));
  assert(enabled_calls == 0 && calls == 0);

  instance = reply;
  enabled = 0;
  meshBleTraceStack(reply, sizeof(reply));
  assert(!strcmp(reply, "> Bluetooth not initialized"));
  assert(enabled_calls == 1 && calls == 0);
  enabled = 1;
  enabled_status = UINT32_MAX;
  meshBleTraceStack(reply, sizeof(reply));
  assert(!strcmp(reply, "> Bluetooth not initialized"));
  assert(enabled_calls == 2 && calls == 0);
  enabled_status = NRF_SUCCESS;
  live_version = {9, 89, 0x0123};
  meshBleTraceStack(reply, sizeof(reply));
  assert(!strcmp(reply, "> status=0,link_layer=9,company=89,fwid=0x0123"));
  assert(calls == 1);
  live_version.subversion_number = 0x00b6;
  meshBleTraceStack(reply, sizeof(reply));
  assert(!strcmp(reply, "> status=0,link_layer=9,company=89,fwid=0x00b6"));
  assert(calls == 2);

  live_version = {UINT8_MAX, UINT16_MAX, UINT16_MAX};
  meshBleTraceStack(reply, sizeof(reply));
  assert(!strcmp(reply, "> status=0,link_layer=255,company=65535,fwid=0xffff"));
  version_status = 8;
  meshBleTraceStack(reply, sizeof(reply));
  assert(!strcmp(reply, "> status=8"));
  version_status = UINT32_MAX;
  meshBleTraceStack(reply, sizeof(reply));
  assert(!strcmp(reply, "> status=4294967295"));

  // Exercise every return path with guarded tiny, one-byte and zero sinks.
  for (unsigned mode = 0; mode < 5; ++mode) {
    instance = mode == 0 ? nullptr : reply;
    enabled = mode == 1 ? 0 : 1;
    enabled_status = mode == 2 ? UINT32_MAX : NRF_SUCCESS;
    version_status = mode == 4 ? UINT32_MAX : NRF_SUCCESS;
    char guarded[] = {'A', 'x', 'x', 'x', 'x', 'x', 'B'};
    meshBleTraceStack(guarded + 1, 5);
    assert(guarded[0] == 'A' && guarded[5] == 0 && guarded[6] == 'B');
    char single = 'X';
    meshBleTraceStack(&single, 1);
    assert(single == 0);
    char untouched = 'X';
    meshBleTraceStack(&untouched, 0);
    assert(untouched == 'X');
    meshBleTraceStack(nullptr, 0);
  }
}
'''.replace("@IMPLEMENTATION@", implementation))
            binary = work / "stack"
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
