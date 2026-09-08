#!/usr/bin/env python3
"""Qualify a 350-contact Full Companion's path and shared-secret caches.

Requires pyserial and exclusive access to the specified Companion data port.
--populate writes 350 deterministic contacts and changes the node's name;
use a dedicated test node. --secrets sends 23 directed LoRa CLI datagrams to
synthetic peers to exercise eviction. Without either flag, only local reads
are performed. --reboot restarts the node after validation.

Run again without --populate after reboot to check persistence. The generation
must match the previous population. Results are newline-delimited JSON.
"""

import argparse
import hashlib
import json
import re
import struct
import time

import serial

from esp32_companion_serial_stress import (
    DeviceFrameReader,
    TransportCounters,
    encode_host_frame,
    validate_core_stats_response,
)


def report(event, **values):
    print(json.dumps(dict(event=event, **values)), flush=True)


def secret_counters(reply):
    return {
        key: int(value)
        for key, value in re.findall(
            r"(ram_hits|flash_hits|calculations|save_skips)=(\d+)", reply
        )
    }


def run(args):
    port = serial.Serial(None, 115200, timeout=0.05, write_timeout=10)
    port.dtr = False
    port.rts = False
    port.port = args.port
    port.open()
    try:
        port.dtr = True
        time.sleep(4)
        reader = DeviceFrameReader(TransportCounters())

        def send(payload):
            port.write(encode_host_frame(payload))
            port.flush()

        def request(payload, expected, timeout=12):
            send(payload)
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                value = reader.read_frame(port, deadline - time.monotonic())
                if value[0] == expected:
                    return value
                if value[0] == 1:
                    raise RuntimeError(f"Command {payload[0]} failed: {value.hex()}")
            raise TimeoutError(f"Command {payload[0]}")

        def cli(command):
            reply = request(b"\x42" + command.encode("ascii"), 29)[1:].decode("ascii")
            report("cli", command=command, reply=reply)
            return reply

        def fixture(index):
            key = hashlib.sha256(f"contact-cache-hil-{index}".encode()).digest()
            route = bytes(
                (index * 19 + j + (index >> 8) + args.generation * 37) % 256
                for j in range(64)
            )
            name = f"Cache test {index:03d}".encode("ascii").ljust(32, b"\0")
            return key, route, name

        version = request(b"\x16\x0e", 13)
        report("device", board=version[20:60].split(b"\0")[0].decode("ascii"),
               contacts=version[2] * 2, channels=version[3])
        assert version[2] * 2 == 350 and version[3] == 40
        request(b"\x01" + b"\0" * 7 + b"Contact Cache HIL", 5)
        policy = cli("get contact.cache")
        assert "paths=16 secrets=16" in policy
        assert ("miss=calculate" if args.expect_calculate else "miss=flash") in policy
        cli("memory")  # Some nRF52 builds do not implement this diagnostic.

        if args.populate:
            request(b"\x08" + args.name.encode("ascii"), 0)
            for index in range(350):
                key, route, name = fixture(index)
                data = (b"\x09" + key + b"\x01\x00\x3f" + route + name
                        + b"\0" * 12 + b"\x01\0\0\0")
                try:
                    request(data, 0, timeout=60)
                except Exception:
                    report("insert_failed", index=index)
                    raise
                if index % 25 == 24:
                    stats = validate_core_stats_response(request(b"\x38\x00", 24))
                    report("inserted", count=index + 1, **stats)
            time.sleep(6)

        start = request(b"\x04", 2, timeout=30)
        assert int.from_bytes(start[1:5], "little") == 350
        expected = {fixture(i)[0]: fixture(i) for i in range(350)}
        seen = set()
        while True:
            value = reader.read_frame(port, 30)
            if value[0] == 4:
                break
            if value[0] != 3:
                continue
            key = value[1:33]
            assert len(value) == 148 and key in expected and key not in seen
            assert value[35] == 63 and value[36:100] == expected[key][1]
            assert value[100:132] == expected[key][2]
            seen.add(key)
        assert seen == expected.keys()
        report("sync", contacts=len(seen), verified_path_bytes=64)
        for index in range(350):
            key, route, _ = fixture(index)
            value = request(b"\x1e" + key, 3)
            assert value[36:100] == route
        report("individual_reads", contacts=350)

        if args.secrets:
            before = secret_counters(cli("get contact.cache"))
            peers = list(range(args.secret_start, args.secret_start + 21))
            for index in peers + [args.secret_start, args.secret_start]:
                key, _, _ = fixture(index)
                # CLI datagrams do not occupy an ACK/correlation slot.
                message = (b"\x02\x01\x00" + struct.pack("<I", int(time.time()))
                           + key[:6] + b"get name")
                request(message, 6)
                time.sleep(2)
            after = secret_counters(cli("get contact.cache"))
            delta = {key: value - before[key] for key, value in after.items()}
            assert delta["ram_hits"] >= 1 and delta["save_skips"] == 0
            if args.expect_calculate:
                assert delta["flash_hits"] == 0 and delta["calculations"] >= 22
            else:
                assert delta["flash_hits"] >= 1
            report("secret_eviction", **delta)
            cli("get contact.cache.timing")

        cli("memory")
        report("stats", **validate_core_stats_response(request(b"\x38\x00", 24)))
        if args.reboot:
            send(b"\x13reboot")
            report("reboot_requested")
        report("passed")
    finally:
        port.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True)
    parser.add_argument("--populate", action="store_true")
    parser.add_argument("--secrets", action="store_true")
    parser.add_argument("--reboot", action="store_true")
    parser.add_argument("--generation", type=int, default=0)
    parser.add_argument("--secret-start", type=int, default=0)
    parser.add_argument("--expect-calculate", action="store_true")
    parser.add_argument("--name", default="Contact-Cache-HIL")
    args = parser.parse_args()
    if not 0 <= args.secret_start <= 329:
        parser.error("--secret-start must leave 21 peers within contacts 0..349")
    if not args.name.isascii() or len(args.name) > 31:
        parser.error("--name must contain at most 31 ASCII characters")
    run(args)


if __name__ == "__main__":
    main()
