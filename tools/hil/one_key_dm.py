#!/usr/bin/env python3
"""Exercise manual acceptance of a one-key private DM.

This test changes the two radios' contact lists and transmits one LoRa DM.
It consumes the recipient's deferred DM from the offline queue. Use two nearby
Companion USB radios on the same radio profile, with no other client attached.
"""

from __future__ import annotations

import argparse
import json
import struct
import time

from esp32_companion_serial_stress import (
    DeviceFrameReader,
    FrameTimeout,
    TransportCounters,
    encode_host_frame,
    make_app_start_spec,
    validate_app_start_response,
)


class Link:
    def __init__(self, port: str) -> None:
        import serial

        # Native USB/JTAG CDC needs DTR. Configure while closed and leave RTS
        # deasserted so the ESP reset line is not deliberately driven.
        self.port = serial.Serial(baudrate=115200, timeout=0.1,
                                  write_timeout=2, exclusive=True)
        self.port.port = port
        self.port.dtr = True
        self.port.rts = False
        self.port.open()
        self.reader = DeviceFrameReader(TransportCounters())
        self.pushes: list[bytes] = []

    def close(self) -> None:
        self.port.close()

    def read(self, seconds: float) -> bytes | None:
        try:
            frame = self.reader.read_frame(self.port, seconds)
        except FrameTimeout:
            return None
        if frame[0] >= 0x80:
            self.pushes.append(frame)
        return frame

    def request(self, payload: bytes, expected: tuple[int, ...], seconds: float = 5) -> bytes:
        self.port.write(encode_host_frame(payload))
        self.port.flush()
        until = time.monotonic() + seconds
        while time.monotonic() < until:
            frame = self.read(min(0.5, until - time.monotonic()))
            if frame is None or frame[0] >= 0x80:
                continue
            if frame[0] not in expected:
                raise RuntimeError(
                    f"unexpected Companion response {frame[0]}"
                    + (f", error {frame[1]}" if frame[0] == 1 and len(frame) > 1 else "")
                )
            return frame
        raise TimeoutError(f"Companion request {payload[0]} timed out")

    def start(self) -> tuple[bytes, dict]:
        # Some USB Companions need a fresh CDC open after DFU activation.
        for attempt in range(3):
            try:
                frame = self.request(make_app_start_spec("OneKeyDM-HIL").payload,
                                     (5,), seconds=5)
                break
            except TimeoutError:
                if attempt == 2:
                    raise
                self.port.close()
                time.sleep(1)
                self.port.open()
                self.reader = DeviceFrameReader(TransportCounters())
        return frame[4:36], validate_app_start_response(frame)

    def contact(self, key: bytes) -> bytes | None:
        frame = self.request(bytes([30]) + key, (1, 3))
        return frame if frame[0] == 3 else None

    def cli(self, command: str) -> str:
        return self.request(bytes([0x42]) + command.encode(), (0x1D,))[1:].decode()


def consume_expected_dm(recipient: Link, sender_key: bytes, timestamp: int,
                        text: bytes, queue_capacity: int) -> dict:
    """Find this test's DM in a bounded FIFO scan without exposing other text."""
    if queue_capacity not in (256, 512):
        raise ValueError("queue capacity must be 256 or 512")
    skipped = 0
    for _ in range(queue_capacity):
        queued = recipient.request(bytes([10]), (7, 8, 10, 16, 17))
        if queued[0] == 10:
            return {"matched": False, "skipped": skipped, "empty": True}
        if queued[0] in (7, 16):
            start = 1 if queued[0] == 7 else 4
            if len(queued) < start + 12:
                raise RuntimeError("truncated queued contact message")
            if (queued[start:start + 6] == sender_key[:6]
                    and queued[start + 7] == 0  # plaintext DM
                    and struct.unpack_from("<I", queued, start + 8)[0] == timestamp
                    and queued[start + 12:] == text):
                return {"matched": True, "skipped": skipped, "empty": False}
        skipped += 1
    return {"matched": False, "skipped": skipped, "empty": False}


def run(sender_port: str, recipient_port: str, reset_contact: bool,
        zero_hop: bool, invalid_signature_first: bool,
        queue_capacity: int = 256) -> dict:
    if queue_capacity not in (256, 512):
        raise ValueError("queue capacity must be 256 or 512")
    sender = Link(sender_port)
    recipient = Link(recipient_port)
    prior_dm_setting = None
    try:
        sender_key, sender_info = sender.start()
        recipient_key, recipient_info = recipient.start()
        prior_dm_setting = recipient.cli("get dm.one_key")
        if prior_dm_setting not in ("> on", "> off"):
            raise RuntimeError("recipient did not report its one-key DM policy")
        if not recipient.cli("set dm.one_key off").endswith("dm.one_key off"):
            raise RuntimeError("recipient could not enable manual DM acceptance")
        radio_fields = ("frequency_khz", "bandwidth_hz", "spreading_factor", "coding_rate")
        if any(sender_info[field] != recipient_info[field] for field in radio_fields):
            raise RuntimeError("radios do not use the same frequency, bandwidth, SF, and CR")

        if recipient.contact(sender_key) is not None:
            if not reset_contact:
                raise RuntimeError("recipient already knows sender; pass --reset-contact to remove it")
            recipient.request(bytes([15]) + sender_key, (0,))
        if recipient.contact(sender_key) is not None:
            raise RuntimeError("recipient still knows sender")

        contact = sender.contact(recipient_key)
        if contact is None:
            advert = recipient.request(bytes([17]), (11,))[1:]
            sender.request(bytes([18]) + advert, (0,))
            for _ in range(10):
                time.sleep(0.25)
                contact = sender.contact(recipient_key)
                if contact is not None:
                    break
        if contact is None:
            raise RuntimeError("sender could not import recipient's signed advert")

        if zero_hop:
            # Contact response and CMD_ADD_UPDATE_CONTACT share the same body.
            update = bytearray(contact)
            update[0] = 9
            update[35] = 0  # zero path hashes
            update[36:100] = bytes(64)
            sender.request(bytes(update), (0,))
            contact = sender.contact(recipient_key)
        if contact is None:
            raise RuntimeError("sender contact vanished")

        if invalid_signature_first:
            # CMD_SEND_ANON_REQ prepends the four-byte tag itself. This has a
            # valid ECDH envelope but an invalid Ed25519 identity signature.
            bogus = b"DMK1forged\0" + bytes(64)
            sender.request(bytes([0x39]) + recipient_key + bogus, (6,), seconds=20)
            time.sleep(2)
            if recipient.contact(sender_key) is not None:
                raise AssertionError("invalid introduction created a contact")

        timestamp = int(time.time())
        text = f"one-key DM HIL {timestamp}".encode()
        message = bytes([2, 0, 0]) + struct.pack("<I", timestamp) + recipient_key[:6] + text
        sent = sender.request(message, (6,), seconds=20)
        expected_ack = sent[2:6]
        timeout_ms = struct.unpack("<I", sent[6:10])[0]
        offered = None
        rejected = False
        until = time.monotonic() + min(timeout_ms / 1000 + 5, 120)
        while time.monotonic() < until:
            for link in (sender, recipient):
                link.read(0.1)
            offered = next((frame for frame in recipient.pushes
                            if frame[0] == 0x8A and frame[1:33] == sender_key), None)
            rejected = any(frame[0] == 0x91 and frame[1:33] == recipient_key
                           for frame in sender.pushes)
            if offered and rejected:
                break

        if offered is None or not rejected:
            raise AssertionError("signed introduction did not produce advert and refusal")
        if recipient.contact(sender_key) is not None:
            raise AssertionError("recipient added sender without acceptance")
        if any(frame[0] == 0x83 for frame in recipient.pushes):
            raise AssertionError("recipient delivered DM before acceptance")

        # The text follows the introduction on air. Ensure it is actually in
        # the holding queue before accepting, not merely delivered afterward.
        until = time.monotonic() + min(timeout_ms / 1000 + 5, 120)
        while time.monotonic() < until and recipient.cli("get dm.held") != "> 1":
            time.sleep(0.5)
        if recipient.cli("get dm.held") != "> 1":
            raise AssertionError("no decryptable DM was held before acceptance")
        recipient.request(bytes([9]) + offered[1:], (0,))
        until = time.monotonic() + min(timeout_ms / 1000 + 5, 120)
        while time.monotonic() < until:
            for link in (sender, recipient):
                link.read(0.1)
            confirmed = any(frame[0] == 0x82 and frame[1:5] == expected_ack
                            for frame in sender.pushes)
            waiting = any(frame[0] == 0x83 for frame in recipient.pushes)
            if confirmed and waiting:
                break

        confirmed = any(
            frame[0] == 0x82 and frame[1:5] == expected_ack for frame in sender.pushes
        )
        waiting = any(frame[0] == 0x83 for frame in recipient.pushes)
        learned = recipient.contact(sender_key) is not None
        queue_scan = consume_expected_dm(recipient, sender_key, timestamp,
                                         text, queue_capacity)
        replayed = queue_scan["matched"]
        result = {
            "sender_prefix": sender_key[:6].hex(),
            "recipient_prefix": recipient_key[:6].hex(),
            "route": "direct" if sent[1] == 0 else "flood",
            "ack_confirmed": confirmed,
            "recipient_message_waiting": waiting,
            "recipient_learned_sender": learned,
            "synthetic_advert_offered": offered is not None,
            "signed_refusal_received": rejected,
            "held_message_replayed": replayed,
            "offline_messages_skipped": queue_scan["skipped"],
            "offline_queue_empty": queue_scan["empty"],
            "offline_queue_scan_limit": queue_capacity,
            "timeout_ms": timeout_ms,
        }
        if invalid_signature_first:
            result["invalid_signature_rejected"] = True
        if not (confirmed and waiting and learned and replayed):
            raise AssertionError(json.dumps(result, sort_keys=True))
        return result
    finally:
        if prior_dm_setting == "> on":
            try:
                recipient.cli("set dm.one_key on")
            except Exception:
                pass
        sender.close()
        recipient.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sender", required=True, help="sender Companion USB serial path")
    parser.add_argument("--recipient", required=True, help="recipient Companion USB serial path")
    parser.add_argument("--reset-contact", action="store_true",
                        help="remove the sender from recipient contacts before the test")
    parser.add_argument("--zero-hop", action="store_true",
                        help="set a direct zero-hop path; use only when both radios are nearby")
    parser.add_argument("--invalid-signature-first", action="store_true",
                        help="verify an encrypted introduction with a bad signature is rejected")
    parser.add_argument("--queue-capacity", type=int, choices=(256, 512), default=256,
                        help="recipient offline queue capacity; 512 for PSRAM builds (default: 256)")
    args = parser.parse_args()
    print(json.dumps(run(args.sender, args.recipient, args.reset_contact,
                         args.zero_hop, args.invalid_signature_first,
                         args.queue_capacity),
                     sort_keys=True))
