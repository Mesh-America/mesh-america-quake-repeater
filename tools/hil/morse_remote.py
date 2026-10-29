#!/usr/bin/env python3
"""Real LoRa ACK-first Morse RX/capture trial on Mercerwood Mesh.

Identity-bound RAK4631 repeater/T096 or Mesh Pocket Companion only. No flashing, erasure,
reboot, power control or service changes. Packets stay on 909.5 MHz, 500 kHz,
SF5, CR5. Keyed CW defaults to the user's 902.1 MHz, isolated from packet RX.
"""
import argparse
import asyncio
import json
from pathlib import Path
import re
import time

if __package__:
    from .morse_bench import (Console, SERIALS, live_temporary_profile,
                              DEFAULT_CW_FREQUENCY, parse_cw_frequency)
else:
    from morse_bench import (Console, SERIALS, live_temporary_profile,
                            DEFAULT_CW_FREQUENCY, parse_cw_frequency)

PACKET_RADIO = "909.5,500,5,5"
DEFAULT_MESSAGE = "REMOTE MORSE TEST 0123456789"
MORSE_CODES = dict(zip("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789", (
    ".-", "-...", "-.-.", "-..", ".", "..-.", "--.", "....", "..", ".---",
    "-.-", ".-..", "--", "-.", "---", ".--.", "--.-", ".-.", "...", "-",
    "..-", "...-", ".--", "-..-", "-.--", "--..", "-----", ".----", "..---",
    "...--", "....-", ".....", "-....", "--...", "---..", "----.")))
MORSE_CODES.update(dict(zip(".,?'!/()&:;=+-_\"$@", (
    ".-.-.-", "--..--", "..--..", ".----.", "-.-.--", "-..-.", "-.--.", "-.--.-",
    ".-...", "---...", "-.-.-.", "-...-", ".-.-.", "-....-", "..--.-", ".-..-.",
    "...-..-", ".--.-."))))
ERROR = re.compile(r"\b(?:Error|ERROR|ERR|Err)\b")
CAPTURE_PAGE = re.compile(
    r"> (\d{4})/(\d{4}) next=(\d{4}|END ) truncated=([01]) ([^\r\n]*)")


def parse_capture_page(reply, offset):
    """Validate production paging, including its padded END marker."""
    match = CAPTURE_PAGE.search(reply)
    if not match or int(match[1]) != offset:
        raise RuntimeError(("Malformed capture page", offset, reply))
    total, fragment = int(match[2]), match[5]
    if int(match[4]) or total > 4096 or offset + len(fragment) > total:
        raise RuntimeError(("Truncated/inconsistent capture", reply))
    if match[3] == "END ":
        if offset + len(fragment) != total:
            raise RuntimeError(("Incomplete final capture page", reply))
        following = None
    else:
        following = int(match[3])
        if following != offset + len(fragment) or following <= offset or following >= total:
            raise RuntimeError(("Non-progressing capture page", reply))
    return fragment, following, total


async def read_capture(command):
    text, offset, expected_total, pages = "", 0, None, []
    for _ in range(100):
        reply = await command(f"morse read {offset}")
        fragment, following, total = parse_capture_page(reply, offset)
        if expected_total is not None and expected_total != total:
            raise RuntimeError("Capture changed during paging")
        expected_total = total
        pages.append({"offset": offset, "reply": reply})
        text += fragment
        if following is None:
            return text, pages
        offset = following
    raise RuntimeError("Capture paging did not finish")


async def apply_live_temporary(command, profile, timeout=12):
    """Wait for the immediate radio change, not a saved-only settings ACK."""
    expected = tuple(float(value) for value in profile.split(","))
    if len(expected) != 4:
        raise ValueError("Expected frequency, bandwidth, SF and CR")
    await command("set tempradio " + profile + ",30")
    deadline = time.monotonic() + timeout
    while True:
        reply = await command("get tempradio")
        if live_temporary_profile(reply) == expected:
            return reply
        if time.monotonic() >= deadline:
            raise RuntimeError(("Live temporary radio did not apply", profile, reply))
        await asyncio.sleep(.1)


def capture_evidence(expected, local_text, local_pages, remote_text=None, remote_pages=None):
    """Retain RF decoding and exact LoRa retrieval as independent evidence."""
    return {"expected": expected, "local": local_text, "remote": remote_text,
            "local_pages": local_pages, "remote_pages": remote_pages or [],
            "exact_remote_match": None if remote_text is None else remote_text == local_text,
            "exact_rf_match": local_text.strip() == expected}


def public_key(reply):
    keys = re.findall(r"(?<![0-9A-Fa-f])[0-9A-Fa-f]{64}(?![0-9A-Fa-f])", reply)
    if len(keys) != 1:
        raise RuntimeError(("Missing/ambiguous public key", reply))
    return keys[0].lower()


def nominal_seconds(message, wpm):
    """Reject impossible test windows before modifying either radio."""
    words = message.split(" ")
    if not words or any(not word for word in words):
        raise ValueError("Use single spaces, without leading/trailing whitespace")
    units = 7 * (len(words) - 1)
    for word in words:
        units += 3 * (len(word) - 1)
        for char in word:
            symbols = MORSE_CODES[char]
            units += len(symbols) - 1 + sum(3 if symbol == "-" else 1 for symbol in symbols)
    return units * ((1200 + wpm // 2) // wpm) / 1000


class BinaryCLI:
    """Process-local SDK compatibility for firmware's local CLI reply 29."""
    def __init__(self, mc, reader_class, contact_event, record):
        self.mc, self.contact_event, self.record = mc, contact_event, record
        self.reader_class, self.original = reader_class, reader_class.handle_rx
        self.replies = asyncio.Queue(maxsize=64)
        self.counter, self.last_timestamp = 0, 0
        self.lock = asyncio.Lock()
        original, target_reader, queue = self.original, mc._reader, self.replies

        async def handle_rx(reader, data):
            if reader is target_reader and data:
                self.record("source_frame", opcode=int(data[0]), bytes=len(data))
            if reader is target_reader and data and data[0] == 29:
                if queue.full():
                    queue.get_nowait()
                queue.put_nowait(bytes(data[1:]).decode("utf-8", "strict"))
                return
            await original(reader, data)

        self.patched = handle_rx
        reader_class.handle_rx = handle_rx

    def restore_reader(self):
        if self.reader_class.handle_rx is self.patched:
            self.reader_class.handle_rx = self.original

    def nonce(self):
        alphabet = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        if self.counter >= len(alphabet) ** 2:
            raise RuntimeError("Two-character nonce space exhausted")
        value = self.counter
        self.counter += 1
        return alphabet[value // len(alphabet)] + alphabet[value % len(alphabet)]

    async def local(self, command, timeout=5, allow_error=False):
        async with self.lock:
            prefix = self.nonce() + "|"
            started = time.monotonic()
            # This return only proves USB admission, never receipt of reply29.
            await self.mc.commands.send(b"\x42" + (prefix + command).encode("ascii"),
                                        expected_events=None)
            while True:
                remaining = timeout - (time.monotonic() - started)
                if remaining <= 0:
                    raise RuntimeError(("Local Binary CLI timeout", command))
                reply = await asyncio.wait_for(self.replies.get(), remaining)
                if reply.startswith(prefix):
                    reply = reply[len(prefix):]
                    break
            self.record("source_local", command=command, reply=reply)
            if not allow_error and ERROR.search(reply):
                raise RuntimeError(("Source CLI error", command, reply))
            return reply

    async def local_when_idle(self, command):
        deadline = time.monotonic() + 10
        while True:
            reply = await self.local(command, allow_error=True)
            if "Error: radio busy" not in reply:
                if ERROR.search(reply):
                    raise RuntimeError(("Source CLI error", command, reply))
                return reply
            if time.monotonic() >= deadline:
                raise RuntimeError(("Source remained busy", command, reply))
            await asyncio.sleep(.1)

    async def remote(self, key, command, timeout=5, allow_error=False):
        async with self.lock:
            prefix = self.nonce() + "|"
            future = asyncio.get_running_loop().create_future()
            peer_prefix = key[:12].lower()

            def receive(event):
                payload = event.payload
                text = payload.get("text", "")
                if (payload.get("pubkey_prefix", "").lower() == peer_prefix
                        and payload.get("txt_type") == 1 and text.startswith(prefix)
                        and not future.done()):
                    future.set_result(text[len(prefix):])

            # Subscribe before send: a fast LoRa reply can precede MSG_SENT.
            subscription = self.mc.subscribe(self.contact_event, receive)
            try:
                # Unique real UTC seconds avoid pushing the peer's anti-replay
                # floor into the future when paging rapidly, including next
                # runs. Cancellation during this wait must retire the listener.
                clock_deadline = time.monotonic() + 2
                while int(time.time()) <= self.last_timestamp:
                    if time.monotonic() >= clock_deadline:
                        raise RuntimeError("UTC clock stopped/backstepped during remote test")
                    await asyncio.sleep(.02)
                self.last_timestamp = int(time.time())
                started = time.monotonic()
                event = await self.mc.commands.send_cmd(key, prefix + command,
                                                       timestamp=self.last_timestamp)
                if event.is_error():
                    raise RuntimeError(("Remote command not admitted", command, event.payload))
                remaining = timeout - (time.monotonic() - started)
                if remaining <= 0:
                    raise RuntimeError(("Remote CLI timeout", command))
                reply = await asyncio.wait_for(future, remaining)
            finally:
                subscription.unsubscribe()
                if not future.done():
                    future.cancel()
            elapsed = time.monotonic() - started
            self.record("remote", command=command, nonce=prefix[:2], reply=reply,
                        latency_seconds=round(elapsed, 4))
            if not allow_error and ERROR.search(reply):
                raise RuntimeError(("Remote CLI error", command, reply))
            return reply, elapsed


async def run(args, results, record):
    from meshcore import MeshCore, EventType
    from meshcore.reader import MessageReader

    peer = source_console = bridge = mc = None
    source_binary = False
    try:
        peer = await asyncio.to_thread(Console, SERIALS["rak"], False)
        source_console = await asyncio.to_thread(Console, SERIALS[args.source])

        async def peer_command(command, allow_error=False):
            reply = await asyncio.to_thread(peer.command, command, 5, allow_error)
            record("peer_local", command=command, reply=reply)
            return reply

        peer_key = public_key(await peer_command("get public.key"))
        source_key = public_key(await asyncio.to_thread(source_console.command, "get public.key"))
        results["public_keys"] = {"peer": peer_key, "source": source_key}
        for device in (peer, source_console):
            for command in ("morse stop", "set radio.rxps off", "set tx -9", "set radio2 off",
                            f"set morse.freq {args.cw_frequency:.6f}", f"set morse.wpm {args.wpm}"):
                await asyncio.to_thread(device.start_when_idle, command)
            await asyncio.to_thread(device.apply_live_temporary, PACKET_RADIO)
        await peer_command("setperm " + source_key + " 3")
        await asyncio.to_thread(source_console.command, "set radio.fem.rxgain on", 5, True)
        source_port = source_console.port.port
        record("configured", peer_usb_serial=SERIALS["rak"], source_usb_serial=SERIALS[args.source],
               peer_commands=peer.commands, source_commands=source_console.commands)

        source_console.port.write(b"+++MESHCORE-TERM-STOP\r\n")
        source_binary = True
        await asyncio.to_thread(source_console.read_quiet, 1)
        # Never Console.close() after STOP: that would inject ASCII into Binary.
        source_console.port.close()
        mc = await MeshCore.create_serial(source_port, baudrate=115200,
                                         only_error=True, default_timeout=5, auto_reconnect=False)
        if mc is None:
            raise RuntimeError("Could not start source Binary Companion session")
        bridge = BinaryCLI(mc, MessageReader, EventType.CONTACT_MSG_RECV, record)
        if public_key(await bridge.local("get public.key")) != source_key:
            raise RuntimeError("Source identity changed at transport handoff")
        contact = {"public_key": peer_key, "type": 2, "flags": 0,
                   "out_path_len": 0, "out_path_hash_mode": 0, "out_path": "",
                   "adv_name": "Morse remote repeater", "last_advert": int(time.time()),
                   "adv_lat": 0, "adv_lon": 0}
        event = await mc.commands.add_contact(contact)
        if event.is_error():
            raise RuntimeError(("Contact admission failed", event.payload))
        await mc.start_auto_message_fetching()
        record("binary_ready", source_port=source_port)

        denied, _ = await bridge.remote(peer_key, "morse listen 6", allow_error=True)
        if not ERROR.search(denied):
            raise RuntimeError((">5 minute listen was not rejected", denied))
        if "> off;" not in await peer_command("get morse"):
            raise RuntimeError("Rejected duration unexpectedly started RX")

        source_live = await bridge.local("get tempradio")
        peer_live = await peer_command("get tempradio")
        if any(live_temporary_profile(reply) != (909.5, 500, 5, 5)
               for reply in (source_live, peer_live)):
            raise RuntimeError(("Packet profile changed before listen", source_live, peer_live))
        record("packet_profiles_verified", source=source_live, peer=peer_live)

        ack, latency = await bridge.remote(peer_key, f"morse listen {args.minutes:g}")
        if latency >= 5 or "Morse RX queued" not in ack:
            raise RuntimeError(("Listen was not acknowledged before RX", ack, latency))
        active_deadline = time.monotonic() + 10
        while True:
            status = await peer_command("get morse")
            if re.search(r"> RX(?:\s| learning)", status):
                break
            if time.monotonic() >= active_deadline:
                raise RuntimeError(("Peer never entered Morse RX", status))
            await asyncio.sleep(.1)
        rx_observed = time.monotonic()
        record("listen_active", status=status, acknowledgement_seconds=round(latency, 4))
        await asyncio.sleep(.8)
        for index in range(args.repeat):
            await bridge.local_when_idle("morse send " + args.message)
            tx_deadline = time.monotonic() + 185
            while "> off;" not in await bridge.local("get morse"):
                if time.monotonic() >= tx_deadline:
                    raise RuntimeError("Source failed to finish Morse TX")
                await asyncio.sleep(.15)
            if index + 1 < args.repeat:
                await asyncio.sleep(.5)
        record("cw_complete", transmissions=args.repeat,
               source_live_packet_radio=PACKET_RADIO)

        expiry_deadline = rx_observed + args.minutes * 60 + 15
        while True:
            status = await peer_command("get morse")
            if "> off;" in status:
                break
            if time.monotonic() >= expiry_deadline:
                raise RuntimeError(("Timed receiver did not recover", status))
            await asyncio.sleep(1)
        record("listen_expired", elapsed_since_observed_seconds=round(time.monotonic() - rx_observed, 3),
               status=status)
        await apply_live_temporary(bridge.local_when_idle, PACKET_RADIO)
        record("source_packet_radio_verified", live_packet_radio=PACKET_RADIO)
        async def local_capture_command(command):
            return await peer_command(command, allow_error=True)

        local_text, local_pages = await read_capture(local_capture_command)
        expected = " ".join([args.message] * args.repeat)
        results["capture"] = capture_evidence(expected, local_text, local_pages)
        record("local_capture_received", captured_characters=len(local_text),
               local_pages=len(local_pages), exact_rf_match=results["capture"]["exact_rf_match"])

        async def remote_command(command):
            return (await bridge.remote(peer_key, command))[0]

        async def remote_capture_command(command):
            # Captured Morse may literally contain ERROR/ERR; the production
            # page parser, not a keyword in the decoded payload, validates it.
            return (await bridge.remote(peer_key, command, allow_error=True))[0]

        remote_text, remote_pages = await read_capture(remote_capture_command)
        results["capture"] = capture_evidence(expected, local_text, local_pages, remote_text, remote_pages)
        record("capture_received", captured_characters=len(local_text), remote_pages=len(remote_pages),
               exact_remote_match=results["capture"]["exact_remote_match"],
               exact_rf_match=results["capture"]["exact_rf_match"])
        radio = await remote_command("get tempradio")
        saved_radio = await remote_command("get radio")
        secondary = await remote_command("get radio2")
        recovered = await remote_command("get morse")
        results["recovery"] = {"live_radio": radio, "saved_radio": saved_radio,
                               "radio2": secondary, "morse": recovered}
        recovery_ok = (live_temporary_profile(radio) == (909.5, 500, 5, 5)
                       and "> off" in secondary and "> off;" in recovered)
        results["recovery"]["passed"] = recovery_ok
        record("recovery_checked", passed=recovery_ok, live_radio=radio,
               saved_radio=saved_radio, radio2=secondary, morse=recovered)
        if not recovery_ok:
            raise RuntimeError(("Packet profile/Morse recovery failed", radio, secondary, recovered))
        if not results["capture"]["exact_remote_match"]:
            raise RuntimeError(("Remote/local capture mismatch", local_text, remote_text))
        if not results["capture"]["exact_rf_match"]:
            raise RuntimeError(("RF decoded text differs from sent text", expected, local_text))
        results["passed"] = True
        record("passed", captured_characters=len(local_text), remote_pages=len(remote_pages))
    finally:
        if bridge is not None:
            for command in ("morse stop", "set morse.wpm 25"):
                try:
                    await bridge.local_when_idle(command)
                except Exception as error:
                    results.setdefault("cleanup_errors", []).append(str(error))
            try:
                await apply_live_temporary(bridge.local_when_idle, PACKET_RADIO)
            except Exception as error:
                results.setdefault("cleanup_errors", []).append(str(error))
        if mc is not None:
            try:
                await mc.disconnect()
            except Exception as error:
                results.setdefault("cleanup_errors", []).append(str(error))
        if bridge is not None:
            bridge.restore_reader()
        if source_console is not None:
            if not source_binary and source_console.port.is_open:
                try:
                    source_console.command("morse stop", allow_error=True)
                    await asyncio.to_thread(source_console.apply_live_temporary, PACKET_RADIO)
                    source_console.close()
                except Exception as error:
                    results.setdefault("cleanup_errors", []).append(str(error))
            source_console.port.close()
            if source_binary and bridge is None:
                # A failed SDK handoff cannot use the already-closed Console.
                # Reacquire this exact identity only after disconnecting SDK.
                recovery = None
                try:
                    recovery = await asyncio.to_thread(Console, SERIALS[args.source])
                    for command in ("morse stop", "set morse.wpm 25"):
                        await asyncio.to_thread(recovery.command, command, 5, True)
                    await asyncio.to_thread(recovery.apply_live_temporary, PACKET_RADIO)
                except Exception as error:
                    results.setdefault("cleanup_errors", []).append(str(error))
                finally:
                    if recovery is not None:
                        recovery.port.close()
        if peer is not None:
            try:
                for command in ("morse stop", "set morse.wpm 25"):
                    await asyncio.to_thread(peer.command, command, 5, True)
                await asyncio.to_thread(peer.apply_live_temporary, PACKET_RADIO)
                peer.close()
            except Exception as error:
                results.setdefault("cleanup_errors", []).append(str(error))
            finally:
                peer.port.close()
                results["peer_commands"] = peer.commands


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--source", choices=("t096", "pocket"), default="t096")
    parser.add_argument("--cw-frequency", type=parse_cw_frequency, default=DEFAULT_CW_FREQUENCY,
                        help="CW MHz (default 902.1); must not overlap the packet radio")
    parser.add_argument("--minutes", type=float, default=.5)
    parser.add_argument("--wpm", type=int, default=25)
    parser.add_argument("--message", default=DEFAULT_MESSAGE)
    parser.add_argument("--repeat", type=int, default=1,
                        help="For multiple pages use --minutes 2 --repeat 8 --message 'REMOTE MORSE TEST'")
    args = parser.parse_args()
    if not 1 / 60 <= args.minutes <= 5 or not 1 <= args.wpm <= 255 or not 1 <= args.repeat <= 10:
        parser.error("Listen 1 second-5 minutes, WPM 1-255, repeats 1-10 only")
    if not 1 <= len(args.message) <= 80 or not args.message.isascii() or args.message != args.message.upper():
        parser.error("Use 1-80 uppercase ASCII Morse characters")
    try:
        duration = nominal_seconds(args.message, args.wpm)
    except (ValueError, KeyError):
        parser.error("Use supported Morse letters/digits/punctuation and single spaces")
    if duration > 180 or args.repeat * duration + (args.repeat - 1) * .5 + 3 > args.minutes * 60:
        parser.error("Message/repeats do not fit the requested listening window; shorten text or extend --minutes")
    results = {"source": args.source, "packet_radio": PACKET_RADIO,
               "cw_frequency_mhz": args.cw_frequency,
               "source_packet_radio_during_cw": PACKET_RADIO,
               "requested_chip_power_dbm": -9, "minutes": args.minutes,
               "wpm": args.wpm, "message": args.message, "repeat": args.repeat,
               "passed": False, "finished": False, "events": []}
    try:
        output = args.output.open("x", encoding="utf-8")
    except FileExistsError:
        parser.error("Refusing to overwrite an existing result")
    with output:
        def save():
            output.seek(0)
            json.dump(results, output, indent=2)
            output.write("\n")
            output.truncate()
            output.flush()

        def record(kind, **fields):
            item = {"kind": kind, "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), **fields}
            results["events"].append(item)
            save()
            print(json.dumps(item), flush=True)

        save()
        try:
            asyncio.run(run(args, results, record))
            results["finished"] = True
        except BaseException as error:
            results["error"] = str(error)
            raise
        finally:
            save()


if __name__ == "__main__":
    main()
