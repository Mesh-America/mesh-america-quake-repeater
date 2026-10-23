"""Exercise saved fast-switch controls through the production shared CLI."""
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest
from cpp_source import body

ROOT = Path(__file__).resolve().parents[1]


class RadioSwitchTuningCLITest(unittest.TestCase):
    def test_five_cli_roles_restore_tuning_before_first_radio_initialization(self):
        for role in ('companion_radio', 'simple_repeater', 'simple_room_server',
                     'simple_sensor', 'simple_secure_chat'):
            with self.subTest(role=role):
                source = (ROOT / f'examples/{role}/main.cpp').read_text()
                setup = body(source, '\nvoid setup(')
                setup = re.sub(r'//[^\n]*|/\*.*?\*/', '', setup, flags=re.S)
                hook = 'mesh::RadioProfileCLI::configureBootTuning('
                self.assertEqual(setup.count(hook), 1)
                if role != 'simple_secure_chat':
                    self.assertLess(setup.index('beginRegulatorSettings('), setup.index(hook))
                    self.assertRegex(setup, r'configureBootTuning\(regulator_prefs_fs,\s*radio_driver\)')
                else:
                    self.assertRegex(setup, r'configureBootTuning\(\s*volatile_primary_fs\s*\?\s*nullptr\s*:\s*primary_fs,\s*radio_driver\)')
                    for mount in ('beginInternalPrimaryFilesystemSafely(',
                                  'LittleFS.begin()', 'SPIFFS.begin(true)'):
                        self.assertEqual(setup.count(mount), 1)
                        self.assertLess(setup.index(mount), setup.index(hook))
                    self.assertEqual(setup.count('the_mesh.begin('), 1)
                    self.assertLess(setup.index('fast_rng.begin('), setup.index('the_mesh.begin('))
                radio_init = re.search(r'\bradio_init\s*\(', setup)
                self.assertIsNotNone(radio_init)
                self.assertLess(setup.index(hook), radio_init.start())
                if role == 'simple_secure_chat':
                    self.assertLess(radio_init.start(), setup.index('fast_rng.begin('))

    def test_saved_controls_and_failure_transactions(self):
        compiler = shutil.which('g++') or shutil.which('clang++')
        self.assertIsNotNone(compiler)
        with tempfile.TemporaryDirectory() as work:
            for fleet_enabled in (False, True):
                with self.subTest(fleet=fleet_enabled):
                    executable = Path(work) / f'switch-{int(fleet_enabled)}'
                    subprocess.run([
                        compiler, '-std=c++17', '-Wall', '-Wextra',
                        f'-DMESH_ENABLE_FLEET_CONTROL={int(fleet_enabled)}',
                        '-I', str(ROOT / 'test/fixtures/radio_profiles/mocks'),
                        '-I', str(ROOT / 'test/mocks'), '-I', str(ROOT / 'src'),
                        str(ROOT / 'src/helpers/RadioProfileCLI.cpp'),
                        str(ROOT / 'test/fixtures/radio_profiles/switch_tuning_test.cpp'),
                        '-o', str(executable)], check=True, capture_output=True, text=True)
                    subprocess.run([str(executable)], check=True)


if __name__ == '__main__':
    unittest.main()
