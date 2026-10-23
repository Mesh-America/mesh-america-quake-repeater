"""The C++17 help encoder is one RAK Full source, never a global ABI change."""
from pathlib import Path
import copy
import importlib.util
import unittest
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('help_language_policy',ROOT/'scripts/nrf52_flash_trim.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class HelpBuildPolicy(unittest.TestCase):
 def test_only_actual_rak_full_companion_profile_selects_cpp17_helper(self):
  yes=dict(platform='nordicnrf52',mcu='nrf52840',src_filter='+<*> +<../examples/companion_radio>',flags='-DRAK_4631 -DCOMPANION_RADIO_FULL')
  self.assertTrue(m.packed_help_policy(**yes))
  for key,value in [('platform','espressif32'),('mcu','nrf52832'),('src_filter','+<*>'),('src_filter','+<../examples/companion_radio> +<../examples/simple_repeater>'),('flags','-DRAK_4631'),('flags','-DCOMPANION_RADIO_FULL'),('flags','-DRAK_4631 -DCOMPANION_RADIO_FULL -UCOMPANION_RADIO_FULL')]:
   with self.subTest(key=key,value=value):
    no=dict(yes);no[key]=value;self.assertFalse(m.packed_help_policy(**no))
  self.assertTrue(m.packed_help_policy('nordicnrf52','nrf52840','+<../examples/companion_radio>',cppdefines=[('RAK_4631',1),('COMPANION_RADIO_FULL',1)]))
 def test_final_object_clone_changes_only_that_translation_units_language(self):
  class Node:
   def __init__(self,path):self.path=path
   def srcnode(self):return self
   def get_abspath(self):return str(self.path)
  class Env(dict):
   def subst(self,text):return text.replace('$PROJECT_DIR',str(ROOT))
   def Clone(self):self.clone=Env(copy.deepcopy(dict(self)));return self.clone
   def Replace(self,**values):self.update(values)
   def Object(self,node):self.object=node;return ('compiled17',node)
  env=Env(CXXFLAGS=['-fno-exceptions','-std=gnu++11','-fno-rtti'],CCFLAGS=['-Os','-flto','-std=gnu++11'],CPPDEFINES=[('FEATURE',1)])
  before=copy.deepcopy(dict(env));other=Node(ROOT/'examples/companion_radio/MyMesh.cpp')
  self.assertIs(m.compile_packed_help(env,other),other);self.assertFalse(hasattr(env,'clone'))
  node=Node(ROOT/'examples/companion_radio/CompanionHelpPacked.cpp');result=m.compile_packed_help(env,node)
  self.assertEqual(result,('compiled17',node));self.assertEqual(dict(env),before)
  self.assertEqual(env.clone['CXXFLAGS'],['-fno-exceptions','-fno-rtti','-std=gnu++17'])
  self.assertEqual(env.clone['CCFLAGS'],['-Os','-flto']);self.assertEqual(env.clone['CPPDEFINES'],before['CPPDEFINES'])
 def test_producer_uses_same_feature_context_and_single_help_source(self):
  cpp=(ROOT/'examples/companion_radio/CompanionHelpPacked.cpp').read_text();mesh=(ROOT/'examples/companion_radio/MyMesh.cpp').read_text()
  self.assertLess(cpp.index('#include "MyMesh.h"'),cpp.index('#include "CompanionHelp.inc"'))
  self.assertIn('#if defined(RAK_4631) && defined(COMPANION_RADIO_FULL)',cpp)
  self.assertEqual(cpp.count('#include "CompanionHelp.inc"'),1)
  branch=mesh[mesh.index('    auto& output = terminalOutput();',mesh.index('} else if (strcmp(command, "help") == 0)')):]
  self.assertIn('mesh::companion::writePackedCompanionHelp(output);',branch)
  self.assertNotIn('constexpr',branch[:branch.index('#else')])
if __name__=='__main__':unittest.main()
