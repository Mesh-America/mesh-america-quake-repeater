#!/usr/bin/env python3
"""Execute the bounded login history and its radio-safe CLI formatter."""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "test/fixtures/login_history/test_login_history.cpp"


class LoginHistoryTest(unittest.TestCase):
    def test_history_and_pages(self):
        compiler = shutil.which("g++") or shutil.which("clang++")
        if compiler is None:
            self.skipTest("a host C++ compiler is required")
        with tempfile.TemporaryDirectory(prefix="meshcore-login-history-") as directory:
            binary = Path(directory) / "login-history.exe"
            sanitizers = ([] if os.name == "nt" else [
                "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
                "-fno-omit-frame-pointer", "-fno-pie", "-no-pie",
            ])
            compiled = subprocess.run([
                compiler, "-std=c++11", "-Wall", "-Wextra", "-Werror", *sanitizers,
                "-I" + str(ROOT / "src"), str(FIXTURE), "-o", str(binary),
            ], capture_output=True, text=True, timeout=60)
            self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
            checked = subprocess.run([str(binary)], capture_output=True, text=True, timeout=15)
            self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
            self.assertIn("10 login history checks passed", checked.stdout)


if __name__ == "__main__":
    unittest.main()
