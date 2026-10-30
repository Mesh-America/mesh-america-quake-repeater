"""Preserve the complete limiter using explicit word-only SRAM0 storage."""
from pathlib import Path
import os
import resource
import re
import signal
import subprocess
import tempfile
import unittest

from test_flood_advert_rtc import HARNESS

ROOT=Path(__file__).resolve().parents[1]


class FloodAdvertIramTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(prefix='advert-iram-')
        cls.work=Path(cls.temp.name)
        (cls.work/'sdkconfig.h').write_text('#define CONFIG_IDF_TARGET_ESP32 1\n')
        cls.compiler=[os.environ.get('CXX','g++')]

    @classmethod
    def tearDownClass(cls): cls.temp.cleanup()

    def build(self,enabled,mutate=False):
        name='probe-'+str(enabled)+('-mutated' if mutate else '')
        cpp=self.work/(name+'.cpp');binary=self.work/name
        code=HARNESS.replace('@BANKS@','')
        code=code.replace('if(!std::strcmp(mode,"lifetime")) {',
            'if(!std::strcmp(mode,"lifetime")) {\n'
            '#if FLOOD_ADVERT_IRAM_WORD_STORAGE\n'
            ' for(unsigned i=0;i<128*35;++i) mesh::floodAdvertIramBank()[i]=0xffffffffU;\n'
            '#endif\n')
        code=code.replace('CHECK(limiter.listLimited(0,0,nullptr,0)==0);',
            'CHECK(limiter.listLimited(0,0,nullptr,0)==0);\n'
            '#if FLOOD_ADVERT_IRAM_WORD_STORAGE\n'
            ' for(unsigned i=0;i<128*35;++i) CHECK(mesh::floodAdvertIramBank()[i]==0);\n'
            '#endif\n')
        # Repeat the original full-capacity trace with colliding prefixes, whose
        # distinct complete keys must still share quota and retain own strikes.
        code=code.replace('key[0] = uint8_t(i); key[1] = uint8_t(i >> 8);',
                          'key[0] = uint8_t(i / 2); key[1] = uint8_t(i >> 8);')
        cpp.write_text(code)
        source=ROOT/'src/helpers/FloodAdvertLimiterIram.cpp'
        if mutate:
            text=source.read_text()
            begin=text.index('void FloodAdvertLimiter::storeEntry(')
            body=text.index('{',begin)+1
            text=text[:body]+'\n  (void)index; (void)source; return;\n'+text[body:]
            source=self.work/'mutated.cpp';source.write_text(text)
        args=['-std=c++11','-Os','-DNDEBUG','-Wall','-Wextra','-Werror',
              '-fsanitize=address,undefined','-fno-sanitize-recover=all','-fno-pie','-no-pie',
              '-DESP32_PLATFORM=1','-DMESHCORE_EXPANDED_PARTITION_PROFILE=1',
              '-DFLOOD_ADVERT_IRAM_WORD_STORAGE='+str(enabled),
              '-I',str(self.work),'-I',str(ROOT/'src/helpers'),'-isystem',str(ROOT/'src'),'-isystem',str(ROOT/'test/mocks')]
        r=subprocess.run(self.compiler+args+[str(cpp),str(ROOT/'src/helpers/FloodAdvertLimiter.cpp'),str(source),'-o',str(binary)],capture_output=True,text=True,timeout=30)
        self.assertEqual(r.returncode,0,r.stdout+r.stderr)
        return binary

    def test_complete_contiguous_and_word_only_traces_are_identical(self):
        baseline=subprocess.run([str(self.build(0))],capture_output=True,text=True,check=True,timeout=20).stdout
        result=subprocess.run([str(self.build(1))],capture_output=True,text=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(result.stdout,baseline)
        self.assertIn('limited=128',result.stdout)

    def test_noload_dirty_records_are_cleared_on_owner_recreation(self):
        r=subprocess.run([str(self.build(1)),'lifetime'],capture_output=True,text=True,timeout=20)
        self.assertEqual(r.returncode,0,r.stdout+r.stderr)

    def test_ndebug_still_rejects_a_second_owner(self):
        def no_core(): resource.setrlimit(resource.RLIMIT_CORE,(0,0))
        r=subprocess.run([str(self.build(1)),'owners'],capture_output=True,text=True,preexec_fn=no_core,timeout=20)
        self.assertEqual(r.returncode,-signal.SIGABRT,r.stdout+r.stderr)

    def test_missing_word_writeback_is_detected(self):
        baseline=subprocess.run([str(self.build(0))],capture_output=True,text=True,check=True,timeout=20).stdout
        result=subprocess.run([str(self.build(1,mutate=True))],capture_output=True,text=True,timeout=20)
        self.assertNotEqual(result.stdout,baseline)

    def test_unselected_backend_produces_no_code_or_storage(self):
        obj=self.work/'unselected.o'
        built=subprocess.run(self.compiler+['-std=c++11','-Os','-DNDEBUG',
            '-DFLOOD_ADVERT_IRAM_WORD_STORAGE=0','-isystem',str(ROOT/'src'),
            '-isystem',str(ROOT/'test/mocks'),'-c',str(ROOT/'src/helpers/FloodAdvertLimiterIram.cpp'),
            '-o',str(obj)],capture_output=True,text=True,timeout=20)
        self.assertEqual(built.returncode,0,built.stdout+built.stderr)
        symbols=subprocess.run(['nm','-C',str(obj)],capture_output=True,text=True,check=True).stdout
        self.assertEqual(symbols.strip(),'')
        sections=subprocess.run(['objdump','-h',str(obj)],capture_output=True,text=True,check=True).stdout
        for section,size in re.findall(r'^\s*\d+\s+(\S+)\s+([0-9a-f]+)',sections,re.M):
            if section.startswith(('.text','.data','.bss','.rodata','.literal')):
                self.assertEqual(int(size,16),0,section)

    def test_only_qualified_classic_full_recipes_select_word_storage(self):
        text=(ROOT/'build_legacy.sh').read_text()
        start=text.index('apply_esp32_iram_advert_storage_profile() {')
        end=text.index('\n}\n',start)+2
        function=text[start:end]
        fixtures=(
            ('LilyGo_TLora_V2_1_1_6_repeater_',True),
            ('LilyGo_TLora_V2_1_1_6_repeater_observer_mqtt_',True),
            ('LilyGo_TLora_V2_1_1_6_room_server_',True),
            ('LilyGo_TLora_V2_1_1_6_room_server_observer_mqtt_',True),
            ('Tbeam_SX1262_repeater_observer_mqtt',True),
            ('Tbeam_SX1276_repeater_observer_mqtt',True),
            ('Tbeam_SX1262_room_server_observer_mqtt',True),
            ('Tbeam_SX1276_room_server_observer_mqtt',True),
            ('Tbeam_SX1262_room_server',False),
            ('Tbeam_SX1276_room_server',False),
            ('Tbeam_SX1276_companion_radio_ble',False),
            ('LilyGo_TLora_V2_1_1_6_companion_radio_ble',False),
            ('Heltec_Wireless_Tracker_repeater',False),
            ('RAK_4631_repeater',False))
        for full in ('0','1'):
            for supported in ('0','1'):
                for target,qualified in fixtures:
                    with self.subTest(full=full,supported=supported,target=target):
                        code=('ESP32_FULL_BUILD="$1"\nQUALIFIED="$2"\n'
                              'PLATFORMIO_BUILD_FLAGS="-DEXISTING=1"\n'
                              'supports_esp32_full_build() { [ "$QUALIFIED" = 1 ]; }\n'
                              +function+'\napply_esp32_iram_advert_storage_profile "$3"\n'
                              'printf "%s" "$PLATFORMIO_BUILD_FLAGS"\n')
                        result=subprocess.run(['bash','-c',code,'bash',full,supported,target],
                            capture_output=True,text=True,check=True,timeout=10)
                        expected='-DEXISTING=1'
                        if full=='1' and supported=='1' and qualified:
                            expected+=' -DFLOOD_ADVERT_IRAM_WORD_STORAGE=1'
                        self.assertEqual(result.stdout,expected)
        body=text[text.index('build_firmware() {'):]
        self.assertEqual(body.count('apply_esp32_iram_advert_storage_profile "$env_name"'),1)
        self.assertLess(body.index('apply_esp32_full_size_profile "$env_name"'),
                        body.index('apply_esp32_iram_advert_storage_profile "$env_name"'))

    def test_unsupported_soc_byte_emulation_and_mixed_backends_are_rejected(self):
        src=self.work/'invalid.cpp';src.write_text('#include <helpers/FloodAdvertLimiter.h>\n')
        isolated=self.work/'bad';isolated.mkdir(exist_ok=True)
        for config,extra in (
            ('#define CONFIG_IDF_TARGET_ESP32S3 1\n',[]),
            ('#define CONFIG_IDF_TARGET_ESP32 1\n#define CONFIG_ESP32_IRAM_AS_8BIT_ACCESSIBLE_MEMORY 1\n',[]),
            ('#define CONFIG_IDF_TARGET_ESP32 1\n',['-DFLOOD_ADVERT_RTC_FAST_SLOTS=16'])):
            with self.subTest(config=config,extra=extra):
                (isolated/'sdkconfig.h').write_text(config)
                r=subprocess.run(self.compiler+['-std=c++11','-fsyntax-only',
                    '-DESP32_PLATFORM=1','-DMESHCORE_EXPANDED_PARTITION_PROFILE=1','-DFLOOD_ADVERT_IRAM_WORD_STORAGE=1',
                    '-I',str(isolated),'-I',str(self.work),'-isystem',str(ROOT/'src'),'-isystem',str(ROOT/'test/mocks'),
                    *extra,str(src)],capture_output=True,text=True,timeout=15)
                self.assertNotEqual(r.returncode,0)


if __name__=='__main__': unittest.main()
