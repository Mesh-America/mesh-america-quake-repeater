"""Host-only stock SDK/boot-readback contracts; no SDK installation or serial IO."""

import copy
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "hil"))
import meshtext_auto_radio2 as hil


class MeshInterfaceError(Exception):
    pass


class PresetEnum:
    values = {p.stock_enum: index for index, p in enumerate(hil.PRESETS) if p.stock_enum}

    @classmethod
    def keys(cls):
        return cls.values.keys()

    @classmethod
    def Value(cls, name):
        return cls.values[name]


def fake_sdk():
    package = ModuleType("meshtastic")
    package.__path__ = []
    protobuf = ModuleType("meshtastic.protobuf")
    protobuf.__path__ = []
    channel = ModuleType("meshtastic.protobuf.channel_pb2")
    channel.Channel = SimpleNamespace(PRIMARY=1)
    config = ModuleType("meshtastic.protobuf.config_pb2")
    config.Config = SimpleNamespace(DeviceConfig=SimpleNamespace(CLIENT_MUTE=1),
                                    LoRaConfig=SimpleNamespace(US=1, ModemPreset=PresetEnum))
    interface = ModuleType("meshtastic.mesh_interface")
    interface.MeshInterface = SimpleNamespace(MeshInterfaceError=MeshInterfaceError)
    util = ModuleType("meshtastic.util")
    util.to_node_num = int
    package.protobuf, package.mesh_interface = protobuf, interface
    protobuf.channel_pb2, protobuf.config_pb2 = channel, config
    return {module.__name__: module for module in (package, protobuf, channel, config, interface, util)}


class Node:
    def __init__(self):
        self.localConfig = SimpleNamespace(device=SimpleNamespace(role=0),
                                           lora=SimpleNamespace(modem_preset=0))
        self.channels = [SimpleNamespace(role=0, settings=SimpleNamespace(
            name="before", psk=b"old", uplink_enabled=True, downlink_enabled=True))]
        self.calls = []
        self.written_lora = None
        self.nodeNum = 0x12345678

    def ensureSessionKey(self):
        self.calls.append("session")

    def beginSettingsTransaction(self):
        self.calls.append("begin")

    def writeChannel(self, index):
        self.calls.append(("channel", index))

    def writeConfig(self, name):
        self.calls.append(("config", name))
        if name == "lora":
            self.written_lora = copy.deepcopy(self.localConfig.lora)

    def commitSettingsTransaction(self):
        self.calls.append("commit")


class StockConfigurationTests(unittest.TestCase):
    def configure(self, preset, *, normalized=False, handshake_misses=0, session_misses=0,
                  readback_cr=None):
        node = Node()
        session_reads = []

        def session_node(node_num):
            self.assertEqual(node_num, node.nodeNum)
            session_reads.append(True)
            return {} if len(session_reads) <= session_misses else {"adminSessionPassKey": b"mock-key"}

        iface = SimpleNamespace(localNode=node, myInfo=SimpleNamespace(my_node_num=0x12345678),
                                metadata=SimpleNamespace(firmware_version="mock-stable"), close=lambda: None,
                                _getOrCreateByNum=session_node)
        stock = hil.StockPeer.__new__(hil.StockPeer)
        stock.iface = iface
        attempts = []

        def connect():
            attempts.append(True)
            if len(attempts) <= handshake_misses:
                raise MeshInterfaceError("transient simulated boot handshake")
            # The official stock boot helper derives BW/SF from the preset.
            if normalized and preset.stock_enum:
                node.localConfig.lora.bandwidth = preset.bandwidth
                node.localConfig.lora.spread_factor = preset.sf
            if readback_cr is not None:
                node.localConfig.lora.coding_rate = readback_cr
            stock.iface = iface

        stock.connect = connect
        with patch.dict(sys.modules, fake_sdk()), patch.object(hil.time, "sleep"), \
                patch.object(hil.time, "monotonic", side_effect=range(1, 250)):
            result = stock.configure(preset, bytes(range(16)), -9, 7)
        return node, result, attempts

    def test_nine_native_presets_clear_bw_sf_and_keep_native_cr_with_hash_slot(self):
        for preset in hil.PRESETS:
            if not preset.stock_enum:
                continue
            with self.subTest(preset=preset.name):
                node, result, _ = self.configure(preset)
                lora = node.written_lora
                self.assertTrue(lora.use_preset)
                self.assertEqual(lora.modem_preset, PresetEnum.Value(preset.stock_enum))
                # Stock clamps a zero CR to 5 instead of selecting preset CR.
                self.assertEqual((lora.bandwidth, lora.spread_factor, lora.coding_rate), (0, 0, preset.cr))
                self.assertEqual((lora.channel_num, lora.override_frequency, lora.frequency_offset), (0, 0, 0))
                self.assertEqual((lora.region, lora.tx_power, lora.hop_limit), (1, -9, 7))
                self.assertTrue(lora.tx_enabled and lora.ignore_mqtt)
                self.assertFalse(lora.config_ok_to_mqtt)
                self.assertEqual(node.calls, ["session", "begin", ("config", "device"),
                                              ("config", "lora"), ("channel", 0), "commit"])
                self.assertEqual(node.channels[0].settings.name, preset.name)
                self.assertEqual(node.channels[0].settings.psk, bytes(range(16)))
                self.assertFalse(node.channels[0].settings.uplink_enabled)
                self.assertFalse(node.channels[0].settings.downlink_enabled)
                self.assertEqual(result["node"], "!12345678")

    def test_native_stock_boot_normalization_is_not_a_readback_failure(self):
        for preset in hil.PRESETS:
            if preset.stock_enum:
                with self.subTest(preset=preset.name):
                    node, _, _ = self.configure(preset, normalized=True)
                    self.assertEqual(node.written_lora.bandwidth, 0)
                    self.assertEqual(node.written_lora.spread_factor, 0)
                    self.assertEqual(node.localConfig.lora.bandwidth, preset.bandwidth)

    def test_custom_mediumturbo_tuple_and_explicit_calculated_slot(self):
        preset = next(p for p in hil.PRESETS if p.name == "MediumTurbo")
        node, _, _ = self.configure(preset)
        lora = node.written_lora
        self.assertFalse(lora.use_preset)
        self.assertEqual((lora.bandwidth, lora.spread_factor, lora.coding_rate), (500, 9, 5))
        self.assertEqual(lora.channel_num, 47)
        self.assertEqual(node.channels[0].settings.name, "MediumTurbo")

    def test_transient_meshinterface_handshake_error_retries(self):
        _, _, attempts = self.configure(hil.PRESETS[0], handshake_misses=1)
        self.assertEqual(len(attempts), 2)

    def test_async_admin_session_is_ready_before_writes(self):
        node, _, _ = self.configure(hil.PRESETS[0], session_misses=3)
        self.assertEqual(node.calls[0:2], ["session", "begin"])

    def test_missing_admin_session_aborts_without_writing(self):
        with self.assertRaisesRegex(hil.TestFailure, "admin session setup timed out"):
            self.configure(hil.PRESETS[0], session_misses=100)

    def test_zero_or_wrong_cr_is_not_accepted_as_native_readback(self):
        for preset_name, observed_cr in (("LongFast", 0), ("LongSlow", 5)):
            preset = next(p for p in hil.PRESETS if p.name == preset_name)
            with self.subTest(preset=preset_name, cr=observed_cr):
                with self.assertRaisesRegex(hil.TestFailure, "configuration readback did not match"):
                    self.configure(preset, readback_cr=observed_cr)


if __name__ == "__main__":
    unittest.main()
