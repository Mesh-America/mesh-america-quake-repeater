"""Deferred RAK application storage is prepared once, with identity binding."""

import argparse
import contextlib
import io
import unittest
from unittest import mock

import lora_ota as ota


class ColdRakStorageTests(unittest.TestCase):
    def fixture(self, *, hw="RAK4631", storage="QSPI", direct=False,
                auto=True, initial_bl="storage-ERR", changes=None):
        prefix = "self body=100 image=156 base_hash=0011223344556677 | maxblk:2048"
        if direct:
            prefix += " abi=3 codecs=0x5"
        prefix += " | "
        tail = {
            "internal": "internal store:252K | bootloader: delta apply OK",
            "QSPI": "QSPI store:2048K | bootloader: QSPI apply OK",
            "SD": "SD store | bootloader: authenticated SD apply OK",
        }[storage]
        header = (
            f"OTA | this fw 00112233 (0K) hw={hw} | target:1234ABCD | "
            "maxblk:2048 | bl:"
        )
        name = ("3401" if hw == "RAK_3401" else "4631")
        name += "_AUTO_DFU" if auto else "_DFU"
        values = {
            "before_status": header + initial_bl + " blrc:00 | no download",
            "before_self": prefix + "storage unsafe: not probed",
            "boot_status": self.boot_reply(name=name, caps=0x1E if auto else 0x0A),
            "after_status": header + storage + " blrc:00 | no download",
            "after_self": prefix + tail,
        }
        for key, value in (changes or {}).items():
            values[key] = value(values[key]) if callable(value) else value
        status_replies = iter((values["before_status"], values["after_status"]))
        self_replies = iter((values["before_self"], values["after_self"]))
        controller = mock.Mock()

        def remote(_target, command, **kwargs):
            if command == "ota status":
                value = next(status_replies)
            elif command == "ota self":
                value = next(self_replies)
            elif command == "ota bootloader status":
                self.assertIs(kwargs.get("retry"), False)
                value = values["boot_status"]
            elif command == "get bootloader.ver":
                value = "> OTAFIX2.4.11-preview.126"
            elif command == "ota stats":
                value = "OTA | fw v1.18.0.1"
            else:
                raise AssertionError(f"unexpected or mutating command: {command}")
            if isinstance(value, Exception):
                raise value
            return value

        controller.remote_command.side_effect = remote
        return controller

    @staticmethod
    def boot_reply(board=0x239A0029, name="4631_AUTO_DFU", caps=0x1E,
                   abi=3, crc=0x12345678):
        target = ota.bootloader_library().bootloader_target_id(board, name)
        return (
            f"BL board={board:08X} target={target:08X} name={name} "
            f"crc={crc:08X} abi={abi} caps={caps:02X} | staged:none mid=- hash=-"
        )

    def query(self, controller, kind="application"):
        with contextlib.redirect_stdout(io.StringIO()) as output:
            result = ota.query_target(
                controller, argparse.Namespace(target="remote", package_kind=kind),
            )
        return result, output.getvalue()

    @staticmethod
    def commands(controller):
        return [call.args[1] for call in controller.remote_command.call_args_list]

    def test_old_and_complete_formats_prepare_all_known_rak_backends_once(self):
        for direct in (False, True):
            for hw in ("RAK_3401", "RAK4631"):
                for storage in ("internal", "QSPI", "SD"):
                    if hw == "RAK_3401" and storage == "SD":
                        continue
                    for auto in (False, True):
                        for initial_bl in ("NONE", "storage-ERR"):
                            with self.subTest(direct=direct, hw=hw, storage=storage,
                                              auto=auto, initial_bl=initial_bl):
                                controller = self.fixture(hw=hw, storage=storage, direct=direct,
                                                          auto=auto, initial_bl=initial_bl)
                                target, log = self.query(controller)
                                self.assertEqual(target.base_hash, bytes.fromhex("0011223344556677"))
                                self.assertEqual((target.hw_id, target.target_id), (hw, 0x1234ABCD))
                                self.assertEqual(target.max_block_size, 2048)
                                self.assertEqual((target.bootloader_abi, target.bootloader_codecs), (3, 5))
                                self.assertEqual(target.nrf_sd, storage == "SD")
                                self.assertEqual(target.nrf_qspi, storage == "QSPI")
                                self.assertIsNone(target.boot_target_id)
                                self.assertIn("running firmware identity unchanged", log)
                                self.assertEqual(self.commands(controller), [
                                    "ota status", "get bootloader.ver", "ota self",
                                    "ota bootloader status", "ota status", "ota self", "ota stats",
                                ])
                                for call in controller.remote_command.call_args_list[3:6]:
                                    self.assertIs(call.kwargs.get("retry"), False)

    def test_running_identity_and_geometry_are_bound_across_preparation(self):
        mutations = (
            ("after_self", "body=100", "body=101"),
            ("after_self", "image=156", "image=157"),
            ("after_self", "base_hash=0011223344556677", "base_hash=1011223344556677"),
            ("after_self", "maxblk:2048", "maxblk:1024"),
            ("after_status", "target:1234ABCD", "target:1234ABCE"),
            ("after_status", "hw=RAK4631", "hw=RAK_3401"),
            ("after_status", "maxblk:2048", "maxblk:1024"),
        )
        for direct in (False, True):
            for field, old, new in mutations:
                with self.subTest(direct=direct, field=field, new=new):
                    controller = self.fixture(direct=direct, changes={
                        field: lambda value, old=old, new=new: value.replace(old, new),
                    })
                    with self.assertRaises(ota.OtaError):
                        self.query(controller)
                    self.assertEqual(self.commands(controller).count("ota bootloader status"), 1)
                    self.assertNotIn("ota stats", self.commands(controller))

    def test_application_capabilities_cannot_change_or_conflict_with_live_abi(self):
        for field, old, new in (
            ("after_self", "abi=3", "abi=4"),
            ("after_self", "codecs=0x5", "codecs=0xD"),
            ("before_self", "abi=3", "abi=2"),
            ("before_self", "codecs=0x5", "codecs=0x1"),
        ):
            with self.subTest(field=field, new=new):
                changes = {field: lambda value, old=old, new=new: value.replace(old, new)}
                if field == "before_self":
                    changes["after_self"] = changes[field]
                with self.assertRaises(ota.OtaError):
                    self.query(self.fixture(direct=True, changes=changes))

    def test_initial_active_or_ambiguous_status_never_prepares(self):
        mutations = (
            lambda value: value.replace("no download", "download: downloading 1/9 id=12345678"),
            lambda value: value.replace("no download", "download: ready to install 9/9 id=12345678"),
            lambda value: value.replace("no download", "download: failed (hash) 1/9 id=12345678"),
            lambda value: value.replace("no download", "no download extra"),
            lambda value: value + " | no download",
            lambda value: value.replace("hw=RAK4631", "hw=RAK4631 hw=RAK4631"),
            lambda value: value + " | target:1234ABCD",
            lambda value: value + " | maxblk:2048",
            lambda value: value + " | bl:storage-ERR",
            lambda value: value.replace("bl:storage-ERR", "bl:QSPI"),
            lambda value: value.replace("hw=RAK4631", "hw=OtherBoard"),
            lambda value: value.replace("maxblk:2048", "maxblk:1024"),
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                controller = self.fixture(changes={"before_status": mutation})
                with self.assertRaises(ota.OtaError):
                    self.query(controller)
                self.assertNotIn("ota bootloader status", self.commands(controller))

    def test_post_preparation_must_still_be_idle_and_storage_views_agree(self):
        for mutation in (
            lambda value: value.replace("no download", "download: downloading 1/9 id=12345678"),
            lambda value: value.replace("bl:QSPI", "bl:internal"),
            lambda value: value.replace("bl:QSPI", "bl:NONE"),
        ):
            with self.subTest(mutation=mutation):
                with self.assertRaises(ota.OtaError):
                    self.query(self.fixture(changes={"after_status": mutation}))

    def test_unsafe_unsupported_unprepared_and_zero_capacity_results_are_refused(self):
        tails = (
            "storage unsafe: not probed", "storage unsafe: external NOR and OTAFIX bootloader do not match",
            "QSPI store:0K | bootloader: QSPI apply OK",
            "QSPI store:ERR 0K | bootloader: QSPI apply OK",
            "QSPI store:2048K | bootloader: NO QSPI apply",
            "internal store:0K | bootloader: delta apply OK",
            "internal store:252K | bootloader: NO delta apply",
            "SD store | bootloader: NO SD apply",
            "QSPI store:2048K | bootloader: QSPI apply OK extra",
        )
        for direct in (False, True):
            for tail in tails:
                with self.subTest(direct=direct, tail=tail):
                    with self.assertRaises(ota.OtaError):
                        self.query(self.fixture(direct=direct, changes={
                            "after_self": lambda value, tail=tail: value.rsplit(" | ", 2)[0] + " | " + tail,
                        }))
        with self.assertRaises(ota.OtaError):
            self.query(self.fixture(hw="RAK_3401", storage="SD"))

    def test_only_exact_installed_family_profile_abi_crc_and_idle_staging_qualify(self):
        valid = self.boot_reply()
        invalid = (
            self.boot_reply(board=0x239A0071, name="TOWER_V2_OTA", caps=9),
            self.boot_reply(name="3401_AUTO_DFU"),
            self.boot_reply(name="OTHER_DFU"),
            self.boot_reply(abi=2), self.boot_reply(abi=65535),
            self.boot_reply(caps=0x0A), self.boot_reply(caps=0xFF),
            self.boot_reply(crc=0), self.boot_reply(crc=0xFFFFFFFF),
            valid.replace("target=", "target=0"),
            valid.replace("staged:none mid=- hash=-", "staged:ready mid=12345678 hash=0011223344556677"),
            valid + " extra", "Unknown command",
            ota.TransmissionError("no reply"),
        )
        for reply in invalid:
            with self.subTest(reply=reply):
                controller = self.fixture(changes={"boot_status": reply})
                with self.assertRaises(ota.OtaError):
                    self.query(controller)
                self.assertEqual(self.commands(controller), [
                    "ota status", "get bootloader.ver", "ota self", "ota bootloader status",
                ])

    def test_requery_failure_is_bounded_without_fallback_retry(self):
        for field in ("after_status", "after_self"):
            with self.subTest(field=field):
                controller = self.fixture(changes={field: ota.TransmissionError("missing reply")})
                with self.assertRaises(ota.OtaError):
                    self.query(controller)
                self.assertEqual(self.commands(controller).count("ota bootloader status"), 1)
                self.assertNotIn("ota stats", self.commands(controller))

    def test_bootloader_packages_never_enter_application_preparation(self):
        for direct in (False, True):
            with self.subTest(direct=direct):
                controller = self.fixture(direct=direct, initial_bl="NONE")
                with self.assertRaises(ota.OtaError):
                    self.query(controller, kind="bootloader")
                self.assertNotIn("ota bootloader status", self.commands(controller))

    def test_unrecognized_unsafe_shape_does_not_trigger_preparation_or_bypass_safety(self):
        for direct in (False, True):
            for tail in ("not probed extra", "unavailable"):
                with self.subTest(direct=direct, tail=tail):
                    controller = self.fixture(direct=direct, changes={
                        "before_self": lambda value, tail=tail: value.replace("not probed", tail),
                    })
                    with self.assertRaises(ota.OtaError):
                        self.query(controller)
                    self.assertNotIn("ota bootloader status", self.commands(controller))


if __name__ == "__main__":
    unittest.main()
