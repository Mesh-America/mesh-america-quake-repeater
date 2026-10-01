#!/usr/bin/env python3
"""Export an opt-in nRF52 Companion BLE trace over USB, without resetting it.

Install pyserial, keep the node powered after a failed phone connection, and
run with --port <serial-port> --output <file.json>. No pairing keys, PINs,
peer addresses or application payloads are requested or saved.
"""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import time


EVENTS = {
    0x10: "link_connected", 0x11: "link_disconnected", 0x12: "connection_parameters",
    0x13: "security_parameters_requested", 0x14: "stored_security_requested",
    0x15: "passkey_display_event", 0x17: "authentication_key_requested",
    0x18: "secure_connections_key_requested", 0x19: "authentication_result",
    0x1A: "security_updated", 0x1B: "gap_timeout", 0x1F: "parameter_update_requested",
    0x21: "phy_update_requested", 0x22: "phy_updated", 0x23: "data_length_requested",
    0x24: "data_length_updated", 0x26: "advertising_terminated",
    0x50: "attribute_write", 0x51: "attribute_authorization_requested",
    0x52: "system_attributes_missing", 0x55: "mtu_requested", 0x56: "att_timeout",
    0x57: "notification_transmitted",
    0xF000: "firmware_start", 0xF001: "connect_callback", 0xF002: "disconnect_callback",
    0xF003: "security_callback", 0xF004: "pairing_prompt", 0xF005: "pairing_complete",
    0xF006: "secured_link_accepted", 0xF010: "preferred_parameters_result",
    0xF011: "parameter_request_result", 0xF012: "advertising_start_result",
    0xF013: "local_disconnect_request_result", 0xF020: "tx_recovery_started",
    0xF021: "security_watchdog", 0xF022: "secured_no_app_watchdog",
    0xF023: "advertising_watchdog", 0xF030: "uart_rx_callback",
    0xF024: "command_reply_watchdog", 0xF025: "partial_uart_frame_recovery",
    0xF031: "uart_tx_attempt", 0xF033: "tx_queue_full", 0xF034: "rx_queue_full",
    0xF035: "uart_fifo_overflow", 0xF040: "uart_subscription_changed",
    0xF041: "ram_subscription_restore_result", 0xF042: "ram_subscription_capture_result",
}
REASONS = {
    0x05: "authentication_failure", 0x06: "pin_or_key_missing",
    0x08: "connection_timeout", 0x13: "remote_user_terminated",
    0x16: "local_host_terminated", 0x22: "link_layer_response_timeout",
    0x3D: "mic_failure", 0x3E: "connection_failed_to_establish",
}


def decode_record(sequence, ms, event, handle, detail, extra):
    record = dict(sequence=sequence, uptime_ms=ms, event=hex(event), handle=handle,
                  detail=detail, extra=extra)
    if 0xE000 <= event <= 0xE0FF or 0xE100 <= event <= 0xE1FF:
        raw = event & 0xFF
        record.update(name="dispatch_enter" if event < 0xE100 else "dispatch_exit",
                      stack_event=EVENTS.get(raw, hex(raw)))
        if event >= 0xE100:
            record["duration_us"] = detail
        return record
    record["name"] = EVENTS.get(event, "unknown_event")
    if event in (0x10, 0x12):
        record.update(min_interval_ms=(detail & 0xFFFF) * 1.25,
                      max_interval_ms=(detail >> 16) * 1.25,
                      latency=extra & 0xFFFF, supervision_timeout_ms=(extra >> 16) * 10)
    elif event in (0x11, 0xF002):
        record.update(reason_hex=hex(detail), reason=REASONS.get(detail, "unknown_reason"))
    elif event == 0x19:
        record.update(authentication_status=detail, error_source=extra & 3,
                      bonded=bool(extra & 0x100), secure_connections=bool(extra & 0x200))
    elif event == 0x1A:
        record.update(security_mode=detail & 0xFF, security_level=detail >> 8,
                      encryption_key_bytes=extra)
    elif event == 0x50:
        record.update(attribute_handle=detail & 0xFFFF, length=detail >> 16,
                      operation=extra & 0xFF, is_subscription=bool(extra & 0x100))
        if extra & 0x100:
            record["subscription_bits"] = extra >> 16
    elif event == 0xF031:
        record.update(requested_bytes=detail, accepted_bytes=extra)
    elif event == 0xF006:
        record.update(bonded=bool(detail), uart_notifications_enabled=bool(extra))
    elif event == 0xF000:
        record.update(reset_reason_hex=hex(detail), ble_tx_dbm=extra if extra < 128 else extra - 2**32)
    return record


def values(reply):
    return {key: int(value) for key, value in re.findall(r"([a-z_]+)=(\d+)", reply)}


class Terminal:
    def __init__(self, port):
        self.port = port

    def read_prompt(self, timeout=3, expected=None):
        result = bytearray()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            result.extend(self.port.read(self.port.in_waiting or 1))
            echoed = None if expected is None else re.search(
                rb"(?:^|\n)(?:> )?" + re.escape(expected.encode("ascii")) + rb"\r?\n", result)
            if result.endswith(b"\n> ") and (expected is None or echoed):
                # Ignore any delayed welcome banner from entering terminal mode.
                return result[echoed.start() if echoed else 0:].decode("ascii", errors="replace")
            if len(result) > 16384:
                raise RuntimeError("Unexpectedly large USB terminal response")
        raise TimeoutError("No USB terminal prompt; close other serial clients")

    def command(self, command):
        self.port.write(command.encode("ascii") + b"\r")
        return self.read_prompt(expected=command)


def export(port_name):
    import serial
    started = time.monotonic()
    result = {"captured_utc": datetime.now(timezone.utc).isoformat(),
              "commands": {}, "records": [], "unavailable_sequences": []}
    with serial.Serial(port_name, 115200, timeout=0.05) as port:
        port.dtr = True
        terminal = Terminal(port)
        port.reset_input_buffer()
        port.write(b"+++MESHCORE-TERM-START\r")
        try:
            terminal.read_prompt()
            for command in ("ver", "get radio", "get tx", "get bluetooth.trace.state",
                            "get bluetooth.trace.stats", "get bluetooth.trace.timing",
                            "get bluetooth.trace"):
                result["commands"][command] = terminal.command(command)
            head = values(result["commands"]["get bluetooth.trace"])
            if head.get("format") != 2 or head.get("capacity") != 256:
                raise RuntimeError("This device does not have the format-2 diagnostic firmware")
            result["trace"] = head
            for sequence in range(max(1, head["next"] - head["capacity"] + 1), head["next"] + 1):
                reply = terminal.command("get bluetooth.trace " + str(sequence))
                match = re.search(r"> (\d+),(\d+),0x([0-9a-fA-F]+),(\d+),(\d+),(\d+)", reply)
                if match is None:
                    result["unavailable_sequences"].append(sequence)
                    continue
                fields = [int(value, 16 if index == 2 else 10)
                          for index, value in enumerate(match.groups())]
                if fields[0] != sequence:
                    raise RuntimeError("Mismatched trace sequence")
                result["records"].append(decode_record(*fields))
            result["state_after"] = terminal.command("get bluetooth.trace.state")
        finally:
            port.write(b"+++MESHCORE-TERM-STOP\r")
    result["export_seconds"] = round(time.monotonic() - started, 3)
    result["limitations"] = [
        "RAM history is lost on power loss or reboot; export before restarting the node.",
        "Old records roll out after 256 events; unavailable sequences are reported.",
        "Dispatch timing measures software handling after the SoftDevice delivers an event, not radio ISR latency.",
        "No connection events cannot alone distinguish the host, RF path and peripheral controller.",
    ]
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True, help="USB serial device or COM port")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = export(args.port)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=True) + "\n", encoding="ascii")
    print("Saved %d events to %s" % (len(result["records"]), args.output))
    print(result["commands"]["get bluetooth.trace.stats"].strip())


if __name__ == "__main__":
    main()
