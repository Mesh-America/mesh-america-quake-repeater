#!/usr/bin/env python3
"""Exercise the nRF52 HEX post-build hook with the installed build dependencies."""

from contextlib import redirect_stdout
import importlib.util
import io
from pathlib import Path
import sys
import tempfile
import unittest

from intelhex import IntelHex


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "mota"))
import motalib as ml  # noqa: E402


class BuildEnvironment(dict):
    def __init__(self, app_base):
        super().__init__(
            PROJECT_DIR=str(ROOT),
            PIOENV="nrf52_sensor_hex_test",
            CPPDEFINES=[
                "ENABLE_OTA", "NRF52_PLATFORM",
                ("FIRMWARE_VERSION", "v1.17.1.9"),
                ("MOTA_TARGET_ID", "0x12345678"),
                ("MOTA_HW_ID", "NRF52_TEST"),
            ],
        )
        self.app_base = app_base
        self.post_actions = {}

    def AddPostAction(self, target, action):
        self.post_actions[target] = action

    def BoardConfig(self):
        return {"upload.maximum_size": ml.NRF52_APP_END - self.app_base}

    def GetProjectOption(self, name, default=""):
        if name in ("build_src_filter", "src_filter"):
            return "+<examples/simple_sensor>"
        return default


class Nrf52EndfHexTests(unittest.TestCase):
    def test_hex_hook_appends_valid_identity_and_preserves_other_segments(self):
        for app_base in (ml.NRF52_APP_BASE_S140_V6, ml.NRF52_APP_BASE_S140_V7):
            with self.subTest(app_base=hex(app_base)), tempfile.TemporaryDirectory() as tmp:
                env = BuildEnvironment(app_base)
                spec = importlib.util.spec_from_file_location(
                    "nrf52_endf_hex_test", ROOT / "tools" / "mota" / "pio_endf.py")
                module = importlib.util.module_from_spec(spec)
                module.Import = lambda _name: None
                module.env = env
                spec.loader.exec_module(module)
                action = env.post_actions["$BUILD_DIR/${PROGNAME}.hex"]

                path = Path(tmp) / "firmware.hex"
                firmware = bytes(range(256))
                uicr_base = 0x10001080
                uicr = b"\x12\x34\x56\x78"
                original = IntelHex()
                original.frombytes(firmware, offset=app_base)
                original.frombytes(uicr, offset=uicr_base)
                original.write_hex_file(str(path))

                with redirect_stdout(io.StringIO()):
                    action([], [path], env)
                result = IntelHex(str(path))
                segments = result.segments()
                self.assertEqual(len(segments), 2)
                self.assertEqual(segments[0], (
                    app_base, app_base + len(firmware) + ml.NRF52_LAYOUT_LEN + ml.ENDF_LEN))
                image = bytes(result.tobinarray(start=app_base, end=segments[0][1] - 1))
                self.assertEqual(image[:len(firmware)], firmware)
                self.assertEqual(bytes(result.tobinarray(
                    start=uicr_base, size=len(uicr))), uicr)
                self.assertTrue(ml.has_endf(image))
                self.assertEqual(ml.parse_endf_ident(image), ml.FwIdent(
                    ml.pack_version("1.17.1.9"), 0x12345678, "NRF52_TEST"))
                self.assertEqual(ml.parse_nrf52_layout(image), ml.Nrf52Layout(
                    app_base, ml.NRF52_APP_END, ml.NRF52_APP_END))

                first_pass = path.read_bytes()
                with redirect_stdout(io.StringIO()):
                    action([], [path], env)
                self.assertEqual(path.read_bytes(), first_pass)


if __name__ == "__main__":
    unittest.main()
