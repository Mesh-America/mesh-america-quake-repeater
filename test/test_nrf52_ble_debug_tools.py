"""Exercise diagnostic dispatch bracketing and the exported event decoder."""
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = spec_from_file_location(name, ROOT / path)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


patcher = load("ble_patcher", "scripts/nrf52_ble_cccd_fix.py")
capture = load("ble_capture", "scripts/capture_nrf52_ble_debug.py")


class BleDebugToolsTest(unittest.TestCase):
    def test_dispatch_brackets_real_callback_and_measures_duration(self):
        source = '''#include "bluefruit.h"
void AdafruitBluefruit::_ble_handler(ble_evt_t* evt)
{
  if (_event_cb) _event_cb(evt);
}
'''
        patched = patcher.patched_trace_source(source)
        self.assertEqual(patcher.patched_trace_source(patched), patched)
        with self.assertRaises(RuntimeError):
            patcher.patched_trace_source("changed SDK dispatcher")
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            (work / "Arduino.h").write_text(
                "#include <stdint.h>\n#include <stddef.h>\n"
                "extern uint32_t fake_us;\n"
                "inline uint32_t millis(){return 1234;}\n"
                "inline uint32_t micros(){return fake_us;}\n")
            (work / "bluefruit.h").write_text('''
#pragma once
#include <stdint.h>
struct ble_evt_t {
  struct {uint16_t evt_id;} header;
  struct {struct {uint16_t conn_handle;} common_evt;} evt;
};
class AdafruitBluefruit {
public:
  void (*_event_cb)(ble_evt_t*) = nullptr;
  void _ble_handler(ble_evt_t*);
};
''')
            (work / "dispatch.cpp").write_text(patched + '''
#include <cassert>
#include <helpers/nrf52/BleDebugTrace.h>
uint32_t fake_us = 100;
#if MESH_NRF52_BLE_TRACE
extern "C" { MeshBleTraceBuffer mesh_ble_trace; }
void meshBleTraceState(char*,size_t) {}
#endif
bool callback_ran = false;
void callback(ble_evt_t* evt) {
  callback_ran = true;
#if MESH_NRF52_BLE_TRACE
  assert(mesh_ble_trace.dispatch_event.load() == evt->header.evt_id);
  meshBleTrace(0xf003, evt->evt.common_evt.conn_handle);
#endif
  fake_us += 50;
}
int main() {
  AdafruitBluefruit bluefruit;
  bluefruit._event_cb = callback;
  ble_evt_t evt = {{0x10},{{7}}};
  bluefruit._ble_handler(&evt);
  assert(callback_ran);
#if MESH_NRF52_BLE_TRACE
  MeshBleTraceRecord r;
  assert(meshBleTraceRead(1,r) && r.event == 0xe010);
  assert(meshBleTraceRead(2,r) && r.event == 0xf003);
  assert(meshBleTraceRead(3,r) && r.event == 0xe110 && r.detail == 50);
  assert(mesh_ble_trace.dispatch_event.load() == 0);
  assert(mesh_ble_trace.max_dispatch_us.load() == 50);
#endif
}
''')
            for enabled in (0, 1):
                binary = work / ("dispatch-" + str(enabled))
                subprocess.run(["c++", "-std=c++17",
                    "-DMESH_NRF52_BLE_TRACE=" + str(enabled), "-I" + str(work),
                    "-I" + str(ROOT / "src"), str(work / "dispatch.cpp"),
                    "-o", str(binary)], check=True, capture_output=True)
                subprocess.run([str(binary)], check=True, capture_output=True)

    def test_reasons_security_subscription_and_timing_decode(self):
        local = capture.decode_record(1, 10, 0xF002, 0, 22, 0)
        self.assertEqual(local["reason"], "local_host_terminated")
        timeout = capture.decode_record(2, 20, 0x11, 0, 8, 0)
        self.assertEqual(timeout["reason"], "connection_timeout")
        connected = capture.decode_record(3, 30, 0x10, 0, 12 | (24 << 16), 4 | (200 << 16))
        self.assertEqual(connected["supervision_timeout_ms"], 2000)
        self.assertEqual(connected["min_interval_ms"], 15)
        secure = capture.decode_record(4, 40, 0x19, 0, 0, 0x302)
        self.assertTrue(secure["bonded"] and secure["secure_connections"])
        self.assertEqual(secure["error_source"], 2)
        cccd = capture.decode_record(5, 50, 0x50, 0, 7 | (2 << 16), 1 | 0x100 | (1 << 16))
        self.assertTrue(cccd["is_subscription"])
        self.assertEqual(cccd["subscription_bits"], 1)
        self.assertNotIn("payload", cccd)
        self.assertEqual(capture.values("> next=9,capacity=256,dropped=0,format=2")["format"], 2)

    def test_terminal_ignores_delayed_banner_before_command_echo(self):
        class Port:
            in_waiting = 0
            def __init__(self):
                self.chunks = iter([b"\r\nWELCOME private-banner\r\n> ",
                                    b"ver\r\nCompanion debug\r\n> "])
            def read(self, _):
                return next(self.chunks)
        reply = capture.Terminal(Port()).read_prompt(expected="ver")
        self.assertNotIn("private-banner", reply)
        self.assertIn("Companion debug", reply)


if __name__ == "__main__":
    unittest.main()
