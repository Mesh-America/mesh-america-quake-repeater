"""Compact Companions isolate one C++17 help source, never a global ABI change."""
from pathlib import Path
import copy
import importlib.util
import os
import re
import shutil
import subprocess
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('help_language_policy',ROOT/'scripts/nrf52_flash_trim.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
spec=importlib.util.spec_from_file_location('stm32_help_language_policy',ROOT/'scripts/stm32_companion_help.py');stm=importlib.util.module_from_spec(spec);spec.loader.exec_module(stm)
class HelpBuildPolicy(unittest.TestCase):
 def test_companion_source_registers_before_late_board_and_profile_flags(self):
  yes=dict(platform='nordicnrf52',mcu='nrf52840',src_filter='+<*> +<../examples/companion_radio>',flags='-DRAK_4631 -DCOMPANION_RADIO_FULL')
  self.assertTrue(m.packed_help_policy(**yes))
  for flags in ('', '-DRAK_4631', '-DCOMPANION_RADIO_FULL', '-DRAK_4631 -URAK_4631', '-DRAK_4631 -DCOMPANION_RADIO_FULL -UCOMPANION_RADIO_FULL'):
   self.assertTrue(m.packed_help_policy(**dict(yes,flags=flags)))
  for key,value in [('platform','espressif32'),('mcu','nrf52832'),('src_filter','+<*>'),('src_filter','+<../examples/companion_radio> +<../examples/simple_repeater>')]:
   with self.subTest(key=key,value=value):
    no=dict(yes);no[key]=value;self.assertFalse(m.packed_help_policy(**no))
  self.assertTrue(m.packed_help_policy('nordicnrf52','nrf52840','+<../examples/companion_radio>',cppdefines=[('RAK_4631',1),('COMPANION_RADIO_FULL',1)]))
 def test_object_overrides_change_only_that_translation_units_language(self):
  class Node:
   def __init__(self,path):self.path=path
   def srcnode(self):return self
   def get_abspath(self):return str(self.path)
  class Env(dict):
   def subst(self,text):return text.replace('$PROJECT_DIR',str(ROOT))
   def Object(self,node,**overrides):self.object=node;self.overrides=overrides;return ('compiled17',node)
  env=Env(CXXFLAGS=['-fno-exceptions','-std=gnu++11','-fno-rtti'],CCFLAGS=['-Os','-flto','-std=gnu++11'],CPPDEFINES=[('FEATURE',1)])
  before=copy.deepcopy(dict(env));other=Node(ROOT/'examples/companion_radio/MyMesh.cpp')
  self.assertIs(m.compile_packed_help(env,other),other);self.assertFalse(hasattr(env,'overrides'))
  node=Node(ROOT/'examples/companion_radio/CompanionHelpPacked.cpp');result=m.compile_packed_help(env,node)
  self.assertEqual(result,('compiled17',node));self.assertEqual(dict(env),before)
  self.assertEqual(env.overrides['CXXFLAGS'],['-fno-exceptions','-fno-rtti','-std=gnu++17'])
  self.assertEqual(env.overrides['CCFLAGS'],['-Os','-flto']);self.assertEqual(env['CPPDEFINES'],before['CPPDEFINES'])
 def test_producer_resolves_header_board_alias_before_feature_gate(self):
  compiler=os.environ.get('CXX') or shutil.which('g++') or shutil.which('clang++')
  if not compiler:
   self.skipTest('host C++ preprocessor required')
  directory=ROOT/'examples/companion_radio'
  producer=(directory/'CompanionHelpPacked.cpp').read_text()
  # RAK3401's variant header defines RAK_4631 only after Arduino/MyMesh is
  # included. A command-line definition would hide the linker's regression.
  board_context='''#pragma once
#if defined(TEST_RAK3401_VARIANT)
#define RAK_4631 1
#endif
#if defined(TEST_STM32WL_VARIANT)
#define STM32WLxx 1
#endif
'''
  profiles=(
   ('rak3401_full',('NRF52_PLATFORM','TEST_RAK3401_VARIANT','COMPANION_RADIO_FULL'),True),
   ('rak3401_usb',('NRF52_PLATFORM','TEST_RAK3401_VARIANT'),False),
   ('other_nrf52_full',('NRF52_PLATFORM','COMPANION_RADIO_FULL'),False),
   ('rak4631_full',('NRF52_PLATFORM','RAK_4631','COMPANION_RADIO_FULL'),True),
   ('stm32wl_terminal',('STM32_PLATFORM','STM32WLxx','COMPANION_FEATURE_TEXT_TERMINAL=1'),True),
   ('stm32wl_header_alias',('STM32_PLATFORM','TEST_STM32WL_VARIANT','COMPANION_FEATURE_TEXT_TERMINAL=1'),True),
   ('stm32wl_no_terminal',('STM32_PLATFORM','STM32WLxx','COMPANION_FEATURE_TEXT_TERMINAL=0'),False),
  )
  with tempfile.TemporaryDirectory(prefix='companion-help-gate-') as folder:
   work=Path(folder)
   (work/'MyMesh.h').write_text(board_context,encoding='ascii')
   source=work/'CompanionHelpPacked.cpp'
   source.write_text(producer,encoding='ascii')
   for name,defines,selected in profiles:
    with self.subTest(profile=name):
     result=subprocess.run([compiler,'-E','-P','-std=c++17',
       *['-D'+value for value in defines],'-I'+str(directory),str(source)],
       capture_output=True,text=True)
     self.assertEqual(result.returncode,0,result.stdout+result.stderr)
     definition=re.search(r'size_t\s+writePackedCompanionHelp\s*\([^)]*\)\s*\{',result.stdout)
     self.assertEqual(definition is not None,selected,
       'packed help producer and caller must see the same header-defined board aliases')
 def test_producer_uses_same_feature_context_and_single_help_source(self):
  cpp=(ROOT/'examples/companion_radio/CompanionHelpPacked.cpp').read_text();mesh=(ROOT/'examples/companion_radio/MyMesh.cpp').read_text()
  self.assertLess(cpp.index('#include "MyMesh.h"'),cpp.index('#include "CompanionHelp.inc"'))
  self.assertIn('#if defined(RAK_4631) && defined(COMPANION_RADIO_FULL)',cpp)
  self.assertEqual(cpp.count('#include "CompanionHelp.inc"'),1)
  branch=mesh[mesh.index('    auto& output = terminalOutput();',mesh.index('} else if (strcmp(command, "help") == 0)')):]
  self.assertIn('mesh::companion::writePackedCompanionHelp(output);',branch)
  self.assertNotIn('constexpr',branch[:branch.index('#else')])
 def test_stm32_registration_is_only_the_small_companion_source_role(self):
  selected='+<*> +<../examples/companion_radio/*.cpp>'
  for mcu in ('stm32wle5jc','STM32WL55JC','stm32wle5cc'):
   self.assertTrue(stm.packed_help_policy('ststm32',mcu,selected))
  for platform,mcu,source in (('nordicnrf52','nrf52840',selected),
      ('espressif32','esp32s3',selected),('ststm32','stm32f405rg',selected),
      ('ststm32','stm32wle5jc','+<*>'),
      ('ststm32','stm32wle5jc',selected+' +<../examples/simple_repeater>'),
      ('ststm32','stm32wle5jc',selected+' +<../examples/simple_secure_chat>')):
   self.assertFalse(stm.packed_help_policy(platform,mcu,source))
 def test_stm32_installer_registers_one_source_without_installing_nrf_trims(self):
  class Env(dict):
   def PioPlatform(self):return type('Platform',(),{'name':'ststm32'})()
   def BoardConfig(self):return {'build.mcu':'stm32wle5jc'}
   def AddBuildMiddleware(self,callback,pattern):self.calls.append((callback,pattern))
  env=Env(SRC_FILTER='+<*> +<../examples/companion_radio/*.cpp>');env.calls=[]
  before=copy.deepcopy(dict(env));stm.install(env)
  self.assertEqual(dict(env),before)
  self.assertEqual(env.calls,[(stm.POLICY.compile_packed_help,'*CompanionHelpPacked.cpp')])
  self.assertIn('pre:scripts/stm32_companion_help.py',(ROOT/'platformio.ini').read_text())
if __name__=='__main__':unittest.main()
