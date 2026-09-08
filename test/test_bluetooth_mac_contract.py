#!/usr/bin/env python3
"""Static contracts for Companion Bluetooth identity configuration."""

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


def source(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


class BluetoothMacContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.main = source("examples/companion_radio/main.cpp")
        cls.mesh = source("examples/companion_radio/MyMesh.cpp")
        cls.nrf_header = source("src/helpers/nrf52/SerialBLEInterface.h")
        cls.nrf_source = source("src/helpers/nrf52/SerialBLEInterface.cpp")
        cls.esp_header = source("src/helpers/esp32/SerialBLEInterface.h")
        cls.esp_source = source("src/helpers/esp32/SerialBLEInterface.cpp")

    def test_both_ble_backends_accept_the_same_configuration(self):
        for header in (self.nrf_header, self.esp_header):
            self.assertIn("const uint8_t* custom_address = nullptr", header)
            self.assertIn("bool clear_bonds = false", header)

        self.assertIn("the_mesh.getBLEPin(), bluetooth_address,", self.main)
        self.assertIn("clear_bonds))", self.main)

    def test_nrf52_uses_random_static_softdevice_address(self):
        self.assertIn("BLE_GAP_ADDR_TYPE_RANDOM_STATIC", self.nrf_source)
        self.assertIn("sd_ble_gap_addr_set(&address)", self.nrf_source)
        self.assertIn(
            "mesh::companion::BLUETOOTH_MAC_BYTES - 1 - i",
            self.nrf_source,
        )

    def test_esp32_supports_nimble_and_bluedroid(self):
        self.assertIn("BLEDevice::setOwnAddr(native_address)", self.esp_source)
        self.assertIn("BLEDevice::setOwnAddrType(BLE_OWN_ADDR_RANDOM)", self.esp_source)
        self.assertIn("setDeviceAddress(", self.esp_source)
        self.assertIn("BLE_ADDR_TYPE_RANDOM", self.esp_source)

    def test_every_boot_mode_is_stable_across_start_retries(self):
        self.assertIn(
            "companion_bluetooth_session_address_ready", self.main
        )
        self.assertIn(
            "BLUETOOTH_MAC_RANDOM_EVERY_BOOT", self.main
        )
        self.assertIn("clear_bonds = true;", self.main)

    def test_cli_exposes_custom_random_every_boot_and_default(self):
        self.assertIn('"get bluetooth.mac"', self.mesh)
        self.assertIn('"set bluetooth.mac"', self.mesh)
        self.assertIn('strcmp(value, "random")', self.mesh)
        self.assertIn('strcmp(value, "random-every-boot")', self.mesh)
        self.assertIn('strcmp(value, "random everyboot")', self.mesh)
        self.assertIn('strcmp(value, "default")', self.mesh)
        self.assertIn("parseBluetoothMac(custom_value, address)", self.mesh)


if __name__ == "__main__":
    unittest.main()
