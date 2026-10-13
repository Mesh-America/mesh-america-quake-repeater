"""Fail-closed lab-tool tests. No real ports, sudo, flashing or radio access."""
from contextlib import redirect_stdout
import copy
import importlib.util
import io
import json
from pathlib import Path
import stat
import struct
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch
import warnings
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.hil import verified_nrf_flash as guard

serial_stub = types.ModuleType("serial")
serial_tools_stub = types.ModuleType("serial.tools")
serial_tools_stub.list_ports = types.SimpleNamespace(comports=Mock(return_value=[]))
serial_stub.Serial = Mock()
with patch.dict(sys.modules, {"serial": serial_stub, "serial.tools": serial_tools_stub}):
    spec = importlib.util.spec_from_file_location("morse_inventory_safety", ROOT / "tools/hil/morse_pi_inventory.py")
    inventory_tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(inventory_tool)


class InventorySafetyTests(unittest.TestCase):
    def setUp(self):
        self.port_info = types.SimpleNamespace(serial_number="9AB3B64C641BA927",
                                               device="/dev/ttyACM-test", interface="MeshCore")
        self.serial_factory = Mock()
        self.comports = Mock(return_value=[self.port_info])
        self.serial_patch = patch.object(inventory_tool.serial, "Serial", self.serial_factory)
        self.ports_patch = patch.object(inventory_tool.list_ports, "comports", self.comports)
        self.serial_patch.start()
        self.ports_patch.start()
        self.addCleanup(self.serial_patch.stop)
        self.addCleanup(self.ports_patch.stop)

    @staticmethod
    def result(command, rc=0, out="", err=""):
        return subprocess.CompletedProcess(command, rc, out, err)

    def run_inventory(self, sudo=None, fuser=None):
        commands = []

        def execute(command, **kwargs):
            commands.append(command)
            selected = sudo if command == ["sudo", "-n", "true"] else fuser if "fuser" in command else None
            if isinstance(selected, Exception):
                raise selected
            return selected or self.result(command)

        with patch.object(inventory_tool.subprocess, "run", side_effect=execute), redirect_stdout(io.StringIO()) as output:
            status = inventory_tool.main()
        return status, commands, [json.loads(line) for line in output.getvalue().splitlines()]

    def test_sudo_refusal_timeout_and_missing_binary_never_enumerate_or_open(self):
        for failure in (self.result([], 1, err="sudo denied"),
                        subprocess.TimeoutExpired("sudo", 15), OSError("sudo missing")):
            with self.subTest(failure=failure):
                self.comports.reset_mock()
                status, commands, records = self.run_inventory(sudo=failure)
                self.assertEqual(status, 1)
                self.comports.assert_not_called()
                self.serial_factory.assert_not_called()
                self.assertFalse(any("fuser" in command for command in commands))
                self.assertTrue(records)

    def test_only_explicit_clean_fuser_no_users_result_allows_access(self):
        for rc, out, err, expected in ((0, "1234", "", False), (0, "", "", False),
                                       (1, "", "", True), (1, " \n", "\n", True)):
            with self.subTest(rc=rc, out=out, err=err):
                with patch.object(inventory_tool.subprocess, "run", return_value=self.result([], rc, out, err)) as call:
                    self.assertIs(inventory_tool.port_is_unowned("/dev/test"), expected)
                self.assertEqual(call.call_args.args[0], ["sudo", "-n", "fuser", "/dev/test"])
        for rc, out, err in ((1, "1234", ""), (1, "", "permission denied"),
                             (2, "", ""), (127, "", "fuser missing"), (-9, "", "")):
            with self.subTest(rc=rc, out=out, err=err):
                with patch.object(inventory_tool.subprocess, "run", return_value=self.result([], rc, out, err)):
                    with self.assertRaisesRegex(RuntimeError, "Cannot verify"):
                        inventory_tool.port_is_unowned("/dev/test")

    def test_uncertain_fuser_and_busy_ports_never_construct_a_serial_port(self):
        for failure in (self.result([], 1, err="sudo denied"), self.result([], 2),
                        self.result([], 127, err="fuser missing"),
                        subprocess.TimeoutExpired("fuser", 10), OSError("fuser missing")):
            with self.subTest(failure=failure):
                status, _, records = self.run_inventory(fuser=failure)
                self.assertEqual(status, 1)
                self.serial_factory.assert_not_called()
                self.assertTrue(records[-1]["refused"])
        status, _, records = self.run_inventory(fuser=self.result([], 0))
        self.assertEqual(status, 0)
        self.serial_factory.assert_not_called()
        self.assertTrue(records[-1]["busy"])

    def test_unreviewed_and_logging_interfaces_are_never_probed(self):
        self.comports.return_value = [types.SimpleNamespace(serial_number="UNKNOWN", device="/dev/other", interface="MeshCore"),
                                      types.SimpleNamespace(serial_number="9AB3B64C641BA927", device="/dev/log", interface="MeshCore Logging")]
        status, commands, _ = self.run_inventory()
        self.assertEqual(status, 0)
        self.assertFalse(any("fuser" in command for command in commands))
        self.serial_factory.assert_not_called()

    def test_verified_free_port_uses_exclusive_access_and_confirmed_terminal(self):
        port = Mock()
        self.serial_factory.return_value = port
        with patch.object(inventory_tool, "read_quiet", side_effect=["", "WELCOME test", *["OK"] * 6]):
            status, _, _ = self.run_inventory(fuser=self.result([], 1))
        self.assertEqual(status, 0)
        self.assertTrue(self.serial_factory.call_args.kwargs["exclusive"])
        port.open.assert_called_once_with()
        port.close.assert_called_once_with()
        self.assertEqual([item.args[0] for item in port.write.call_args_list],
                         [b"+++MESHCORE-TERM-START\n", b"ver\n", b"board\n", b"get name\n",
                          b"get radio\n", b"get tx\n", b"get radio2.status\n", b"+++MESHCORE-TERM-STOP\n"])

    def test_failed_terminal_entry_sends_no_commands_and_closes_port(self):
        port = Mock()
        self.serial_factory.return_value = port
        with patch.object(inventory_tool, "read_quiet", side_effect=["", "binary mode"]):
            status, _, records = self.run_inventory(fuser=self.result([], 1))
        self.assertEqual(status, 1)
        self.assertTrue(records[-1]["refused"])
        self.assertEqual([item.args[0] for item in port.write.call_args_list], [b"+++MESHCORE-TERM-START\n"])
        port.close.assert_called_once_with()

    def test_terminal_stop_failure_still_closes_port(self):
        port = Mock()
        port.write.side_effect = lambda data: (_ for _ in ()).throw(OSError("USB vanished")) if b"TERM-STOP" in data else None
        self.serial_factory.return_value = port
        with patch.object(inventory_tool, "read_quiet", side_effect=["", "WELCOME test", *["OK"] * 6]):
            with self.assertRaisesRegex(OSError, "USB vanished"):
                self.run_inventory(fuser=self.result([], 1))
        port.close.assert_called_once_with()


class ApplicationZipSafetyTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.application = {"bin_file": "firmware.bin", "dat_file": "firmware.dat",
                            "init_packet_data": {"device_type": 82, "softdevice_req": [182]}}
        self.document = {"manifest": {"application": self.application, "dfu_version": 0.5}}

    def make_zip(self, document=None, entries=None, raw_manifest=None, name="RAK_4631_companion-test.zip"):
        artifact = self.root / name
        body = raw_manifest if raw_manifest is not None else json.dumps(document or self.document).encode()
        selected = [("manifest.json", body), ("firmware.bin", b"application bytes"), ("firmware.dat", b"init bytes")]
        with warnings.catch_warnings(), zipfile.ZipFile(artifact, "w", compression=zipfile.ZIP_DEFLATED) as package:
            warnings.simplefilter("ignore", UserWarning)
            for member, data in selected if entries is None else entries:
                package.writestr(member, data)
        return artifact

    def test_current_legacy_and_minimal_application_packages_are_accepted(self):
        self.assertEqual(guard.verify_application_zip(self.make_zip()), ("firmware.bin", "firmware.dat"))
        self.assertEqual(guard.verify_application_zip(self.make_zip({"manifest": {"application": {
            "bin_file": "firmware.bin", "dat_file": "firmware.dat"}}})), ("firmware.bin", "firmware.dat"))

    def test_any_bootloader_softdevice_or_unknown_component_is_refused_even_if_null(self):
        for component in ("bootloader", "softdevice", "softdevice_bootloader", "unknown"):
            for value in (None, {"bin_file": "firmware.bin", "dat_file": "firmware.dat"}):
                document = copy.deepcopy(self.document)
                document["manifest"][component] = value
                with self.subTest(component=component, value=value), self.assertRaisesRegex(ValueError, "forbids"):
                    guard.verify_application_zip(self.make_zip(document))

    def test_missing_malformed_ambiguous_manifest_objects_are_refused(self):
        for document in ([], {"other": {}}, {"manifest": []}, {"manifest": {}},
                         {"manifest": {"application": None}}, {"manifest": {"application": []}},
                         {"manifest": {"application": {"bin_file": "firmware.bin"}}},
                         {"manifest": {"application": dict(self.application, sd_size=100)}}):
            with self.subTest(document=document), self.assertRaises(ValueError):
                guard.verify_application_zip(self.make_zip(raw_manifest=json.dumps(document).encode()))
        for raw in (b"not JSON", b"\xff", b'{"manifest":{"application":{},"application":{}}}',
                    b'{"manifest":{"application":{},"dfu_version":NaN}}'):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                guard.verify_application_zip(self.make_zip(raw_manifest=raw))

    def test_invalid_metadata_and_version_are_refused(self):
        for metadata in (None, [], "init"):
            document = copy.deepcopy(self.document)
            document["manifest"]["application"]["init_packet_data"] = metadata
            with self.subTest(metadata=metadata), self.assertRaisesRegex(ValueError, "metadata"):
                guard.verify_application_zip(self.make_zip(document))
        for version in (None, "0.5", [], True, 0, -1, float("inf")):
            document = copy.deepcopy(self.document)
            document["manifest"]["dfu_version"] = version
            with self.subTest(version=version), self.assertRaises(ValueError):
                guard.verify_application_zip(self.make_zip(document))

    def test_application_references_must_be_safe_existing_root_bin_and_dat_files(self):
        for key in ("bin_file", "dat_file"):
            for name in (None, [], "", "../firmware.bin", "folder/firmware.bin", r"folder\firmware.bin",
                         "/firmware.bin", "C:firmware.bin", "firmware.hex", "missing.bin"):
                document = copy.deepcopy(self.document)
                document["manifest"]["application"][key] = name
                with self.subTest(key=key, name=name), self.assertRaises(ValueError):
                    guard.verify_application_zip(self.make_zip(document))

    def test_extra_duplicate_missing_empty_and_oversized_members_are_refused(self):
        body = json.dumps(self.document).encode()
        good = [("manifest.json", body), ("firmware.bin", b"app"), ("firmware.dat", b"init")]
        for entries in (good + [("bootloader.bin", b"boot")], good + [("firmware.bin", b"duplicate")],
                        good[:2], good[1:], [good[0], ("other.bin", b"app"), good[2]],
                        [good[0], ("firmware.bin", b""), good[2]],
                        [good[0], good[1], ("firmware.dat", b"")],
                        [good[0], ("firmware.bin", b"x" * (1024 * 1024 + 1)), good[2]],
                        [good[0], good[1], ("firmware.dat", b"x" * 65537)]):
            with self.subTest(members=[entry[0] for entry in entries]), self.assertRaises(ValueError):
                guard.verify_application_zip(self.make_zip(entries=entries))

    def test_symlink_directory_encryption_and_unsupported_compression_are_refused(self):
        body = json.dumps(self.document).encode()
        for kind in (stat.S_IFLNK, stat.S_IFDIR, stat.S_IFIFO, stat.S_IFCHR):
            special = zipfile.ZipInfo("firmware.bin")
            special.create_system = 3
            special.external_attr = (kind | 0o777) << 16
            with self.subTest(kind=kind), self.assertRaisesRegex(ValueError, "unsafe"):
                guard.verify_application_zip(self.make_zip(entries=[("manifest.json", body), (special, b"target"), ("firmware.dat", b"init")]))
        with self.assertRaisesRegex(ValueError, "unsafe"):
            guard.verify_application_zip(self.make_zip(entries=[("manifest.json", body), ("folder/", b"folder"), ("firmware.dat", b"init")]))
        for property_name, value in (("flag_bits", 1), ("compress_type", zipfile.ZIP_BZIP2)):
            artifact = self.make_zip()
            with zipfile.ZipFile(artifact) as package:
                members = package.infolist()
            setattr(members[1], property_name, value)
            fake_package = Mock()
            fake_package.__enter__ = Mock(return_value=fake_package)
            fake_package.__exit__ = Mock(return_value=False)
            fake_package.infolist.return_value = members
            with self.subTest(property=property_name), patch.object(guard.zipfile, "ZipFile", return_value=fake_package):
                with self.assertRaisesRegex(ValueError, "unsafe"):
                    guard.verify_application_zip(artifact)
            fake_package.read.assert_not_called()

    def test_corrupt_zip_and_bin_crc_are_refused(self):
        artifact = self.root / "bad.zip"
        artifact.write_bytes(b"not a ZIP")
        with self.assertRaisesRegex(ValueError, "unreadable"):
            guard.verify_application_zip(artifact)
        artifact = self.make_zip()
        with zipfile.ZipFile(artifact) as package:
            entry = package.getinfo("firmware.bin")
        data = bytearray(artifact.read_bytes())
        filename_size, extra_size = struct.unpack_from("<HH", data, entry.header_offset + 26)
        data[entry.header_offset + 30 + filename_size + extra_size] ^= 0xFF
        artifact.write_bytes(data)
        with self.assertRaises(ValueError):
            guard.verify_application_zip(artifact)

    def cli_arguments(self, artifact):
        inventory = self.root / "inventory.json"
        inventory.write_text(json.dumps({"devices": {"ABC": {"board": "Test Board",
                             "firmware_prefixes": ["RAK_4631"], "bootloader_prefixes": ["RAK_4631"]}}}))
        return ["--inventory", str(inventory), "--serial", "ABC", "--board", "Test Board",
                "--artifact", str(artifact), "--port", "/dev/test"]

    def test_invalid_application_package_is_rejected_before_any_port_query(self):
        document = copy.deepcopy(self.document)
        document["manifest"]["bootloader"] = {"bin_file": "firmware.bin", "dat_file": "firmware.dat"}
        args = self.cli_arguments(self.make_zip(document)) + ["--application-only"]
        with patch.object(guard, "verify_port") as port, redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit) as error:
                guard.main(args)
        self.assertEqual(error.exception.code, 1)
        port.assert_not_called()

    def test_cli_validates_application_before_port_and_default_mode_stays_compatible(self):
        args = self.cli_arguments(self.make_zip())
        sequence = []
        with patch.object(guard, "verify_application_zip", side_effect=lambda artifact: sequence.append("ZIP")), \
             patch.object(guard, "verify_port", side_effect=lambda port, serial: sequence.append("port")), \
             redirect_stdout(io.StringIO()):
            guard.main(args + ["--application-only"])
        self.assertEqual(sequence, ["ZIP", "port"])
        artifact = self.make_zip({"manifest": {"bootloader": {"bin_file": "firmware.bin", "dat_file": "firmware.dat"}}},
                                 name="RAK_4631_bootloader-test.zip")
        with patch.object(guard, "verify_application_zip") as validation, patch.object(guard, "verify_port") as port, \
             redirect_stdout(io.StringIO()):
            guard.main(self.cli_arguments(artifact))
        validation.assert_not_called()
        port.assert_called_once_with("/dev/test", "ABC")

    def test_bash_adapter_requires_application_only_gate_before_port_or_flash(self):
        source = (ROOT / "tools/hil/morse_nrf_flash.sh").read_text()
        self.assertIn("set -euo pipefail", source)
        gate = source.index('--application-only')
        self.assertLess(gate, source.index('morse_assert_unowned "$bench_port"'))
        self.assertLess(gate, source.index('sha256sum -- "$bench_image"'))
        self.assertLess(gate, source.index('run_nrf52_dfu_package_buttonless "$bench_image"'))


if __name__ == "__main__":
    unittest.main()
