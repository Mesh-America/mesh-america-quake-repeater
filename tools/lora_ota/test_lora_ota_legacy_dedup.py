"""Offline coverage for the bounded, explicit legacy relay workaround."""
import argparse
import contextlib
import io
import subprocess
import unittest
from unittest import mock

import lora_ota as ota
from test_lora_ota import firmware, mota_blob, VERSION_NEW


class LegacyManifestRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.package = ota.parse_mota(mota_blob(firmware(b"test" * 100, VERSION_NEW)))
        self.relay = "ab" * 32
        self.args = argparse.Namespace(
            legacy_relay_dedup_workaround=True, source_shares_controller=True,
            relay_values=[(self.relay, "secret")], target="cd" * 32,
            temp_values=(909.5, 125, 7, 5, 120),
        )
        self.status = ("OTA | download: failed (manifest timeout) 0/0 "
                       f"id={self.package.manifest_id}")
        self.controller = mock.Mock()
        self.contact = {"public_key": self.relay, "out_path_len": 0}
        self.lease = "TempRadio active: 909.500,125.00,7,5 6000s left,preamble=32"
        self.controller._run.side_effect = lambda cmd, *a, **kw: (
            [self.contact] if cmd[0] == "contact_info" else [{"text": self.lease}]
        )
        self.controller.remote_command.side_effect = [
            self.status, f"OK pulling mid={self.package.manifest_id} -> flash (primary traffic)"
        ]
        self.addCleanup(mock.patch.stopall)
        mock.patch.object(ota.time, "sleep").start()
        mock.patch.object(ota.time, "monotonic", return_value=100).start()
        self.output = contextlib.redirect_stdout(io.StringIO())
        self.output.__enter__()
        self.addCleanup(self.output.__exit__, None, None, None)

    def recover(self, status=None, attempt=0, deadline=1000):
        return ota.recover_legacy_manifest_timeout(
            self.controller, self.args, self.package, None,
            self.status if status is None else status, deadline, attempt,
        )

    def test_unique_small_direct_frames_and_single_exact_pull(self):
        self.assertTrue(self.recover())
        frames = [c.args[0] for c in self.controller.send_legacy_ota_cache_probe.call_args_list]
        self.assertEqual(len(frames), 192)
        self.assertEqual(len(set(frames)), 192)
        self.assertEqual({len(f) for f in frames}, {13})
        self.assertTrue(all(f[:3] == bytes.fromhex("320000") for f in frames))
        self.assertEqual([c.args[1] for c in self.controller.remote_command.call_args_list],
                         ["ota status", f"ota pull {self.package.manifest_id} flash"])
        self.assertFalse(self.controller.remote_command.call_args_list[-1].kwargs["retry"])
        self.assertEqual(self.controller._run.call_count, 13)  # route + 12 lease proofs

    def test_off_by_default_and_two_round_limit(self):
        self.args.legacy_relay_dedup_workaround = False
        self.assertFalse(self.recover())
        self.args.legacy_relay_dedup_workaround = True
        self.assertFalse(self.recover(attempt=2))
        self.controller._run.assert_not_called()

    def test_wrong_mid_partial_ready_and_other_errors_never_trigger(self):
        for status in (
            self.status.replace(self.package.manifest_id, "FFFFFFFF"),
            self.status.replace("0/0", "1/40"),
            self.status.replace("manifest timeout", "signature invalid"),
            f"download: fetching 1/40 id={self.package.manifest_id}",
            f"download: ready to install 40/40 id={self.package.manifest_id}",
        ):
            with self.subTest(status=status):
                self.assertFalse(self.recover(status))
        self.controller.send_legacy_ota_cache_probe.assert_not_called()

    def test_not_direct_and_unproven_temp_lease_fail_before_transmit(self):
        for path in (-1, 1, None):
            self.contact["out_path_len"] = path
            with self.assertRaisesRegex(ota.OtaError, "direct"):
                self.recover()
        self.contact["out_path_len"] = 0
        for lease in ("TempRadio inactive", self.lease.replace("6000s", "30s"),
                      self.lease.replace("125.00", "250.00"),
                      self.lease.replace(" 6000s left", "")):
            self.lease = lease
            with self.assertRaises(ota.OtaError):
                self.recover()
        self.controller.send_legacy_ota_cache_probe.assert_not_called()

    def test_global_deadline_is_not_extended(self):
        with self.assertRaisesRegex(ota.OtaError, "insufficient"):
            self.recover(deadline=101)
        self.controller.send_legacy_ota_cache_probe.assert_not_called()

    def test_session_change_never_cancels_or_pulls(self):
        self.controller.remote_command.side_effect = ["no download"]
        with self.assertRaisesRegex(ota.OtaError, "session changed"):
            self.recover()
        self.assertEqual(self.controller.remote_command.call_count, 1)

    def test_completion_during_turnover_is_preserved(self):
        self.controller.remote_command.side_effect = [
            f"download: ready to install 40/40 id={self.package.manifest_id}"
        ]
        self.assertTrue(self.recover())
        self.assertEqual(self.controller.remote_command.call_count, 1)

    def test_lost_pull_ack_reconciles_without_resending(self):
        self.controller.remote_command.side_effect = [self.status, ota.TransmissionError("lost"),
            f"download: fetching 0/40 id={self.package.manifest_id}"]
        self.assertTrue(self.recover())
        self.assertEqual([c.args[1] for c in self.controller.remote_command.call_args_list],
                         ["ota status", f"ota pull {self.package.manifest_id} flash", "ota status"])

    def test_probe_error_aborts_no_pull(self):
        self.controller.send_legacy_ota_cache_probe.side_effect = ota.OtaError("queue full")
        with self.assertRaisesRegex(ota.OtaError, "queue full"):
            self.recover()
        self.controller.remote_command.assert_not_called()

    def test_raw_send_error_or_missing_marker_is_not_success(self):
        for failure in ("Error sending raw packet", "Unknown command", ""):
            controller = object.__new__(ota.Controller)
            def execute(commands, *a, **kw):
                output = failure + (commands[-1] if failure else "")
                return subprocess.CompletedProcess([], 0, stdout=output, stderr="")
            with mock.patch.object(controller, "_execute", side_effect=execute):
                with self.assertRaises(ota.OtaError):
                    controller.send_legacy_ota_cache_probe(b"\x32\0\0", timeout=5)

    def test_parser_requires_explicit_compatible_topology(self):
        parser = ota.build_parser()
        common = ["update.mota", "target", "--legacy-relay-dedup-workaround"]
        for flags in ([], ["--relay", "relay"], ["--source-shares-controller"],
                      ["--relay", "a", "--relay", "b", "--source-shares-controller"]):
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                ota.validate_args(parser.parse_args(common + flags), parser)

    def test_monitor_uses_same_deadline_and_bounded_attempt_counter(self):
        self.args.transfer_timeout_minutes = 20
        self.args.poll_seconds = 1
        self.args.reply_timeout = 1
        ready = f"download: ready to install 1/1 id={self.package.manifest_id}"
        for passive in (False, True):
            with self.subTest(passive=passive):
                self.controller.remote_command.side_effect = [self.status, self.status, ready]
                seeder = mock.Mock() if passive else None
                if seeder:
                    seeder.payload_read_progress.return_value = (0, 1, 0)
                with mock.patch.object(ota, "initial_status_wait_seconds", return_value=0), \
                     mock.patch.object(ota, "passive_progress_stall_seconds", return_value=0), \
                     mock.patch.object(ota, "transfer_tail_guard_seconds", return_value=0), \
                     mock.patch.object(ota, "recover_legacy_manifest_timeout",
                                       side_effect=[True, True, False]) as recover:
                    self.assertEqual(ota.monitor_download(self.controller, self.args,
                                                         self.package, seeder), ready)
                self.assertEqual([c.args[-1] for c in recover.call_args_list], [0, 1, 2])
                self.assertEqual({c.args[-2] for c in recover.call_args_list}, {1300})

    def test_monitor_offers_reboot_only_for_exact_zero_block_timeout(self):
        self.args.transfer_timeout_minutes = 20
        self.args.poll_seconds = 1
        self.args.reply_timeout = 1
        fetching = f"download: fetching 0/40 id={self.package.manifest_id}"
        ready = f"download: ready to install 40/40 id={self.package.manifest_id}"
        self.controller.remote_command.side_effect = [fetching, self.status, ready]
        reboot = mock.Mock(return_value=True)
        with mock.patch.object(ota, "initial_status_wait_seconds", return_value=0), \
             mock.patch.object(ota, "recover_legacy_manifest_timeout", return_value=False):
            self.assertEqual(
                ota.monitor_download(self.controller, self.args, self.package,
                                     reboot_recovery=reboot), ready,
            )
        reboot.assert_called_once_with(self.status, 1300)


class RelayRebootRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.package = ota.parse_mota(mota_blob(firmware(b"reboot" * 100, VERSION_NEW)))
        self.relay = "ab" * 32
        self.target = "cd" * 32
        self.status = ("OTA | download: failed (manifest timeout) 0/0 "
                       f"id={self.package.manifest_id}")
        self.args = argparse.Namespace(
            source_shares_controller=True, relay_values=[(self.relay, "secret")],
            relay_reboot_normal_hops=1, target=self.target,
            temp_values=(909.5, 125, 7, 5, 120), yes=True,
        )
        self.controller = mock.Mock()
        self.controller._run.return_value = [{
            "public_key": self.relay, "out_path_len": 1,
        }]
        self.controller.get_radio.return_value = ota.RadioSettings(910.525, 62.5, 7, 5, False)
        self.controller.remote_command.side_effect = [
            self.status, ota.TransmissionError("no reboot reply"), self.status,
            f"OK pulling mid={self.package.manifest_id} -> flash",
        ]
        self.on_normal = mock.Mock()
        self.on_temp = mock.Mock()
        self.on_temp_active = mock.Mock()
        self.addCleanup(mock.patch.stopall)
        mock.patch.object(ota.time, "sleep").start()
        mock.patch.object(ota.time, "monotonic", return_value=100).start()
        self.source_cli = mock.patch.object(
            ota, "source_cli_command",
            return_value="TempRadio active: 909.500,125.00,7,5 7000s left,preamble=32",
        ).start()
        self.shorten = mock.patch.object(ota, "shorten_source_temp_window", return_value=True).start()
        self.read_key = mock.patch.object(
            ota, "read_remote_public_key_bounded",
            side_effect=[self.target, self.relay, self.relay, self.relay, self.target],
        ).start()
        self.arm = mock.patch.object(ota, "arm_relay_temp_radio_once", return_value=True).start()
        self.switch = mock.patch.object(ota, "switch_controller_to_temp_radio").start()
        mock.patch.object(ota, "require_source_on_temp_after_uncertain_arm").start()
        self.output = contextlib.redirect_stdout(io.StringIO())
        self.output.__enter__()
        self.addCleanup(self.output.__exit__, None, None, None)

    def recover(self, status=None, armed_at=100, deadline=1300):
        return ota.recover_manifest_by_relay_reboot(
            self.controller, self.args, self.package, None,
            self.status if status is None else status, deadline, armed_at,
            {self.relay: self.relay}, self.controller.get_radio.return_value,
            ota.RadioSettings(909.5, 125, 7, 5, False),
            self.on_normal, self.on_temp, self.on_temp_active,
        )

    def test_one_hop_reboot_rearms_bounded_lease_and_same_mid(self):
        self.assertTrue(self.recover())
        commands = [c.args[1] for c in self.controller.remote_command.call_args_list]
        self.assertEqual(commands, [
            "ota status", "reboot", "ota status",
            f"ota pull {self.package.manifest_id} flash",
        ])
        self.controller.forget_remote_auth.assert_called_once_with(self.relay)
        self.on_normal.assert_called_once()
        self.on_temp.assert_called_once()
        self.on_temp_active.assert_called_once()
        self.assertEqual(
            self.arm.call_args.args[3], "tempradio 909.5,125,7,5,119",
        )
        self.assertEqual(self.read_key.call_count, 5)

    def test_direct_relay_is_also_eligible(self):
        self.args.relay_reboot_normal_hops = 0
        self.controller._run.return_value[0]["out_path_len"] = 0
        self.assertTrue(self.recover())

    def test_recent_progress_avoids_reboot(self):
        self.controller.remote_command.side_effect = [
            f"download: fetching 1/40 id={self.package.manifest_id}",
        ]
        self.assertTrue(self.recover())
        self.assertEqual([c.args[1] for c in self.controller.remote_command.call_args_list],
                         ["ota status"])
        self.on_normal.assert_not_called()

    def test_wrong_status_or_route_cannot_reboot(self):
        self.assertFalse(self.recover(status=self.status.replace("0/0", "1/40")))
        self.controller.remote_command.assert_not_called()
        self.controller._run.return_value[0]["out_path_len"] = 2
        with self.assertRaisesRegex(ota.OtaError, "0- or 1-hop"):
            self.recover()
        self.controller.remote_command.assert_not_called()

    def test_short_lease_fails_before_reboot(self):
        with self.assertRaisesRegex(ota.OtaError, "too little"):
            self.recover(armed_at=-7000)
        self.controller.remote_command.assert_not_called()

    def test_declined_prompt_does_not_reboot(self):
        self.args.yes = False
        with mock.patch.object(ota.sys.stdin, "isatty", return_value=True), \
             mock.patch("builtins.input", return_value="n"):
            self.assertFalse(self.recover())
        self.assertEqual([c.args[1] for c in self.controller.remote_command.call_args_list],
                         ["ota status"])

    def test_normal_path_failure_does_not_rearm_or_pull(self):
        self.read_key.side_effect = [self.target, self.relay, ota.TransmissionError("offline")]
        with self.assertRaisesRegex(ota.TransmissionError, "offline"):
            self.recover()
        self.on_normal.assert_called_once()
        self.on_temp.assert_not_called()
        self.on_temp_active.assert_not_called()
        self.arm.assert_not_called()
        commands = [c.args[1] for c in self.controller.remote_command.call_args_list]
        self.assertEqual(commands, ["ota status", "reboot"])

    def test_parser_requires_one_managed_shared_relay(self):
        parser = ota.build_parser()
        common = ["update.mota", "target", "--legacy-relay-reboot-recovery"]
        for flags in ([], ["--relay", "relay"], ["--source-shares-controller"],
                      ["--relay", "a", "--relay", "b", "--source-shares-controller"],
                      ["--relay", "a", "--source-shares-controller", "--source-already-temp"]):
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                ota.validate_args(parser.parse_args(common + flags), parser)
        args = parser.parse_args(common + [
            "--relay", "relay", "--source-shares-controller",
            "--controller-tcp", "127.0.0.1", "--source-tcp", "127.0.0.1",
            "--source-cli-tcp", "127.0.0.1",
        ])
        ota.validate_args(args, parser)


if __name__ == "__main__":
    unittest.main()
