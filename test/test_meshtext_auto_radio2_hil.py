"""Host-only checks of the preset sweep; never opens a hardware port."""
import contextlib
import io
import pathlib
import random
import struct
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "tools" / "hil"))
import meshtext_auto_radio2 as hil


class SweepPlanTests(unittest.TestCase):
    def test_meshtext_help_exposes_stock_peer_port_without_opening_hardware(self):
        output = io.StringIO()
        with patch.object(sys, "argv", ["meshtext_auto_radio2.py", "--help"]), \
                patch.object(hil, "Companion") as companion, \
                patch.object(hil, "StockPeer") as stock, \
                contextlib.redirect_stdout(output), self.assertRaises(SystemExit) as exit_result:
            hil.main()
        self.assertEqual(exit_result.exception.code, 0)
        self.assertIn("Meshtext Companion / stock-peer", output.getvalue())
        self.assertIn("--stock-port", output.getvalue())
        self.assertNotIn("meshtastic", output.getvalue().lower())
        companion.assert_not_called()
        stock.assert_not_called()

    def test_us_centers_and_native_stable_presets(self):
        expected = {
            "LongFast": 906.875, "ShortTurbo": 926.75,
            "ShortFast": 918.875, "ShortSlow": 920.625,
            "MediumFast": 913.125, "MediumSlow": 914.875,
            "LongTurbo": 908.75, "LongMod": 902.6875,
            "LongSlow": 905.3125, "MediumTurbo": 925.25,
        }
        self.assertEqual(sum(p.stock_enum is not None for p in hil.PRESETS), 9)
        for preset in hil.PRESETS:
            self.assertEqual(preset.frequency, expected[preset.name])
            self.assertEqual(preset.describe()["preamble"], 16)

    def test_alias_selection_and_rejections(self):
        self.assertEqual(hil.choose_presets("long_moderate")[0].name, "LongMod")
        for value in ("", "longfast,longfast", "not-a-preset"):
            with self.assertRaises(hil.TestFailure):
                hil.choose_presets(value)

    def test_auto_profile_readback(self):
        profile = hil.parse_profile("> 906.875,250.000,11,5,rxtx,16; auto-owned")
        self.assertEqual(profile, (906.875, 250, 11, 5, "rxtx", 16))
        with self.assertRaises(hil.TestFailure):
            hil.parse_profile("> off")

    def test_queue_envelopes(self):
        body = bytes((1, 0, 0)) + struct.pack("<I", 123456) + b"!12345678: test"
        for packet in (b"\x08" + body, b"\x11\x00\x00\x00" + body):
            value = hil.decode_channel_frame(packet)
            self.assertEqual(value["channel"], 1)
            self.assertEqual(value["timestamp"], 123456)
            self.assertEqual(value["text"], b"!12345678: test")
        self.assertIsNone(hil.decode_channel_frame(b"\x0a"))
        with self.assertRaises(hil.TestFailure):
            hil.decode_channel_frame(b"\x08")

    def test_temporary_profile_status_dialects(self):
        for value in ("> off", "off", "TempRadio inactive"):
            self.assertTrue(hil.temporary_off(value))
        for value in ("> 1 min left", "TempRadio active", "TempRadio inactive; scheduled"):
            self.assertFalse(hil.temporary_off(value))


class SweepPolicyTests(unittest.TestCase):
    def test_traffic_counts_preserve_the_configured_threshold(self):
        case = {"v4_to_v3": [{"received": True}] * 3,
                "v3_to_v4": [{"received": True}, {"received": False}, {"received": True}]}
        self.assertEqual(hil.assess_traffic(case, 3), [
            {"direction": "v3_to_v4", "received": 2, "attempted": 3, "required": 3}])
        self.assertEqual(case["traffic_counts"]["v4_to_v3"], {"received": 3, "attempted": 3})
        self.assertFalse(hil.assess_traffic(case, 2))

    def test_seeded_gap_jitter_is_reproducible_and_zero_is_unchanged(self):
        gaps = []
        with patch.object(hil.time, "sleep") as sleep:
            for _ in range(2):
                rng = random.Random(0x12345678)
                packets = [{} for _ in range(4)]
                for packet in packets:
                    hil.pause_after_packet(packet, 1, 0.5, rng)
                gaps.append([packet["gap_after_seconds"] for packet in packets])
            self.assertEqual(gaps[0], gaps[1])
            self.assertTrue(all(1 <= gap <= 1.5 for gap in gaps[0]))
            rng = Mock()
            packet = {}
            hil.pause_after_packet(packet, 1, 0, rng)
            rng.uniform.assert_not_called()
            sleep.assert_called_with(1)
            self.assertEqual(packet["gap_after_seconds"], 1)

    def run_fake(self, *, continue_on_loss=False, lose_first=True, reboot=False,
                 reboot_loss=False, auto_clear=False):
        presets = [hil.PRESETS[1], hil.PRESETS[0]]
        state = SimpleNamespace(alias="", rebooted=False, configured=[], commands=[])

        class FakeCompanion:
            max_channels = 2

            def __init__(self, port):
                self.port = SimpleNamespace(write=self.write, flush=lambda: None)

            def write(self, frame):
                state.rebooted = True
                return len(frame)

            def start(self):
                return {"primary": {"public_key_prefix": "unchanged"}}

            def close(self):
                pass

            def channel_name(self, slot):
                return "normal"

            def cli(self, command):
                state.commands.append(command)
                if command.startswith("set mt.channel "):
                    state.alias = command.split()[3]
                elif command.startswith("delete mt.channel "):
                    state.alias = ""
                if command in ("get tempradio", "get tempradio2"):
                    return "> off"
                if command == "get radio":
                    return "unchanged-primary"
                if command == "get mt.status":
                    return "> Meshtext; active; TX=0 RX=0 fail=0" if state.alias else "> Meshtext; no Meshtext channels; TX=0 RX=0 fail=0"
                if command == "get radio2":
                    return "auto-owned" if state.alias else "> off (automatic allowed)"
                return "> diagnostic"

            def mt_node(self):
                return 0x12345678

            def wait_auto(self, preset):
                return {"radio2": "auto-owned", "status": "active"}

            def send_text(self, slot, token):
                pass

            def wait_text(self, slot, from_node, token, timeout):
                lost = ((lose_first and state.alias == presets[0].alias and not state.rebooted)
                        or (reboot_loss and state.rebooted))
                return {"received": not lost}

        class FakeStock:
            node = 0x87654321

            def __init__(self, port):
                pass

            def configure(self, preset, key, tx, hops):
                state.configured.append(preset.name)
                return {"readback": {"use_preset": True, "channel_num": 0, "bandwidth": preset.bandwidth,
                                     "spread_factor": preset.sf, "coding_rate": preset.cr,
                                     "tx_power": tx, "hop_limit": hops}}

            def packets_since(self, timestamp, sender):
                return []

            def wait_packet(self, sender, predicate, since, timeout):
                return {"id": 1}

            def send_text(self, token, hops):
                return SimpleNamespace(id=1)

            def close(self):
                pass

        args = SimpleNamespace(key_bits=128, region="auto", tx_power=-9, hops=7,
                               minimum_received=3, messages_per_direction=3,
                               continue_on_loss=continue_on_loss, gap_seconds=1, gap_jitter_seconds=0.5,
                               companion_port="fake-v4", stock_port="fake-v3", channel_slot=1,
                               quiet_seconds=1, timeout=15, nodeinfo=False, reboot=reboot,
                               auto_clear=auto_clear, output=pathlib.Path("unused-mocked-report.json"))
        with patch.object(hil, "Companion", FakeCompanion), patch.object(hil, "StockPeer", FakeStock), \
                patch.object(hil.time, "sleep"), patch.object(hil, "write_report") as writer, \
                patch.object(hil.importlib.metadata, "version", return_value="mock"), \
                patch.object(hil.secrets, "token_hex", return_value="12345678"), \
                contextlib.redirect_stdout(io.StringIO()):
            report = hil.run(args, presets)
        writer.assert_called_once_with(args.output, report)
        return report, state

    def test_default_loss_policy_is_failfast_with_diagnostics(self):
        report, state = self.run_fake()
        self.assertEqual(state.configured, ["ShortTurbo"])
        self.assertEqual(report["result"], "FAIL")
        self.assertEqual(report["failed_cases"], ["ShortTurbo"])
        case = report["cases"][0]
        self.assertEqual(case["traffic_counts"]["v3_to_v4"]["received"], 0)
        for name in ("status_after_traffic", "radio2_after_traffic",
                     "radio2_status_after_traffic", "radio2_scan_after_traffic"):
            self.assertIn(name, case)

    def test_continue_on_loss_collects_both_cases_but_still_fails(self):
        report, state = self.run_fake(continue_on_loss=True)
        self.assertEqual(state.configured, ["ShortTurbo", "LongFast"])
        self.assertEqual([case["result"] for case in report["cases"]], ["FAIL", "PASS"])
        self.assertEqual(report["result"], "FAIL")
        self.assertIn("ShortTurbo", report["failure"]["message"])
        self.assertEqual(report["gap_jitter_seed"], 0x12345678)
        for case in report["cases"]:
            for direction in ("v4_to_v3", "v3_to_v4"):
                self.assertTrue(all(1 <= packet["gap_after_seconds"] <= 1.5 for packet in case[direction]))

    def test_continued_loss_does_not_skip_reboot_and_reboot_loss_is_strict(self):
        report, state = self.run_fake(continue_on_loss=True, reboot=True, reboot_loss=True)
        self.assertTrue(state.rebooted)
        self.assertEqual(report["reboot_persistence"]["result"], "FAIL")
        self.assertEqual(report["result"], "FAIL")
        self.assertIn("after reboot in v3_to_v4", report["failure"]["message"])

    def test_successful_reboot_and_auto_clear_leave_final_profile_readded(self):
        report, state = self.run_fake(continue_on_loss=True, lose_first=False, reboot=True, auto_clear=True)
        self.assertEqual(report["result"], "PASS")
        self.assertEqual(report["reboot_persistence"]["result"], "PASS")
        self.assertEqual(report["auto_clear"]["result"], "PASS")
        self.assertIn("no Meshtext channels", report["auto_clear"]["removed"]["mt_status"])
        self.assertEqual(state.alias, "mt-longfast")
        self.assertEqual(report["failed_cases"], [])


if __name__ == "__main__":
    unittest.main()
