"""Offline queue and serial-control regressions for the one-key DM HIL run."""

import struct
import sys
import types
import unittest
from unittest import mock

import one_key_dm as hil


SENDER = bytes(range(32))
TIMESTAMP = 1_791_096_123
TEXT = b"one-key DM HIL 1791096123"


def contact_frame(code=7, text=TEXT, sender=SENDER, timestamp=TIMESTAMP):
    header = bytes([code]) + (b"\0\0\0" if code == 16 else b"")
    return header + sender[:6] + b"\xff\0" + struct.pack("<I", timestamp) + text


class Queue:
    def __init__(self, frames):
        self.frames = iter(frames)
        self.reads = 0

    def request(self, payload, expected):
        assert payload == bytes([10])
        assert expected == (7, 8, 10, 16, 17)
        self.reads += 1
        return next(self.frames)


class OneKeyDmTest(unittest.TestCase):
    def scan(self, queue, capacity=256):
        return hil.consume_expected_dm(queue, SENDER, TIMESTAMP, TEXT, capacity)

    def test_channel_messages_before_dm_are_skipped_for_both_protocol_versions(self):
        for code in (7, 16):
            with self.subTest(code=code):
                queue = Queue([b"\x08ambient channel", b"\x11another channel",
                               contact_frame(code)])
                self.assertEqual(self.scan(queue),
                                 {"matched": True, "skipped": 2, "empty": False})
                self.assertEqual(queue.reads, 3)

    def test_earlier_unrelated_dms_cannot_match_by_substring_or_other_sender(self):
        queue = Queue([
            contact_frame(text=b"earlier " + TEXT),
            contact_frame(sender=bytes(range(1, 33))),
            contact_frame(timestamp=TIMESTAMP - 1),
            contact_frame(16),
        ])
        self.assertEqual(self.scan(queue),
                         {"matched": True, "skipped": 3, "empty": False})

    def test_empty_queue_stops_without_reading_another_frame(self):
        queue = Queue([b"\x0a", contact_frame()])
        self.assertEqual(self.scan(queue),
                         {"matched": False, "skipped": 0, "empty": True})
        self.assertEqual(queue.reads, 1)

    def test_nonmatching_queue_stops_at_each_supported_capacity(self):
        for capacity in (256, 512):
            with self.subTest(capacity=capacity):
                queue = Queue([contact_frame(text=b"unrelated")] * capacity
                              + [contact_frame()])
                self.assertEqual(self.scan(queue, capacity),
                                 {"matched": False, "skipped": capacity, "empty": False})
                self.assertEqual(queue.reads, capacity)

    def test_dm_in_last_queue_slot_is_still_found(self):
        queue = Queue([b"\x08ambient"] * 255 + [contact_frame()])
        self.assertTrue(self.scan(queue)["matched"])
        self.assertEqual(queue.reads, 256)

    def test_truncated_contact_fails_without_exposing_its_contents(self):
        with self.assertRaisesRegex(RuntimeError, "^truncated queued contact message$"):
            self.scan(Queue([b"\x07sensitive"]))

    def test_invalid_capacity_does_not_consume_queue(self):
        queue = Queue([contact_frame()])
        with self.assertRaises(ValueError):
            self.scan(queue, 1024)
        self.assertEqual(queue.reads, 0)

    def test_serial_control_lines_and_exclusivity_are_set_before_open(self):
        events = []

        class Serial:
            def __init__(self, **kwargs):
                self.kwargs = kwargs
                self.is_open = False
                events.append(("create", kwargs))

            def __setattr__(self, name, value):
                if name in ("dtr", "rts", "port"):
                    assert not self.is_open
                    events.append((name, value))
                object.__setattr__(self, name, value)

            def open(self):
                assert self.dtr is True and self.rts is False
                assert self.kwargs["exclusive"] is True
                self.is_open = True
                events.append(("open", None))

        with mock.patch.dict(sys.modules, {"serial": types.SimpleNamespace(Serial=Serial)}):
            link = hil.Link("/dev/ttyFAKE")
        self.assertTrue(link.port.is_open)
        self.assertLess(events.index(("dtr", True)), events.index(("open", None)))
        self.assertLess(events.index(("rts", False)), events.index(("open", None)))


if __name__ == "__main__":
    unittest.main()
