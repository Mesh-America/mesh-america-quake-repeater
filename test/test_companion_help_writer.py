#!/usr/bin/env python3
"""Execute actual help branches; preserve807 UI and bounded partial writes."""
from pathlib import Path
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
FEATURES = ['COMPANION_FEATURE_READER=1', 'COMPANION_FEATURE_TEMP_RADIO=1',
            'COMPANION_FEATURE_OTA_CLI=1', 'COMPANION_FEATURE_NOTIFICATIONS=1',
            'MESH_ENABLE_LOST_REPLY=1', 'MESH_ENABLE_TX_BEACONS=1',
            'MESH_ENABLE_MESHTEXT_CHAT=1', 'MESH_ENABLE_ETHERNET_TUNNEL=1']
PROFILES = {
    'rak_full': ['NRF52_PLATFORM', 'RAK_4631', 'COMPANION_RADIO_FULL', 'EXTRAFS',
                 'DISPLAY_CLASS', 'OLED_AUTO_DETECT=1', 'BLE_PIN_CODE=123456',
                 'OTA_RAK15002_SD_STORE', 'ETHERNET_USE_RAK13800', 'OTA_SD_STORE',
                 'MESH_USB_LOGGING_AVAILABLE=1', 'MESH_USB_CONSOLE_COOPERATIVE=1', *FEATURES],
    'nrf_full': ['NRF52_PLATFORM', 'COMPANION_RADIO_FULL', 'EXTRAFS', 'DISPLAY_CLASS',
                 'OLED_AUTO_DETECT=1', 'BLE_PIN_CODE=123456', 'MESH_USB_LOGGING_AVAILABLE=1',
                 'MESH_USB_CONSOLE_COOPERATIVE=1', *FEATURES],
    'nrf_minimal': ['NRF52_PLATFORM'],
    'esp_full': ['ESP32_PLATFORM', 'ESP32', 'WIFI_SSID', 'COMPANION_RADIO_FULL',
                 'COMPANION_FEATURE_MEMORY_DIAGNOSTICS=1', 'WITH_WEBCONFIG',
                 'MESH_USB_LOGGING_AVAILABLE=1', 'MESH_USB_CONSOLE_COOPERATIVE=1',
                 'MESH_PRIMARY_ESPNOW=1', 'BLE_PIN_CODE=123456', 'PIN_BUZZER',
                 'PIN_VIBRATION', *FEATURES],
}
# Generated from807's original literal groups, including its dynamic TERM-STOP
# suffix. Non-RAK call hashes bind print/println order as well as all text bytes.
GOLDEN = {'rak_full': {'text': '9a68ce5a10905a201c3bddeb19f4819ce03c6dcaff248cff9c140803b70b14a7', 'calls': '56ed09dee7d53881b2c9fcf3f4ec9b6223e1562ce63e110a065e46706702b53b'}, 'nrf_full': {'text': 'b114ac12ae2ea01b7c47609b72f7eafb616c1dbeb7fb796a95b1377465fd9105', 'calls': '4973a7f21887d07b129cce4ae4cc8145f3f35e664bae09be658957210440d52e'}, 'nrf_minimal': {'text': '15fa8f290cd8c75cfde2fd2ac1cb5b5151a6755c68448fb2793dde3f27669033', 'calls': '6063fd1a699f9c0b588252bd8ce5922e0ff31cec6bbd24522789284ab2a37644'}, 'esp_full': {'text': '1e3b6781c81b5603f7092108e5e309543c60cef8ff4d7cb41a891f67396f716f', 'calls': 'b6335df2bd05b9cab44a7933469b76c5b2611c4b81057436a959feaf3bfbaf60'}}

HARNESS = r'''
#include "CompanionHelpWriter.h"
#include <algorithm>
#include <cassert>
#include <cstdio>
#include <cstring>
#include <string>
#include <vector>
#include <utility>
struct Output {
  std::string text, trace;
  std::vector<size_t> writes;
  size_t throttle = 256, credit = size_t(-1);
  bool overreport = false;
  void record(char kind, const char* value, size_t length) {
    trace += kind;
    for (unsigned i=0;i<4;++i) trace += char((length>>(i*8))&255);
    trace.append(value,length);
  }
  size_t print(const char* value) {
    size_t n=strlen(value);text+=value;record('P',value,n);return n;
  }
  size_t println(const char* value) {
    std::string line=std::string(value)+"\r\n";
    text+=line;record('L',line.data(),line.size());return line.size();
  }
  size_t write(const uint8_t* value, size_t length) {
    assert(length<=256);writes.push_back(length);
    if (overreport) return length+1;
    size_t n=std::min(length,std::min(throttle,credit));
    text.append(reinterpret_cast<const char*>(value),n);credit-=n;
    record('W',reinterpret_cast<const char*>(value),n);return n;
  }
} output;
Output& terminalOutput() {return output;}
void actualHelp(bool _terminal_mode) {
@ACTUAL_HELP@
}
int main() {
  actualHelp(true);
#if defined(RAK_4631) && defined(COMPANION_RADIO_FULL)
  assert(!output.writes.empty());
#else
  assert(output.writes.empty());
#endif
  fwrite(output.text.data(),1,output.text.size(),stdout);
  fwrite(output.trace.data(),1,output.trace.size(),stderr);
  std::string text(777,'x');
  Output partial;partial.throttle=7;
  assert(mesh::companion::writeHelpChunks(partial,text.data(),text.size())==text.size());
  assert(partial.text==text && partial.writes.size()<=text.size());
  Output stalled;stalled.credit=13;
  assert(mesh::companion::writeHelpChunks(stalled,text.data(),text.size())==13);
  assert(stalled.text==text.substr(0,13) && stalled.writes.size()==2);
  Output closed;closed.credit=0;
  assert(mesh::companion::writeHelpChunks(closed,text.data(),text.size())==0);
  assert(closed.writes.size()==1 && closed.text.empty());
  Output invalid;invalid.overreport=true;
  assert(mesh::companion::writeHelpChunks(invalid,text.data(),text.size())==0);
  assert(invalid.writes.size()==1 && invalid.text.empty());
  Output empty;
  assert(mesh::companion::writeHelpChunks(empty,nullptr,1)==0);
  assert(mesh::companion::writeHelpChunks(empty,"",0)==0 && empty.writes.empty());
}
'''


class CompanionHelpWriterTests(unittest.TestCase):
    def test_actual_branch_preserves_ui_and_non_rak_call_sequence(self):
        compiler = os.environ.get('CXX') or shutil.which('g++') or shutil.which('clang++')
        if not compiler:
            self.skipTest('host C++17 compiler required')
        source = (ROOT / 'examples/companion_radio/MyMesh.cpp').read_text()
        start = source.index('    auto& output = terminalOutput();',
                             source.index('} else if (strcmp(command, "help") == 0)'))
        end = source.index('  } else if (handleCommand(command, 0, local_reply))', start)
        harness = HARNESS.replace('@ACTUAL_HELP@', source[start:end])
        for name, defines in PROFILES.items():
            with self.subTest(profile=name), tempfile.TemporaryDirectory(prefix='companion-help-') as folder:
                work = Path(folder);(work / 'test.cpp').write_text(harness)
                sanitizer = ['-fsanitize=address,undefined', '-fno-sanitize-recover=all',
                             '-fno-pie', '-no-pie'] if sys.platform.startswith('linux') else []
                result = subprocess.run([compiler, '-std=c++17', '-Wall', '-Wextra', '-Werror',
                    *sanitizer, *['-D'+value for value in defines],
                    '-I'+str(ROOT/'examples/companion_radio'), str(work/'test.cpp'),
                    '-o', str(work/'test')], capture_output=True, text=True)
                self.assertEqual(result.returncode,0,result.stdout+result.stderr)
                result = subprocess.run([str(work/'test')],capture_output=True)
                self.assertEqual(result.returncode,0,result.stderr.decode(errors='replace'))
                self.assertEqual(hashlib.sha256(result.stdout).hexdigest(),GOLDEN[name]['text'])
                if name != 'rak_full':
                    self.assertEqual(hashlib.sha256(result.stderr).hexdigest(),GOLDEN[name]['calls'])


if __name__ == '__main__':
    unittest.main()
