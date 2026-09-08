"""Offline source-card import tests. No radios, flashes, or LoRa transmissions."""

import argparse
import contextlib
import io
import subprocess
import unittest
from unittest import mock

import lora_ota as ota
from test_lora_ota_source_identity import banner, connection


SOURCE = "a5" * 32
TARGET = "b6" * 32
CONTROLLER = "c7" * 32
NAME = "Source \U0001f4e1"


def card(key=SOURCE, name=NAME, flags=0x81, extra=b""):
    # Same Packet::writeTo envelope as firmware `card`. Signature bytes are
    # dummy: production signature verification remains inside the controller.
    packet = b"\x11\x00" + bytes.fromhex(key) + (123).to_bytes(4, "little") + b"s" * 64
    return "meshcore://" + (packet + bytes([flags]) + extra + name.encode()).hex()


def entry(key, name):
    return {"public_key": key, "adv_name": name}


def result(stdout="", stderr=""):
    return subprocess.CompletedProcess([], 0, stdout, stderr)


class SourceCardTests(unittest.TestCase):
    def test_accepts_pathless_card_with_unicode_name_and_optional_fields(self):
        for flags, extra in ((0x81, b""), (0xf2, b"x" * 12)):
            uri = card(flags=flags, extra=extra)
            output = banner() + "\r\n> " + uri + "\r\n> \r\nBinary mode\r\n"
            self.assertEqual(ota.parse_source_contact_card(output, SOURCE), (uri, entry(SOURCE, NAME)))

    def test_uppercase_hex_is_normalized(self):
        uri = card()
        self.assertEqual(ota.parse_source_contact_card("meshcore://" + uri[11:].upper(), SOURCE.upper())[0], uri)

    def test_rejects_missing_duplicate_embedded_malformed_or_wrong_key(self):
        uri = card()
        values = ["OK", uri + "\n" + uri, "Received " + uri, uri + "z", uri[:-1],
                  card(TARGET), "meshcore://", uri + "\nmeshcore://broken"]
        for value in values:
            with self.subTest(value=value), self.assertRaises(ota.OtaError):
                ota.parse_source_contact_card(value, SOURCE)

    def test_rejects_unsupported_envelopes_flags_and_name(self):
        raw = bytes.fromhex(card()[11:])
        values = [raw[:50], b"\x51" + raw[1:], b"\x12" + raw[1:],
                  b"\x11\x01" + raw[2:], raw + b"x" * 40]
        for packet in values:
            with self.subTest(packet=packet), self.assertRaises(ota.OtaError):
                ota.parse_source_contact_card("meshcore://" + packet.hex(), SOURCE)
        for uri in (card(name=""), card(flags=0x01), card(flags=0x80), card(flags=0x91, name="x"), card(name="bad\x00name")):
            with self.subTest(uri=uri), self.assertRaises(ota.OtaError):
                ota.parse_source_contact_card(uri, SOURCE)

    def test_full_tcp_card_uses_existing_read_only_terminal_command(self):
        args = argparse.Namespace(source_cli_tcp="192.0.2.1:5002", source_cli_serial=None,
                                  source_serial=None, source_full_companion=True)
        conn = connection(reply=card())
        with mock.patch.object(ota.socket, "create_connection", return_value=conn), contextlib.redirect_stdout(io.StringIO()):
            output = ota.optional_source_cli_command(args, "card")
        self.assertEqual(ota.parse_source_contact_card(output, SOURCE)[0], card())
        conn.sendall.assert_called_once_with(b"card\r\n")

    def test_full_usb_card_wraps_terminal_even_after_identity_left_binary_mode(self):
        args = argparse.Namespace(source_cli_tcp=None, source_cli_serial="COM42", source_serial=None,
                                  source_baud=115200, meshcli="meshcli", source_full_companion=True,
                                  source_companion_terminal=False)
        with mock.patch.object(ota, "run_checked", return_value=result(banner() + card())) as run, contextlib.redirect_stdout(io.StringIO()):
            output = ota.optional_source_cli_command(args, "card")
        self.assertEqual(ota.parse_source_contact_card(output, SOURCE)[0], card())
        self.assertEqual(run.call_args.args[0][-1],
                         f"{ota.COMPANION_TERMINAL_STOP}\r{ota.COMPANION_TERMINAL_START}\rcard\r{ota.COMPANION_TERMINAL_STOP}\r")


class ContactImportTests(unittest.TestCase):
    def setUp(self):
        self.args = argparse.Namespace(target="Target", relay_values=[], source_contact_value=None,
                                       source_shares_controller=False, source_cli_tcp="192.0.2.1:5002", yes=True)
        self.before = {TARGET: entry(TARGET, "Target")}
        self.after = {**self.before, SOURCE: entry(SOURCE, NAME)}
        self.controller = mock.Mock()
        self.controller.get_public_key.return_value = CONTROLLER
        self.controller._run.side_effect = [[self.before], [self.before], [self.after]]
        self.controller._execute.side_effect = [result("0x1e\n"), result()]
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
        self.tty = stack.enter_context(mock.patch.object(ota.sys.stdin, "isatty", return_value=True))
        self.answer = stack.enter_context(mock.patch("builtins.input", return_value="yes"))
        self.read_key = stack.enter_context(mock.patch.object(ota, "read_source_public_key_bounded", return_value=SOURCE))
        self.read_card = stack.enter_context(mock.patch.object(ota, "optional_source_cli_command", return_value=card()))
        stack.enter_context(mock.patch.object(ota.time, "sleep"))

    def bind(self):
        ota.bind_contact_selectors(self.controller, self.args)

    def test_approved_import_verified_then_continue_with_full_key(self):
        self.bind()
        self.assertEqual(self.args.source_contact_value, SOURCE)
        self.assertEqual(self.args.target, TARGET)
        self.answer.assert_called_once()
        self.assertEqual(self.read_key.call_count, 2)
        self.assertEqual([call.args[0] for call in self.controller._execute.call_args_list],
                         [["get", "autoadd_config"], ["import_contact", card()]])
        self.assertEqual([call.args[0] for call in self.controller._run.call_args_list],
                         [["contacts"], ["reload_contacts"], ["reload_contacts"]])
        self.controller.remote_command.assert_not_called()
        self.controller.set_radio.assert_not_called()

    def test_explicit_source_name_or_key_can_be_imported(self):
        for selector in (NAME, SOURCE, SOURCE[:12]):
            with self.subTest(selector=selector):
                self.args.target = "Target"
                self.controller._run.side_effect = [[self.before], [self.before], [self.after]]
                self.controller._execute.side_effect = [result("0x1e\r\n"), result()]
                self.args.source_contact_value = selector
                self.bind()
                self.assertEqual(self.args.source_contact_value, SOURCE)

    def test_existing_contact_has_no_prompt_or_card_read(self):
        self.controller._run.side_effect = [[self.after]]
        self.bind()
        self.answer.assert_not_called()
        self.read_card.assert_not_called()
        self.controller._execute.assert_not_called()

    def test_declined_blank_eof_and_non_yes_do_not_mutate_even_with_yes_flag(self):
        for answer in ("", "n", "no", "sure", EOFError()):
            with self.subTest(answer=answer):
                self.controller._run.side_effect = [[self.before]]
                self.answer.side_effect = answer if isinstance(answer, Exception) else None
                self.answer.return_value = answer
                with self.assertRaisesRegex(ota.OtaError, "declined"):
                    self.bind()
                self.controller._execute.assert_not_called()

    def test_noninteractive_gives_instructions_without_card_read_or_mutation(self):
        self.tty.return_value = False
        with self.assertRaisesRegex(ota.OtaError, "--yes does not approve"):
            self.bind()
        self.answer.assert_not_called()
        self.read_card.assert_not_called()
        self.controller._execute.assert_not_called()

    def test_keyboard_interrupt_is_not_consent(self):
        self.answer.side_effect = KeyboardInterrupt
        with self.assertRaises(KeyboardInterrupt):
            self.bind()
        self.controller._execute.assert_not_called()

    def test_unsupported_source_card_reports_manual_fallback(self):
        self.read_card.return_value = None
        with self.assertRaisesRegex(ota.OtaError, "does not support `card`"):
            self.bind()
        self.answer.assert_not_called()
        self.controller._execute.assert_not_called()

    def test_card_timeout_does_not_become_import(self):
        self.read_card.side_effect = ota.TransmissionError("timeout")
        with self.assertRaises(ota.TransmissionError):
            self.bind()
        self.controller._execute.assert_not_called()

    def test_card_key_mismatch_is_refused_before_consent(self):
        self.read_card.return_value = card(TARGET)
        with self.assertRaisesRegex(ota.OtaError, "key mismatch"):
            self.bind()
        self.answer.assert_not_called()
        self.controller._execute.assert_not_called()

    def test_wrong_explicit_selector_does_not_prompt_or_import(self):
        self.args.source_contact_value = "Target"
        with self.assertRaisesRegex(ota.OtaError, "--source-contact identifies"):
            self.bind()
        self.answer.assert_not_called()
        self.read_card.assert_not_called()

    def test_unknown_explicit_selector_must_match_card_before_prompt(self):
        self.args.source_contact_value = "Wrong name"
        with self.assertRaisesRegex(ota.OtaError, "does not identify"):
            self.bind()
        self.answer.assert_not_called()

    def test_shared_source_does_not_import_self(self):
        self.args.source_shares_controller = True
        self.controller._run.side_effect = [[self.before]]
        self.bind()
        self.read_key.assert_not_called()
        self.answer.assert_not_called()
        self.controller._execute.assert_not_called()

    def test_misconfigured_same_controller_gives_topology_option(self):
        self.controller.get_public_key.return_value = SOURCE
        with self.assertRaisesRegex(ota.OtaError, "--source-shares-controller"):
            self.bind()
        self.read_card.assert_not_called()
        self.answer.assert_not_called()

    def test_source_swap_after_consent_stops_before_import(self):
        self.read_key.side_effect = [SOURCE, TARGET]
        with self.assertRaisesRegex(ota.OtaError, "identity changed"):
            self.bind()
        self.controller._execute.assert_not_called()

    def test_controller_swap_after_consent_stops_before_import(self):
        self.controller.get_public_key.side_effect = [CONTROLLER, "d8" * 32]
        with self.assertRaisesRegex(ota.OtaError, "identity changed"):
            self.bind()
        self.controller._execute.assert_not_called()

    def test_contact_added_while_prompt_open_is_not_reimported(self):
        self.controller._run.side_effect = [[self.before], [self.after]]
        self.bind()
        self.controller._execute.assert_not_called()

    def test_removed_existing_contact_stops_before_import(self):
        self.controller._run.side_effect = [[self.before], [{}]]
        with self.assertRaisesRegex(ota.OtaError, "contacts changed"):
            self.bind()
        self.controller._execute.assert_not_called()

    def test_overwrite_enabled_is_refused_without_policy_change(self):
        self.controller._execute.side_effect = [result("0x1f\n")]
        with self.assertRaisesRegex(ota.OtaError, "set autoadd_config 0x1e"):
            self.bind()
        self.assertEqual(self.controller._execute.call_count, 1)

    def test_unknown_overwrite_policy_is_refused(self):
        self.controller._execute.side_effect = [result("Can't get autoadd_config")]
        with self.assertRaisesRegex(ota.OtaError, "cannot verify"):
            self.bind()
        self.assertEqual(self.controller._execute.call_count, 1)

    def test_import_acknowledgement_alone_is_not_success_and_is_not_retried(self):
        self.controller._run.side_effect = [[self.before], [self.before]] + [[self.before], [{}]] * 5
        with self.assertRaisesRegex(ota.OtaError, "table may be full"):
            self.bind()
        self.assertEqual(self.controller._execute.call_count, 2)

    def test_delayed_device_import_is_polled_using_fresh_tables(self):
        self.controller._run.side_effect = [[self.before], [self.before], [self.before], [{}], [self.after]]
        self.bind()
        self.assertEqual(self.controller._execute.call_count, 2)

    def test_manual_add_uses_only_matching_pending_key_without_changing_settings(self):
        pending = {SOURCE: entry(SOURCE, NAME), "d8" * 32: entry("d8" * 32, NAME)}
        self.controller._run.side_effect = [[self.before], [self.before], [self.before], [pending], [self.after]]
        self.controller._execute.side_effect = [result("0x00"), result(), result("0x00"), result("{}")]
        self.bind()
        self.assertEqual([call.args[0] for call in self.controller._execute.call_args_list],
                         [["get", "autoadd_config"], ["import_contact", card()],
                          ["get", "autoadd_config"], ["add_pending", SOURCE]])

    def test_pending_add_once_when_table_full(self):
        pending = {SOURCE: entry(SOURCE, NAME)}
        self.controller._run.side_effect = [[self.before], [self.before], [self.before], [pending]] + [[self.before]] * 4
        self.controller._execute.side_effect = [result("0x00"), result(), result("0x00"), result("{}")]
        with self.assertRaisesRegex(ota.OtaError, "table may be full"):
            self.bind()
        self.assertEqual(self.controller._execute.call_count, 4)

    def test_import_rejection_and_lost_ack_never_retry(self):
        for response in (result("Error while importing contact: full"), result('{"error_code": 3}'), ota.OtaError("timeout")):
            with self.subTest(response=response):
                self.controller._run.side_effect = [[self.before], [self.before]]
                self.controller._execute.reset_mock()
                self.controller._execute.side_effect = [result("0x00"), response]
                with self.assertRaises(ota.OtaError):
                    self.bind()
                self.assertEqual(self.controller._execute.call_count, 2)

    def test_inventory_loss_after_import_stops(self):
        self.controller._run.side_effect = [[self.before], [self.before], [{SOURCE: entry(SOURCE, NAME)}]]
        with self.assertRaisesRegex(ota.OtaError, "lost an existing key"):
            self.bind()

    def test_malformed_refreshed_table_is_not_success(self):
        self.controller._run.side_effect = [[self.before], [{"error": "storage error"}]]
        with self.assertRaisesRegex(ota.OtaError, "complete reload_contacts"):
            self.bind()
        self.controller._execute.assert_not_called()


if __name__ == "__main__":
    unittest.main()
