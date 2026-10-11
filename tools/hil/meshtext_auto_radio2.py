#!/usr/bin/env python3
"""Meshtext Companion / stock-peer automatic-radio2 hardware sweep.

CHANGES BOTH RADIOS' SETTINGS AND TRANSMITS LoRa. The operator must back up
and restore both radios separately. No firmware flashing or PlatformIO is used.
One private random AES-128/256 key is held in memory, never included in the report.
The US stock hash frequencies are intentional, not the 909.5-MHz lab baseline.
The Companion primary modem is not changed. Other channel slots are not erased.

Dependencies: pyserial, stock peer SDK, pypubsub. Run --plan without opening ports.
The installed stable stock schema has nine matching preset enums; the
MediumTurbo tuple is tested as an explicitly reported custom stock-radio mode.
Use distinct USB ports, no other attached clients, and conservative TX power.
"""

from __future__ import annotations

import argparse
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import random
import re
import secrets
import struct
import threading
import time

from esp32_companion_serial_stress import (
    DeviceFrameReader, FrameTimeout, TransportCounters, encode_host_frame,
    make_app_start_spec, validate_app_start_response,
)


class TestFailure(RuntimeError):
    pass


def require(condition, message):
    if not condition:
        raise TestFailure(message)


@dataclass(frozen=True)
class Preset:
    name: str
    bandwidth: int
    sf: int
    cr: int
    stock_enum: str | None

    @property
    def alias(self):
        return "mt-" + self.name.lower()

    @property
    def frequency_slot(self):
        value = 5381
        for byte in self.name.encode("ascii"):
            value = (value * 33 + byte) & 0xffffffff
        return value % (26000 // self.bandwidth) + 1

    @property
    def frequency(self):
        return 902 + self.bandwidth / 2000 + (self.frequency_slot - 1) * self.bandwidth / 1000

    def describe(self):
        return {"name": self.name, "alias": self.alias, "frequency_mhz": self.frequency,
                "frequency_slot": self.frequency_slot, "bandwidth_khz": self.bandwidth,
                "sf": self.sf, "cr": self.cr, "preamble": 16,
                "stock_mode": self.stock_enum or "CUSTOM (MediumTurbo tuple; no stable enum)"}


PRESETS = (
    Preset("LongFast", 250, 11, 5, "LONG_FAST"),
    Preset("ShortTurbo", 500, 7, 5, "SHORT_TURBO"),
    Preset("ShortFast", 250, 7, 5, "SHORT_FAST"),
    Preset("ShortSlow", 250, 8, 5, "SHORT_SLOW"),
    Preset("MediumFast", 250, 9, 5, "MEDIUM_FAST"),
    Preset("MediumSlow", 250, 10, 5, "MEDIUM_SLOW"),
    Preset("LongTurbo", 500, 11, 8, "LONG_TURBO"),
    Preset("LongMod", 125, 11, 8, "LONG_MODERATE"),
    Preset("LongSlow", 125, 12, 8, "LONG_SLOW"),
    Preset("MediumTurbo", 500, 9, 5, None),
)


def choose_presets(names):
    selected = []
    for name in names.split(","):
        normalized = name.strip().lower().replace("_", "")
        if normalized in ("longmoderate", "longmod"):
            normalized = "longmod"
        found = next((p for p in PRESETS if p.name.lower() == normalized), None)
        require(found is not None, "unknown preset: " + name)
        require(found not in selected, "duplicate preset: " + name)
        selected.append(found)
    require(selected, "at least one preset is required")
    return selected


def parse_profile(reply):
    match = re.search(r"(?:^|>\s*)([0-9.]+),([0-9.]+),(\d+),(\d+),(rx|rxtx),(\d+)", reply)
    require(match, "radio2 did not report a modem tuple")
    return (float(match[1]), float(match[2]), int(match[3]), int(match[4]), match[5], int(match[6]))


def temporary_off(reply):
    return reply in ("> off", "off", "TempRadio inactive")


def decode_channel_frame(frame):
    if not frame or frame[0] not in (8, 17):
        return None
    offset = 4 if frame[0] == 17 else 1
    require(len(frame) >= offset + 7, "truncated Companion channel frame")
    return {"channel": frame[offset], "path": frame[offset + 1], "type": frame[offset + 2],
            "timestamp": struct.unpack_from("<I", frame, offset + 3)[0],
            "text": frame[offset + 7:]}


class Companion:
    def __init__(self, port):
        import serial
        self.port = serial.Serial(port=None, baudrate=115200, timeout=0.1,
                                  write_timeout=2, exclusive=True)
        self.port.port, self.port.dtr, self.port.rts = port, True, False
        self.port.open()
        self.reader = DeviceFrameReader(TransportCounters())
        self.max_channels = 0

    def close(self):
        self.port.close()

    def request(self, payload, expected, timeout=5):
        encoded = encode_host_frame(payload)
        require(self.port.write(encoded) == len(encoded), "incomplete Companion write")
        self.port.flush()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                frame = self.reader.read_frame(self.port, min(0.5, deadline - time.monotonic()))
            except FrameTimeout:
                continue
            if frame[0] >= 0x80:
                continue
            if frame[0] == 1:
                raise TestFailure("Companion command rejected, error " + str(frame[1:2].hex()))
            require(frame[0] in expected, "unexpected Companion response " + str(frame[0]))
            return frame
        raise TestFailure("Companion response timeout for command " + str(payload[0]))

    def start(self):
        info = self.request(bytes((22, 14)), (13,))
        require(len(info) >= 80, "truncated Companion device info")
        self.max_channels = info[3]
        frame = self.request(make_app_start_spec("Meshtext-Auto-HIL").payload, (5,))
        return {"protocol": info[1], "max_channels": self.max_channels,
                "model": info[20:60].split(b"\0")[0].decode("utf-8", "replace"),
                "firmware": info[60:80].split(b"\0")[0].decode("utf-8", "replace"),
                "primary": validate_app_start_response(frame)}

    def cli(self, command):
        frame = self.request(b"\x42" + command.encode("utf-8"), (0x1d,))
        text = frame[1:].decode("utf-8", "strict").strip()
        require(not re.match(r"(?:Error|ERR|Err)\b", text), "Companion CLI rejected " + command.split()[0])
        return text

    def channel_name(self, slot):
        frame = self.request(bytes((31, slot)), (18,))
        require(len(frame) >= 50, "truncated channel info")
        return frame[2:34].split(b"\0")[0].decode("utf-8", "strict")

    def mt_node(self):
        match = re.search(r"!([0-9a-fA-F]{8})", self.cli("get mt.node"))
        require(match, "missing Companion Meshtext node ID")
        return int(match[1], 16)

    def send_text(self, slot, token):
        self.request(bytes((3, 0, slot)) + struct.pack("<I", int(time.time())) + token.encode(), (0,))

    def wait_text(self, slot, from_node, token, timeout):
        expected = (f"!{from_node:08x}: " + token).encode()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            frame = self.request(b"\x0a", (7, 8, 10, 16, 17), timeout=min(5, max(0.1, deadline - time.monotonic())))
            channel = decode_channel_frame(frame)
            if channel and channel["channel"] == slot and channel["text"] == expected:
                return {"received": True, "timestamp": channel["timestamp"], "path": channel["path"]}
            time.sleep(0.1)
        return {"received": False}

    def wait_auto(self, preset, timeout=12):
        deadline = time.monotonic() + timeout
        last = ""
        while time.monotonic() < deadline:
            last = self.cli("get radio2")
            if "auto-owned" in last:
                actual = parse_profile(last)
                desired = (preset.frequency, preset.bandwidth, preset.sf, preset.cr, "rxtx", 16)
                if (abs(actual[0] - desired[0]) <= 0.001 and actual[1:] == desired[1:]):
                    status = self.cli("get mt.status")
                    require("auto radio2" in status and "; active;" in status, "Meshtext automatic profile is not active")
                    return {"radio2": last, "status": status}
            time.sleep(0.25)
        raise TestFailure("automatic radio2 did not reach expected tuple: " + last)


class StockPeer:
    def __init__(self, port):
        from pubsub import pub
        self.port, self.iface = port, None
        self.events = deque(maxlen=4096)
        self.lock = threading.Lock()
        pub.subscribe(self.on_packet, "meshtastic.receive")
        self.pub = pub
        self.connect()

    def on_packet(self, packet, interface):
        if interface is self.iface:
            with self.lock:
                self.events.append((time.monotonic(), packet))

    def connect(self):
        from meshtastic.serial_interface import SerialInterface
        self.iface = SerialInterface(devPath=self.port, timeout=20)
        require(self.iface.myInfo is not None and self.iface.localNode.localConfig is not None,
                "stock radio configuration was not loaded")

    def close(self):
        self.pub.unsubscribe(self.on_packet, "meshtastic.receive")
        if self.iface:
            self.iface.close()
            self.iface = None

    @property
    def node(self):
        return int(self.iface.myInfo.my_node_num)

    def identity(self):
        metadata = getattr(self.iface, "metadata", None)
        return {"node": f"!{self.node:08x}", "firmware": getattr(metadata, "firmware_version", "unknown")}

    def configure(self, preset, key, tx_power, hops):
        from meshtastic.protobuf import channel_pb2, config_pb2
        from meshtastic.mesh_interface import MeshInterface
        from meshtastic.util import to_node_num
        node = self.iface.localNode
        # The SDK's ensureSessionKey() only queues a request. Wait for its
        # response so each subsequent write does not enqueue another request.
        # Stock's local receive queue holds only four packets; pace writes too.
        node.ensureSessionKey()
        deadline = time.monotonic() + 10
        while not self.iface._getOrCreateByNum(to_node_num(node.nodeNum)).get("adminSessionPassKey"):
            require(time.monotonic() < deadline, "stock admin session setup timed out")
            time.sleep(0.05)
        node.beginSettingsTransaction()
        time.sleep(0.75)
        primary = node.channels[0]
        primary.role = channel_pb2.Channel.PRIMARY
        primary.settings.name, primary.settings.psk = preset.name, key
        primary.settings.uplink_enabled = primary.settings.downlink_enabled = False
        # Avoid local relaying contaminating a two-radio reception measurement.
        node.localConfig.device.role = config_pb2.Config.DeviceConfig.CLIENT_MUTE
        node.writeConfig("device")
        time.sleep(0.75)
        lora = node.localConfig.lora
        lora.region = config_pb2.Config.LoRaConfig.US
        lora.use_preset = preset.stock_enum is not None
        if preset.stock_enum:
            require(preset.stock_enum in config_pb2.Config.LoRaConfig.ModemPreset.keys(),
                    "installed stock schema lacks " + preset.stock_enum)
            lora.modem_preset = config_pb2.Config.LoRaConfig.ModemPreset.Value(preset.stock_enum)
        # Clear BW/SF overrides for native presets. Stock AdminModule clamps
        # coding_rate=0 to 5, so request the preset's CR explicitly, including 8.
        custom_tuple = (0, 0, preset.cr) if preset.stock_enum else (preset.bandwidth, preset.sf, preset.cr)
        lora.bandwidth, lora.spread_factor, lora.coding_rate = custom_tuple
        # Nine native presets independently exercise the stock name-hash default.
        # Custom MediumTurbo uses an explicit slot because stable has no enum
        # whose stock default preset behavior can be independently compared.
        requested_slot = 0 if preset.stock_enum else preset.frequency_slot
        lora.channel_num, lora.override_frequency, lora.frequency_offset = requested_slot, 0, 0
        lora.hop_limit, lora.tx_power, lora.tx_enabled = hops, tx_power, True
        lora.config_ok_to_mqtt, lora.ignore_mqtt = False, True
        node.writeConfig("lora")
        time.sleep(0.75)
        node.writeChannel(0)
        time.sleep(0.75)
        node.commitSettingsTransaction()
        time.sleep(2)
        self.iface.close()
        self.iface = None
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            try:
                self.connect()
                node = self.iface.localNode
                observed, primary = node.localConfig.lora, node.channels[0]
                # Stable firmware bootstraps effective BW/SF into these fields
                # even in preset mode. The write clears overrides; normalized
                # readback may contain zero or the preset's effective value.
                observed_tuple = (observed.bandwidth, observed.spread_factor, observed.coding_rate)
                tuple_matches = (all(value in (0, effective) for value, effective in zip(
                    observed_tuple[:2], (preset.bandwidth, preset.sf)))
                    and observed.coding_rate == preset.cr if preset.stock_enum
                    else observed_tuple == custom_tuple)
                good = (primary.role == channel_pb2.Channel.PRIMARY
                        and primary.settings.name == preset.name and primary.settings.psk == key
                        and not primary.settings.uplink_enabled and not primary.settings.downlink_enabled
                        and observed.region == config_pb2.Config.LoRaConfig.US
                        and observed.channel_num == requested_slot
                        and observed.override_frequency == 0 and observed.frequency_offset == 0
                        and observed.use_preset == (preset.stock_enum is not None)
                        and tuple_matches
                        and observed.tx_power == tx_power
                        and observed.tx_enabled and observed.hop_limit == hops
                        and not observed.config_ok_to_mqtt and observed.ignore_mqtt
                        and node.localConfig.device.role == config_pb2.Config.DeviceConfig.CLIENT_MUTE)
                if preset.stock_enum:
                    good = good and observed.modem_preset == config_pb2.Config.LoRaConfig.ModemPreset.Value(preset.stock_enum)
                if good:
                    return {**self.identity(), "readback": {
                        "use_preset": observed.use_preset, "modem_preset": observed.modem_preset,
                        "channel_num": observed.channel_num, "bandwidth": observed.bandwidth,
                        "spread_factor": observed.spread_factor, "coding_rate": observed.coding_rate,
                        "tx_power": observed.tx_power, "hop_limit": observed.hop_limit}}
                self.iface.close()
                self.iface = None
            except (OSError, TimeoutError, MeshInterface.MeshInterfaceError):
                if self.iface:
                    self.iface.close()
                    self.iface = None
            time.sleep(1)
        raise TestFailure("stock configuration readback did not match requested private US preset")

    def packets_since(self, timestamp, sender):
        with self.lock:
            return [p for when, p in self.events if when >= timestamp and p.get("from") == sender]

    def wait_packet(self, sender, predicate, since, timeout):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for packet in self.packets_since(since, sender):
                if predicate(packet):
                    return packet
            time.sleep(0.05)
        return None

    def send_text(self, token, hops):
        return self.iface.sendText(token, destinationId="^all", wantAck=False,
                                   wantResponse=False, channelIndex=0, hopLimit=hops)


def text_payload(packet):
    return packet.get("decoded", {}).get("payload")


def print_packet_progress(label, direction, packets, total):
    # Only receipt metadata is logged; payload tokens and keys stay out of stdout.
    latest = packets[-1]
    outcome = "received" if latest["received"] else "timeout"
    elapsed = (f" in {latest['elapsed_seconds']:.3f}s"
               if "elapsed_seconds" in latest else "")
    received = sum(packet["received"] for packet in packets)
    print(f"  {label} {direction}: packet {len(packets)}/{total} {outcome}{elapsed}; "
          f"received {received}/{len(packets)}", flush=True)


def assess_traffic(case, minimum_received):
    counts = {direction: {"received": sum(packet["received"] for packet in case[direction]),
                          "attempted": len(case[direction])}
              for direction in ("v4_to_v3", "v3_to_v4")}
    failures = [{"direction": direction, **count, "required": minimum_received}
                for direction, count in counts.items() if count["received"] < minimum_received]
    case["traffic_counts"], case["traffic_failure"] = counts, failures
    return failures


def pause_after_packet(packet, gap_seconds, jitter_seconds, rng):
    gap = gap_seconds if jitter_seconds == 0 else rng.uniform(gap_seconds, gap_seconds + jitter_seconds)
    packet["gap_after_seconds"] = gap
    time.sleep(gap)


def write_report(path, data):
    # A report must never overwrite an earlier test; the key is not in data.
    with path.open("x", encoding="utf-8") as stream:
        json.dump(data, stream, indent=2)
        stream.write("\n")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def run(args, presets):
    key = secrets.token_bytes(args.key_bits // 8)
    run_id = secrets.token_hex(4)
    gap_seed = int(run_id, 16)
    gap_rng = random.Random(gap_seed)
    report = {"schema": 1, "started_utc": datetime.now(timezone.utc).isoformat(),
              "result": "FAIL", "run_id": run_id, "region": "US", "companion_region_setting": args.region,
              "tx_power_dbm": args.tx_power, "hops": args.hops,
              "key_bits": args.key_bits, "key_fingerprint": hashlib.sha256(key).hexdigest()[:16],
              "minimum_received_per_direction": args.minimum_received,
              "continue_on_loss": args.continue_on_loss, "gap_seconds": args.gap_seconds,
              "gap_jitter_seconds": args.gap_jitter_seconds, "gap_jitter_seed": gap_seed,
              "auto_clear_requested": args.auto_clear,
              "settings_restored": False, "restore_owner": "operator",
              "packages": {n: importlib.metadata.version(n) for n in ("pyserial", "meshtastic", "pypubsub")},
              "cases": []}
    companion = stock = None
    try:
        if args.gap_jitter_seconds:
            print(f"Gap jitter seed={gap_seed}; packet gaps {args.gap_seconds:g}.."
                  f"{args.gap_seconds + args.gap_jitter_seconds:g}s", flush=True)
        companion = Companion(args.companion_port)
        report["companion"] = companion.start()
        require(args.channel_slot < companion.max_channels, "Companion channel slot out of range")
        for slot in range(companion.max_channels):
            if slot == args.channel_slot:
                continue
            name = companion.channel_name(slot).lstrip("#")
            require(not name.startswith(("mt-", "r2-")),
                    "another Meshtext/radio2 slot conflicts with the sweep; operator must back up and resolve it first")
        require(temporary_off(companion.cli("get tempradio")), "temporary primary profile is active")
        require(temporary_off(companion.cli("get tempradio2")), "temporary radio2 profile is active")
        report["primary_before"] = companion.cli("get radio")
        for command in (f"set mt.region {args.region}", "set mt.slot 0", f"set mt.hops {args.hops}",
                        f"set tx {args.tx_power}", "set radio2.cross off", "set radio2 auto"):
            companion.cli(command)
        time.sleep(2.2)
        mt_node = companion.mt_node()
        report["companion"]["mt_node"] = f"!{mt_node:08x}"
        stock = StockPeer(args.stock_port)
        require(stock.node != mt_node, "stock and Companion Meshtext sender IDs collide")
        for preset in presets:
            case = {**preset.describe(), "result": "FAIL", "v4_to_v3": [], "v3_to_v4": []}
            report["cases"].append(case)
            print(f"Testing {preset.name}: {preset.frequency:.4f} MHz / {preset.bandwidth} / SF{preset.sf} / CR{preset.cr}", flush=True)
            case["stock"] = stock.configure(preset, key, args.tx_power, args.hops)
            observed = case["stock"]["readback"]
            print(f"  Stock readback verified: {'preset' if observed['use_preset'] else 'custom'}, "
                  f"slot={observed['channel_num']}, BW={observed['bandwidth']}, "
                  f"SF={observed['spread_factor']}, CR={observed['coding_rate']}, "
                  f"TX={observed['tx_power']} dBm, hops={observed['hop_limit']}", flush=True)
            companion.cli(f"set mt.channel {args.channel_slot} {preset.alias} {key.hex()}")
            case["automatic"] = companion.wait_auto(preset)
            require(companion.cli("get radio") == report["primary_before"], "primary RF settings changed")
            since = time.monotonic()
            before = companion.cli("get mt.status")
            time.sleep(args.quiet_seconds)
            after = companion.cli("get mt.status")
            before_tx, after_tx = re.search(r"\bTX=(\d+)", before), re.search(r"\bTX=(\d+)", after)
            require(before_tx and after_tx and before_tx[1] == after_tx[1], "unsolicited Companion Meshtext TX during quiet window")
            require(not stock.packets_since(since, mt_node), "unsolicited Companion Meshtext packet observed")
            case["quiet_seconds"] = args.quiet_seconds
            for sequence in range(args.messages_per_direction):
                token = f"Meshtext-HIL {run_id} {preset.name} V4-V3 {sequence}"
                started = time.monotonic()
                companion.send_text(args.channel_slot, token)
                packet = stock.wait_packet(mt_node, lambda p: text_payload(p) == token.encode(), started, args.timeout)
                case["v4_to_v3"].append({"token": token, "received": packet is not None,
                    "elapsed_seconds": round(time.monotonic() - started, 3),
                    "packet_id": packet.get("id") if packet else None})
                print_packet_progress(preset.name, "V4->V3", case["v4_to_v3"], args.messages_per_direction)
                # No automatic retransmit or ACK assumption: each token is one new send.
                pause_after_packet(case["v4_to_v3"][-1], args.gap_seconds, args.gap_jitter_seconds, gap_rng)
                token = f"Meshtext-HIL {run_id} {preset.name} V3-V4 {sequence}"
                started = time.monotonic()
                sent = stock.send_text(token, args.hops)
                received = companion.wait_text(args.channel_slot, stock.node, token, args.timeout)
                case["v3_to_v4"].append({"token": token, **received,
                    "elapsed_seconds": round(time.monotonic() - started, 3), "packet_id": sent.id})
                print_packet_progress(preset.name, "V3->V4", case["v3_to_v4"], args.messages_per_direction)
                pause_after_packet(case["v3_to_v4"][-1], args.gap_seconds, args.gap_jitter_seconds, gap_rng)
            # Capture RX/TX/failure counters even when reception misses the threshold.
            case["status_after_traffic"] = companion.cli("get mt.status")
            case["radio2_after_traffic"] = companion.cli("get radio2")
            case["radio2_status_after_traffic"] = companion.cli("get radio2.status")
            case["radio2_scan_after_traffic"] = companion.cli("get radio2.scan")
            traffic_failures = assess_traffic(case, args.minimum_received)
            if traffic_failures and not args.continue_on_loss:
                raise TestFailure(preset.name + " insufficient received messages in " + traffic_failures[0]["direction"])
            if args.nodeinfo:
                from meshtastic.protobuf import mesh_pb2
                started = time.monotonic()
                companion.cli(f"send mt.nodeinfo {args.channel_slot}")
                packet = stock.wait_packet(mt_node, lambda p: p.get("decoded", {}).get("portnum") == "NODEINFO_APP", started, args.timeout)
                require(packet is not None, "manual NodeInfo not received")
                user = mesh_pb2.User()
                user.ParseFromString(text_payload(packet))
                require(user.id == f"!{mt_node:08x}" and user.role == 1 and user.is_unmessagable
                        and 1 <= len(user.short_name.encode()) <= 4 and len(user.long_name.encode()) <= 24
                        and not user.public_key and not packet["raw"].want_ack
                        and not packet["raw"].decoded.want_response, "manual NodeInfo fields/flags invalid")
                case["nodeinfo"] = {"received": True, "id": user.id, "role": user.role,
                                    "long_name": user.long_name, "short_name": user.short_name}
            case["result"] = "FAIL" if traffic_failures else "PASS"
            print(f"{case['result']} {preset.name}: " + ", ".join(f"{d}={sum(p['received'] for p in case[d])}/{len(case[d])}" for d in ("v4_to_v3", "v3_to_v4")), flush=True)
        if args.reboot:
            # Reboot only the Companion; keep the stock observer connected.
            # The NVS settings/channel remain, but the auto-owned modem is RAM-only.
            print("Testing Companion reboot / automatic-profile reacquisition", flush=True)
            time.sleep(max(1, args.gap_seconds))
            old_identity = report["companion"]["primary"]["public_key_prefix"]
            frame = encode_host_frame(b"\x13reboot")
            require(companion.port.write(frame) == len(frame), "incomplete Companion reboot command")
            companion.port.flush()
            companion.close()
            companion = None
            time.sleep(3)
            deadline = time.monotonic() + 90
            while time.monotonic() < deadline:
                candidate = None
                try:
                    candidate = Companion(args.companion_port)
                    info = candidate.start()
                except (OSError, TestFailure):
                    if candidate:
                        candidate.close()
                    time.sleep(1)
                    continue
                companion = candidate
                require(info["primary"]["public_key_prefix"] == old_identity,
                        "Companion identity changed on reconnect; wrong device or lost persistence")
                break
            require(companion is not None, "Companion reboot reconnect timed out")
            require(companion.mt_node() == mt_node, "Meshtext sender ID changed after reboot")
            persistence = {"automatic": companion.wait_auto(presets[-1]), "result": "FAIL",
                           "v4_to_v3": [], "v3_to_v4": []}
            report["reboot_persistence"] = persistence
            for sequence in range(args.messages_per_direction):
                token = f"Meshtext-HIL {run_id} REBOOT V4-V3 {sequence}"
                started = time.monotonic()
                companion.send_text(args.channel_slot, token)
                received = stock.wait_packet(mt_node, lambda p: text_payload(p) == token.encode(), started, args.timeout) is not None
                persistence["v4_to_v3"].append({"token": token, "received": received})
                print_packet_progress("Reboot", "V4->V3", persistence["v4_to_v3"], args.messages_per_direction)
                pause_after_packet(persistence["v4_to_v3"][-1], args.gap_seconds, args.gap_jitter_seconds, gap_rng)
                token = f"Meshtext-HIL {run_id} REBOOT V3-V4 {sequence}"
                stock.send_text(token, args.hops)
                received = companion.wait_text(args.channel_slot, stock.node, token, args.timeout)
                persistence["v3_to_v4"].append({"token": token, **received})
                print_packet_progress("Reboot", "V3->V4", persistence["v3_to_v4"], args.messages_per_direction)
                pause_after_packet(persistence["v3_to_v4"][-1], args.gap_seconds, args.gap_jitter_seconds, gap_rng)
            persistence["status_after_traffic"] = companion.cli("get mt.status")
            persistence["radio2_after_traffic"] = companion.cli("get radio2")
            persistence["radio2_status_after_traffic"] = companion.cli("get radio2.status")
            persistence["radio2_scan_after_traffic"] = companion.cli("get radio2.scan")
            reboot_failures = assess_traffic(persistence, args.minimum_received)
            require(not reboot_failures, "insufficient received messages after reboot in "
                    + (reboot_failures[0]["direction"] if reboot_failures else ""))
            persistence["result"] = "PASS"
        if args.auto_clear:
            print("Testing automatic radio2 release / channel re-add", flush=True)
            cleanup = {"result": "FAIL"}
            report["auto_clear"] = cleanup

            def capture_cleanup_state(label):
                state = {}
                cleanup[label] = state
                for name, command in (("mt_status", "get mt.status"), ("radio2", "get radio2"),
                                      ("radio2_status", "get radio2.status"), ("radio2_scan", "get radio2.scan"),
                                      ("primary", "get radio")):
                    state[name] = companion.cli(command)
                require(state["primary"] == report["primary_before"], "primary RF settings changed")
                return state

            capture_cleanup_state("before")
            companion.cli(f"delete mt.channel {args.channel_slot}")
            removed = capture_cleanup_state("removed")
            require(re.fullmatch(r"(?:>\s*)?off(?:\s+\(automatic allowed\))?", removed["radio2"]),
                    "automatic radio2 did not release after the last Meshtext channel was deleted")
            require("no Meshtext channels" in removed["mt_status"], "Meshtext backend did not become inactive after channel deletion")
            companion.cli(f"set mt.channel {args.channel_slot} {presets[-1].alias} {key.hex()}")
            cleanup["automatic_readded"] = companion.wait_auto(presets[-1])
            capture_cleanup_state("readded")
            cleanup["result"] = "PASS"
            print("PASS automatic radio2 release / channel re-add", flush=True)
        report["primary_after"] = companion.cli("get radio")
        require(report["primary_after"] == report["primary_before"], "primary RF settings changed")
        failed_cases = [case["name"] for case in report["cases"] if case["result"] != "PASS"]
        require(not failed_cases, "traffic reception threshold failed for presets: " + ", ".join(failed_cases))
        report["result"] = "PASS"
    except (Exception, SystemExit, KeyboardInterrupt) as error:
        message = str(error).replace(key.hex(), "<redacted>")
        report["failure"] = {"type": type(error).__name__, "message": message[:500]}
    finally:
        report["failed_cases"] = [case["name"] for case in report["cases"] if case["result"] != "PASS"]
        for name, device in (("stock", stock), ("companion", companion)):
            if device:
                try:
                    device.close()
                except Exception as error:
                    report.setdefault("close_failures", []).append({"device": name, "type": type(error).__name__})
                    report["result"] = "FAIL"
        report["finished_utc"] = datetime.now(timezone.utc).isoformat()
        write_report(args.output, report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--companion-port")
    parser.add_argument("--stock-port")
    parser.add_argument("--channel-slot", type=int, default=1, help="Companion channel index to overwrite; backup separately")
    parser.add_argument("--key-bits", type=int, choices=(128, 256), default=128)
    parser.add_argument("--region", choices=("auto", "us"), default="auto", help="Companion inference from unambiguous US primary frequency")
    parser.add_argument("--presets", default=",".join(p.name for p in PRESETS))
    parser.add_argument("--tx-power", type=int, default=-9, help="conservative chip TX dBm, -9..-1 (stock 0 means maximum)")
    parser.add_argument("--hops", type=int, default=7, help="production default 7; use 0 for an initial-hop-only lab test")
    parser.add_argument("--messages-per-direction", type=int, default=3)
    parser.add_argument("--minimum-received", type=int, default=1, help="connectivity threshold; report all losses, use 3 for 3/3")
    parser.add_argument("--continue-on-loss", action="store_true", help="collect traffic losses across presets; failed cases still fail the run")
    parser.add_argument("--timeout", type=float, default=15)
    parser.add_argument("--gap-seconds", type=float, default=1)
    parser.add_argument("--gap-jitter-seconds", type=float, default=0, help="seeded uniform extra delay after each packet; recorded in report")
    parser.add_argument("--quiet-seconds", type=float, default=5)
    parser.add_argument("--nodeinfo", action="store_true")
    parser.add_argument("--reboot", action="store_true", help="reboot Companion at the end and verify RAM auto-profile reacquisition/chat")
    parser.add_argument("--auto-clear", action="store_true", help="delete/re-add the final Meshtext channel and verify automatic radio2 release/reacquisition")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--plan", action="store_true", help="print matrix without importing/opening serial interfaces")
    args = parser.parse_args()
    try:
        presets = choose_presets(args.presets)
        require(0 <= args.channel_slot <= 255, "channel slot must be 0..255")
        require(-9 <= args.tx_power <= -1 and 0 <= args.hops <= 7, "invalid lab TX power/hops; stock TX 0 means maximum")
        require(1 <= args.minimum_received <= args.messages_per_direction, "invalid message/reception counts")
        require(0 < args.timeout <= 60 and args.gap_seconds >= 0 and args.gap_jitter_seconds >= 0
                and args.quiet_seconds > 0, "invalid timing")
        if args.plan:
            print(json.dumps([p.describe() for p in presets], indent=2))
            return 0
        require(args.companion_port and args.stock_port and args.output, "ports and --output are required")
        require(args.companion_port != args.stock_port, "ports must be distinct")
        require(not args.output.exists() and args.output.parent.is_dir(), "choose a fresh report in an existing directory")
        report = run(args, presets)
        print(json.dumps({"result": report["result"], "output": str(args.output),
                          "failure": report.get("failure"), "restore_required": True}, indent=2))
        return 0 if report["result"] == "PASS" else 1
    except TestFailure as error:
        parser.error(str(error))


if __name__ == "__main__":
    raise SystemExit(main())
