#!/usr/bin/env python3
"""Offline serial-framing and safety tests for the two-V4 own-flash harness."""

import contextlib
import copy
import importlib.util
import io
import json
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


SESSION = load_module("self_serve_test_serial_session", HIL_DIR / "serial_session.py")
with mock.patch.dict(sys.modules, {"serial_session": SESSION}):
    SOAK = load_module("self_serve_test_soak", HIL_DIR / "s3_memory_soak.py")
with mock.patch.dict(sys.modules, {"s3_memory_soak": SOAK}):
    HIL = load_module("self_serve_test_harness", HIL_DIR / "esp32_self_serve_ota.py")


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class ScriptedSerial:
    """Deliver timed USB chunks; writes are captured, never sent to hardware."""

    def __init__(self, clock, response):
        self.clock = clock
        self.response = response
        self.pending = []
        self.writes = []
        self.closed = False

    @property
    def in_waiting(self):
        if self.pending and self.pending[0][0] <= self.clock.now:
            return len(self.pending[0][1])
        return 0

    def read(self, size):
        if not self.in_waiting:
            self.clock.sleep(.05)
        if self.in_waiting:
            due, data = self.pending[0]
            chunk, remaining = data[:size], data[size:]
            if remaining:
                self.pending[0] = (due, remaining)
            else:
                self.pending.pop(0)
            return chunk
        return b""

    def write(self, data):
        self.writes.append(data)
        self.pending.extend((self.clock.now + delay, chunk)
                            for delay, chunk in self.response)
        return len(data)

    def flush(self):
        pass

    def close(self):
        self.closed = True


class FramingTests(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(mock.patch.object(HIL.time, "monotonic", self.clock.monotonic))
        self.stack.enter_context(mock.patch.object(HIL.time, "sleep", self.clock.sleep))

    def device(self, response):
        device = HIL.V4Device("A", "441BF669CF98")
        stream = ScriptedSerial(self.clock, response)
        device.stream = stream
        return device, stream

    def test_late_setter_ack_uses_full_deadline_and_one_write(self):
        device, stream = self.device([(8, b"set radio2 x\r\n  -> OK - radio2\r\n")])
        self.assertEqual(device.checked("set radio2 909.5,500,6,5,rx", timeout=30), "OK - radio2")
        self.assertEqual(stream.writes, [b"set radio2 909.5,500,6,5,rx\r"])
        self.assertLess(self.clock.now, 30)

    def test_missing_marker_closes_transport_without_retry_or_secret_in_error(self):
        device, stream = self.device([])
        secret = "AB" * 64
        with self.assertRaises(HIL.TestFailure) as raised:
            device.checked("set prv.key " + secret, timeout=30)
        self.assertEqual(len(stream.writes), 1)
        self.assertTrue(stream.closed)
        self.assertIsNone(device.stream)
        self.assertIn("set prv.key", str(raised.exception))
        self.assertNotIn(secret, str(raised.exception))
        self.assertLessEqual(self.clock.now, 30.2)

    def test_split_marker_and_key_packets_are_joined_without_logging_secret(self):
        secret = "AB" * 64
        device, stream = self.device([
            (.1, b"get prv.key\r\n  -"),
            (.2, b"> > " + secret[:64].encode()),
            (.3, secret[64:].encode() + b"\r\n"),
        ])
        self.assertEqual(HIL.key_token(device.command("get prv.key"), 128), secret)
        self.assertEqual(stream.writes, [b"get prv.key\r"])

    def test_embedded_debug_arrow_does_not_end_wait_before_eight_second_ack(self):
        device, stream = self.device([
            (.1, b"debug packet [01 -> 02]\r\n"),
            (8, b"set radio2 x\r\n  -> OK - radio2\r\n"),
        ])
        self.assertEqual(device.checked("set radio2 909.5,500,6,5,rx", timeout=30), "OK - radio2")
        self.assertEqual(len(stream.writes), 1)
        self.assertLess(self.clock.now, 30)

    def test_marker_at_100ms_and_complete_reply_at_800ms_do_not_resend(self):
        device, stream = self.device([
            (.1, b"set radio2 x\r\n  -> "),
            (.8, b"OK - radio2\r\n"),
        ])
        self.assertEqual(device.checked("set radio2 909.5,500,6,5,rx", timeout=30), "OK - radio2")
        self.assertEqual(len(stream.writes), 1)
        self.assertGreaterEqual(self.clock.now, .8)

    def test_empty_or_unterminated_reply_fails_boundedly_without_resend_or_raw_reply_leak(self):
        secret = "AB" * 64
        for tail in (b"", b"\r\n", secret.encode()):
            with self.subTest(empty=not tail, terminated=tail.endswith(b"\r\n")):
                started = self.clock.now
                device, stream = self.device([(.1, b"get prv.key\r\n  -> " + tail)])
                close = mock.Mock(wraps=device.close)
                device.close = close
                with self.assertRaisesRegex(HIL.TestFailure, "CLI reply was incomplete for get prv.key") as raised:
                    device.command("get prv.key", timeout=2)
                self.assertNotIn(secret, str(raised.exception))
                self.assertEqual(len(stream.writes), 1)
                close.assert_called_once_with()
                self.assertTrue(stream.closed)
                self.assertIsNone(device.stream)
                self.assertLessEqual(self.clock.now - started, 2.2)


class PreparationTests(unittest.TestCase):
    def devices(self):
        return [SimpleNamespace(name=name, checked=mock.Mock(return_value="OK"),
                                reboot=mock.Mock()) for name in ("A", "B")]

    def test_every_prepare_mutation_uses_30s_and_diagnostic_labels_only(self):
        devices = self.devices()
        report = SimpleNamespace(event=mock.Mock())
        keys = ["AB" * 32, "CD" * 32]
        with mock.patch.object(HIL.time, "sleep") as sleep:
            HIL.prepare(devices, keys, "0123456789ABCDEF", report)
        for device in devices:
            self.assertEqual(device.checked.call_count, 10)
            for call in device.checked.call_args_list:
                self.assertEqual(call.kwargs, {"timeout": 30})
            device.reboot.assert_called_once_with("0123456789ABCDEF")
        sleep.assert_called_once_with(6)
        events = "\n".join(call.args[0] for call in report.event.call_args_list)
        for key in keys:
            self.assertNotIn(key, events)
        self.assertNotIn(HIL.LAB_RADIO, events)
        self.assertIn("Preparing A: set radio2", events)

    def test_timed_out_mutation_is_never_retried_or_followed_by_reboot(self):
        devices = self.devices()
        devices[0].checked.side_effect = ["OK", "OK", "OK", HIL.TestFailure("marker missing")]
        report = SimpleNamespace(event=mock.Mock())
        with mock.patch.object(HIL.time, "sleep") as sleep:
            with self.assertRaisesRegex(HIL.TestFailure, "marker missing"):
                HIL.prepare(devices, ["AB" * 32, "CD" * 32], "0123456789ABCDEF", report)
        self.assertEqual(devices[0].checked.call_count, 4)
        self.assertEqual(devices[0].checked.call_args.args,
                         ("set radio2 " + HIL.LAB_SECONDARY,))
        devices[1].checked.assert_not_called()
        for device in devices:
            device.reboot.assert_not_called()
        sleep.assert_not_called()

    def test_command_labels_exclude_setting_values_and_ota_ids(self):
        cases = {
            "set prv.key " + "AB" * 64: "set prv.key",
            "setperm " + "CD" * 32 + " 1": "setperm",
            "set name secret-node-name": "set name",
            "ota get DEADBEEF flash": "ota get",
            "get acl 128": "get acl",
            "tempradio 909.5,500,5,5,120": "tempradio",
        }
        for command, label in cases.items():
            with self.subTest(label=label):
                self.assertEqual(HIL.command_label(command), label)


class LabActivationTests(unittest.TestCase):
    PRIMARY = "909.500,500.000,5,5,32; 0d1h59m (119 min) left"
    SECONDARY = "909.500,500.000,5,5,rxtx,32 (auto); timing self-test pending"
    POLICY = "autofetch=off autoinstall=off hops=0"

    def setUp(self):
        self.clock = FakeClock()
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.sleep = self.stack.enter_context(
            mock.patch.object(HIL.time, "sleep", side_effect=self.clock.sleep))
        self.stack.enter_context(mock.patch.object(HIL.time, "monotonic", self.clock.monotonic))

    def device(self, name, ready_at=0, secondary=None, policy=None, getter_delays=None):
        def checked(command, timeout=5):
            if command == "ota config":
                return self.POLICY if policy is None else policy
            return "OK"

        def command(command, timeout=5):
            self.clock.sleep((getter_delays or {}).get(command, 0))
            if self.clock.now < ready_at:
                text = "off" if command == "get tempradio" else "909.500,500.000,6,5,rx,32"
            elif command == "get tempradio":
                text = self.PRIMARY
            else:
                text = self.SECONDARY if secondary is None else secondary
            return "\r\n  -> > " + text + "\r\n"

        return SimpleNamespace(name=name, checked=mock.Mock(side_effect=checked),
                               command=mock.Mock(side_effect=command))

    def test_lab_tuple_is_strict_about_frequency_bandwidth_sf_cr_and_secondary_mode(self):
        self.assertTrue(HIL.lab_profile_matches(self.PRIMARY))
        self.assertTrue(HIL.lab_profile_matches(self.SECONDARY, secondary=True))
        for text in ("off", "910.525,500.000,5,5,32", "909.500,250.000,5,5,32",
                     "909.500,500.000,6,5,32", "909.500,500.000,5,7,32"):
            with self.subTest(text=text):
                self.assertFalse(HIL.lab_profile_matches(text))
                with self.assertRaises(HIL.TestFailure):
                    HIL.require_lab_profile(text)
        for text in (self.PRIMARY, "909.500,500.000,5,5,rx,32",
                     "909.500,500.000,6,5,rxtx,32"):
            with self.subTest(secondary=text):
                self.assertFalse(HIL.lab_profile_matches(text, secondary=True))

    def test_arm_writes_each_mutation_once_with_30s_before_live_verification(self):
        devices = [self.device("A"), self.device("B")]
        HIL.arm_lab(devices)
        expected = ["ota config autofetch off", "ota config autoinstall off", "ota config hops 0",
                    "set tempradio2 909.5,500,5,5,rxtx,120", "tempradio 909.5,500,5,5,120"]
        for device in devices:
            writes = [call for call in device.checked.call_args_list if call.args[0] != "ota config"]
            self.assertEqual([call.args[0] for call in writes], expected)
            self.assertTrue(all(call.kwargs == {"timeout": 30} for call in writes))
            self.assertEqual([call.args[0] for call in device.command.call_args_list],
                             ["get tempradio", "get tempradio2"])
            device.checked.assert_any_call("ota config")
        self.sleep.assert_not_called()

    def test_arm_polls_delayed_primary_and_secondary_activation_without_reapplying(self):
        devices = [self.device("A", ready_at=2), self.device("B", ready_at=4)]
        HIL.arm_lab(devices)
        self.assertEqual(self.clock.now, 4)
        self.assertEqual(self.sleep.call_count, 8)
        for device in devices:
            self.assertGreater(device.command.call_count, 2)
            self.assertEqual(device.checked.call_count, 6)
            writes = [call.args[0] for call in device.checked.call_args_list
                      if call.args[0] != "ota config"]
            self.assertEqual(len(writes), len(set(writes)))

    def test_arm_never_accepts_saved_sf6_rx_as_live_sf5_rxtx_and_times_out(self):
        devices = [self.device("A", secondary="909.500,500.000,6,5,rx,32"), self.device("B")]
        with self.assertRaisesRegex(HIL.TestFailure, "A: temporary lab profiles were not activated"):
            HIL.arm_lab(devices)
        self.assertEqual(self.clock.now, 30)
        self.assertEqual(devices[0].checked.call_count, 5)
        devices[1].command.assert_not_called()
        for device in devices:
            self.assertNotIn("ota config", [call.args[0] for call in device.checked.call_args_list])
            self.assertEqual(device.checked.call_count, 5)

    def test_arm_rejects_auto_policy_even_when_both_live_profiles_match(self):
        devices = [self.device("A", policy="autofetch=on autoinstall=off hops=0"), self.device("B")]
        with self.assertRaisesRegex(HIL.TestFailure, "Manual-only one-hop OTA policy"):
            HIL.arm_lab(devices)
        devices[1].command.assert_not_called()
        self.sleep.assert_not_called()

    def test_activation_getter_can_take_eight_seconds_without_short_read_timeout(self):
        device = self.device("A", getter_delays={"get tempradio": 8})
        HIL.arm_lab([device])
        self.assertEqual(self.clock.now, 8)
        self.assertEqual(device.command.call_args_list,
                         [mock.call("get tempradio", timeout=30), mock.call("get tempradio2", timeout=22)])
        self.assertEqual(device.checked.call_count, 6)

    def test_each_board_has_its_own_30_second_activation_deadline(self):
        devices = [self.device(name, getter_delays={"get tempradio": 20}) for name in ("A", "B")]
        HIL.arm_lab(devices)
        self.assertEqual(self.clock.now, 40)
        for device in devices:
            self.assertEqual(device.command.call_args_list,
                             [mock.call("get tempradio", timeout=30), mock.call("get tempradio2", timeout=10)])

    def test_matching_profiles_received_at_expired_deadline_are_not_accepted(self):
        device = self.device("A", getter_delays={"get tempradio": 8, "get tempradio2": 22})
        with self.assertRaisesRegex(HIL.TestFailure, "not activated in time"):
            HIL.arm_lab([device])
        self.assertEqual(self.clock.now, 30)
        self.assertEqual(device.checked.call_count, 5)
        self.assertNotIn("ota config", [call.args[0] for call in device.checked.call_args_list])


class NormalModeTests(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.trace = []
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(mock.patch.object(HIL.time, "monotonic", self.clock.monotonic))
        self.stack.enter_context(mock.patch.object(HIL.time, "sleep", self.clock.sleep))

    def device(self, name, active=True, ready_at=0, ota_active=False):
        state = SimpleNamespace(primary_off=not active, secondary_off=not active)

        def command(command, timeout=5):
            self.trace.append((name, "read", command))
            if command == "ota status":
                text = "OTA | fw lab | download: pulling 1/3 | serving:1" if ota_active else \
                    "OTA | fw lab | no download | serving:1"
            elif command == "get tempradio":
                text = "off" if state.primary_off and self.clock.now >= ready_at else LabActivationTests.PRIMARY
            elif command == "get tempradio2":
                text = "off" if state.secondary_off and self.clock.now >= ready_at else LabActivationTests.SECONDARY
            else:
                raise AssertionError("Unexpected normal-mode getter: " + command)
            return "\r\n  -> > " + text + "\r\n"

        def checked(command, timeout=5):
            self.trace.append((name, "write", command))
            if command == "normalradio":
                state.primary_off = True
            elif command == "set tempradio2 off":
                state.secondary_off = True
            else:
                raise AssertionError("Unexpected normal-mode mutation: " + command)
            return "OK"

        return SimpleNamespace(name=name, serial_number=ContinuationTests.SERIALS[ord(name)-ord("A")],
                               state=state, command=mock.Mock(side_effect=command),
                               checked=mock.Mock(side_effect=checked), close=mock.Mock())

    def test_disarm_checks_both_receivers_before_any_write_and_never_resends(self):
        devices = [self.device("A", ready_at=1), self.device("B", ready_at=2)]
        HIL.disarm_lab(devices)
        first_write = next(n for n, row in enumerate(self.trace) if row[1] == "write")
        self.assertEqual(self.trace[:first_write], [("A", "read", "ota status"),
                                                  ("B", "read", "ota status")])
        for device in devices:
            self.assertEqual(device.checked.call_args_list,
                             [mock.call("normalradio", timeout=30), mock.call("set tempradio2 off", timeout=30)])
            self.assertGreater(device.command.call_count, 3)
        self.assertEqual(self.clock.now, 2)

    def test_active_download_on_either_peer_prevents_every_disarm_write(self):
        for active in ("A", "B"):
            with self.subTest(active=active):
                devices = [self.device(name, ota_active=name == active) for name in ("A", "B")]
                with self.assertRaisesRegex(HIL.TestFailure, "cannot disarm a live OTA download"):
                    HIL.disarm_lab(devices)
                for device in devices:
                    device.checked.assert_not_called()

    def test_disarm_activation_timeout_fails_closed_without_repeated_mutations(self):
        devices = [self.device("A", ready_at=100), self.device("B")]
        with self.assertRaisesRegex(HIL.TestFailure, "baseline deadline"):
            HIL.disarm_lab(devices)
        self.assertEqual(self.clock.now, 30)
        for device in devices:
            self.assertEqual(device.checked.call_count, 2)
        for call in devices[0].command.call_args_list:
            if call.args[0] != "ota status":
                self.assertTrue(0 < call.kwargs["timeout"] <= 5)

    def test_normal_profile_validation_is_read_only_and_rejects_either_overlay(self):
        for primary, secondary in ((True, False), (False, True)):
            with self.subTest(primary=primary, secondary=secondary):
                device = self.device("A", active=False)
                device.state.primary_off = not primary
                device.state.secondary_off = not secondary
                with self.assertRaisesRegex(HIL.TestFailure, "inactive temporary profiles"):
                    HIL.require_normal_profiles([device])
                device.checked.assert_not_called()
        devices = [self.device("A", active=False), self.device("B", active=False)]
        HIL.require_normal_profiles(devices)
        for device in devices:
            device.checked.assert_not_called()

    def run_main(self, action="run", start_source="b", rounds=2, active=True):
        devices = [self.device("A", active=active), self.device("B", active=active)]
        report = SimpleNamespace(data={"rounds": []}, save=mock.Mock(), event=mock.Mock())
        apps = {"A": 0, "B": 1}
        directions = []

        def snapshot(device):
            self.assertTrue(device.state.primary_off and device.state.secondary_off)
            return {"private_key_sha256": device.name * 64, "settings": {"advert.interval": "0"}}

        def finish_round(number, source, receiver, peers, expected_hash, baseline, args, output, continuing):
            self.assertIsNone(continuing)
            directions.append((source.name, receiver.name))
            output.data["rounds"].append({
                "source_slot": {"inactive_address": 0x10000 if apps[source.name] else 0x310000},
                "receiver_slot_before": {"inactive_address": 0x10000 if apps[receiver.name] else 0x310000},
            })
            apps[receiver.name] = 1 - apps[receiver.name]

        with mock.patch.object(HIL, "Report", return_value=report), \
                mock.patch.object(HIL, "V4Device", side_effect=devices), \
                mock.patch.object(HIL, "preflight", return_value=[]), \
                mock.patch.object(HIL, "prepare") as prepare, \
                mock.patch.object(HIL, "snapshot", side_effect=snapshot) as snapshots, \
                mock.patch.object(HIL, "run_round", side_effect=finish_round) as run:
            result = HIL.main([action, "--serial-a", ContinuationTests.SERIALS[0],
                               "--serial-b", ContinuationTests.SERIALS[1],
                               "--expected-body-hash16", ContinuationTests.HASH,
                               "--rounds", str(rounds), "--start-source", start_source,
                               "--report", "unused.json"])
        prepare.assert_not_called()
        return result, report, devices, directions, snapshots, run

    def test_fresh_run_takes_normal_advert_baseline_then_starts_from_b(self):
        code, report, devices, directions, snapshots, _run = self.run_main()
        self.assertEqual(code, 0)
        self.assertEqual(directions, [("B", "A"), ("A", "B")])
        self.assertEqual(report.data["baseline_mode"], HIL.BASELINE_MODE)
        self.assertEqual(snapshots.call_count, 2)
        self.assertTrue(all(value["settings"]["advert.interval"] == "0"
                            for value in report.data["baseline"].values()))
        for device in devices:
            self.assertEqual(device.checked.call_count, 2)
        # Both new sources run appB; original A-appA transfer is needed to
        # complete source coverage across the separate real-hardware reports.
        self.assertFalse(report.data["both_source_slots_covered"])
        self.assertTrue(report.data["both_destination_slots_covered"])
        source_slots = {row["source_slot"]["inactive_address"] for row in report.data["rounds"]}
        self.assertEqual(len(source_slots | {0x310000}), 2)

    def test_three_rounds_starting_b_measure_both_source_and_destination_slots(self):
        code, report, _devices, directions, _snapshots, _run = self.run_main(rounds=3)
        self.assertEqual(code, 0)
        self.assertEqual(directions, [("B", "A"), ("A", "B"), ("B", "A")])
        self.assertTrue(report.data["both_source_slots_covered"])
        self.assertTrue(report.data["both_destination_slots_covered"])

    def test_probe_never_disarms_and_fails_before_snapshot_if_temp_is_active(self):
        code, report, devices, _directions, snapshots, run = self.run_main(action="probe", active=True)
        self.assertEqual(code, 1)
        self.assertIn("inactive temporary profiles", report.data["failure"])
        snapshots.assert_not_called()
        run.assert_not_called()
        for device in devices:
            device.checked.assert_not_called()

    def test_probe_accepts_normal_profile_getters_without_any_mutation(self):
        code, report, devices, _directions, snapshots, run = self.run_main(action="probe", active=False)
        self.assertEqual(code, 0)
        self.assertEqual(report.data["baseline_mode"], HIL.BASELINE_MODE)
        self.assertEqual(snapshots.call_count, 2)
        run.assert_not_called()
        for device in devices:
            device.checked.assert_not_called()


class ContinuationTests(unittest.TestCase):
    HASH = "0123456789ABCDEF"
    MID = "DEADBEEF"
    SERIALS = ("441BF669CF98", "441BF669C9C0")

    @staticmethod
    def raw(text):
        return "\r\n  -> > " + text + "\r\n"

    def fixture(self):
        state = SimpleNamespace(
            clock=FakeClock(), downtime=0,
            receiver_reconnected=False,
            info={"body_bytes": 4000, "image_bytes": 4112, "body_hash16": self.HASH},
            source_slot={"inactive_address": 0x310000, "size_bytes": 0x300000},
            receiver_slot={"inactive_address": 0x310000, "size_bytes": 0x300000},
            primary=LabActivationTests.PRIMARY, secondary=LabActivationTests.SECONDARY,
            serve_status="default:on serving:on", serve_mid=self.MID, stats_suffix="",
            statuses=[("pulling", 1, 3, self.MID), ("pulling", 2, 3, self.MID),
                      ("ready to install", 3, 3, self.MID)],
            baseline={
                "A": {"private_key_sha256": "aa", "acl": [], "settings": {
                    "name": "SelfOTA_A", "advert.interval": "0", "flood.advert.interval": "0"}},
                "B": {"private_key_sha256": "bb", "acl": [], "settings": {
                    "name": "SelfOTA_B", "advert.interval": "0", "flood.advert.interval": "0"}},
            },
        )
        state.entry = {
            "round": 1, "source": "A", "receiver": "B", "result": "RUNNING",
            "source_slot": copy.deepcopy(state.source_slot),
            "receiver_slot_before": copy.deepcopy(state.receiver_slot),
            "source_self": copy.deepcopy(state.info), "manifest_id": self.MID,
            "progress": [{"done": 1, "total": 3, "elapsed_seconds": 10,
                          "utc": "2001-09-09T01:46:40Z"}],
        }
        state.after_snapshot = copy.deepcopy(state.baseline["B"])
        state.snapshot_calls = []

        def slot_reply(slot):
            return self.raw("inactive slot addr=0x%x size=%u" %
                            (slot["inactive_address"], slot["size_bytes"]))

        def source_command(command):
            if command == "ota self":
                return self.raw("self body=%u image=%u base_hash=%s" %
                                (state.info["body_bytes"], state.info["image_bytes"],
                                 state.info["body_hash16"]))
            if command == "ota dev apply slot":
                return slot_reply(state.source_slot)
            if command == "get tempradio":
                return self.raw(state.primary)
            if command == "get tempradio2":
                return self.raw(state.secondary)
            raise AssertionError("Unexpected source command: " + command)

        def source_checked(command, timeout=5):
            if command == "ota serve status":
                return state.serve_status
            if command == "ota stats":
                return "OTA | fw lab id=" + state.serve_mid + state.stats_suffix
            raise AssertionError("Continuation must not mutate source: " + command)

        state.receiver_slot_reads = 0

        def receiver_command(command):
            if command == "ota dev apply slot":
                state.receiver_slot_reads += 1
                return slot_reply(state.receiver_slot if state.receiver_slot_reads == 1 else
                                  dict(state.receiver_slot, inactive_address=0x10000))
            if command == "get tempradio":
                return self.raw("off" if state.receiver_reconnected else state.primary)
            if command == "get tempradio2":
                return self.raw("off" if state.receiver_reconnected else state.secondary)
            if command == "ota status":
                status, done, total, mid = state.statuses.pop(0)
                return self.raw("download: %s %u/%u pace=1.0x id=%s" % (status, done, total, mid))
            raise AssertionError("Unexpected receiver command: " + command)

        def receiver_checked(command, timeout=5):
            if command != "ota install":
                raise AssertionError("Continuation must not restart receiver: " + command)
            self.assertIn("install_requested_utc", state.entry)
            self.assertIn("install_requested_utc", state.saved_entries[-1])
            return "OK installing"

        state.source = SimpleNamespace(name="A", serial_number=self.SERIALS[0],
                                       command=mock.Mock(side_effect=source_command),
                                       checked=mock.Mock(side_effect=source_checked), close=mock.Mock())
        state.receiver = SimpleNamespace(name="B", serial_number=self.SERIALS[1],
                                         command=mock.Mock(side_effect=receiver_command),
                                         checked=mock.Mock(side_effect=receiver_checked), close=mock.Mock(),
                                         reconnect=mock.Mock())

        def reconnect(expected_hash):
            state.receiver_reconnected = True
            return copy.deepcopy(state.info)

        state.receiver.reconnect.side_effect = reconnect
        state.saved_entries = []
        state.report = SimpleNamespace(
            data={"rounds": [state.entry]}, event=mock.Mock(),
            save=mock.Mock(side_effect=lambda: state.saved_entries.append(copy.deepcopy(state.entry))))
        state.args = SimpleNamespace(timeout=10, stall_timeout=5, poll_interval=1)
        return state

    def run_continuation(self, state):
        def snapshot(receiver):
            self.assertIs(receiver, state.receiver)
            self.assertTrue(state.receiver_reconnected)
            self.assertEqual([call.args[0] for call in receiver.command.call_args_list[-2:]],
                             ["get tempradio", "get tempradio2"])
            state.snapshot_calls.append(receiver.name)
            return state.after_snapshot

        with mock.patch.object(HIL.time, "monotonic", state.clock.monotonic), \
                mock.patch.object(HIL.time, "sleep", state.clock.sleep), \
                mock.patch.object(HIL.time, "time", return_value=1000000000 + state.downtime), \
                mock.patch.object(HIL, "arm_lab") as arm, \
                mock.patch.object(HIL, "snapshot", side_effect=snapshot):
            HIL.run_round(1, state.source, state.receiver, [state.source, state.receiver], self.HASH,
                          state.baseline, state.args, state.report, continuing=state.entry)
        arm.assert_not_called()

    def test_valid_continuation_preserves_progress_and_never_restarts_rf_session(self):
        state = self.fixture()
        self.run_continuation(state)
        self.assertEqual(state.entry["result"], "PASS")
        self.assertTrue(state.entry["preservation"]["equal"])
        self.assertTrue(state.entry["intermediate_rf_progress_observed"])
        self.assertEqual([p["done"] for p in state.entry["progress"]], [1, 2, 3])
        self.assertEqual(state.entry["download_seconds"], 11)
        self.assertIn("install_requested_utc", state.entry)
        self.assertEqual([call.args[0] for call in state.source.checked.call_args_list],
                         ["ota serve status", "ota stats"])
        state.receiver.checked.assert_called_once_with("ota install", timeout=30)
        state.receiver.reconnect.assert_called_once_with(self.HASH)
        self.assertEqual(len(state.report.data["rounds"]), 1)

    def test_mismatched_live_continuation_fails_before_install(self):
        def mutate(state, case):
            if case == "hash":
                state.info["body_hash16"] = "FFFFFFFFFFFFFFFF"
            elif case == "source slot":
                state.source_slot["inactive_address"] = 0x10000
            elif case == "receiver slot":
                state.receiver_slot["inactive_address"] = 0x10000
            elif case == "source geometry":
                state.info["body_bytes"] += 1
            elif case == "direction":
                state.entry["receiver"] = "A"
            elif case == "completed":
                state.entry["result"] = "PASS"
            elif case == "installing":
                state.entry["install_reply"] = "OK"
            elif case == "install requested":
                state.entry["install_requested_utc"] = "2001-09-09T01:46:40Z"
            elif case == "invalid manifest":
                state.entry["manifest_id"] = "not-a-mid"
            elif case == "serving manifest":
                state.serve_mid = "AAAAAAAA"
            elif case == "receive id cannot prove serving id":
                state.serve_mid = "AAAAAAAA"
                state.stats_suffix = " | download id=" + self.MID
            elif case == "not serving":
                state.serve_status = "default:on serving:off"
            elif case == "receive manifest":
                state.statuses[0] = ("pulling", 1, 3, "AAAAAAAA")
            elif case == "receive geometry":
                state.statuses[0] = ("pulling", 1, 4, self.MID)
            elif case == "lost progress":
                state.statuses[0] = ("pulling", 0, 3, self.MID)
            elif case == "primary profile":
                state.primary = "910.525,500.000,5,5,32"
            elif case == "secondary profile":
                state.secondary = "909.500,500.000,6,5,rx,32"

        for case in ("hash", "source slot", "receiver slot", "source geometry", "direction",
                     "completed", "installing", "install requested", "invalid manifest", "serving manifest",
                     "receive id cannot prove serving id", "not serving",
                     "receive manifest", "receive geometry", "lost progress", "primary profile",
                     "secondary profile"):
            with self.subTest(case=case):
                state = self.fixture()
                mutate(state, case)
                with self.assertRaises(HIL.TestFailure):
                    self.run_continuation(state)
                state.receiver.checked.assert_not_called()
                state.receiver.reconnect.assert_not_called()

    def test_live_adoption_count_cannot_regress_on_first_followup_poll(self):
        state = self.fixture()
        state.statuses = [("pulling", 2, 3, self.MID), ("pulling", 1, 3, self.MID)]
        with self.assertRaisesRegex(HIL.TestFailure, "completed-block count moved backwards"):
            self.run_continuation(state)
        state.receiver.checked.assert_not_called()

    def test_geometry_is_rechecked_after_initial_adoption(self):
        state = self.fixture()
        state.statuses = [("pulling", 1, 3, self.MID), ("pulling", 2, 4, self.MID)]
        with self.assertRaisesRegex(HIL.TestFailure, "block geometry changed"):
            self.run_continuation(state)
        state.receiver.checked.assert_not_called()

    def test_observer_downtime_is_included_in_elapsed_transfer_pace(self):
        state = self.fixture()
        state.downtime = 7
        self.run_continuation(state)
        self.assertEqual(state.entry["download_seconds"], 18)
        self.assertEqual(state.entry["progress"][-1]["elapsed_seconds"], 18)

    def test_transport_interruption_after_install_send_leaves_persisted_intent(self):
        state = self.fixture()
        state.receiver.checked.side_effect = HIL.TestFailure("CLI reply marker was not received for ota install")
        with self.assertRaisesRegex(HIL.TestFailure, "marker was not received"):
            self.run_continuation(state)
        self.assertIn("install_requested_utc", state.entry)
        self.assertNotIn("install_reply", state.entry)
        self.assertIn("install_requested_utc", state.saved_entries[-1])
        state.receiver.checked.assert_called_once_with("ota install", timeout=30)
        state.receiver.reconnect.assert_not_called()

    def test_post_install_temp_overlay_fails_before_saved_setting_snapshot(self):
        state = self.fixture()
        state.receiver.reconnect.side_effect = None
        state.receiver.reconnect.return_value = copy.deepcopy(state.info)
        with self.assertRaisesRegex(HIL.TestFailure, "inactive temporary profiles"):
            self.run_continuation(state)
        self.assertEqual(state.snapshot_calls, [])

    def test_post_install_normal_snapshot_rechecks_original_saved_advert_interval(self):
        state = self.fixture()
        state.after_snapshot["settings"]["advert.interval"] = "60"
        with self.assertRaisesRegex(HIL.TestFailure, "saved settings changed across OTA install"):
            self.run_continuation(state)
        self.assertEqual(state.snapshot_calls, ["B"])
        self.assertEqual(state.entry["preservation"], {"equal": False, "changed_fields": ["settings"]})

    def previous_report(self, state):
        return {"schema": 1, "action": "run", "expected_body_hash16": self.HASH,
                "baseline_mode": HIL.BASELINE_MODE, "first_source": "a",
                "lab_radio": HIL.LAB_RADIO, "requested_rounds": 1, "result": "ABORTED",
                "baseline": copy.deepcopy(state.baseline), "rounds": [copy.deepcopy(state.entry)],
                "devices": {name: {"identity": {"usb_serial": serial}}
                            for name, serial in zip(("A", "B"), self.SERIALS)}}

    def call_main(self, state, previous):
        report = SimpleNamespace(data={"rounds": []}, save=mock.Mock(), event=mock.Mock())
        live = copy.deepcopy(state.baseline)
        for value in live.values():
            value["settings"]["advert.interval"] = "60"

        def preflight(devices, expected_hash, output):
            output.data["devices"] = copy.deepcopy(previous["devices"])
            return ["AB" * 32, "CD" * 32]

        def finish_round(*args):
            args[-1]["result"] = "PASS"

        with tempfile.TemporaryDirectory() as folder:
            previous_path = Path(folder) / "previous.json"
            previous_path.write_text(json.dumps(previous), encoding="utf-8")
            with mock.patch.object(HIL, "Report", return_value=report), \
                    mock.patch.object(HIL, "V4Device", side_effect=[state.source, state.receiver]), \
                    mock.patch.object(HIL, "preflight", side_effect=preflight), \
                    mock.patch.object(HIL, "prepare") as prepare, \
                    mock.patch.object(HIL, "disarm_lab") as disarm, \
                    mock.patch.object(HIL, "snapshot", side_effect=[live["A"], live["B"]]), \
                    mock.patch.object(HIL, "run_round", side_effect=finish_round) as run:
                result = HIL.main(["run", "--serial-a", self.SERIALS[0], "--serial-b", self.SERIALS[1],
                                   "--expected-body-hash16", self.HASH, "--rounds", "1",
                                   "--report", str(Path(folder) / "new.json"),
                                   "--continue-report", str(previous_path)])
        prepare.assert_not_called()
        disarm.assert_not_called()
        return result, report, run

    def test_main_accepts_matching_baseline_for_interrupted_or_timed_out_observer(self):
        for result in ("ABORTED", "FAIL"):
            with self.subTest(result=result):
                state = self.fixture()
                previous = self.previous_report(state)
                previous["result"] = result
                if result == "FAIL":
                    previous["failure"] = "OTA download exceeded its per-round timeout"
                code, report, run = self.call_main(state, previous)
                self.assertEqual(code, 0)
                self.assertEqual(report.data["result"], "PASS")
                self.assertEqual(report.data["baseline"], previous["baseline"])
                self.assertEqual(run.call_count, 1)
                self.assertIs(run.call_args.args[-1], report.data["rounds"][0])
                self.assertIn("continued_from", report.data)

    def test_live_continuation_defers_only_local_advert_and_keeps_all_other_settings_strict(self):
        saved = self.fixture().baseline["A"]
        original = copy.deepcopy(saved)
        live = copy.deepcopy(saved)
        live["settings"]["advert.interval"] = "60"
        self.assertTrue(HIL.live_snapshot_matches_saved(saved, live))
        self.assertEqual(saved, original)
        for key in ("name", "radio", "radio2", "flood.advert.interval"):
            with self.subTest(key=key):
                changed = copy.deepcopy(live)
                changed["settings"][key] = "changed"
                self.assertFalse(HIL.live_snapshot_matches_saved(saved, changed))
        for value in ("0", "59", "61"):
            with self.subTest(local_advert=value):
                changed = copy.deepcopy(live)
                changed["settings"]["advert.interval"] = value
                self.assertFalse(HIL.live_snapshot_matches_saved(saved, changed))

    def test_main_rejects_changed_key_acl_name_or_radio_settings_before_any_round(self):
        for field in ("private_key_sha256", "acl", "name", "radio", "radio2"):
            with self.subTest(field=field):
                state = self.fixture()
                previous = self.previous_report(state)
                if field in ("private_key_sha256", "acl"):
                    previous["baseline"]["A"][field] = "changed"
                else:
                    previous["baseline"]["A"]["settings"][field] = "changed"
                code, report, run = self.call_main(state, previous)
                self.assertEqual(code, 1)
                self.assertEqual(report.data["failure"], "Identity, ACL or settings changed before continuation")
                run.assert_not_called()

    def test_main_rejects_invalid_definition_identity_or_pending_round(self):
        for case in ("schema", "hash", "radio", "round count", "baseline mode", "first source", "not interrupted",
                     "other failure", "physical identity", "empty progress", "completed round"):
            with self.subTest(case=case):
                state = self.fixture()
                previous = self.previous_report(state)
                if case == "schema":
                    previous["schema"] = 2
                elif case == "hash":
                    previous["expected_body_hash16"] = "FFFFFFFFFFFFFFFF"
                elif case == "radio":
                    previous["lab_radio"] = "910.525,500,5,5"
                elif case == "round count":
                    previous["requested_rounds"] = 3
                elif case == "baseline mode":
                    previous.pop("baseline_mode")
                elif case == "first source":
                    previous["first_source"] = "b"
                elif case == "not interrupted":
                    previous["result"] = "RUNNING"
                elif case == "other failure":
                    previous.update(result="FAIL", failure="Some other failure")
                elif case == "physical identity":
                    previous["devices"]["A"]["identity"]["usb_serial"] = "OTHER"
                elif case == "empty progress":
                    previous["rounds"][0]["progress"] = []
                elif case == "completed round":
                    previous["rounds"][0]["result"] = "PASS"
                code, report, run = self.call_main(state, previous)
                self.assertEqual(code, 1)
                self.assertEqual(report.data["result"], "FAIL")
                run.assert_not_called()

    def test_continuation_refuses_prepare_or_probe_before_creating_devices(self):
        for action, extra in (("run", ["--prepare"]), ("prepare", []), ("probe", [])):
            with self.subTest(action=action), mock.patch.object(HIL, "Report") as report, \
                    mock.patch.object(HIL, "V4Device") as devices, \
                    contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as raised:
                    HIL.main([action, "--serial-a", self.SERIALS[0], "--serial-b", self.SERIALS[1],
                              "--expected-body-hash16", self.HASH, "--report", "unused.json",
                              "--continue-report", "previous.json"] + extra)
                self.assertEqual(raised.exception.code, 2)
                report.assert_not_called()
                devices.assert_not_called()


class ConnectionTests(unittest.TestCase):
    def test_native_usb_session_holds_dtr_and_keeps_rts_low(self):
        device = HIL.V4Device("A", "44:1b:f6:69:cf:98")
        serial_instance = mock.Mock()
        serial_module = SimpleNamespace(Serial=mock.Mock(return_value=serial_instance))
        port = SimpleNamespace(device="/dev/ttyACM9", vid=0x303A, pid=0x1001)
        with mock.patch.dict(sys.modules, {"serial": serial_module}), \
                mock.patch.object(HIL, "find_port", return_value=port), \
                mock.patch.object(device, "read", return_value=""), \
                mock.patch.object(device, "_command", side_effect=[
                    "\r\n  -> Heltec V4.3 OLED\r\n", "\r\n  -> > repeater\r\n"]):
            device.connect()
        self.assertIs(device.stream, serial_instance)
        self.assertTrue(serial_instance.dtr)
        self.assertFalse(serial_instance.rts)
        serial_instance.open.assert_called_once_with()
        self.assertEqual(device.identity["usb_serial"], "441BF669CF98")
        self.assertEqual(device.connections, 1)

    def reconnect_case(self, startup_error):
        device = HIL.V4Device("A", "441BF669CF98")
        clock = FakeClock()
        reply = "\r\n  -> self body=1600000 image=1600200 base_hash=0123456789ABCDEF\r\n"
        with mock.patch.object(device, "close") as close, \
                mock.patch.object(device, "connect", side_effect=[startup_error, None]) as connect, \
                mock.patch.object(device, "command", return_value=reply) as command, \
                mock.patch.object(HIL.time, "monotonic", clock.monotonic), \
                mock.patch.object(HIL.time, "sleep", clock.sleep):
            result = device.reconnect("0123456789ABCDEF", timeout=10)
        self.assertEqual(result["body_hash16"], "0123456789ABCDEF")
        self.assertEqual(connect.call_count, 2)
        self.assertEqual(close.call_count, 2)
        command.assert_called_once_with("ota self")

    def test_reconnect_retries_missing_startup_marker(self):
        self.reconnect_case(HIL.TestFailure("A: CLI reply marker was not received for board"))

    def test_reconnect_never_retries_wrong_identity_role_or_image_hash(self):
        for error in ("USB identity is not a Heltec V4", "Board firmware role is not Repeater",
                      "Running firmware hash changed after reconnect"):
            with self.subTest(error=error):
                device = HIL.V4Device("A", "441BF669CF98")
                with mock.patch.object(device, "close"), \
                        mock.patch.object(device, "connect", side_effect=HIL.TestFailure(error)) as connect, \
                        mock.patch.object(HIL.time, "sleep") as sleep:
                    with self.assertRaisesRegex(HIL.TestFailure, error):
                        device.reconnect("0123456789ABCDEF", timeout=10)
                connect.assert_called_once_with()
                sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main()
