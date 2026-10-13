#!/usr/bin/env python3
"""Identity-bound Morse TX/RX trial at 902.1 MHz, low TX power.

No flashing, erasure, service stopping or power cycling. Received text comes
from the actual firmware's CLI capture pages, never a host-side decoder.
The active LoRa packet profile stays at 909.5 MHz, 500 kHz, SF5, CR5.
"""
import argparse
import json
import math
from pathlib import Path
import re
import time
import serial
from serial.tools import list_ports

SERIALS = {"rak": "9AB3B64C641BA927", "t096": "651F8E496197F882",
           "pocket": "93DA83ADF7B2092B"}
DEFAULT_CW_FREQUENCY = 902.1
PACKET_RADIO = "909.5,500,5,5"
MESSAGES = (
    "SOS TEST DE N0CALL 0123456789 ABCDEFGHIJKLMNOPQRSTUVWXYZ",
    "E T I M S O H Z 5 0 PARIS QUICK BROWN FOX JUMPS OVER LAZY DOG",
    ". , ? ' ! / ( ) & : ; = + - _ \" $ @",
)


def parse_cw_frequency(text):
    """Keep CW in the lab band, clear of the 500 kHz packet RX bandwidth."""
    try:
        frequency = round(float(text), 6)
    except (ValueError, TypeError, OverflowError):
        raise argparse.ArgumentTypeError("CW frequency must be a finite MHz value") from None
    if not math.isfinite(frequency) or not 902 <= frequency <= 928:
        raise argparse.ArgumentTypeError("CW frequency must be between 902 and 928 MHz")
    if abs(frequency - 909.5) <= .260 + 1e-9:
        raise argparse.ArgumentTypeError("CW frequency overlaps the 909.5 MHz packet radio and guard")
    return frequency


def live_temporary_profile(reply):
    """Parse only confirmed live profiles, never saved/pending radio settings."""
    fields = r"(\d+(?:\.\d+)?),(\d+(?:\.\d+)?),(\d+),(\d+)"
    companion = re.search(r"TempRadio active:\s*" + fields + r"(?=\s|$)", reply)
    infrastructure = re.search(
        r"(?m)^\s*(?:->\s*)?>\s*" + fields + r"(?:,\d+)?\s*$", reply)
    match = companion or infrastructure
    if match is None:
        return None
    return float(match[1]), float(match[2]), int(match[3]), int(match[4])


class Console:
    def __init__(self, serial_number, companion=True):
        matches = [p for p in list_ports.comports()
                   if (p.serial_number or "").upper() == serial_number
                   and p.interface != "MeshCore Logging"]
        if len(matches) != 1:
            raise RuntimeError(f"Missing/ambiguous application USB identity {serial_number}")
        self.serial_number = serial_number
        self.companion = companion
        self.port = serial.Serial(port=None, baudrate=115200, timeout=.015)
        self.port.dtr, self.port.rts = True, False
        self.port.port = matches[0].device
        self.port.open()
        self.commands = []
        try:
            hello = self.read_quiet(1)
            if companion and "WELCOME" not in hello:
                self.port.write(b"+++MESHCORE-TERM-START\r\n")
                self.read_quiet(1)
            self.command("ver")
            self.command("board")
        except BaseException:
            self.port.close()
            raise

    def read_quiet(self, timeout=2):
        data = bytearray()
        end = quiet = time.monotonic() + timeout
        while time.monotonic() < end and time.monotonic() < quiet:
            chunk = self.port.read(self.port.in_waiting or 1)
            if chunk:
                data.extend(chunk)
                quiet = time.monotonic() + .12
        return data.decode("utf-8", errors="replace")

    def command(self, text, timeout=3, allow_error=False):
        if self.port.in_waiting:
            self.read_quiet(.15)
        self.port.write((text + "\r\n").encode())
        data = bytearray()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            data.extend(self.port.read(self.port.in_waiting or 1))
            reply = data.decode("utf-8", errors="replace")
            # Flash writes/display callbacks can outlast a quiet interval.
            # Await the command response AND its closing owned-terminal prompt,
            # not merely an echoed command or asynchronous RX prompt redraw.
            complete = reply.endswith("\r\n> ") if self.companion else reply.endswith("\r\n")
            if ("  -> " in reply or "  ERROR:" in reply
                    or re.search(r"(?:^|\r\n)  OK(?:\r\n| -)", reply)) and complete:
                break
        else:
            raise RuntimeError(("Incomplete CLI response", self.serial_number, text,
                                data.decode("utf-8", errors="replace")))
        self.commands.append({"command": text, "reply": reply})
        if not reply or (not allow_error and re.search(r"\b(?:Error|ERROR|ERR)\b", reply)):
            raise RuntimeError((self.serial_number, text, reply))
        return reply

    def setup(self, cw_frequency=DEFAULT_CW_FREQUENCY):
        self.command("morse stop")
        self.start_when_idle("set radio.rxps off")
        self.start_when_idle("set tx -9")
        self.start_when_idle("set radio2 off")
        self.command(f"set morse.freq {cw_frequency:.6f}")
        self.command("set morse.wpm 25")
        self.apply_live_temporary(PACKET_RADIO)

    def apply_live_temporary(self, profile, timeout=12):
        expected = tuple(float(value) for value in profile.split(","))
        if len(expected) != 4:
            raise ValueError("Expected frequency, bandwidth, SF and CR")
        self.start_when_idle("set tempradio " + profile + ",30")
        deadline = time.monotonic() + timeout
        while True:
            reply = self.command("get tempradio")
            if live_temporary_profile(reply) == expected:
                return reply
            if time.monotonic() >= deadline:
                raise RuntimeError(("Live temporary radio did not apply", self.serial_number,
                                    profile, reply))
            time.sleep(.1)

    def start_when_idle(self, text):
        deadline = time.monotonic() + 10
        while True:
            reply = self.command(text, allow_error=True)
            if "Error: radio busy" not in reply:
                if re.search(r"\b(?:Error|ERROR|ERR)\b", reply):
                    raise RuntimeError((self.serial_number, text, reply))
                return reply
            if time.monotonic() >= deadline:
                raise RuntimeError(("Radio remained busy", self.serial_number, text, reply))
            time.sleep(.1)

    def capture(self):
        text, offset = "", 0
        for _ in range(100):
            # A valid text capture can itself contain ERROR; only the framed
            # page parser can distinguish that payload from a CLI failure.
            reply = self.command(f"morse read {offset}", allow_error=True)
            page = re.search(
                r"> (\d{4})/(\d{4}) next=(\d{4}|END ) truncated=(\d) ([^\r\n]*)",
                reply)
            if not page or int(page[1]) != offset or int(page[4]):
                raise RuntimeError(("Malformed/truncated capture page", reply))
            text += page[5]
            if page[3].strip() == "END":
                return text
            following = int(page[3])
            if following != len(text) or following <= offset:
                raise RuntimeError(("Non-progressing capture", reply))
            offset = following
        raise RuntimeError("Capture paging did not finish")

    def trace(self):
        rows, offset, total = [], 0, None
        for _ in range(100):
            reply = self.command(f"morse trace {offset}")
            page = re.search(r"> (\d{3})/(\d{3}) t=(\d+) n=(\d{3}|END) x=([01]) ([^\r\n]*)", reply)
            if not page or int(page[1]) != offset:
                raise RuntimeError(("Malformed trace page", reply))
            if total is not None and total != int(page[3]):
                raise RuntimeError("Trace changed during retrieval")
            total = int(page[3])
            for item in page[6].split(";"):
                if item:
                    at, rssi, flags = map(int, item.split(","))
                    rows.append({"ms": at, "dbm": rssi, "flags": flags})
            if page[4] == "END":
                if len(rows) != int(page[2]):
                    raise RuntimeError("Incomplete retained trace")
                return {"total": total, "overwritten": bool(int(page[5])), "rows": rows}
            following = int(page[4])
            if following != len(rows) or following <= offset:
                raise RuntimeError("Non-progressing trace")
            offset = following
        raise RuntimeError("Trace paging did not finish")

    def close(self):
        try:
            self.command("morse stop", allow_error=True)
            self.command("set morse.wpm 25", allow_error=True)
        finally:
            self.port.close()


def trial(tx, rx, wpm, message, seconds=60, trace=False):
    tx.command("morse stop")
    rx.command("morse stop")
    tx.command(f"set morse.wpm {wpm}")
    rx.command(f"set morse.wpm {wpm}")
    rx.start_when_idle(f"morse listen {seconds / 60:.4f}")
    # Establish a real quiet RSSI floor before any carrier transmission.
    time.sleep(.8)
    started = time.monotonic()
    tx.start_when_idle("morse send " + message)
    while time.monotonic() - started < 180:
        if "> off;" in tx.command("get morse"):
            break
        time.sleep(.15)
    else:
        raise RuntimeError("Transmitter did not stop")
    tx_finished = time.monotonic()
    time.sleep(.6)
    rx_status = rx.command("get morse")
    stats = rx.command("morse stats")
    rx.command("morse stop")
    decoded = rx.capture()
    result = {"wpm": wpm, "nominal_dot_ms": (1200 + wpm // 2) // wpm,
            "tx_serial": tx.serial_number, "rx_serial": rx.serial_number,
            "sent": message, "decoded": decoded, "passed": decoded.strip() == message,
            "tx_elapsed_s": round(tx_finished - started, 3),
            "rx_status": rx_status, "rx_stats": stats}
    if trace:
        result["trace"] = rx.trace()
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--cw-frequency", type=parse_cw_frequency, default=DEFAULT_CW_FREQUENCY,
                        help="CW MHz (default 902.1); must not overlap the packet radio")
    parser.add_argument("--rates", default="25,40,60,75,80,100,120,150,200,240")
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--messages", type=int, default=3, choices=(1, 2, 3))
    parser.add_argument("--partner", choices=("t096", "pocket"), default="t096",
                        help="Exact USB partner to pair with the RAK; no other radio is opened")
    parser.add_argument("--direction", choices=("both", "to-rak", "from-rak"), default="both",
                        help="Test both directions, partner TX to RAK, or RAK TX to partner")
    parser.add_argument("--trace", action="store_true", help="Requires a MESH_MORSE_HIL trace build")
    parser.add_argument("--quiet-seconds", type=int, default=0,
                        help="No-transmitter receive control, 1-30 seconds")
    parser.add_argument("--t096-rxgain", choices=("on", "off"),
                        help="Temporary diagnostic gain setting; restored afterward")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Refusing to overwrite an existing result")
    rates = [int(value) for value in args.rates.split(",")]
    if not rates or any(rate < 1 or rate > 255 for rate in rates) or not 1 <= args.repeats <= 10:
        parser.error("Rates 1-255 and repeats 1-10 only")
    if args.quiet_seconds and not 1 <= args.quiet_seconds <= 30:
        parser.error("Quiet control duration must be 1-30 seconds")
    if args.t096_rxgain and args.partner != "t096":
        parser.error("--t096-rxgain requires --partner t096")
    results = {"frequency_mhz": args.cw_frequency, "packet_radio": PACKET_RADIO,
               "requested_chip_power_dbm": -9,
               "partner": args.partner, "direction": args.direction,
               "scope": "Experimental HIL applications on this pair; not production speed qualification or all radio families.",
               "trials": [], "finished": False}
    devices = {}
    original_gain = None
    try:
        for name in ("rak", args.partner):
            devices[name] = Console(SERIALS[name])
        for device in devices.values():
            device.setup(args.cw_frequency)
        if args.t096_rxgain:
            gain_reply = devices["t096"].command("get radio.fem.rxgain")
            match = re.search(r"> (on|off)\b", gain_reply)
            if not match:
                raise RuntimeError(("Unrecognized gain status", gain_reply))
            original_gain = match[1]
            devices["t096"].command("set radio.fem.rxgain " + args.t096_rxgain)
        if args.quiet_seconds:
            for device in devices.values():
                device.start_when_idle(f"morse listen {args.quiet_seconds / 60:.4f}")
            time.sleep(args.quiet_seconds + .2)
            for name, device in devices.items():
                result = {"kind": "quiet_control", "receiver": name,
                          "rx_stats": device.command("morse stats")}
                device.command("morse stop")
                result["decoded"] = device.capture()
                result["passed"] = not result["decoded"]
                if args.trace:
                    result["trace"] = device.trace()
                results["trials"].append(result)
                print(json.dumps({key: value for key, value in result.items()
                                  if key != "trace"}), flush=True)
            results["finished"] = True
            return
        directions = []
        if args.direction in ("both", "to-rak"):
            directions.append((args.partner, "rak"))
        if args.direction in ("both", "from-rak"):
            directions.append(("rak", args.partner))
        for rate in rates:
            for tx_name, rx_name in directions:
                for repeat in range(args.repeats):
                    for message in MESSAGES[:args.messages]:
                        result = trial(devices[tx_name], devices[rx_name], rate, message, trace=args.trace)
                        result["repeat"] = repeat
                        results["trials"].append(result)
                        printable = {key: value for key, value in result.items() if key != "trace"}
                        if "trace" in result:
                            printable["trace_rows"] = len(result["trace"]["rows"])
                        print(json.dumps(printable), flush=True)
                        args.output.write_text(json.dumps(results, indent=2) + "\n")
        results["finished"] = True
    except BaseException as error:
        results["error"] = str(error)
        raise
    finally:
        if original_gain is not None:
            try:
                devices["t096"].command("morse stop", allow_error=True)
                devices["t096"].command("set radio.fem.rxgain " + original_gain)
            except Exception as error:
                results.setdefault("cleanup_errors", []).append(str(error))
        for device in devices.values():
            try:
                device.close()
            except Exception as error:
                results.setdefault("cleanup_errors", []).append(str(error))
        results["commands"] = {name: device.commands for name, device in devices.items()}
        args.output.write_text(json.dumps(results, indent=2) + "\n")


if __name__ == "__main__":
    main()
