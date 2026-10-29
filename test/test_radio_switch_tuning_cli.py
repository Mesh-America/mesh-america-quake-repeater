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

    def test_capability_gate_only_defaults_off_for_integrated_stm32wl(self):
        compiler = shutil.which('g++') or shutil.which('clang++')
        self.assertIsNotNone(compiler)
        for defines, expected in (((), 1), (('NRF52_PLATFORM',), 1), (('ESP32_PLATFORM',), 1),
                                  (('RP2040_PLATFORM',), 1), (('STM32_PLATFORM',), 1),
                                  (('STM32WLxx',), 1), (('STM32_PLATFORM', 'STM32WLxx'), 0),
                                  (('STM32_PLATFORM', 'STM32WLxx', 'MESH_RADIO_SWITCH_TUNING=1'), 1)):
            with self.subTest(defines=defines):
                source = '#include <helpers/RadioSwitchTuning.h>\n'
                source += f'static_assert(MESH_RADIO_SWITCH_TUNING == {expected}, "capability gate");\n'
                built = subprocess.run([compiler, '-std=c++11', '-fsyntax-only', '-x', 'c++',
                    '-I', str(ROOT / 'src'), *['-D' + value for value in defines], '-'],
                    input=source, capture_output=True, text=True)
                self.assertEqual(built.returncode, 0, built.stdout + built.stderr)

    def test_integrated_stm32wl_omits_unsupported_controls_and_boot_storage_reads(self):
        compiler = shutil.which('g++') or shutil.which('clang++')
        self.assertIsNotNone(compiler)
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            helpers = work / 'helpers'
            helpers.mkdir()
            # Instrument the existing filesystem mock, rather than accepting
            # an untouched file as proof that no startup read occurred.
            mock = (ROOT / 'test/fixtures/radio_profiles/mocks/helpers/IdentityStore.h').read_text()
            mock = mock.replace('  std::map<std::string, std::vector<uint8_t>> files;',
                '  std::map<std::string, std::vector<uint8_t>> files;\n'
                '  std::vector<std::string> opened_paths;')
            mock = mock.replace('  File open(const char* path, const char* mode = "r", bool = false) {',
                '  File open(const char* path, const char* mode = "r", bool = false) {\n'
                '    opened_paths.push_back(path);')
            mock = mock.replace('  File open(const char* path, const char* mode = "r", bool = false) {',
                '  File open(const char* path, int mode) { return open(path, mode ? "w" : "r"); }\n'
                '  File open(const char* path, const char* mode = "r", bool = false) {')
            (helpers / 'IdentityStore.h').write_text(mock, encoding='ascii')
            flags = [compiler, '-std=c++17', '-O2', '-Wall', '-Wextra', '-DSTM32_PLATFORM',
                     '-DSTM32WLxx', '-DLFS_ERR_NOENT=-2', '-I', str(work),
                     '-I', str(ROOT / 'test/fixtures/radio_profiles/mocks'),
                     '-I', str(ROOT / 'test/mocks'), '-I', str(ROOT / 'src')]
            source = ROOT / 'src/helpers/RadioProfileCLI.cpp'
            executable = work / 'unsupported'
            built = subprocess.run(flags + [str(source), str(ROOT / 'test/fixtures/radio_profiles/'
                'switch_tuning_unsupported_test.cpp'), '-o', str(executable)],
                capture_output=True, text=True)
            self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
            subprocess.run([str(executable)], check=True)
            # Inspect real production objects. The inactive branch must omit
            # both saved-file names and all parser/persistence entry points.
            for enabled in (False, True):
                obj = work / f'cli-{int(enabled)}.o'
                override = ['-DMESH_RADIO_SWITCH_TUNING=1'] if enabled else []
                subprocess.run(flags + override + ['-c', str(source), '-o', str(obj)],
                               check=True, capture_output=True, text=True)
                raw = obj.read_bytes()
                for marker in (b'/radio_fast', b'handleFastSettings', b'loadFastSettings',
                               b'saveFastSettings', b'validFastImage'):
                    self.assertEqual(marker in raw, enabled, marker)
                self.assertIn(b'/radio_profiles', raw)

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
