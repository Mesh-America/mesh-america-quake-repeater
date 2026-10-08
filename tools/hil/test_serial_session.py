"""Verify the shared serial opener keeps optional SDK dependencies optional."""
from pathlib import Path
import ast
import hashlib
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest


class SerialSessionImportTests(unittest.TestCase):
    def test_immutable_collectors_require_only_their_shipped_dependencies(self):
        base = Path(__file__).parent
        fixture_names = ("profile_pair.py", "profile_pair_run.py", "profile_four_tx_fixture.py",
                         "profile_switch.py", "profile_switch_channels.py",
                         "profile_switch_packets.py", "profile_switch_sweep.py")
        for script, end in (("profile_pair_launch.py", "with (root/'collector.log')"),
                            ("profile_four_tx_repeat_run.py", "code=base64.b64decode")):
            source = (base / script).read_text()
            # Execute the actual dependency-selection and hash-validation
            # block, without launch, subprocess, firmware or output operations.
            block = source[source.index("dependencies="):source.index(end)]
            for current, helper in ((False, "absent"), (True, "valid"),
                                    (True, "absent"), (True, "tampered")):
                with self.subTest(script=script, current=current, helper=helper), TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    for name in fixture_names:
                        (root / name).write_text("")
                    (root / "profile_switch.py").write_text(
                        "from serial_session import open_configured_session\n" if current else "# Legacy snapshot\n")
                    if helper != "absent":
                        (root / "serial_session.py").write_text("# Shipped helper\n")
                    manifest = {"files": {file.name: {"sha256": hashlib.sha256(file.read_bytes()).hexdigest()}
                                          for file in root.iterdir()}}
                    if helper == "tampered":
                        (root / "serial_session.py").write_text("# Changed after packaging\n")
                    namespace = dict(root=root, previous=root, manifest=manifest,
                                     ast=ast, hashlib=hashlib)
                    if current and helper == "absent":
                        with self.assertRaises(FileNotFoundError):
                            exec(block, namespace)
                    elif helper == "tampered":
                        with self.assertRaises(RuntimeError):
                            exec(block, namespace)
                    else:
                        exec(block, namespace)
                        self.assertEqual("serial_session.py" in namespace["dependencies"], current)

    def test_helpers_import_with_only_the_standard_library(self):
        # -S removes installed site packages. The companion/FEM/soak modules
        # must remain importable until their caller actually requests serial.
        program = ("import sys; sys.path.insert(0, " + repr(str(Path(__file__).parent)) + "); "
                   "import serial_session, esp32_companion_serial_stress, "
                   "fem_noise_floor_test, s3_memory_soak; "
                   "assert 'serial' not in sys.modules")
        result = subprocess.run([sys.executable, "-I", "-S", "-c", program],
                                text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
