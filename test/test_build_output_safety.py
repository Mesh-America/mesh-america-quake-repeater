"""Reject dangerous cleanup paths without touching any existing build output."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class Tests(unittest.TestCase):
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
