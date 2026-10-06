"""Reject dangerous cleanup paths without touching any existing build output."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class Tests(unittest.TestCase):
    def run_main(self, output, target, *options, old_resume_bug=False,
                 inherited_resume=False):
        # Exercise the real parser, target/profile resolution, main policy,
        # and filesystem cleanup. Only discovery, locking/version prompts and
        # final compilation are doubles; no PlatformIO process is permitted.
        script = r'''
source "$1/build_legacy.sh"
OUTPUT_DIR=$2
RESUME_BUILD_OUTPUT=$3
OUTPUT_POLICY_EXPLICIT=0
shift 3
pio() { echo 'UNEXPECTED_PLATFORMIO' >&2; return 99; }
acquire_build_script_lock() { return 0; }
release_build_script_lock() { return 0; }
refresh_firmware_version_tags() { return 0; }
prompt_for_resolved_firmware_version() { return 0; }
init_project_context() {
  ALL_PIO_ENVS=(wio-e5-mini_companion_radio_usb Tbeam_SX1262_repeater Heltec_mesh_solar_companion_radio_usb)
  SUPPORTED_PIO_ENVS=("${ALL_PIO_ENVS[@]}")
  PIO_ENV_PLATFORM_BY_NAME[wio-e5-mini_companion_radio_usb]=STM32_PLATFORM
  PIO_ENV_PLATFORM_BY_NAME[Tbeam_SX1262_repeater]=ESP32_PLATFORM
  PIO_ENV_PLATFORM_BY_NAME[Heltec_mesh_solar_companion_radio_usb]=NRF52_PLATFORM
  PIO_ENV_FULL_BUILD_BY_NAME[Tbeam_SX1262_repeater]=1
}
record_stub_build() {
  local target
  for target in "$@"; do
    printf '%s\n' "$BUILD_PROFILE_EFFECTIVE" > "$OUTPUT_DIR/$target-$BUILD_PROFILE_EFFECTIVE.bin"
  done
}
run_resolved_build_targets() { record_stub_build "$@"; }
run_full_only_esp32_profile() { record_stub_build "$@"; }
run_full_esp32_build_targets() { shift; record_stub_build "$@"; }
run_auto_two_pass_build() { record_stub_build "$@"; }
'''
        if old_resume_bug:
            source = (ROOT / 'build_legacy.sh').read_text(encoding='ascii')
            main = source[source.index('main() {\n'):source.index('\nif [[ "${BASH_SOURCE[0]}" == "$0" ]]')]
            begin = main.index('    # Single-target builds still clean by default,')
            end = main.index('\n  fi\n', begin)
            # Reintroduce the historical override in the complete real main;
            # all other production functions retain their original source path.
            script += main[:begin] + '    RESUME_BUILD_OUTPUT=0' + main[end:] + '\n'
        script += 'main "$@"\n'
        return subprocess.run(['bash', '-c', script, 'main-output-policy', str(ROOT),
                               str(output), '1' if inherited_resume else '0',
                               'build-firmware', target, '--radio-preset', 'target',
                               *options], cwd=ROOT, capture_output=True, text=True, timeout=10)

    def assert_main_passed(self, result):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn('UNEXPECTED_PLATFORMIO', result.stderr)

    def prepare(self, output, *, cwd=ROOT, resume=False, stub=False, overrides=''):
        script = r'''
source "$1/build_legacy.sh"
OUTPUT_DIR=$2
RESUME_BUILD_OUTPUT=$3
'''
        if stub:
            # Protected-path tests never execute a real filesystem mutation,
            # even if this regression is reintroduced in production.
            script += r'''
rm() { printf 'UNSAFE_DELETE_CALL:%s\n' "$*"; }
mkdir() { printf 'UNSAFE_MKDIR_CALL:%s\n' "$*"; }
'''
        script += overrides + '\nprepare_output_dir\n'
        return subprocess.run(['bash', '-c', script, 'output-safety', str(ROOT),
                               str(output), '1' if resume else '0'], cwd=cwd,
                              capture_output=True, text=True, timeout=10)

    def assert_rejected_without_mutation(self, output, **kwargs):
        result = self.prepare(output, stub=True, **kwargs)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('Refusing unsafe output directory:', result.stderr)
        self.assertNotIn('UNSAFE_DELETE_CALL:', result.stdout)
        self.assertNotIn('UNSAFE_MKDIR_CALL:', result.stdout)

    def test_roots_homes_checkout_ancestors_and_dot_aliases_fail_before_rm(self):
        targets = ('', '/', '//', '.', './', '..', '../', str(ROOT),
                   str(ROOT/'out/..'), str(ROOT.parent), str(Path.home()),
                   *(str(parent) for parent in ROOT.parents))
        for resume in (False, True):
            for output in dict.fromkeys(targets):
                with self.subTest(output=output, resume=resume):
                    self.assert_rejected_without_mutation(output, resume=resume)

    def test_protected_symlink_targets_and_loops_are_not_deleted(self):
        with tempfile.TemporaryDirectory(prefix='mesh-build-output-safety-') as temporary:
            directory = Path(temporary)
            for i, protected in enumerate((ROOT, ROOT.parent, Path.home(), Path('/'))):
                link = directory/f'protected-{i}'
                link.symlink_to(protected, target_is_directory=True)
                for output in (link, str(link)+'/', str(link)+'/out/..'):
                    self.assert_rejected_without_mutation(output)
                self.assertTrue(link.is_symlink())
            loop = directory/'loop'
            loop.symlink_to(loop)
            self.assert_rejected_without_mutation(loop)
            self.assertTrue(loop.is_symlink())

    def test_tracked_subtrees_and_git_metadata_fail_before_rm_even_through_parent_links(self):
        for output in (ROOT/'src', ROOT/'examples', ROOT/'scripts', ROOT/'test',
                       ROOT/'.git', ROOT/'.git/objects', ROOT/'.git/config'):
            with self.subTest(output=output):
                self.assert_rejected_without_mutation(output)
        with tempfile.TemporaryDirectory(prefix='mesh-build-output-safety-') as temporary:
            link = Path(temporary)/'checkout-parent-link'
            link.symlink_to(ROOT, target_is_directory=True)
            for suffix in ('src', 'examples', '.git/objects'):
                self.assert_rejected_without_mutation(link/suffix)
            self.assertTrue(link.is_symlink())

    def test_safe_output_directory_is_cleaned_and_created_without_touching_siblings(self):
        with tempfile.TemporaryDirectory(prefix='mesh-build-output-safety-') as temporary:
            directory = Path(temporary)
            sibling = directory/'keep.bin'; sibling.write_bytes(b'keep sibling')
            for relative in ('output', 'path with spaces', 'nested/output',
                             'output; touch injected', '$(touch injected)'):
                output = directory/relative; output.mkdir(parents=True)
                (output/'old.bin').write_bytes(b'old diagnostic artifact')
                result = self.prepare(relative, cwd=directory)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertTrue(output.is_dir())
                self.assertEqual(list(output.iterdir()), [])
                self.assertEqual(sibling.read_bytes(), b'keep sibling')
                self.assertFalse((directory/'injected').exists())
            result = self.prepare(directory/'not-created-yet'/'output')
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue((directory/'not-created-yet'/'output').is_dir())

    def test_resume_preserves_output_files_and_safe_symlink_but_clean_refuses_the_link(self):
        with tempfile.TemporaryDirectory(prefix='mesh-build-output-safety-') as temporary:
            directory = Path(temporary)
            output = directory/'output'; output.mkdir()
            artifact = output/'previous.bin'; artifact.write_bytes(b'previous diagnostic build')
            initial = artifact.stat()
            link = directory/'output-link'; link.symlink_to(output, target_is_directory=True)
            for selected in (output, link):
                result = self.prepare(selected, resume=True)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(artifact.read_bytes(), b'previous diagnostic build')
                self.assertEqual((artifact.stat().st_ino, artifact.stat().st_mtime_ns),
                                 (initial.st_ino, initial.st_mtime_ns))
            self.assert_rejected_without_mutation(link)
            self.assert_rejected_without_mutation(str(link)+'/')
            self.assertTrue(link.is_symlink())
            self.assertEqual(artifact.read_bytes(), b'previous diagnostic build')

    def test_main_explicit_resume_preserves_sequential_standard_and_full_outputs(self):
        with tempfile.TemporaryDirectory(prefix='mesh-main-output-policy-') as temporary:
            output = Path(temporary) / 'output'
            output.mkdir()
            previous = output / 'qualified-image.bin'
            previous.write_bytes(b'already qualified build')
            initial = previous.stat()
            targets = (('wio-e5-mini_companion_radio_usb', (), 'auto'),
                       ('Tbeam_SX1262_repeater', ('--full-exact',), 'full'),
                       ('Heltec_mesh_solar_companion_radio_usb', ('--standard',), 'standard'))
            for target, options, profile in targets:
                result = self.run_main(output, target, *options, '--resume')
                self.assert_main_passed(result)
                self.assertEqual(previous.read_bytes(), b'already qualified build')
                self.assertEqual((previous.stat().st_ino, previous.stat().st_mtime_ns),
                                 (initial.st_ino, initial.st_mtime_ns))
                self.assertEqual((output / f'{target}-{profile}.bin').read_text(), profile + '\n')
            self.assertEqual(len(list(output.iterdir())), 4)

    def test_main_ordinary_default_and_explicit_clean_still_remove_old_outputs(self):
        for options, inherited in (((), False), ((), True), (('--clean',), False),
                                   (('--resume', '--clean'), False)):
            with self.subTest(options=options, inherited=inherited):
                with tempfile.TemporaryDirectory(prefix='mesh-main-output-clean-') as temporary:
                    output = Path(temporary) / 'output'
                    output.mkdir()
                    previous = output / 'previous.bin'
                    previous.write_bytes(b'old isolated build')
                    result = self.run_main(output, 'Heltec_mesh_solar_companion_radio_usb',
                                           '--standard', *options, inherited_resume=inherited)
                    self.assert_main_passed(result)
                    self.assertFalse(previous.exists())
                    self.assertEqual([item.name for item in output.iterdir()],
                                     ['Heltec_mesh_solar_companion_radio_usb-standard.bin'])

    def test_main_last_output_policy_wins_and_resume_keeps_safe_symlink(self):
        with tempfile.TemporaryDirectory(prefix='mesh-main-output-link-') as temporary:
            output = Path(temporary) / 'output'
            output.mkdir()
            previous = output / 'previous.bin'
            previous.write_bytes(b'previous build')
            link = Path(temporary) / 'output-link'
            link.symlink_to(output, target_is_directory=True)
            result = self.run_main(link, 'Heltec_mesh_solar_companion_radio_usb', '--standard',
                                   '--clean', '--resume')
            self.assert_main_passed(result)
            self.assertTrue(link.is_symlink())
            self.assertEqual(previous.read_bytes(), b'previous build')

    def test_historical_main_resume_override_reproduces_artifact_loss(self):
        with tempfile.TemporaryDirectory(prefix='mesh-main-output-negative-') as temporary:
            output = Path(temporary) / 'output'
            output.mkdir()
            previous = output / 'qualified-image.bin'
            previous.write_bytes(b'already qualified build')
            result = self.run_main(output, 'Heltec_mesh_solar_companion_radio_usb', '--standard',
                                   '--resume', old_resume_bug=True)
            self.assert_main_passed(result)
            self.assertFalse(previous.exists(), 'negative control must expose the historical deletion')

    def test_safe_parent_symlink_keeps_link_and_other_outputs(self):
        with tempfile.TemporaryDirectory(prefix='mesh-build-output-safety-') as temporary:
            directory = Path(temporary)
            physical = directory/'physical'; physical.mkdir()
            output = physical/'output'; output.mkdir()
            (output/'old.bin').write_bytes(b'old isolated diagnostic artifact')
            sibling = physical/'keep.bin'; sibling.write_bytes(b'keep sibling')
            link = directory/'parent-link'; link.symlink_to(physical, target_is_directory=True)
            result = self.prepare(link/'output')
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue(link.is_symlink())
            self.assertTrue(output.is_dir())
            self.assertEqual(list(output.iterdir()), [])
            self.assertEqual(sibling.read_bytes(), b'keep sibling')

    def test_existing_regular_files_are_preserved_and_rejected(self):
        with tempfile.TemporaryDirectory(prefix='mesh-build-output-safety-') as temporary:
            path = Path(temporary)/'not-a-build-directory'
            path.write_bytes(b'user data')
            for resume in (False, True):
                self.assert_rejected_without_mutation(path, resume=resume)
                self.assertEqual(path.read_bytes(), b'user data')

    def test_delete_and_mkdir_failures_abort_before_build_can_continue(self):
        with tempfile.TemporaryDirectory(prefix='mesh-build-output-safety-') as temporary:
            output = Path(temporary)/'output'; output.mkdir()
            (output/'previous.bin').write_bytes(b'previous isolated diagnostic artifact')
            result = self.prepare(output, overrides=r'''
rm() { printf 'FAILED_DELETE\n'; return 67; }
mkdir() { printf 'SHOULD_NOT_MKDIR\n'; }
''')
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('FAILED_DELETE', result.stdout)
            self.assertNotIn('SHOULD_NOT_MKDIR', result.stdout)
            self.assertTrue((output/'previous.bin').exists())
            result = self.prepare(output, resume=True, overrides='mkdir() { return 73; }')
            self.assertNotEqual(result.returncode, 0)
            self.assertTrue((output/'previous.bin').exists())

if __name__ == '__main__':
    unittest.main()
