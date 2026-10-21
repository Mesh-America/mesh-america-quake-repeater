"""Read-only capability fallback for deployed adaptive storage diagnostics."""

import argparse
import contextlib
import io
import unittest
from unittest import mock

import lora_ota as ota


class AdaptiveBootloaderCapsTests(unittest.TestCase):
    prefix = "self body=100 image=156 base_hash=0011223344556677 | maxblk:2048 | "

    def fixture(self, hw="RAK_3401", storage="internal", auto=False, **overrides):
        if hw == "Heltec_tower_v2":
            board, name, caps = 0x239A0071, "TOWER_V2_OTA", 0x09
            tail = f"store:{storage} | bootloader:apply OK"
        else:
            family = "3401" if hw == "RAK_3401" else "4631"
            board = 0x239A0029
            name = family + ("_AUTO_DFU" if auto else "_DFU")
            caps = 0x1E if auto else 0x0A
            tail = {
                "internal": "internal store:252K | bootloader: delta apply OK",
                "QSPI": "QSPI store:2048K | bootloader: QSPI apply OK",
                "SD": "SD store | bootloader: authenticated SD apply OK",
            }[storage]
        replies = {
            "ota status": (
                f"OTA | this fw 00112233 (100K) hw={hw} | target:1234ABCD | "
                f"maxblk:2048 | bl:{storage} blrc:00 | no download"
            ),
            "get bootloader.ver": "> OTAFIX2.4.11-preview.126",
            "ota self": self.prefix + tail,
            "ota bootloader status": self.boot_reply(board, name, caps),
            "ota stats": "OTA | fw v1.18.0.1",
        }
        replies.update(overrides)
        controller = mock.Mock()

        def remote(_target, command, **kwargs):
            value = replies[command]  # Any mutating or unexpected command fails.
            if command == "ota bootloader status":
                self.assertIs(kwargs.get("retry"), False)
            if isinstance(value, Exception):
                raise value
            return value

        controller.remote_command.side_effect = remote
        return controller

    @staticmethod
    def boot_reply(board=0x239A0029, name="3401_DFU", caps=0x0A, abi=3):
        target = ota.bootloader_library().bootloader_target_id(board, name)
        return (
            f"BL board={board:08X} target={target:08X} name={name} "
            f"crc=12345678 abi={abi} caps={caps:02X} | staged:none mid=- hash=-"
        )

    def query(self, controller, package_kind="application"):
        with contextlib.redirect_stdout(io.StringIO()) as output:
            result = ota.query_target(
                controller, argparse.Namespace(target="remote", package_kind=package_kind)
            )
        return result, output.getvalue()

    def test_adaptive_rak_internal_qspi_and_sd(self):
        for hw in ("RAK_3401", "RAK4631"):
            for storage in ("internal", "QSPI", "SD"):
                if hw == "RAK_3401" and storage == "SD":
                    continue
                for auto in (False, True):
                    with self.subTest(hw=hw, storage=storage, auto=auto):
                        controller = self.fixture(hw, storage, auto)
                        result, log = self.query(controller)
                        self.assertEqual(result.bootloader_abi, 3)
                        self.assertEqual(result.bootloader_codecs, 0x5)
                        self.assertEqual(result.nrf_sd, storage == "SD")
                        self.assertEqual(result.nrf_qspi, storage == "QSPI")
                        self.assertIsNone(result.boot_target_id)
                        self.assertIn("guaranteed codec subset 0x5", log)
                        self.assertIn("storage flags are independent", log)
                        self.assertEqual(
                            sum(c.args[1] == "ota bootloader status"
                                for c in controller.remote_command.call_args_list), 1,
                        )

    def test_adaptive_tower_sd_and_internal(self):
        for storage in ("SD", "internal"):
            with self.subTest(storage=storage):
                result, _ = self.query(self.fixture("Heltec_tower_v2", storage))
                self.assertEqual(result.bootloader_abi, 3)
                self.assertEqual(result.bootloader_codecs, 5)
                self.assertEqual(result.nrf_sd, storage == "SD")

    def test_direct_fields_remain_authoritative_without_fallback(self):
        controller = self.fixture(**{
            "ota self": self.prefix + "bootloader: apply OK (abi=2 codecs=0x4)",
            "ota bootloader status": AssertionError("unexpected fallback"),
        })
        result, log = self.query(controller)
        self.assertEqual((result.bootloader_abi, result.bootloader_codecs), (2, 4))
        self.assertNotIn("guaranteed codec subset", log)
        self.assertNotIn("ota bootloader status", [
            c.args[1] for c in controller.remote_command.call_args_list
        ])

    def test_guaranteed_subset_never_substitutes_for_bootloader_exact_mask(self):
        controller = self.fixture()
        with self.assertRaisesRegex(ota.OtaError, "bootloader packages require a directly reported"):
            self.query(controller, package_kind="bootloader")
        self.assertNotIn("ota bootloader status", [
            c.args[1] for c in controller.remote_command.call_args_list
        ])

    def test_generic_or_malformed_missing_fields_are_not_inferred(self):
        tails = (
            "bootloader: apply OK", "bootloader: SD apply OK",
            "internal store:252K | bootloader: delta apply OK (abi=bad codecs=0x5)",
            "internal store:252K | bootloader: delta apply OK extra",
            "internal store:0K | bootloader: delta apply OK",
            "internal store:252K | bootloader: NO delta apply",
            "storage unsafe: unavailable",
        )
        for tail in tails:
            with self.subTest(tail=tail):
                controller = self.fixture(**{"ota self": self.prefix + tail})
                with self.assertRaisesRegex(ota.OtaError, "ABI and codec mask.*upgrade the application"):
                    self.query(controller)
                self.assertNotIn("ota bootloader status", [
                    c.args[1] for c in controller.remote_command.call_args_list
                ])

    def test_hardware_and_storage_views_must_agree(self):
        for status in (
            "OTA | hw=RAK_3401 | target:1234ABCD | maxblk:2048 | bl:QSPI blrc:00",
            "OTA | hw=RAK_3401 hw=RAK4631 | target:1234ABCD | maxblk:2048 | bl:internal",
            "OTA | hw=RAK_3401 | target:1234ABCD | maxblk:2048 | bl:internal bl:QSPI",
        ):
            with self.subTest(status=status):
                with self.assertRaisesRegex(ota.OtaError, "conflicting hardware/storage"):
                    self.query(self.fixture(**{"ota status": status}))
        with self.assertRaisesRegex(ota.OtaError, "upgrade the application"):
            self.query(self.fixture(**{
                "ota status": "OTA | hw=OtherBoard | target:1234ABCD | maxblk:2048 | bl:internal",
            }))

    def test_unavailable_or_malformed_status_remains_failure(self):
        valid = self.boot_reply()
        for reply in (
            "Unknown command",
            "Bootloader update unavailable: installed embedded manifest/CRC is invalid",
            ota.TransmissionError("missing reply"),
            valid[:-1], valid + " unexpected", valid + "\n" + valid,
            valid.replace("staged:none mid=- hash=-", "staged:none mid=12345678 hash=-"),
            valid.replace("staged:none mid=- hash=-", "staged:ready mid=- hash=-"),
            valid.replace("crc=12345678", "crc=00000000"),
            valid.replace("crc=12345678", "crc=FFFFFFFF"),
        ):
            with self.subTest(reply=reply):
                with self.assertRaisesRegex(ota.OtaError, "upgrade the application"):
                    self.query(self.fixture(**{"ota bootloader status": reply}))

    def test_bootloader_identity_abi_and_primary_profile_are_checked(self):
        valid = self.boot_reply()
        for reply in (
            valid.replace("target=23818A80", "target=00000000"),
            self.boot_reply(board=0x239A0071, name="TOWER_V2_OTA", caps=9),
            self.boot_reply(name="4631_DFU"),
            self.boot_reply(name="OTHER_DFU"),
            self.boot_reply(abi=2), self.boot_reply(abi=65535),
            self.boot_reply(caps=4), self.boot_reply(caps=9),
            self.boot_reply(caps=0x1E), self.boot_reply(caps=0xFF),
        ):
            with self.subTest(reply=reply):
                with self.assertRaisesRegex(ota.OtaError, "upgrade the application"):
                    self.query(self.fixture(**{"ota bootloader status": reply}))

    def test_missing_version_does_not_replace_live_status_validation(self):
        for version in ("> unknown", "Unknown command", ota.OtaError("optional unavailable")):
            with self.subTest(version=version):
                result, _ = self.query(self.fixture(**{"get bootloader.ver": version}))
                self.assertEqual(result.bootloader_codecs, 5)
                with self.assertRaisesRegex(ota.OtaError, "upgrade the application"):
                    self.query(self.fixture(**{
                        "get bootloader.ver": version,
                        "ota bootloader status": "Unknown command",
                    }))


if __name__ == "__main__":
    unittest.main()
