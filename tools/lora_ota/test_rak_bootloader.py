"""Adaptive bootloader packages use internal flash regardless of app storage."""

from dataclasses import replace
import unittest

import lora_ota as ota


class RakBootloaderCompatibilityTest(unittest.TestCase):
    def fixture(self, name, target_id, external):
        hw = f"NRF_BL_239A0029_{name}_DFU"
        package = ota.MotaInfo(
            path=None, blob=b"", flags=ota.MOTA_FLAG_FULL | ota.MOTA_FLAG_BOOTLOADER,
            target_id=target_id, fw_version=0x02040A02, image_size=40960,
            payload_size=40960, block_size=1024, merkle_root=b"\0" * 4,
            image_hash=b"\0" * 8, codec_id=0, hw_id=hw,
            base_hash=b"\0" * 8, payload_offset=365, bootloader_storage=0x0A,
        )
        target = ota.TargetInfo(
            name=name, target_id=1, base_hash=b"\0" * 8, platform="nrf52",
            nrf_sd=False, nrf_qspi=external, hw_id=name,
            bootloader_version="OTAFIX2.4.10-preview.1", bootloader_abi=3,
            bootloader_codecs=5, status="", self_status="",
            boot_target_id=target_id, boot_hw_id=hw, boot_storage=0x0A,
        )
        return package, target

    def test_internal_boot_update_with_either_application_backend(self):
        for name, target_id in (("3401", 0x23818A80), ("4631", 0x2D0DF000)):
            for external in (False, True):
                with self.subTest(board=name, external=external):
                    package, target = self.fixture(name, target_id, external)
                    self.assertTrue(ota.compatible_mota(package, target)[0])
                    for flags in (0x1E, 0x0E, 0x16):
                        self.assertFalse(ota.compatible_mota(
                            replace(package, bootloader_storage=flags), target)[0])
                        self.assertFalse(ota.compatible_mota(
                            package, replace(target, boot_storage=flags))[0])
                    self.assertFalse(ota.compatible_mota(
                        package, replace(target, bootloader_abi=2))[0])
                    self.assertFalse(ota.compatible_mota(
                        package, replace(target, boot_hw_id="NRF_BL_239A0029_4631_AUTO_DFU"))[0])
                    self.assertFalse(ota.compatible_mota(
                        package, replace(target, boot_target_id=target_id ^ 1))[0])


if __name__ == "__main__":
    unittest.main()
