"""Offline policy and lifecycle tests; no radio access or firmware writes."""
import argparse
import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import lora_ota as ota
from test_lora_ota import firmware, mota_blob, target, VERSION_NEW


class Stations:
    def __init__(self, relays=1, source_hops=0, target_hops=0):
        self.hops = {"source": source_hops, "remote": target_hops,
                     **{f"relay{i}": 0 for i in range(relays)}}
        self.calls = []
        self.events = []
        self.lost = set()
        self.fail_reads = set()
        self.overrides = {}
        self.seeding = False
        self.normal = ota.RadioSettings(910.525, 62.5, 7, 5, False)

    def command(self, name, command, **options):
        self.calls.append((name, command, options))
        if name in self.fail_reads and command == "ota config":
            raise ota.TransmissionError("lost config read")
        if (name, command) in self.overrides:
            return self.overrides[name, command]
        if command == "ota folder off":
            return "OK"
        if command == "ota config":
            return f"ota config: autofetch=off autoinstall=off hops={self.hops[name]} keys=0"
        if command.startswith("ota config hops "):
            if name == "source" and self.seeding:
                raise AssertionError("source text CLI used while seeder owns serial")
            value = int(command.rsplit(" ", 1)[1])
            self.hops[name] = value
            self.events.append(f"set:{name}:{value}")
            if (name, value) in self.lost:
                self.lost.remove((name, value))
                raise ota.TransmissionError("lost setting acknowledgement")
            return f"OK OTA reach = {value} hops (saved)" + (" - direct only" if value == 0 else "")
        raise AssertionError((name, command))

    def remote_command(self, name, command, **options):
        return self.command(name, command, **options)

    def source_cli(self, _args, command, **options):
        return self.command("source", command, **options)

    def get_radio(self):
        return self.normal

    def set_radio(self, _radio, _label):
        self.events.append("controller-restore")

    def close(self):
        pass


def arguments(relays=1, minimum=None):
    return argparse.Namespace(
        target="remote", relay_values=[(f"relay{i}", "relay-secret") for i in range(relays)],
        ota_hops=minimum, source_serial="/dev/source", source_cli_serial=None,
        source_cli_tcp=None, source_contact_value="source",
    )


class OtaHopTests(unittest.TestCase):
    def setUp(self):
        self.output = contextlib.redirect_stdout(io.StringIO())
        self.output.__enter__()
        self.addCleanup(self.output.__exit__, None, None, None)
        self.sleep = mock.patch.object(ota.time, "sleep")
        self.sleep.start()
        self.addCleanup(self.sleep.stop)

    def test_config_parser_accepts_legacy_and_terminal_banners(self):
        for hops in range(9):
            reply = f"ota config: cache=off/0 autofetch=off advert=1440min hops={hops} keys=0"
            self.assertEqual(ota.parse_ota_hops(reply, "station"), hops)
            self.assertEqual(ota.parse_ota_hops(f"WELCOME\n> ota config\n> {reply}\r\n> ", "station"), hops)

    def test_parser_rejects_missing_ambiguous_malformed_and_error_values(self):
        for reply in ("", "ERR permission denied", "Unknown command", "OTA | hops=0",
                      "ota config: hops=9", "ota config: hops=-1", "ota config: hops=1foo",
                      "ota config: hops=1 hops=1", "ota config: advert=1440",
                      "ota config: hops=1\nota config: hops=2"):
            with self.subTest(reply=reply), self.assertRaises(ota.OtaError):
                ota.parse_ota_hops(reply, "station")

    def test_command_reply_matching_does_not_accept_unrelated_ok(self):
        self.assertTrue(ota.reply_matches_command("ota config", "ota config: hops=0"))
        self.assertTrue(ota.reply_matches_command("ota config", "LoRa OTA not included in this build"))
        self.assertTrue(ota.reply_matches_command("ota config", "LoRa OTA is not included in this build; tempradio cannot enable it."))
        self.assertTrue(ota.reply_matches_command("ota config hops 1", "OK OTA reach = 1 hop (saved)"))
        self.assertFalse(ota.reply_matches_command("ota config hops 1", "OK - temp params for 1 mins"))

    def test_direct_run_has_no_policy_queries_or_writes(self):
        stations = Stations(0)
        with mock.patch.object(ota, "source_cli_command", side_effect=stations.source_cli):
            self.assertEqual(ota.prepare_ota_hop_settings(stations, arguments(0)), [])
        self.assertEqual(stations.calls, [])

    def test_infers_route_count_preserves_higher_limits_and_restores(self):
        for count in (1, 2, 3, 8):
            with self.subTest(relays=count), tempfile.TemporaryDirectory() as directory:
                stations = Stations(count)
                stations.hops["relay0"] = 8
                original = stations.hops.copy()
                args = arguments(count)
                owned = []
                with mock.patch.object(ota, "source_cli_command", side_effect=stations.source_cli):
                    settings = ota.prepare_ota_hop_settings(stations, args)
                    self.assertTrue(all(s.minimum == count for s in settings))
                    ota.apply_ota_hop_settings(stations, args, settings, owned, Path(directory))
                    self.assertEqual(stations.hops["remote"], count)
                    self.assertEqual(stations.hops["source"], count)
                    self.assertEqual(stations.hops["relay0"], 8)
                    ota.restore_ota_hop_settings(stations, args, owned)
                self.assertEqual(stations.hops, original)
                self.assertEqual(owned, [])
                self.assertFalse(any(name == "relay0" and cmd.startswith("ota config hops ")
                                     for name, cmd, _ in stations.calls))
                remote_writes = [options for name, cmd, options in stations.calls
                                 if name != "source" and cmd.startswith("ota config hops ")]
                self.assertTrue(all(options["retry"] is False for options in remote_writes))
                relay_options = [options for name, _cmd, options in stations.calls if name.startswith("relay")]
                self.assertTrue(all(options["password"] == "relay-secret" for options in relay_options))

    def test_explicit_minimum_handles_additional_undeclared_hops(self):
        stations = Stations(0)
        with mock.patch.object(ota, "source_cli_command", side_effect=stations.source_cli):
            settings = ota.prepare_ota_hop_settings(stations, arguments(0, 3))
        self.assertEqual([s.transfer for s in settings], [3, 3])

    def test_higher_limits_produce_no_recovery_file_or_changes(self):
        stations = Stations(source_hops=4, target_hops=3)
        stations.hops["relay0"] = 2
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.object(ota, "source_cli_command", side_effect=stations.source_cli):
                settings = ota.prepare_ota_hop_settings(stations, arguments())
                ota.apply_ota_hop_settings(stations, arguments(), settings, [], Path(directory))
            self.assertFalse((Path(directory) / ota.OTA_HOPS_RECOVERY_FILE).exists())
        self.assertFalse(stations.events)

    def test_unknown_source_or_relay_stops_before_any_setting_change(self):
        for name in ("source", "remote", "relay0"):
            for reply in ("Unknown command", "ERR permission denied", "ota config: hops=9", ""):
                with self.subTest(name=name, reply=reply):
                    stations = Stations()
                    stations.overrides[name, "ota config"] = reply
                    with mock.patch.object(ota, "source_cli_command", side_effect=stations.source_cli):
                        with self.assertRaises(ota.OtaError):
                            ota.prepare_ota_hop_settings(stations, arguments())
                    self.assertEqual(stations.events, [])

    def test_explicit_non_ota_relay_is_left_opaque(self):
        stations = Stations()
        stations.overrides["relay0", "ota config"] = "LoRa OTA is not included in this build; tempradio cannot enable it. Use an OTA-enabled repeater firmware"
        with mock.patch.object(ota, "source_cli_command", side_effect=stations.source_cli):
            settings = ota.prepare_ota_hop_settings(stations, arguments())
        self.assertEqual([s.name for s in settings], ["source", "remote"])

    def test_setter_reply_lost_without_delivery_stops_without_replaying(self):
        stations = Stations()
        saved = ota.OtaHopSettings("remote", None, False, 0, 1)
        with mock.patch.object(stations, "remote_command", side_effect=[
            ota.TransmissionError("not delivered"), "ota config: hops=0",
        ]) as command:
            with self.assertRaisesRegex(ota.OtaError, "did not read back"):
                ota.set_ota_hops_verified(stations, arguments(), saved, 1)
        self.assertEqual([c.args[1] for c in command.call_args_list], ["ota config hops 1", "ota config"])

    def test_recovery_write_failure_prevents_any_mutation(self):
        stations = Stations()
        owned = []
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.object(ota, "source_cli_command", side_effect=stations.source_cli):
                settings = ota.prepare_ota_hop_settings(stations, arguments())
                with mock.patch.object(ota, "write_private_recovery_file", side_effect=OSError("disk full")):
                    with self.assertRaises(OSError):
                        ota.apply_ota_hop_settings(stations, arguments(), settings, owned, Path(directory))
        self.assertFalse(stations.events)
        self.assertEqual(owned, [])

    def test_source_serial_ack_can_include_a_welcome_banner(self):
        stations = Stations()
        saved = ota.OtaHopSettings("source", None, True, 0, 1)
        with mock.patch.object(ota, "source_cli_command", side_effect=[
            "WELCOME\n> ota config hops 1\nOK OTA reach = 1 hop (saved)\n> ",
            "WELCOME\nota config: hops=1\n> ",
        ]):
            ota.set_ota_hops_verified(stations, arguments(), saved, 1)

    def test_unmanaged_source_and_excessive_route_are_rejected(self):
        for args in (arguments(9), arguments()):
            if len(args.relay_values) == 1:
                args.source_serial = None
            stations = Stations()
            with self.assertRaises(ota.OtaError):
                ota.prepare_ota_hop_settings(stations, args)
            self.assertEqual(stations.calls, [])

    def test_timeout_has_finite_read_retries_and_never_means_zero(self):
        stations = Stations()
        stations.fail_reads.add("remote")
        with mock.patch.object(ota, "source_cli_command", side_effect=stations.source_cli):
            with self.assertRaises(ota.TransmissionError):
                ota.prepare_ota_hop_settings(stations, arguments())
        self.assertEqual(len([c for c in stations.calls if c[0] == "remote"]), ota.TRANSMISSION_RETRY_LIMIT + 1)
        self.assertEqual(stations.events, [])

    def test_external_change_during_rehearsal_aborts_all_writes(self):
        stations = Stations()
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.object(ota, "source_cli_command", side_effect=stations.source_cli):
                settings = ota.prepare_ota_hop_settings(stations, arguments())
                stations.hops["relay0"] = 4
                with self.assertRaisesRegex(ota.OtaError, "changed during preparation"):
                    ota.apply_ota_hop_settings(stations, arguments(), settings, [], Path(directory))
            self.assertFalse((Path(directory) / ota.OTA_HOPS_RECOVERY_FILE).exists())
        self.assertEqual(stations.events, [])

    def test_recovery_is_private_password_free_and_durable_before_writes(self):
        stations = Stations()
        args = arguments()
        owned = []
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original_command = stations.command

            def command(name, text, **options):
                if text.startswith("ota config hops "):
                    path = root / ota.OTA_HOPS_RECOVERY_FILE
                    self.assertTrue(path.is_file())
                    self.assertTrue(any(saved.name == name for saved in owned))
                    raw = path.read_text()
                    self.assertNotIn("relay-secret", raw)
                    self.assertIn("restore_command", raw)
                    if os.name != "nt":
                        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
                return original_command(name, text, **options)

            with mock.patch.object(stations, "command", side_effect=command):
                with mock.patch.object(ota, "source_cli_command", side_effect=stations.source_cli):
                    settings = ota.prepare_ota_hop_settings(stations, args)
                    ota.apply_ota_hop_settings(stations, args, settings, owned, root)
            saved = json.loads((root / ota.OTA_HOPS_RECOVERY_FILE).read_text())
            self.assertEqual(saved["source_endpoint"]["serial"], "/dev/source")

    def test_lost_set_and_restore_acknowledgements_use_readback_without_replay(self):
        stations = Stations()
        stations.lost = {("source", 1), ("remote", 1), ("relay0", 1),
                         ("source", 0), ("remote", 0), ("relay0", 0)}
        with tempfile.TemporaryDirectory() as directory:
            owned = []
            with mock.patch.object(ota, "source_cli_command", side_effect=stations.source_cli):
                settings = ota.prepare_ota_hop_settings(stations, arguments())
                ota.apply_ota_hop_settings(stations, arguments(), settings, owned, Path(directory))
                ota.restore_ota_hop_settings(stations, arguments(), owned)
        self.assertEqual(owned, [])
        self.assertEqual(len(stations.events), 6)
        self.assertTrue(all(value == 0 for value in stations.hops.values()))

    def test_bad_readback_is_not_success_and_partial_changes_are_restored(self):
        stations = Stations()
        stations.overrides["remote", "ota config hops 1"] = "OK OTA reach = 1 hop (saved)"
        with tempfile.TemporaryDirectory() as directory:
            owned = []
            with mock.patch.object(ota, "source_cli_command", side_effect=stations.source_cli):
                settings = ota.prepare_ota_hop_settings(stations, arguments())
                with self.assertRaisesRegex(ota.OtaError, "did not read back"):
                    ota.apply_ota_hop_settings(stations, arguments(), settings, owned, Path(directory))
                self.assertEqual([s.name for s in owned], ["source", "remote"])
                ota.restore_ota_hop_settings(stations, arguments(), owned)
        self.assertEqual(owned, [])
        self.assertEqual(stations.hops["source"], 0)

    def test_restore_attempts_all_nodes_and_preserves_external_changes(self):
        stations = Stations()
        with tempfile.TemporaryDirectory() as directory:
            owned = []
            with mock.patch.object(ota, "source_cli_command", side_effect=stations.source_cli):
                settings = ota.prepare_ota_hop_settings(stations, arguments())
                ota.apply_ota_hop_settings(stations, arguments(), settings, owned, Path(directory))
                stations.hops["relay0"] = 4
                with self.assertRaisesRegex(ota.OtaError, "changed externally"):
                    ota.restore_ota_hop_settings(stations, arguments(), owned)
                self.assertEqual(stations.hops, {"source": 0, "remote": 0, "relay0": 4})
                self.assertEqual([s.name for s in owned], ["relay0"])

    def test_cli_minimum_must_cover_declared_route_and_stay_in_range(self):
        parser = ota.build_parser()
        for extra in (["--ota-hops", "-1"], ["--ota-hops", "9"],
                      ["--relay", "relay", "--ota-hops", "0"],
                      ["--relay", "relay"] * 9):
            with self.subTest(extra=extra), contextlib.redirect_stderr(io.StringIO()):
                args = parser.parse_args(["release.mota", "remote", *extra])
                with self.assertRaises(SystemExit):
                    ota.validate_args(args, parser)


class OtaHopLifecycleTests(unittest.TestCase):
    def run_main(self, directory, *, failure=None, leave=False, no_install=True):
        stations = Stations()
        image = firmware(b"ota hop lifecycle" * 300, VERSION_NEW)
        package = ota.parse_mota(mota_blob(image))
        seeder = mock.Mock()

        def start():
            stations.seeding = True
            stations.events.append("seeder-start")

        def stop():
            stations.seeding = False
            stations.events.append("seeder-stop")

        seeder.start.side_effect = start
        seeder.stop.side_effect = stop

        def phase(name):
            def action(*_args, **_kwargs):
                stations.events.append(name)
                if failure == name:
                    if name == "interrupt":
                        raise KeyboardInterrupt
                    raise ota.OtaError("synthetic " + name)
            return action

        def pull(*_args):
            stations.events.append("pull")
            if failure == "interrupt":
                raise KeyboardInterrupt
            if failure == "pull":
                raise ota.OtaError("synthetic discovery failure")
            self.assertTrue(all(hops == 1 for hops in stations.hops.values()))

        def install(*_args):
            stations.events.append("install")
            self.assertTrue(all(hops == 0 for hops in stations.hops.values()))
            if failure == "install":
                raise ota.OtaError("synthetic install failure")
            return True

        argv = ["release.mota", "remote", "--controller-serial", "/dev/controller",
                "--source-serial", "/dev/source", "--password", "secret",
                "--relay", "relay0=relay-secret", "--work-dir", str(Path(directory) / "work"),
                "--yes"]
        if no_install:
            argv.append("--no-install")
        if leave:
            argv.append("--leave-controller-radio")
        with contextlib.ExitStack() as stack:
            for name in ("preflight_inputs", "preflight_source_cli", "bind_contact_selectors",
                         "verify_shared_source_identity", "ensure_controller_clock_safe",
                         "restore_relay_timings", "shorten_relay_temp_windows",
                         "shorten_target_temp_window", "enforce_relay_timing", "report_staged_update",
                         "wait_for_post_install_identity", "verify_installed"):
                stack.enter_context(mock.patch.object(ota, name))
            stack.enter_context(mock.patch.object(ota, "ensure_source_clock_gate_safe", return_value=(1800000000, 1800000059)))
            stack.enter_context(mock.patch.object(ota, "read_source_rxps", return_value=ota.RxpsSettings(False, 100, 100)))
            stack.enter_context(mock.patch.object(ota, "disable_source_rxps", return_value=False))
            stack.enter_context(mock.patch.object(ota, "query_target", return_value=target()))
            stack.enter_context(mock.patch.object(ota, "prepare_package", return_value=(Path("release.mota"), package, None)))
            stack.enter_context(mock.patch.object(ota, "read_lora_ota_participant_versions", return_value={}))
            stack.enter_context(mock.patch.object(ota, "read_remote_rxps", return_value=ota.RxpsSettings(False, 100, 100)))
            stack.enter_context(mock.patch.object(ota, "confirm_update", side_effect=phase("confirm")))
            stack.enter_context(mock.patch.object(ota, "run_temp_radio_preflight", side_effect=phase("rehearse")))
            stack.enter_context(mock.patch.object(ota, "source_cli_command", side_effect=stations.source_cli))
            stack.enter_context(mock.patch.object(ota, "arm_target_temp_radio", side_effect=phase("arm-target")))
            stack.enter_context(mock.patch.object(ota, "arm_relay_temp_radio_once", return_value=True))
            stack.enter_context(mock.patch.object(ota, "arm_source_temp_radio_once", return_value=True))
            stack.enter_context(mock.patch.object(ota, "switch_controller_to_temp_radio", side_effect=phase("switch")))
            stack.enter_context(mock.patch.object(ota, "read_relay_timing", return_value=ota.RelayTimingSettings("relay0", "relay-secret", 0, 0.3)))
            stack.enter_context(mock.patch.object(ota, "read_remote_public_key_bounded", return_value="a" * 64))
            stack.enter_context(mock.patch.object(ota, "shorten_source_temp_window", return_value=True))
            stack.enter_context(mock.patch.object(ota, "SeederProcess", return_value=seeder))
            stack.enter_context(mock.patch.object(ota, "find_and_start_pull", side_effect=pull))
            stack.enter_context(mock.patch.object(ota, "monitor_download", side_effect=phase("monitor")))
            stack.enter_context(mock.patch.object(ota, "request_install", side_effect=install))
            stack.enter_context(mock.patch.object(ota.time, "sleep"))
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            stack.enter_context(contextlib.redirect_stderr(io.StringIO()))
            # The production source name is a bound public key; this test uses
            # the descriptive fallback while the source CLI fixture is local.
            original_prepare = ota.prepare_ota_hop_settings

            def prepare(controller, args):
                args.source_contact_value = "source"
                return original_prepare(controller, args)

            stack.enter_context(mock.patch.object(ota, "prepare_ota_hop_settings", side_effect=prepare))
            result = ota.main(argv, controller_override=stations)
        return result, stations

    def test_success_restores_after_seeder_stop_even_when_temp_radio_is_preserved(self):
        for leave in (False, True):
            with self.subTest(leave=leave), tempfile.TemporaryDirectory() as directory:
                result, stations = self.run_main(directory, leave=leave)
                self.assertEqual(result, 0)
                self.assertEqual(stations.hops, {"source": 0, "remote": 0, "relay0": 0})
                events = stations.events
                self.assertLess(events.index("confirm"), events.index("rehearse"))
                self.assertLess(events.index("rehearse"), events.index("set:source:1"))
                self.assertLess(events.index("set:remote:1"), events.index("arm-target"))
                self.assertLess(events.index("seeder-stop"), events.index("set:source:0"))

    def test_rehearsal_and_confirmation_failures_never_write_hop_settings(self):
        for failure in ("confirm", "rehearse"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as directory:
                result, stations = self.run_main(directory, failure=failure)
                self.assertEqual(result, 2)
                self.assertFalse(any(event.startswith("set:") for event in stations.events))

    def test_discovery_failure_and_interrupt_restore_all_original_settings(self):
        for failure in ("pull", "interrupt", "arm-target"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as directory:
                result, stations = self.run_main(directory, failure=failure)
                self.assertEqual(result, 130 if failure == "interrupt" else 2)
                self.assertEqual(stations.hops, {"source": 0, "remote": 0, "relay0": 0})

    def test_install_runs_only_after_policies_are_restored(self):
        for failure in (None, "install"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as directory:
                result, stations = self.run_main(directory, failure=failure, no_install=False)
                self.assertEqual(result, 2 if failure else 0)
                self.assertEqual(stations.hops, {"source": 0, "remote": 0, "relay0": 0})
                self.assertLess(stations.events.index("set:source:0"), stations.events.index("install"))


if __name__ == "__main__":
    unittest.main()
