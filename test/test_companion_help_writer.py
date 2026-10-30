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
from cpp_source import body

ROOT = Path(__file__).resolve().parents[1]
FEATURES = ['COMPANION_FEATURE_READER=1', 'COMPANION_FEATURE_TEMP_RADIO=1',
            'COMPANION_FEATURE_OTA_CLI=1', 'COMPANION_FEATURE_NOTIFICATIONS=1',
            'MESH_ENABLE_LOST_REPLY=1', 'MESH_ENABLE_TX_BEACONS=1',
            'MESH_ENABLE_MESHTEXT_CHAT=1', 'MESH_ENABLE_ETHERNET_TUNNEL=1']
PACKED_PROFILES = {'rak_full', 'stm32_wl_usb'}
PROFILES = {
    'rak_full': ['NRF52_PLATFORM', 'RAK_4631', 'COMPANION_RADIO_FULL', 'EXTRAFS',
                 'DISPLAY_CLASS', 'OLED_AUTO_DETECT=1', 'BLE_PIN_CODE=123456',
                 'OTA_RAK15002_SD_STORE', 'ETHERNET_USE_RAK13800', 'OTA_SD_STORE',
                 'MESH_USB_LOGGING_AVAILABLE=1', 'MESH_USB_CONSOLE_COOPERATIVE=1', *FEATURES],
    'nrf_full': ['NRF52_PLATFORM', 'COMPANION_RADIO_FULL', 'EXTRAFS', 'DISPLAY_CLASS',
                 'OLED_AUTO_DETECT=1', 'BLE_PIN_CODE=123456', 'MESH_USB_LOGGING_AVAILABLE=1',
                 'MESH_USB_CONSOLE_COOPERATIVE=1', *FEATURES],
    'nrf_minimal': ['NRF52_PLATFORM'],
    'stm32_wl_usb': ['STM32_PLATFORM', 'STM32WLxx', 'ENABLE_USB_INTERFACE',
                     'COMPANION_FEATURE_TEXT_TERMINAL=1', 'MESH_RADIO_SWITCH_TUNING=0'],
    'esp_full': ['ESP32_PLATFORM', 'ESP32', 'WIFI_SSID', 'COMPANION_RADIO_FULL',
                 'COMPANION_FEATURE_MEMORY_DIAGNOSTICS=1', 'WITH_WEBCONFIG',
                 'MESH_USB_LOGGING_AVAILABLE=1', 'MESH_USB_CONSOLE_COOPERATIVE=1',
                 'MESH_PRIMARY_ESPNOW=1', 'BLE_PIN_CODE=123456', 'PIN_BUZZER',
                 'PIN_VIBRATION', *FEATURES],
}
# Generated from807's original literal groups, including its dynamic TERM-STOP
# suffix. Non-RAK call hashes bind print/println order as well as all text bytes.
GOLDEN = {'rak_full': {'text': '9a68ce5a10905a201c3bddeb19f4819ce03c6dcaff248cff9c140803b70b14a7', 'calls': '56ed09dee7d53881b2c9fcf3f4ec9b6223e1562ce63e110a065e46706702b53b'}, 'nrf_full': {'text': 'b114ac12ae2ea01b7c47609b72f7eafb616c1dbeb7fb796a95b1377465fd9105', 'calls': '4973a7f21887d07b129cce4ae4cc8145f3f35e664bae09be658957210440d52e'}, 'nrf_minimal': {'text': '15fa8f290cd8c75cfde2fd2ac1cb5b5151a6755c68448fb2793dde3f27669033', 'calls': '6063fd1a699f9c0b588252bd8ce5922e0ff31cec6bbd24522789284ab2a37644'}, 'esp_full': {'text': '1e3b6781c81b5603f7092108e5e309543c60cef8ff4d7cb41a891f67396f716f', 'calls': 'b6335df2bd05b9cab44a7933469b76c5b2611c4b81057436a959feaf3bfbaf60'}}

GOLDEN['stm32_wl_usb'] = {'text': '9e587ac9f287c8f8fe64fe5c899fe635b6de5d6cf436c4c43a27ffd4add42474'}

FAST_HELP = (b'  get radio.fast / get radio.fast.caps (supported saved controls)\r\n'
             b'  set radio.fast <on|off> / set radio.fast.spi <0|2|4|8|9|16>\r\n')

HARNESS = r'''
#include "CompanionHelpWriter.h"
#include <algorithm>
#include <cassert>
#include <cstdio>
#include <cstring>
#include <string>
#include <vector>
#include <utility>
class Stream {
public:
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
};
using Output=Stream;
Output output;
Output& terminalOutput() {return output;}
@PACKED_IMPLEMENTATION@
void actualHelp(bool _terminal_mode) {
@ACTUAL_HELP@
}
int main() {
  actualHelp(true);
#if defined(RAK_4631) && defined(COMPANION_RADIO_FULL) \
    || (defined(STM32_PLATFORM) && defined(STM32WLxx) && COMPANION_FEATURE_TEXT_TERMINAL)
  assert(!output.writes.empty());
#else
  assert(output.writes.empty());
#endif
  fwrite(output.text.data(),1,output.text.size(),stdout);
  fwrite(output.trace.data(),1,output.trace.size(),stderr);
  const std::string usb_text=output.text;
  const std::string usb_suffix="  +++MESHCORE-TERM-STOP\r\n";
  assert(usb_text.substr(usb_text.size()-usb_suffix.size())==usb_suffix);
  output=Output{};
  actualHelp(false);
  assert(output.text==usb_text.substr(0,usb_text.size()-usb_suffix.size())
      +"  disconnect (network terminal)\r\n");
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

  constexpr char literal[] =
      "  get/set radio.preamble on|off\r\n"
      "  get bluetooth.name / get pwrmgt.source\r\n"
      "  set radio.cad on (saved; default on)\r\n";
  static_assert(mesh::companion::validHelpText(literal), "ASCII accepted");
  static_assert(!mesh::companion::validHelpText("bad\x80"), "Token bytes reserved");
  static_assert(!mesh::companion::validHelpText("a\0b"), "Embedded NUL rejected");
  static constexpr auto packed = mesh::companion::packHelp<
      mesh::companion::packedHelpSize(literal)>(literal);
  static_assert(sizeof(packed) == mesh::companion::packedHelpSize(literal),
                "No raw-size padding retained");
  static_assert(sizeof(packed) < sizeof(literal), "Repeated fragments compress");
  Output decoded;
  assert(mesh::companion::writePackedHelp(decoded,packed.bytes,sizeof(packed))==sizeof(literal)-1);
  assert(decoded.text==literal);
  Output slow;slow.throttle=3;
  assert(mesh::companion::writePackedHelp(slow,packed.bytes,sizeof(packed))==sizeof(literal)-1);
  assert(slow.text==literal && slow.writes.size()<=sizeof(literal)-1);
  for (size_t credit : {size_t(0),size_t(1),size_t(13),size_t(63),size_t(64),size_t(65)}) {
    Output blocked;blocked.credit=credit;
    assert(mesh::companion::writePackedHelp(blocked,packed.bytes,sizeof(packed))==credit);
    assert(blocked.text==std::string(literal,credit));
    assert(blocked.writes.size()<=credit+1);
  }
  Output bad;bad.overreport=true;
  assert(mesh::companion::writePackedHelp(bad,packed.bytes,sizeof(packed))==0);
  assert(bad.writes.size()==1 && bad.text.empty());
  Output unused;
  assert(mesh::companion::writePackedHelp(unused,nullptr,1)==0);
  assert(mesh::companion::writePackedHelp(unused,packed.bytes,0)==0 && unused.writes.empty());
  const uint8_t invalid_token[]={0xff};
  assert(mesh::companion::writePackedHelp(unused,invalid_token,1)==0 && unused.writes.empty());

  // A match may overlap itself: one literal followed by distance-one runs.
  constexpr char overlap[]="aaaaaaaaaaaaaaaaaaaaaaa";
  static constexpr auto overlap_packed=mesh::companion::packHelp<
      mesh::companion::packedHelpSize(overlap)>(overlap);
  static_assert(sizeof(overlap_packed)==5 && overlap_packed.bytes[0]=='a' &&
      overlap_packed.bytes[1]==0xf8 && overlap_packed.bytes[2]==0 &&
      overlap_packed.bytes[3]==0x88 && overlap_packed.bytes[4]==0,
      "Greedy longest match and overlapping references");
  Output repeated;
  assert(mesh::companion::writePackedHelp(repeated,overlap_packed.bytes,
      sizeof(overlap_packed))==sizeof(overlap)-1 && repeated.text==overlap);

  // Exercise the selected distance limit and ring wrap on both families,
  // independent of the encoder's choice of nearer repeated phrases.
  constexpr size_t window=mesh::companion::help_packing::WindowSize;
  std::vector<uint8_t> boundary;
  for(size_t i=0;i<window;++i) boundary.push_back('!'+(i%90));
  std::string expected(boundary.begin(),boundary.end());
  boundary.push_back(0xf8 | ((window-1)>>8));boundary.push_back((window-1)&255);
  expected+=expected.substr(0,18);
  boundary.push_back(0xf8);boundary.push_back(0); // length18, distance1
  expected+=std::string(18,expected.back());
  Output wrapped;wrapped.throttle=5;
  assert(mesh::companion::writePackedHelp(wrapped,boundary.data(),boundary.size())==expected.size());
  assert(wrapped.text==expected);
  if (window<2048) {
    std::vector<uint8_t> too_far(window+64,'q');
    too_far.push_back(0x80 | (window>>8));too_far.push_back(window&255);
    Output rejected;
    assert(mesh::companion::writePackedHelp(rejected,too_far.data(),too_far.size())==window+64);
    assert(rejected.text==std::string(window+64,'q'));
  }
  for(const auto& corrupt : std::vector<std::vector<uint8_t>>{
      {0x80}, {0x80,0}, {0xff,0xff}, {'x',0x80,1}}) {
    Output rejected;
    assert(mesh::companion::writePackedHelp(rejected,corrupt.data(),corrupt.size())==0);
    assert(rejected.text.empty() && rejected.writes.empty());
  }
  std::vector<uint8_t> late_bad(64,'q');late_bad.push_back(0x80);
  Output prefix;
  assert(mesh::companion::writePackedHelp(prefix,late_bad.data(),late_bad.size())==64);
  assert(prefix.text==std::string(64,'q') && prefix.writes.size()==1);
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
        implementation = body((ROOT / 'examples/companion_radio/CompanionHelpPacked.cpp').read_text(), 'size_t writePackedCompanionHelp(Stream& output)')
        implementation = '#if defined(RAK_4631) && defined(COMPANION_RADIO_FULL) || (defined(STM32_PLATFORM) && defined(STM32WLxx) && COMPANION_FEATURE_TEXT_TERMINAL)\nnamespace mesh { namespace companion {\n' + implementation + '\n} }\n#endif\n'
        harness = HARNESS.replace('@ACTUAL_HELP@', source[start:end]).replace('@PACKED_IMPLEMENTATION@', implementation)
        for name, defines in PROFILES.items():
            with self.subTest(profile=name), tempfile.TemporaryDirectory(prefix='companion-help-') as folder:
                work = Path(folder);(work / 'test.cpp').write_text(harness)
                sanitizer = ['-fsanitize=address,undefined', '-fno-sanitize-recover=all',
                             '-fno-pie', '-no-pie'] if sys.platform.startswith('linux') else []
                result = subprocess.run([compiler, '-std=c++17', '-Os', '-Wall', '-Wextra', '-Werror',
                    *sanitizer, *['-D'+value for value in defines],
                    '-I'+str(ROOT/'examples/companion_radio'), str(work/'test.cpp'),
                    '-o', str(work/'test')], capture_output=True, text=True)
                self.assertEqual(result.returncode,0,result.stdout+result.stderr)
                result = subprocess.run([str(work/'test')],capture_output=True)
                self.assertEqual(result.returncode,0,result.stderr.decode(errors='replace'))
                self.assertEqual(result.stdout.count(FAST_HELP), 0 if name == 'stm32_wl_usb' else 1)
                previous_help = result.stdout.replace(FAST_HELP, b'')
                self.assertEqual(hashlib.sha256(previous_help).hexdigest(),GOLDEN[name]['text'])
                if name not in PACKED_PROFILES:
                    fast_call = b'P' + len(FAST_HELP).to_bytes(4, 'little') + FAST_HELP
                    self.assertEqual(result.stderr.count(fast_call), 1)
                    previous_calls = result.stderr.replace(fast_call, b'')
                    self.assertEqual(hashlib.sha256(previous_calls).hexdigest(),GOLDEN[name]['calls'])
                else:
                    image = (work / 'test').read_bytes()
                    self.assertNotIn(b'Commands:\r\n  stats-core / stats-radio / stats-radio-diag',image)


    def test_cpp11_caller_links_actual_cpp17_packing_translation_unit(self):
        source=(ROOT/'examples/companion_radio/MyMesh.cpp').read_text()
        start=source.index('    auto& output = terminalOutput();',source.index('} else if (strcmp(command, "help") == 0)'))
        end=source.index('  } else if (handleCommand(command, 0, local_reply))',start)
        consumer=HARNESS.replace('@ACTUAL_HELP@',source[start:end]).replace('@PACKED_IMPLEMENTATION@','')
        consumer=consumer[:consumer.index('  constexpr char literal[] =')]+"}\n"
        stream=HARNESS[HARNESS.index('class Stream {'):HARNESS.index('using Output=Stream;')]
        headers='#include <cstdint>\n#include <algorithm>\n#include <cassert>\n#include <cstdio>\n#include <cstring>\n#include <string>\n#include <vector>\n#include <utility>\n'
        for profile in ('rak_full', 'stm32_wl_usb'):
            with tempfile.TemporaryDirectory(prefix='companion-help-language-') as folder:
                work=Path(folder)
                (work/'MyMesh.h').write_text(headers+stream)
                (work/'CompanionHelpPacked.cpp').write_bytes((ROOT/'examples/companion_radio/CompanionHelpPacked.cpp').read_bytes())
                (work/'consumer.cpp').write_text(consumer)
                compiler=os.environ.get('CXX','g++')
                options=['-Os','-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-fno-sanitize-recover=all','-fno-pie','-no-pie',*['-D'+v for v in PROFILES[profile]],'-I'+str(work),'-I'+str(ROOT/'examples/companion_radio')]
                for name,standard in [('CompanionHelpPacked','c++17'),('consumer','c++11')]:
                    result=subprocess.run([compiler,'-std='+standard,*options,'-c',str(work/(name+'.cpp')),'-o',str(work/(name+'.o'))],capture_output=True,text=True)
                    self.assertEqual(result.returncode,0,result.stdout+result.stderr)
                result=subprocess.run([compiler,*options,str(work/'consumer.o'),str(work/'CompanionHelpPacked.o'),'-o',str(work/'test')],capture_output=True,text=True)
                self.assertEqual(result.returncode,0,result.stdout+result.stderr)
                result=subprocess.run([str(work/'test')],capture_output=True)
                self.assertEqual(result.returncode,0,result.stderr.decode(errors='replace'))
                self.assertEqual(result.stdout.count(FAST_HELP), 0 if profile == 'stm32_wl_usb' else 1)
                self.assertEqual(hashlib.sha256(result.stdout.replace(FAST_HELP, b'')).hexdigest(),GOLDEN[profile]['text'])
                self.assertNotIn(b'Commands:\r\n  stats-core / stats-radio / stats-radio-diag',(work/'test').read_bytes())

    def test_small_stm32_arm_help_saves_flash_with_a_bounded_frame(self):
        tool = shutil.which('arm-none-eabi-g++')
        if not tool:
            candidate = Path.home()/'.platformio/packages/toolchain-gccarmnoneeabi/bin/arm-none-eabi-g++'
            if candidate.is_file(): tool = str(candidate)
        if not tool:
            self.skipTest('ARM compiler unavailable; linked image qualification remains required')
        size_tool = str(Path(tool).with_name('arm-none-eabi-size'))
        header = ('#include <stdint.h>\n#include <stddef.h>\n'
                  'class Stream { public: virtual size_t write(const uint8_t*,size_t)=0;'
                  'size_t print(const char*);size_t println(const char*);};\n')
        raw = '''#include "MyMesh.h"
extern "C" void rawHelp(Stream& output) {
#define MESH_COMPANION_HELP_BEGIN output.print(
#define MESH_COMPANION_HELP_END );
#define MESH_COMPANION_HELP_LINE_BEGIN output.println(
#define MESH_COMPANION_HELP_LINE_END );
#include "CompanionHelp.inc"
}
'''
        with tempfile.TemporaryDirectory(prefix='stm32-help-arm-') as folder:
            work=Path(folder)
            (work/'MyMesh.h').write_text(header)
            (work/'packed.cpp').write_bytes((ROOT/'examples/companion_radio/CompanionHelpPacked.cpp').read_bytes())
            (work/'raw.cpp').write_text(raw)
            flags=['-std=gnu++17','-mcpu=cortex-m4','-mthumb','-Oz',
                   '-fno-inline-small-functions','-fno-rtti','-fno-exceptions',
                   '-fmerge-all-constants','-fno-tree-dominator-opts','-fstack-usage',
                   *['-D'+v for v in PROFILES['stm32_wl_usb']],
                   '-I'+str(work),'-I'+str(ROOT/'examples/companion_radio')]
            sizes={}
            for name in ('raw','packed'):
                result=subprocess.run([tool,*flags,'-c',str(work/(name+'.cpp')),
                                       '-o',str(work/(name+'.o'))],capture_output=True,text=True)
                self.assertEqual(result.returncode,0,result.stdout+result.stderr)
                result=subprocess.run([size_tool,str(work/(name+'.o'))],capture_output=True,text=True)
                self.assertEqual(result.returncode,0,result.stdout+result.stderr)
                sizes[name]=int(result.stdout.splitlines()[-1].split()[0])
            self.assertGreaterEqual(sizes['raw']-sizes['packed'],700)
            frames=[]
            for line in (work/'packed.su').read_text().splitlines():
                function,count,kind=line.rsplit('\t',2)
                self.assertEqual(kind,'static',line)
                frames.append(int(count))
            # Overbound all emitted producer/helper frames. The reserve covers
            # its caller and output sink here, not physical ISR high-water.
            self.assertTrue(frames)
            self.assertLessEqual(sum(frames),512)
            self.assertLessEqual(sum(frames)+512,1024)
            print('STM32WL help: object saving %d bytes; producer/helper stack %d + 512 reserve / 1024'
                  % (sizes['raw']-sizes['packed'],sum(frames)))

if __name__ == '__main__':
    unittest.main()
