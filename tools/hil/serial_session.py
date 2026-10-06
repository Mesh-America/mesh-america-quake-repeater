"""Open an already configured serial session without a bridge reset pulse."""
import os


def open_configured_session(port):
    # POSIX pySerial normally applies DTR before RTS when opening. Some
    # bridge drivers initially assert both lines; clearing DTR first pulses
    # ESP32 EN. Defer DTR until RTS is released. Windows configures both in
    # one DCB operation and uses dsrdtr for real handshaking, so leave it alone.
    # The caller selects DTR and supplies the already configured port; no USB
    # inventory or pySerial import is needed here.
    defer_dtr = os.name == "posix" and not port.dtr
    previous_dsrdtr = port.dsrdtr
    try:
        if defer_dtr:
            port.dsrdtr = True
        port.open()
        if defer_dtr:
            port.rts = False
            port.dtr = False
            port.dsrdtr = previous_dsrdtr
    except BaseException:
        try:
            port.close()
        finally:
            if defer_dtr:
                port.dsrdtr = previous_dsrdtr
        raise
