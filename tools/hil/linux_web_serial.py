"""Scope Linux TTY read settings to a native Web Serial hardware test.

Call after the last pyserial session, while other serial clients are paused.
The caller must close its browser streams before leaving the context, including
on failure. No descriptor is held across the trial, so a stock browser close
retains its normal last-close behavior. This helper sends no serial data and
does not set DTR/RTS, reset USB, or change firmware.
"""

from contextlib import contextmanager
import copy
import os
from pathlib import Path
import sys
import termios


def _identity(fd):
    stat = os.fstat(fd)
    return stat.st_dev, stat.st_ino, stat.st_rdev


def _open_tty(path):
    fd = os.open(path, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    if not os.isatty(fd):
        os.close(fd)
        raise ValueError("The explicit path must identify a TTY")
    return fd


def _apply_and_check(fd, attributes):
    if termios.tcgetattr(fd) != attributes:
        termios.tcsetattr(fd, termios.TCSANOW, attributes)
    if termios.tcgetattr(fd) != attributes:
        raise RuntimeError("TTY attribute readback differs from the requested settings")


@contextmanager
def prepared_linux_web_serial(port):
    """Set/check VMIN=1, VTIME=0 for one test; restore exact prior termios.

    Requires an explicit absolute path. A replaced endpoint is rejected before
    restoration rather than changing a different device. Preparation failures
    also restore the original attributes. Browser/serial ownership and signal
    cleanup remain the caller's responsibility; close native streams first.
    """
    if sys.platform != "linux":
        raise RuntimeError("This preflight is for Linux native Web Serial only")
    path = os.fspath(port)
    if not Path(path).is_absolute():
        raise ValueError("An explicit absolute TTY path is required")

    fd = _open_tty(path)
    original = None
    try:
        identity = _identity(fd)
        original = termios.tcgetattr(fd)
        desired = copy.deepcopy(original)
        # Python represents these slots as bytes in canonical mode and ints
        # in noncanonical mode. Preserve that representation for exact checks.
        desired[6][termios.VMIN] = (
            b"\x01" if isinstance(original[6][termios.VMIN], bytes) else 1)
        desired[6][termios.VTIME] = (
            b"\x00" if isinstance(original[6][termios.VTIME], bytes) else 0)
        try:
            _apply_and_check(fd, desired)
        except BaseException:
            _apply_and_check(fd, original)
            raise
    finally:
        os.close(fd)

    def cc_number(value):
        return value[0] if isinstance(value, bytes) else value

    try:
        yield {
            "vmin_before": cc_number(original[6][termios.VMIN]),
            "vtime_before": cc_number(original[6][termios.VTIME]),
            "vmin_during_test": 1,
            "vtime_during_test": 0,
        }
    finally:
        fd = _open_tty(path)
        try:
            if _identity(fd) != identity:
                raise RuntimeError("TTY endpoint changed; original attributes were not applied")
            _apply_and_check(fd, original)
        finally:
            os.close(fd)
