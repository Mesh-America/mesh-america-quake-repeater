"""Opt-in real wheel installation test, isolated from system packages and radios.

Set MOTA_CRYPTO_INSTALL_TEST=1 to allow PyPI downloads into a temporary test cache.
"""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from test_lora_ota_bootloader import boot_blob


CHILD = r'''
import importlib.util
from pathlib import Path
import sys
from unittest import mock

sys.path.insert(0, sys.argv[1])
import lora_ota as ota
root, package, mode = Path(sys.argv[2]), Path(sys.argv[3]), sys.argv[4]
assert importlib.util.find_spec("cryptography") is None, "venv must start without crypto"
args = ota.build_parser().parse_args([str(package), "remote", "--no-install"])
with (
    mock.patch.object(ota, "cryptography_repair_root", return_value=root),
    mock.patch.object(ota.sys.stdin, "isatty", return_value=True),
    mock.patch("builtins.input", return_value="yes") as approval,
    mock.patch.object(ota, "check_bootloader_tool"),
    mock.patch.object(ota, "require_meshcli_version"),
    mock.patch.object(ota, "Controller") as controller,
    mock.patch.object(ota, "source_cli_command") as source,
):
    if mode == "install":
        ota.preflight_inputs(args)
        approval.assert_called_once()
    else:
        with mock.patch.object(ota.subprocess, "run", side_effect=AssertionError("cache must not reinstall")):
            ota.preflight_inputs(args)
        approval.assert_not_called()
    controller.assert_not_called()
    source.assert_not_called()
import cryptography
assert Path(cryptography.__file__).is_relative_to(root)
assert cryptography.__version__ == ota.CRYPTOGRAPHY_REPAIR_REQUIREMENT.split("==")[1]
assert args.package_kind == "bootloader"
bad = bytearray(package.read_bytes())
bad[137] ^= 1
try:
    ota.parse_mota(bytes(bad))
except ota.OtaError as exc:
    assert "invalid bootloader mOTA" in str(exc), str(exc)
else:
    raise AssertionError("tampered signature was accepted")
print("REAL CRYPTO REPAIR OK:", mode)
'''


@unittest.skipUnless(os.environ.get("MOTA_CRYPTO_INSTALL_TEST") == "1", "opt-in PyPI wheel download")
class CryptoInstallIntegrationTests(unittest.TestCase):
    def test_clean_venv_installs_then_new_process_reuses_cache(self):
        with tempfile.TemporaryDirectory(prefix="meshcore-crypto-install-test-") as directory:
            folder = Path(directory)
            environment = folder / "venv"
            child_env = os.environ.copy()
            child_env.pop("MESHCORE_ADMIN_PASSWORD", None)
            subprocess.run(
                [sys.executable, "-m", "venv", str(environment)],
                env=child_env, check=True, timeout=120,
            )
            python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
            package = folder / "boot.mota"
            package.write_bytes(boot_blob())
            for mode in ("install", "reuse"):
                result = subprocess.run(
                    [str(python), "-I", "-c", CHILD, str(Path(__file__).parent.resolve()),
                     str(folder / "private-crypto"), str(package), mode],
                    env=child_env, check=False, timeout=660, text=True,
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                )
                self.assertEqual(result.returncode, 0, result.stdout)
                self.assertIn("REAL CRYPTO REPAIR OK: " + mode, result.stdout)


if __name__ == "__main__":
    unittest.main()
