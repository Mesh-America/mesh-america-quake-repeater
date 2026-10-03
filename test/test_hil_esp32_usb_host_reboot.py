#!/usr/bin/env python3
"""Offline safety and evidence tests; no serial devices or host reboot calls."""

import contextlib
import copy
import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
HIL_DIR = ROOT / "tools" / "hil"


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SOAK = load_module("usb_reboot_test_soak", HIL_DIR / "s3_memory_soak.py")
with mock.patch.dict(sys.modules, {"s3_memory_soak": SOAK}):
    OTA = load_module("usb_reboot_test_ota", HIL_DIR / "esp32_self_serve_ota.py")
with mock.patch.dict(sys.modules, {"esp32_self_serve_ota": OTA}):
    HIL = load_module("usb_reboot_test_harness", HIL_DIR / "esp32_usb_host_reboot.py")


HASH = "0123456789ABCDEF"
SERIALS = ("441BF669CF98", "441BF669C9C0")
CORE = {"battery_mv": 4000, "uptime_secs": 200, "errors": 0, "queue_len": 0}
DIAG = {"state": 1, "state_name": "RX", "recv": 1, "sent": 0, "errors": 0,
        "err_flags": 0, "outbound": False, "last_rx_secs": 3}
DIAG_TEXT = "state=1(RX), recv=1, sent=0, errors=0, err_flags=0, outbound=no, last_rx=3s ago"
STATE = {
    "radio": "909.500,500.000,5,5", "radio2": "off", "tempradio": "off",
    "tempradio2": "off", "powersaving": "on",
    "radio2.status": "off; RX=1,0 TX=0,0 switches=0 errors=0 max=0us preamble=16,16",
    "usb.logging": {"available": False, "enabled": False},
}


def probe():
    data = {
        "schema": 1, "evidence_kind": HIL.KIND, "action": "probe", "result": "PASS",
        "expected_body_hash16": HASH, "host_reboot_performed_by_tool": False,
        "minimum_board_age_seconds": 180,
        "pi": {"boot_id": "11111111-1111-1111-1111-111111111111",
               "dwc_otg_speed": 1, "cmdline_sha256": "a" * 64,
               "model": "Raspberry Pi", "kernel": "same"},
        "devices": {},
    }
    for name, serial in zip(("A", "B"), SERIALS):
        data["devices"][name] = {
            "identity": {"usb_serial": serial, "vid": 0x303A, "pid": 0x1001,
                         "role": "Repeater", "board": "Heltec V4", "endpoint": "/dev/ttyACM0"},
            "self": {"body_hash16": HASH, "body_bytes": 2000, "image_bytes": 2100},
            "inactive_slot": {"inactive_address": 4096, "size_bytes": 5000},
            "usb": {"usb_serial": serial, "speed_mbps": 12}, "ota_idle": True,
            "ota_policy": {"autofetch": "off", "autoinstall": "off"},
            "core": copy.deepcopy(CORE), "radio_diag": copy.deepcopy(DIAG),
            "radio_state": copy.deepcopy(STATE),
            "snapshot": {"private_key_sha256": "b" * 64, "public_key": "C" * 64,
                         "acl": [], "settings": {"name": name, "radio2": {"mode": "off"},
                                                "advert.interval": "0",
                                                "flood.advert.interval": "0"}},
            "reset_reason": "Power on reset", "observed_unix_seconds": 1000.,
            "sample_uncertainty_seconds": .2,
        }
    return data


def post_probe():
    data = probe()
    data["pi"]["boot_id"] = "22222222-2222-2222-2222-222222222222"
    for item in data["devices"].values():
        item["core"]["uptime_secs"] += 90
        item["observed_unix_seconds"] += 90
    return data


class ParserTests(unittest.TestCase):
    def rejected(self, fn, *args):
        with self.assertRaises(HIL.TestFailure):
            fn(*args)

    def test_exact_core_json(self):
        self.assertEqual(HIL.parse_core(json.dumps(CORE)), CORE)
        for data in ("{", "{}", "[]", json.dumps(dict(CORE, queue_len=True)),
                     json.dumps(dict(CORE, queue_len=-1)), json.dumps(dict(CORE, extra=1)),
                     json.dumps(dict(CORE, queue_len=2**32))):
            with self.subTest(data=data):
                self.rejected(HIL.parse_core, data)

    def test_radio_diagnostics_reject_truncation_and_unsolicited_tail(self):
        self.assertEqual(HIL.parse_radio_diag(DIAG_TEXT), DIAG)
        for data in ("state=1(RX)", DIAG_TEXT + " asynchronous output",
                     DIAG_TEXT.replace("outbound=no", "outbound=maybe"),
                     DIAG_TEXT.replace("recv=1", "recv=4294967296")):
            with self.subTest(data=data):
                self.rejected(HIL.parse_radio_diag, data)

    def test_quiet_requires_empty_queue_receive_and_no_outbound(self):
        HIL.require_quiet(CORE, DIAG)
        self.rejected(HIL.require_quiet, dict(CORE, queue_len=1), DIAG)
        self.rejected(HIL.require_quiet, CORE, dict(DIAG, state=3, state_name="TX_WAIT"))
        self.rejected(HIL.require_quiet, CORE, dict(DIAG, outbound=True))

    def test_logging_accepts_only_exact_compiled_out_response(self):
        device = SimpleNamespace(name="A")
        for text, expected in (
                ("> off", {"available": True, "enabled": False}),
                ("> on", {"available": True, "enabled": True}),
                ("Error: unknown setting: usb.logging", {"available": False, "enabled": False})):
            device.command = mock.Mock(return_value="\n -> " + text)
            self.assertEqual(HIL.logging_state(device), expected)
        for text in ("Error: invalid", "Error: unknown setting: usb.logging extra", "unavailable", ""):
            device.command = mock.Mock(return_value="\n -> " + text)
            self.rejected(HIL.logging_state, device)

    def test_only_idle_ota_is_accepted(self):
        device = SimpleNamespace(name="A", command=mock.Mock(
            return_value="\n -> OTA | thing | no download | serving:on"))
        HIL.require_idle(device)
        for text in ("OTA | download: complete 1/1 | serving:on",
                     "OTA | download: failed 1/1 | serving:on", "no download",
                     "OTA | download: receiving 1/2 | serving:on"):
            device.command.return_value = "\n -> " + text
            self.rejected(HIL.require_idle, device)

    def test_automatic_ota_policy_must_already_be_off(self):
        device = SimpleNamespace(name="A", command=mock.Mock(
            return_value="\n -> ota config: autofetch=off autoinstall=off checkpoint=16"))
        self.assertEqual(HIL.manual_ota_policy(device),
                         {"autofetch": "off", "autoinstall": "off"})
        for text in ("ota config: autofetch=any autoinstall=off",
                     "ota config: autofetch=off autoinstall=trusted",
                     "ota config: autofetch=off", "Error: unknown command",
                     "ota config: autofetch=off autofetch=off autoinstall=off"):
            device.command.return_value = "\n -> " + text
            self.rejected(HIL.manual_ota_policy, device)

    def test_running_hash_and_slot_geometry_are_checked_before_policy(self):
        device = SimpleNamespace(name="A", connect=mock.Mock(),
                                 identity=probe()["devices"]["A"]["identity"])
        replies = {
            "ota self": "\n -> self body=2000 image=2100 base_hash=" + HASH,
            "ota dev apply slot": "\n -> inactive slot addr=0x1000 size=5000",
            "ota config": "\n -> ota config: autofetch=off autoinstall=off",
        }
        device.command = mock.Mock(side_effect=lambda command: replies[command])
        self.assertEqual(HIL.verified_device(device, HASH)["self"]["body_hash16"], HASH)
        device.command.reset_mock()
        self.rejected(HIL.verified_device, device, "FEDCBA9876543210")
        self.assertEqual(device.command.call_args_list, [mock.call("ota self")])
        replies["ota dev apply slot"] = "\n -> inactive slot addr=0x1000 size=1000"
        self.rejected(HIL.verified_device, device, HASH)

    def test_temporary_profile_fields_are_strict_and_diagnostic_tails_not_retained(self):
        device = SimpleNamespace(command=mock.Mock(side_effect=lambda command, **kwargs:
            "\n -> > " + ("909.500,500.000,5,5,32" if command == "get tempradio"
                          else "909.500,500.000,5,5,rxtx,32 (auto); diagnostic tail")))
        state = HIL.temporary_profiles(device)
        self.assertEqual(state["tempradio2"], "909.500,500.000,5,5,rxtx,32 (auto)")
        self.assertNotIn("diagnostic tail", json.dumps(state))
        for value in ("Error: unknown setting", "unavailable", "60", "1,2,3", "off extra"):
            device.command = mock.Mock(return_value="\n -> > " + value)
            self.rejected(HIL.temporary_profiles, device)


class ComparisonTests(unittest.TestCase):
    def test_continued_uptime_and_renumbered_tty_pass(self):
        old, new = probe(), post_probe()
        new["devices"]["A"]["identity"]["endpoint"] = "/dev/ttyACM7"
        HIL.validate_probe(old, HASH, SERIALS)
        HIL.validate_probe(new, HASH, SERIALS)
        result = HIL.compare_probes(old, new, 10)
        self.assertFalse(result["devices"]["A"]["board_reboot_observed"])
        self.assertEqual(result["devices"]["A"]["board_uptime_gain_seconds"], 90)

    def test_host_must_reboot_without_configuration_or_kernel_change(self):
        for key, value in (
                ("boot_id", probe()["pi"]["boot_id"]), ("dwc_otg_speed", 2),
                ("cmdline_sha256", "changed"), ("kernel", "changed"), ("model", "changed")):
            with self.subTest(key=key):
                new = post_probe()
                new["pi"][key] = value
                with self.assertRaises(HIL.TestFailure):
                    HIL.compare_probes(probe(), new, 10)

    def test_radio_reboot_or_changed_settings_hash_slot_identity_fail(self):
        for field, value in (
                ("reset_reason", "Software reset"), ("inactive_slot", {}), ("snapshot", {}),
                ("self", {})):
            with self.subTest(field=field):
                new = post_probe()
                new["devices"]["A"][field] = value
                with self.assertRaises(HIL.TestFailure):
                    HIL.compare_probes(probe(), new, 10)
        for uptime in (10, 200, 400):
            new = post_probe()
            new["devices"]["A"]["core"]["uptime_secs"] = uptime
            with self.assertRaises(HIL.TestFailure):
                HIL.compare_probes(probe(), new, 10)
        for field, value in (("usb_serial", "other"), ("pid", 0x1002), ("role", "Companion")):
            new = post_probe()
            new["devices"]["A"]["identity"][field] = value
            with self.assertRaises(HIL.TestFailure):
                HIL.compare_probes(probe(), new, 10)
        new = post_probe()
        new["devices"]["A"]["radio_state"]["radio"] = "910.525,500,5,5"
        with self.assertRaises(HIL.TestFailure):
            HIL.compare_probes(probe(), new, 10)

    def test_probe_rejects_sleep_inhibitors_and_boot_grace(self):
        for field, value in (
                ("powersaving", "off"), ("radio2", "909.5,500,5,5,rx"),
                ("tempradio", "pending"), ("tempradio2", "pending"),
                ("radio2.status", "radio2 change pending"),
                ("usb.logging", {"available": True, "enabled": True})):
            with self.subTest(field=field):
                data = probe()
                data["devices"]["A"]["radio_state"][field] = value
                with self.assertRaises(HIL.TestFailure):
                    HIL.validate_probe(data, HASH, SERIALS)
        for field, value in (("uptime_secs", 180), ("queue_len", 1)):
            data = probe()
            data["devices"]["A"]["core"][field] = value
            with self.assertRaises(HIL.TestFailure):
                HIL.validate_probe(data, HASH, SERIALS)

    def test_probe_hash_physical_serial_role_native_speed_are_required(self):
        data = probe()
        data["devices"]["A"]["usb"]["speed_mbps"] = 480
        with self.assertRaises(HIL.TestFailure):
            HIL.validate_probe(data, HASH, SERIALS)
        with self.assertRaises(HIL.TestFailure):
            HIL.validate_probe(probe(), "FEDCBA9876543210", SERIALS)
        with self.assertRaises(HIL.TestFailure):
            HIL.validate_probe(probe(), HASH, tuple(reversed(SERIALS)))

    def test_probe_rejects_invalid_time_or_secret_digest(self):
        for field, value in (("observed_unix_seconds", float("nan")),
                             ("sample_uncertainty_seconds", 6)):
            data = probe()
            data["devices"]["A"][field] = value
            with self.assertRaises(HIL.TestFailure):
                HIL.validate_probe(data, HASH, SERIALS)
        data = probe()
        data["devices"]["A"]["snapshot"]["private_key_sha256"] = "raw private key"
        with self.assertRaises(HIL.TestFailure):
            HIL.validate_probe(data, HASH, SERIALS)


class FakeClock:
    def __init__(self):
        self.now = 0.

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class FakeDevice:
    def __init__(self, name, ledger):
        self.name = name
        self.ledger = ledger
        self.active = False
        self.rebooted = False
        self.busy_polls = 0
        self.logging_available = False
        self.fail_write = False
        self.autofetch = "off"
        self.temp_primary = True
        self.temp_secondary = True
        self.saved_advert = "0"
        self.saved_flood_advert = "0"
        self.long_temp = False
        self.secondary_mode = "rx"

    def command(self, command, timeout=5):
        self.ledger.append((self.name, "read", command))
        if command == "ota status":
            text = "OTA | download: receiving 1/2 | serving:on" if self.active else \
                   "OTA | thing | no download | serving:on"
        elif command == "ota config":
            text = "ota config: autofetch=" + self.autofetch + " autoinstall=off"
        elif command == "stats-core":
            text = json.dumps(CORE)
        elif command == "stats-radio-diag":
            text = DIAG_TEXT
            if self.busy_polls:
                self.busy_polls -= 1
                text = text.replace("1(RX)", "3(TX_WAIT)")
        elif command == "get usb.logging":
            text = "> off" if self.logging_available else "Error: unknown setting: usb.logging"
        elif command == "get tempradio":
            text = "> 909.500,500.000,5,5,120" if self.temp_primary else "> off"
        elif command == "get tempradio2":
            text = "> 909.500,500.000,5,5,rxtx,120" if self.temp_secondary else "> off"
        elif command == "get powersaving":
            text = "> on"
        else:
            raise AssertionError("Unexpected fake read command")
        return "\n -> " + text

    def checked(self, command, timeout=5):
        self.ledger.append((self.name, "write", command, timeout))
        if self.fail_write:
            raise HIL.TestFailure("Acknowledgement timed out")
        if command == "normalradio":
            self.temp_primary = False
        elif command == "set tempradio2 off":
            self.temp_secondary = False
        elif command == "set radio2 off":
            self.secondary_mode = "off"
        return "OK - acknowledged"

    def reboot(self, expected_hash):
        self.ledger.append((self.name, "reboot", expected_hash))
        self.rebooted = True


class PreparationTests(unittest.TestCase):
    def setUp(self):
        self.ledger = []
        self.devices = [FakeDevice(name, self.ledger) for name in ("A", "B")]
        self.report = SimpleNamespace(data={"devices": {}}, save=mock.Mock(), event=mock.Mock())
        self.clock = FakeClock()
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(mock.patch.object(HIL.time, "monotonic", self.clock.monotonic))
        self.stack.enter_context(mock.patch.object(HIL.time, "sleep", self.clock.sleep))
        self.stack.enter_context(mock.patch.object(HIL, "native_usb_state", return_value={"speed_mbps": 12}))
        self.stack.enter_context(mock.patch.object(HIL, "verified_device", side_effect=self.verify))
        self.stack.enter_context(mock.patch.object(HIL, "snapshot", side_effect=self.saved))

    def verify(self, device, expected_hash):
        self.ledger.append((device.name, "verify", expected_hash))
        result = copy.deepcopy(probe()["devices"][device.name])
        result["ota_policy"] = HIL.manual_ota_policy(device)
        return result

    def saved(self, device):
        self.ledger.append((device.name, "snapshot"))
        result = copy.deepcopy(probe()["devices"][device.name]["snapshot"])
        result["settings"]["radio2"] = {"mode": device.secondary_mode}
        result["settings"]["advert.interval"] = "60" if device.temp_primary else device.saved_advert
        result["settings"]["flood.advert.interval"] = (
            "3" if device.temp_primary and device.long_temp else device.saved_flood_advert)
        return result

    def test_both_preflights_precede_first_write_and_reboots_preserve_identity(self):
        HIL.prepare_devices(self.devices, HASH, self.report)
        first_write = next(i for i, row in enumerate(self.ledger) if row[1] == "write")
        self.assertIn(("A", "snapshot"), self.ledger[:first_write])
        self.assertIn(("B", "snapshot"), self.ledger[:first_write])
        for device in self.devices:
            writes = [row for row in self.ledger if row[0] == device.name and row[1] == "write"]
            self.assertEqual([row[2] for row in writes],
                             ["normalradio", "set tempradio2 off", "set radio2 off", "set powersaving on"])
            self.assertTrue(all(row[3] == 30 for row in writes))
            self.assertTrue(device.rebooted)
        self.assertTrue(self.report.data["board_reboots_intentionally_performed"])

    def test_raw_temporary_getter_and_normalized_saved_baselines_are_both_retained(self):
        HIL.prepare_devices(self.devices, HASH, self.report)
        entry = self.report.data["devices"]["A"]
        self.assertEqual(entry["before_prepare"]["snapshot"]["settings"]["advert.interval"], "60")
        self.assertEqual(entry["before_prepare"]["core"], CORE)
        self.assertEqual(entry["before_prepare"]["radio_diag"], DIAG)
        self.assertEqual(entry["normalized_saved_snapshot"]["settings"]["advert.interval"], "0")
        self.assertEqual(entry["normalized_saved_snapshot"]["settings"]["radio2"], {"mode": "rx"})
        self.assertEqual(entry["after_prepare"]["snapshot"]["settings"]["advert.interval"], "0")
        self.assertEqual(entry["normalization_differences"]["advert.interval"],
                         {"live_before": "60", "saved_after_normalradio": "0",
                          "reason": "documented temporary radio timing getter override"})
        self.assertFalse(any("advert.interval" in row[2]
                             for row in self.ledger if row[1] == "write"))
        # Both normalized snapshots must be taken before either saved radio2
        # setting is changed; clearing temporary overlays is a separate phase.
        first_saved_write = next(i for i, row in enumerate(self.ledger)
                                 if row[1] == "write" and row[2] == "set radio2 off")
        for name in ("A", "B"):
            self.assertEqual(self.ledger[:first_saved_write].count((name, "snapshot")), 2)

    def test_normalization_does_not_assume_saved_advert_is_zero(self):
        self.devices[0].saved_advert = "72"
        self.devices[0].saved_flood_advert = "7"
        self.devices[0].long_temp = True
        HIL.prepare_devices(self.devices, HASH, self.report)
        entry = self.report.data["devices"]["A"]
        self.assertEqual(entry["normalized_saved_snapshot"]["settings"]["advert.interval"], "72")
        self.assertEqual(entry["after_prepare"]["snapshot"]["settings"]["advert.interval"], "72")
        self.assertEqual(entry["normalization_differences"]["flood.advert.interval"]
                         ["saved_after_normalradio"], "7")

    def test_unrelated_normalization_change_fails_before_persistent_settings_or_reboot(self):
        original = self.saved
        def changed(device):
            result = original(device)
            if not device.temp_primary:
                result["settings"]["name"] = "changed unexpectedly"
            return result
        with mock.patch.object(HIL, "snapshot", side_effect=changed):
            with self.assertRaisesRegex(HIL.TestFailure, "unrelated saved setting"):
                HIL.prepare_devices(self.devices, HASH, self.report)
        self.assertFalse(any(row[1] == "reboot" or row[1:3] == ("write", "set radio2 off")
                             for row in self.ledger))

    def test_advert_change_without_original_temporary_profile_is_not_ignored(self):
        self.devices[0].temp_primary = False
        original = self.saved
        calls = {}
        def changed(device):
            result = original(device)
            calls[device.name] = calls.get(device.name, 0) + 1
            if calls[device.name] >= 2:
                result["settings"]["advert.interval"] = "2"
            return result
        with mock.patch.object(HIL, "snapshot", side_effect=changed):
            with self.assertRaisesRegex(HIL.TestFailure, "unrelated saved setting"):
                HIL.prepare_devices(self.devices, HASH, self.report)
        self.assertFalse(any(device.rebooted for device in self.devices))

    def test_arbitrary_advert_change_after_reboot_still_fails(self):
        original = self.saved
        def changed(device):
            result = original(device)
            if device.rebooted:
                result["settings"]["advert.interval"] = "2"
            return result
        with mock.patch.object(HIL, "snapshot", side_effect=changed):
            with self.assertRaisesRegex(HIL.TestFailure, "unrelated saved setting"):
                HIL.prepare_devices(self.devices, HASH, self.report)
        self.assertEqual(self.report.data["devices"]["A"]["normalized_saved_snapshot"]
                         ["settings"]["advert.interval"], "0")

    def test_identity_change_during_normalization_is_rejected(self):
        original = self.saved
        def changed(device):
            result = original(device)
            if not device.temp_primary:
                result["private_key_sha256"] = "d" * 64
            return result
        with mock.patch.object(HIL, "snapshot", side_effect=changed):
            with self.assertRaisesRegex(HIL.TestFailure, "identity or ACL"):
                HIL.prepare_devices(self.devices, HASH, self.report)
        self.assertFalse(any(device.rebooted for device in self.devices))

    def test_pending_temporary_restoration_timeout_never_changes_saved_radio2_or_reboots(self):
        original = self.devices[0].checked
        def stays_temporary(command, timeout=5):
            result = original(command, timeout)
            self.devices[0].temp_primary = True
            return result
        self.devices[0].checked = stays_temporary
        with self.assertRaisesRegex(HIL.TestFailure, "restoration timed out"):
            HIL.prepare_devices(self.devices, HASH, self.report)
        self.assertFalse(any(row[1] == "reboot" or row[1:3] == ("write", "set radio2 off")
                             for row in self.ledger))
        self.assertLessEqual(self.clock.now, 30)

    def test_logging_off_only_if_available(self):
        self.devices[0].logging_available = True
        HIL.prepare_devices(self.devices, HASH, self.report)
        self.assertIn(("A", "write", "set usb.logging off", 30), self.ledger)
        self.assertNotIn(("B", "write", "set usb.logging off", 30), self.ledger)

    def test_any_active_download_refuses_all_writes(self):
        self.devices[1].active = True
        with self.assertRaises(HIL.TestFailure):
            HIL.prepare_devices(self.devices, HASH, self.report)
        self.assertFalse(any(row[1] in ("write", "reboot") for row in self.ledger))

    def test_auto_download_policy_refuses_all_writes(self):
        self.devices[1].autofetch = "any"
        with self.assertRaises(HIL.TestFailure):
            HIL.prepare_devices(self.devices, HASH, self.report)
        self.assertFalse(any(row[1] in ("write", "reboot") for row in self.ledger))

    def test_failed_setter_is_not_retried_and_neither_radio_reboots(self):
        self.devices[0].fail_write = True
        with self.assertRaises(HIL.TestFailure):
            HIL.prepare_devices(self.devices, HASH, self.report)
        self.assertEqual([row for row in self.ledger if row[1] == "write"],
                         [("A", "write", "normalradio", 30)])
        self.assertFalse(any(device.rebooted for device in self.devices))

    def test_transient_beacon_tx_waits_without_mutations(self):
        self.devices[0].busy_polls = 1
        result = HIL.wait_quiet(self.devices)
        self.assertEqual(set(result), {"A", "B"})
        self.assertGreater(self.clock.now, 0)
        self.assertFalse(any(row[1] in ("write", "reboot") for row in self.ledger))

    def test_persistent_busy_state_has_bounded_timeout(self):
        self.devices[0].busy_polls = 100000
        with self.assertRaises(HIL.TestFailure):
            HIL.wait_quiet(self.devices, timeout=2)
        self.assertLessEqual(self.clock.now, 2)
        self.assertFalse(any(row[1] in ("write", "reboot") for row in self.ledger))

    def test_new_download_during_quiet_poll_fails_without_writes(self):
        self.devices[0].active = True
        with self.assertRaises(HIL.TestFailure):
            HIL.wait_quiet(self.devices)
        self.assertFalse(any(row[1] in ("write", "reboot") for row in self.ledger))

    def test_download_started_after_quiet_sample_refuses_first_mutation(self):
        def newly_active(devices):
            self.devices[1].active = True
            return {device.name: {"core": CORE, "radio_diag": DIAG} for device in devices}
        with mock.patch.object(HIL, "wait_quiet", side_effect=newly_active):
            with self.assertRaises(HIL.TestFailure):
                HIL.prepare_devices(self.devices, HASH, self.report)
        self.assertFalse(any(row[1] in ("write", "reboot") for row in self.ledger))

    def test_download_started_after_settings_refuses_board_reboots(self):
        original = self.devices[1].checked
        def active_after_settings(command, timeout=5):
            result = original(command, timeout)
            if command == "set powersaving on":
                self.devices[1].active = True
            return result
        self.devices[1].checked = active_after_settings
        with self.assertRaises(HIL.TestFailure):
            HIL.prepare_devices(self.devices, HASH, self.report)
        self.assertFalse(any(row[1] == "reboot" for row in self.ledger))


class FilesystemEvidenceTests(unittest.TestCase):
    def test_new_report_is_final_read_only_and_cannot_be_overwritten(self):
        args = SimpleNamespace(action="probe", expected_body_hash16=HASH, rounds=0, timeout=30,
                               poll_interval=0, min_age=180, uptime_tolerance=10)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.json"
            report = HIL.EvidenceReport(path, args)
            report.data["result"] = "PASS"
            report.seal()
            self.assertEqual(json.loads(path.read_text())["result"], "PASS")
            if os.name != "nt":
                self.assertEqual(path.stat().st_mode & 0o777, 0o400)
            with self.assertRaises(HIL.TestFailure):
                report.save()
            with self.assertRaises(HIL.TestFailure):
                HIL.EvidenceReport(path, args)
            os.chmod(path, 0o600)  # Permit temporary-fixture cleanup on Windows.

    def test_report_creation_race_cannot_replace_existing_evidence(self):
        args = SimpleNamespace(action="probe", expected_body_hash16=HASH, rounds=0, timeout=30,
                               poll_interval=0, min_age=180, uptime_tolerance=10)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.json"
            path.write_text("existing evidence", encoding="utf-8")
            # Simulate another process creating the report after the initial
            # exists() check. The atomic hard-link creation still rejects it.
            with mock.patch.object(Path, "exists", return_value=False):
                with self.assertRaises(HIL.TestFailure):
                    HIL.EvidenceReport(path, args)
            self.assertEqual(path.read_text(encoding="utf-8"), "existing evidence")

    def test_host_records_speed_and_hash_not_raw_cmdline(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = {
                "proc/sys/kernel/random/boot_id": probe()["pi"]["boot_id"],
                "proc/uptime": "200.1 300.2",
                "proc/cmdline": "dwc_otg.speed=1 secret_argument=not-for-report",
                "proc/device-tree/model": "Raspberry Pi 3 Model B Rev 1.2\0",
            }
            for relative, value in paths.items():
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(value, encoding="ascii")
            result = HIL.pi_state(root)
            self.assertEqual(result["dwc_otg_speed"], 1)
            self.assertNotIn("secret_argument", json.dumps(result))
            (root / "proc/cmdline").write_text("dwc_otg.speed=0", encoding="ascii")
            with self.assertRaises(HIL.TestFailure):
                HIL.pi_state(root)

    def test_native_usb_serial_full_speed_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            device_path = root / "sys/class/tty/ttyACM0/device"
            device_path.mkdir(parents=True)
            for name, value in {"idVendor": "303a", "idProduct": "1001",
                                "serial": SERIALS[0], "speed": "12"}.items():
                (device_path / name).write_text(value, encoding="ascii")
            device = SimpleNamespace(endpoint="/dev/ttyACM0", serial_number=SERIALS[0])
            self.assertEqual(HIL.native_usb_state(device, root)["speed_mbps"], 12)
            for name, value in (("speed", "480"), ("speed", "unknown"),
                                ("idProduct", "1002"), ("serial", SERIALS[1])):
                original = (device_path / name).read_text(encoding="ascii")
                (device_path / name).write_text(value, encoding="ascii")
                with self.assertRaises(HIL.TestFailure):
                    HIL.native_usb_state(device, root)
                (device_path / name).write_text(original, encoding="ascii")

    def test_load_report_requires_successful_probe(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "probe.json"
            path.write_text(json.dumps(probe()), encoding="utf-8")
            self.assertEqual(HIL.load_probe(path, HASH, SERIALS)["result"], "PASS")
            data = probe()
            data["result"] = "RUNNING"
            path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaises(HIL.TestFailure):
                HIL.load_probe(path, HASH, SERIALS)


if __name__ == "__main__":
    unittest.main()
