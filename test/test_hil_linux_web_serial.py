#!/usr/bin/env python3
"""Actual Linux pseudoterminal tests; never opens a physical radio."""

import copy
import errno
import importlib.util
import os
from pathlib import Path
import pty
import select
import termios
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "hil_linux_web_serial", ROOT / "tools/hil/linux_web_serial.py")
HIL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(HIL)


class NativeTTYTests(unittest.TestCase):
    def setUp(self):
        self.master, slave = pty.openpty()
        self.path = os.ttyname(slave)
        self.assertTrue(self.path.startswith("/dev/pts/"))
        attrs = termios.tcgetattr(slave)
        attrs[3] &= ~(termios.ICANON | termios.ECHO | termios.ISIG)
        attrs[1] &= ~termios.OPOST
        attrs[6][termios.VMIN] = 0
        attrs[6][termios.VTIME] = 0
        termios.tcsetattr(slave, termios.TCSANOW, attrs)
        self.original = termios.tcgetattr(slave)
        os.close(slave)
        self.addCleanup(os.close, self.master)

    def attributes(self):
        fd = os.open(self.path, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        try:
            return termios.tcgetattr(fd)
        finally:
            os.close(fd)

    def test_inherited_zero_read_is_fixed_and_exact_attributes_restored(self):
        fd = os.open(self.path, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        self.assertEqual(os.read(fd, 16), b"")
        os.close(fd)
        with HIL.prepared_linux_web_serial(self.path) as evidence:
            self.assertEqual(evidence["vmin_before"], 0)
            fd = os.open(self.path, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
            try:
                expected = copy.deepcopy(self.original)
                expected[6][termios.VMIN] = 1
                self.assertEqual(termios.tcgetattr(fd), expected)
                with self.assertRaises(BlockingIOError) as raised:
                    os.read(fd, 16)
                self.assertEqual(raised.exception.errno, errno.EAGAIN)
                os.write(self.master, b"x")
                readable, _, _ = select.select([fd], [], [], 1.0)
                self.assertEqual(readable, [fd])
                self.assertEqual(os.read(fd, 16), b"x")
            finally:
                os.close(fd)
        self.assertEqual(self.attributes(), self.original)

    def test_test_failure_restores_all_attributes(self):
        with self.assertRaisesRegex(RuntimeError, "browser failed"):
            with HIL.prepared_linux_web_serial(self.path):
                fd = os.open(self.path, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
                try:
                    attrs = termios.tcgetattr(fd)
                    attrs[0] ^= termios.IXOFF
                    attrs[6][termios.VTIME] = 7
                    termios.tcsetattr(fd, termios.TCSANOW, attrs)
                finally:
                    os.close(fd)
                raise RuntimeError("browser failed")
        self.assertEqual(self.attributes(), self.original)

    def test_interrupted_test_restores_attributes(self):
        with self.assertRaises(KeyboardInterrupt):
            with HIL.prepared_linux_web_serial(self.path):
                raise KeyboardInterrupt()
        self.assertEqual(self.attributes(), self.original)

    def test_failed_preparation_readback_restores_before_yield(self):
        original_apply = HIL._apply_and_check

        def fail_after_normalization(fd, attrs):
            original_apply(fd, attrs)
            if attrs[6][termios.VMIN] == 1:
                raise RuntimeError("simulated preparation readback failure")

        with mock.patch.object(HIL, "_apply_and_check", side_effect=fail_after_normalization):
            with self.assertRaisesRegex(RuntimeError, "preparation readback failure"):
                with HIL.prepared_linux_web_serial(self.path):
                    self.fail("failed preflight must not yield")
        self.assertEqual(self.attributes(), self.original)

    def test_ignored_write_is_rejected_by_actual_readback(self):
        with mock.patch.object(termios, "tcsetattr") as setter:
            with self.assertRaisesRegex(RuntimeError, "readback differs"):
                with HIL.prepared_linux_web_serial(self.path):
                    self.fail("ignored normalization must not yield")
            self.assertEqual(setter.call_count, 1)
        self.assertEqual(self.attributes(), self.original)

    def test_already_normalized_tty_needs_no_attribute_write(self):
        fd = os.open(self.path, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        attrs = termios.tcgetattr(fd)
        attrs[6][termios.VMIN] = 1
        termios.tcsetattr(fd, termios.TCSANOW, attrs)
        os.close(fd)
        with mock.patch.object(termios, "tcsetattr", wraps=termios.tcsetattr) as setter:
            with HIL.prepared_linux_web_serial(self.path):
                pass
            setter.assert_not_called()
        self.assertEqual(self.attributes(), attrs)

    def test_canonical_attribute_representation_is_preserved(self):
        fd = os.open(self.path, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        attrs = termios.tcgetattr(fd)
        attrs[3] |= termios.ICANON
        termios.tcsetattr(fd, termios.TCSANOW, attrs)
        original = termios.tcgetattr(fd)
        os.close(fd)
        with HIL.prepared_linux_web_serial(self.path) as evidence:
            self.assertEqual(evidence["vmin_before"], 0)
            expected = copy.deepcopy(original)
            expected[6][termios.VMIN] = b"\x01"
            self.assertEqual(self.attributes(), expected)
        self.assertEqual(self.attributes(), original)

    def test_no_second_descriptor_is_held_during_the_trial(self):
        opened = []
        original_open = HIL._open_tty

        def capture(path):
            fd = original_open(path)
            opened.append(fd)
            return fd

        with mock.patch.object(HIL, "_open_tty", side_effect=capture):
            with HIL.prepared_linux_web_serial(self.path):
                with self.assertRaises(OSError):
                    os.fstat(opened[0])
        self.assertEqual(self.attributes(), self.original)

    def test_replaced_endpoint_is_not_modified(self):
        other_master, other_slave = pty.openpty()
        other_path = os.ttyname(other_slave)
        self.addCleanup(os.close, other_master)
        self.addCleanup(os.close, other_slave)
        attrs = termios.tcgetattr(other_slave)
        original_open = HIL._open_tty
        calls = 0

        def substitute_restore(path):
            nonlocal calls
            calls += 1
            return original_open(path if calls == 1 else other_path)

        with mock.patch.object(HIL, "_open_tty", side_effect=substitute_restore):
            with self.assertRaisesRegex(RuntimeError, "endpoint changed"):
                with HIL.prepared_linux_web_serial(self.path):
                    pass
        self.assertEqual(termios.tcgetattr(other_slave), attrs)

    def test_explicit_absolute_tty_required(self):
        with self.assertRaisesRegex(ValueError, "absolute TTY"):
            with HIL.prepared_linux_web_serial("ttyACM0"):
                self.fail("relative device must not be opened")
        with self.assertRaisesRegex(ValueError, "must identify a TTY"):
            with HIL.prepared_linux_web_serial("/dev/null"):
                self.fail("non-TTY must not be yielded")


if __name__ == "__main__":
    unittest.main()
