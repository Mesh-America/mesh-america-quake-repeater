#!/usr/bin/env python3
"""Two Heltec V4 own-flash LoRa OTA test, without a host firmware seeder.

Run on the Linux hardware gateway after flashing both identified boards with
the same lab-default repeater image. This tool never erases a device, supplies
an image over USB, or opens a host .mota file. USB carries CLI control only.

Example:
  python3 esp32_self_serve_ota.py run --prepare \
    --serial-a 441BF669CF98 --serial-b 441BF669C9C0 \
    --expected-body-hash16 0123456789ABCDEF --report /tmp/self-ota/report.json

The three default rounds cover source reads from both running A/B slots and
receiver installs in both directions. Private keys are read locally solely to
compare SHA-256 digests: raw replies and raw key bytes are never logged.
"""

import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import time

from s3_memory_soak import Device


LAB_RADIO = "909.5,500,5,5"
LAB_SECONDARY = "909.5,500,6,5,rx"
BASELINE_MODE = "normal; no temporary radio profiles"
HEX16 = re.compile(r"^[0-9A-Fa-f]{16}$")
SNAPSHOT_COMMANDS = (
    "get name", "get radio", "get radio2", "get radio2.cross",
    "get tx.reply", "get tx", "get radio.rxps.config", "get radio.rxgain",
    "get radio.fem.txgain", "get radio.fem.rxgain", "get advert.interval",
    "get flood.advert.interval", "get lat", "get lon",
)


class TestFailure(RuntimeError):
    """A bounded, non-secret failure description suitable for the report."""


def require(condition, message):
    if not condition:
        raise TestFailure(message)


def utc():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def normalized_serial(value):
    return re.sub(r"[^A-Za-z0-9]", "", str(value or "")).upper()


def command_label(command):
    # Diagnostic verbs/settings only, never arguments, keys or raw replies.
    words = command.split()
    label = words[0]
    if words[0] in ("get", "set", "ota") and len(words) > 1 \
            and re.fullmatch(r"[a-z][a-z0-9.]*", words[1]):
        label += " " + words[1]
    return label


def reply_text(raw):
    # Drop command echoes and unsolicited startup/debug output. Only the CLI
    # reply suffix is used, and callers never retain the private-key suffix.
    match = re.search(r"(?:^|\n)\s*->\s*", raw)
    require(match is not None, "CLI reply marker was not received")
    return raw[match.end():].replace("\r", "").strip()


def value_reply(raw):
    text = reply_text(raw)
    require(bool(text), "CLI reply was empty")
    first = text.splitlines()[0].strip()
    return re.sub(r"^>\s*", "", first)


def key_token(raw, digits):
    # Do not interpolate raw/text into any failure message or exception.
    text = value_reply(raw)
    require(re.fullmatch(r"[0-9A-Fa-f]{%d}" % digits, text) is not None,
            "Local identity reply has an invalid bounded key length")
    return text.upper()


def parse_self(raw):
    text = value_reply(raw)
    match = re.search(r"self body=(\d+) image=(\d+) base_hash=([0-9A-Fa-f]{16})\b", text)
    require(match is not None, "Running image lacks a valid OTA self identity")
    return {"body_bytes": int(match[1]), "image_bytes": int(match[2]),
            "body_hash16": match[3].upper()}


def parse_slot(raw):
    text = value_reply(raw)
    match = re.search(r"inactive slot addr=0x([0-9A-Fa-f]+) size=(\d+)\b", text)
    require(match is not None, "Board does not expose an inactive A/B app slot")
    return {"inactive_address": int(match[1], 16), "size_bytes": int(match[2])}


def saved_secondary(text):
    # get radio2 appends measured timing/recommended-preamble diagnostics. An
    # automatic preamble is recomputed at each boot, not a saved setting; do
    # not mistake a different self-test result for changed configuration.
    if text == "off":
        return {"mode": "off"}
    match = re.match(r"^([0-9.]+),([0-9.]+),(\d+),(\d+),(rx|rxtx),(\d+)(\s+\(auto\))?(?:;|$)", text)
    require(match is not None, "Saved radio2 reply has invalid profile fields")
    return {"frequency_mhz": float(match[1]), "bandwidth_khz": float(match[2]),
            "sf": int(match[3]), "cr": int(match[4]), "mode": match[5],
            "preamble": "auto" if match[7] else int(match[6])}


def lab_profile_matches(text, secondary=False):
    prefix = r"^909\.500,500\.000,5,5,rxtx," if secondary else r"^909\.500,500\.000,5,5,"
    return re.match(prefix, text) is not None


def require_lab_profile(text, secondary=False):
    require(lab_profile_matches(text, secondary),
            "Active temporary radio profile does not match the lab frequency/modem tuple")


def parse_progress(raw, mid):
    text = value_reply(raw)
    match = re.search(r"download:\s*(.*?)\s+(\d+)/(\d+)\s+.*?id=([0-9A-Fa-f]{8})\b", text)
    if not match:
        require("no download" not in text, "Receive session unexpectedly became idle")
        raise TestFailure("OTA status lacks complete download progress fields")
    require(match[4].upper() == mid, "Receive session selected a different manifest")
    state, done, total = match[1], int(match[2]), int(match[3])
    require(total >= 0 and 0 <= done <= total, "Invalid OTA block progress")
    require(total > 0 or state == "starting", "Non-starting download has zero blocks")
    require(not state.startswith("failed"), "Firmware reported a failed OTA download")
    return {"state": state, "done": done, "total": total, "status": text}


def find_port(serial_number):
    from serial.tools import list_ports
    matches = [p for p in list_ports.comports()
               if normalized_serial(p.serial_number) == serial_number]
    require(len(matches) == 1, "Expected exactly one matching physical USB serial")
    port = matches[0]
    require(port.vid == 0x303A, "Matched USB device does not have ESP32 VID 303A")
    return port


class V4Device(Device):
    """Reuse the soak transport, with held native-HWCDC DTR on Linux as well."""

    def __init__(self, name, serial_number):
        self.serial_number = normalized_serial(serial_number)
        require(bool(self.serial_number), "A nonempty physical USB serial is required")
        super().__init__(name, "", "Heltec V4")
        self.is_serial = True
        self.identity = None

    def connect(self):
        if self.stream:
            return
        import serial
        port = find_port(self.serial_number)
        self.endpoint = port.device
        stream = serial.Serial()
        stream.port, stream.baudrate, stream.timeout = self.endpoint, 115200, .05
        stream.write_timeout = 5
        stream.dtr, stream.rts = True, False
        stream.open()
        self.stream = stream
        self.connections += 1
        self.read(time.monotonic() + 1)
        board = value_reply(self._command("board"))
        require(re.search(r"Heltec\s+V4\b", board, re.I) is not None,
                "USB identity is not a Heltec V4")
        role = value_reply(self._command("get role"))
        require(role.lower() == "repeater", "Board firmware role is not Repeater")
        self.identity = {"usb_serial": self.serial_number, "vid": port.vid,
                         "pid": port.pid, "board": board, "role": role,
                         "endpoint": self.endpoint}

    def _command(self, command, timeout=5):
        # A fresh bounded request cannot consume a stale previous CLI reply.
        self.read(time.monotonic() + .05)
        self.write(command.encode("ascii") + b"\r")
        deadline = time.monotonic() + timeout
        result, complete = "", False
        while time.monotonic() < deadline:
            # A debug line may contain an embedded arrow; only the CLI marker
            # at line start counts. USB can split the marker and reply itself.
            result += self.read(min(deadline, time.monotonic() + .1))
            marker = re.search(r"(?:^|\n)[ \t]*->[ \t]*", result)
            if marker and re.match(r"[^\r\n]+(?:\r\n|\n|\r)", result[marker.end():]):
                complete = True
                break
        if complete:
            # ACL is a multi-line, maximum-160-byte reply. Wait for the tail,
            # not merely the marker (USB may split key bytes across packets).
            result += self.read(min(deadline, time.monotonic() + .35))
        elif re.search(r"(?:^|\n)[ \t]*->[ \t]*", result):
            raise TestFailure(self.name + ": CLI reply was incomplete for " + command_label(command))
        else:
            raise TestFailure(self.name + ": CLI reply marker was not received for "
                              + command_label(command))
        return result

    def write(self, data):
        require(self.stream.write(data) == len(data), "USB command write was incomplete")
        self.stream.flush()

    def checked(self, command, timeout=5):
        text = reply_text(self.command(command, timeout))
        require(not re.match(r"(?:ERR|Error|Err)\b", text, re.I),
                self.name + ": command rejected: " + command.split()[0])
        # Only bounded protocol rows can extend a multi-line CLI reply. Never
        # retain unrelated asynchronous logs in our JSON report.
        lines = text.splitlines()
        if command.startswith("get acl "):
            rows = [line for line in lines[1:]
                    if re.fullmatch(r"[0-9A-Fa-f]{2} [0-9A-Fa-f]{64}", line)]
            return "\n".join([lines[0]] + rows[:2])
        if command == "ota ls" or command.startswith("ota ls "):
            rows = [line for line in lines[1:]
                    if re.match(r"^\s+\d+\) [0-9A-Fa-f]{8} ", line)]
            return "\n".join([lines[0]] + rows[:2])
        return lines[0]

    def reconnect(self, expected_hash, timeout=90):
        self.close()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                self.connect()
                info = parse_self(self.command("ota self"))
                require(info["body_hash16"] == expected_hash,
                        "Running firmware hash changed after reconnect")
                return info
            except TestFailure as error:
                self.close()
                # Missing enumeration/startup responses can recover. Wrong
                # board/role/hash is a safety failure, never a retry candidate.
                if "exactly one" not in str(error) and "marker" not in str(error):
                    raise
            except (OSError, IOError):
                self.close()
            time.sleep(1)
        raise TestFailure(self.name + ": exact-serial reconnect timed out")

    def reboot(self, expected_hash):
        with self.lock:
            self.connect()
            self.write(b"reboot\r")  # This command intentionally has no reply.
        self.close()
        time.sleep(3)
        self.reconnect(expected_hash)


class Report:
    def __init__(self, path, args):
        self.path = Path(path)
        require(not self.path.exists(), "Report path already exists; select a new report")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.data = {"schema": 1, "started_utc": utc(), "result": "RUNNING",
                     "action": args.action, "lab_radio": LAB_RADIO,
                     "expected_body_hash16": args.expected_body_hash16.upper(),
                     "requested_rounds": args.rounds, "devices": {}, "rounds": [],
                     "first_source": getattr(args, "start_source", "a"),
                     "observer_timeout_seconds": args.timeout,
                     "observer_poll_interval_seconds": args.poll_interval,
                     "events": [], "firmware_transport": "LoRa, own running app flash",
                     "host_firmware_payload_supplied": False}
        self.save()

    def save(self):
        # Owner-only report and atomic replace; no secrets or raw CLI logs.
        fd, temporary = tempfile.mkstemp(prefix=self.path.name + ".", suffix=".tmp",
                                         dir=self.path.parent)
        temp = Path(temporary)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(self.data, stream, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp, self.path)
        finally:
            if temp.exists():
                temp.unlink()

    def event(self, text):
        entry = {"utc": utc(), "message": text}
        self.data["events"].append(entry)
        self.save()
        print(entry["utc"] + " " + text, flush=True)


def acl_snapshot(device):
    rows, pages = [], 1
    for page in range(1, 129):
        text = device.checked("get acl " + str(page))
        if page == 1 and text == "ACL: empty":
            return []
        match = re.match(r"ACL (\d+)/(\d+)\s*", text)
        require(match is not None and int(match[1]) == page,
                "ACL snapshot returned invalid pagination")
        pages = int(match[2])
        require(1 <= pages <= 128, "ACL snapshot page count exceeded bound")
        current = re.findall(r"(?:^|\n)([0-9A-Fa-f]{2}) ([0-9A-Fa-f]{64})(?=\n|$)", text)
        require(1 <= len(current) <= 2, "ACL page contained truncated or missing rows")
        require(page == pages or len(current) == 2, "Non-final ACL page lost a complete row")
        rows.extend({"permissions": int(perm, 16), "public_key": key.upper()}
                    for perm, key in current)
        if page == pages:
            return sorted(rows, key=lambda row: (row["public_key"], row["permissions"]))
    raise TestFailure("ACL snapshot did not finish")


def snapshot(device):
    private_hex = key_token(device.command("get prv.key"), 128)
    private_digest = hashlib.sha256(bytes.fromhex(private_hex)).hexdigest()
    del private_hex
    data = {"private_key_sha256": private_digest,
            "public_key": key_token(device.command("get public.key"), 64),
            "acl": acl_snapshot(device), "settings": {}}
    for command in SNAPSHOT_COMMANDS:
        # Unsupported FEM controls are legitimate on boards without a switch;
        # record their bounded first-line response and require it stays equal.
        text = value_reply(device.command(command))
        if command not in ("get radio.fem.txgain", "get radio.fem.rxgain"):
            require(not re.match(r"(?:ERR|Error|Err)\b", text, re.I),
                    "Required saved-setting snapshot command was rejected")
        data["settings"][command[4:]] = saved_secondary(text) if command == "get radio2" else text
    return data


def preflight(devices, expected_hash, report):
    for device in devices:
        device.connect()
        info = parse_self(device.command("ota self"))
        require(info["body_hash16"] == expected_hash,
                device.name + ": unexpected running firmware body hash")
        require(info["image_bytes"] > info["body_bytes"] > 0,
                "Running image geometry is invalid")
        slot = parse_slot(device.command("ota dev apply slot"))
        require(info["image_bytes"] <= slot["size_bytes"], "Own image will not fit the A/B slot")
        report.data["devices"][device.name] = {"identity": device.identity,
                                                   "self": info, "initial_slot": slot}
        report.save()
    require(devices[0].serial_number != devices[1].serial_number,
            "The two radios must have different physical USB serials")
    public_keys = [key_token(d.command("get public.key"), 64) for d in devices]
    require(public_keys[0] != public_keys[1], "Radios have duplicated mesh identities")
    report.event("Both exact USB identities, V4 repeater roles, and image hashes verified")
    return public_keys


def prepare(devices, public_keys, expected_hash, report):
    for index, device in enumerate(devices):
        commands = (
            "set name SelfOTA_" + device.name,
            "setperm " + public_keys[1-index] + " 1",
            "set radio " + LAB_RADIO,
            "set radio2 " + LAB_SECONDARY,
            "set radio2.cross off", "set tx.reply auto", "set tx -5",
            "ota config autofetch off", "ota config autoinstall off", "ota config hops 0",
        )
        for command in commands:
            report.event("Preparing " + device.name + ": " + command_label(command))
            # SPIFFS transactions and dual-radio timing calibration can exceed
            # the short read-only CLI deadline. Do not resend a timed-out write.
            text = device.checked(command, timeout=30)
            require(text.startswith("OK"), device.name + ": preparation was not acknowledged")
    report.event("Lab settings, distinct names, and nonempty ACLs seeded; allowing lazy writes")
    time.sleep(6)
    for device in devices:
        device.reboot(expected_hash)
    report.event("Both boards rebooted after saved-setting persistence")


def arm_lab(devices):
    for device in devices:
        # The secondary CLI accepts only rx/rxtx tuples; bare tempradio2 off
        # restores the saved SF6 profile. Overlay the exact same primary lab
        # tuple instead, leaving the saved secondary configuration untouched.
        # Use rxtx because tx.reply auto answers on the receive profile and
        # cross is deliberately off; an rx-only overlay would drop replies.
        commands = ("ota config autofetch off", "ota config autoinstall off", "ota config hops 0",
                    "set tempradio2 " + LAB_RADIO + ",rxtx,120", "tempradio " + LAB_RADIO + ",120")
        for command in commands:
            require(device.checked(command, timeout=30).startswith("OK"),
                    "Lab maintenance/policy command was not acknowledged")
    # Both commands intentionally schedule changes. Wait for published live
    # profiles, rather than treating a fixed delay as evidence of activation.
    for device in devices:
        deadline = time.monotonic() + 30
        while True:
            remaining = deadline - time.monotonic()
            require(remaining > 0, device.name + ": temporary lab profiles were not activated in time")
            primary = value_reply(device.command("get tempradio", timeout=remaining))
            remaining = deadline - time.monotonic()
            require(remaining > 0, device.name + ": temporary lab profiles were not activated in time")
            secondary = value_reply(device.command("get tempradio2", timeout=remaining))
            require(time.monotonic() < deadline,
                    device.name + ": temporary lab profiles were not activated in time")
            if lab_profile_matches(primary) and lab_profile_matches(secondary, True):
                break
            require(time.monotonic() < deadline,
                    device.name + ": temporary lab profiles were not activated in time")
            time.sleep(.5)
        config = device.checked("ota config")
        require("autofetch=off" in config and "autoinstall=off" in config and "hops=0" in config,
                "Manual-only one-hop OTA policy was not applied")


def require_normal_profiles(devices):
    for device in devices:
        require(value_reply(device.command("get tempradio")) == "off"
                and value_reply(device.command("get tempradio2")) == "off",
                device.name + ": saved-setting snapshot requires inactive temporary profiles")


def disarm_lab(devices):
    # Getters for advert intervals describe EFFECTIVE TempRadio timing, not
    # saved preferences. Take the baseline with both temporary profiles off.
    # Qualify every receiver as idle before clearing any maintenance window.
    for device in devices:
        require(" | no download | " in value_reply(device.command("ota status")),
                device.name + ": cannot disarm a live OTA download for a baseline")
    for device in devices:
        for command in ("normalradio", "set tempradio2 off"):
            require(device.checked(command, timeout=30).startswith("OK"),
                    "Normal-mode baseline command was not acknowledged")
    deadline = time.monotonic() + 30
    for device in devices:
        while True:
            remaining = deadline - time.monotonic()
            require(remaining > 0, "Temporary profiles did not stop before the baseline deadline")
            primary = value_reply(device.command("get tempradio", timeout=min(5, remaining)))
            remaining = deadline - time.monotonic()
            require(remaining > 0, "Temporary profiles did not stop before the baseline deadline")
            secondary = value_reply(device.command("get tempradio2", timeout=min(5, remaining)))
            require(time.monotonic() < deadline, "Temporary profiles did not stop before the baseline deadline")
            if primary == secondary == "off":
                break
            time.sleep(.5)


def live_snapshot_matches_saved(original, current):
    # Our fixed 120-minute window forces ONLY the local advert getter to60.
    # Do not stop a live RF transfer to read saved timing. Defer that one field
    # until the post-install normal-mode snapshot; keep every other field strict.
    if current["settings"].get("advert.interval") != "60":
        return False
    for key in original:
        if key == "settings":
            old = {k: v for k, v in original[key].items() if k != "advert.interval"}
            new = {k: v for k, v in current[key].items() if k != "advert.interval"}
            if old != new:
                return False
        elif original[key] != current.get(key):
            return False
    return set(original) == set(current)


def discover(receiver, mid, timeout=60):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        first = receiver.checked("ota ls")
        if first.startswith("No updates seen yet"):
            time.sleep(2)
            continue
        header = re.search(r"Updates 1/(\d+)\b", first)
        require(header is not None, "Receiver catalog has an invalid page header")
        pages = int(header[1])
        require(1 <= pages <= 128, "Receiver catalog exceeds page bound")
        catalog = [first]
        catalog.extend(receiver.checked("ota ls " + str(page)) for page in range(2, pages+1))
        if any(re.search(r"\b" + mid + r"\b", row, re.I) for row in catalog):
            return catalog
        time.sleep(2)
    raise TestFailure("Receiver did not discover the source's own-flash manifest over LoRa")


def run_round(number, source, receiver, devices, expected_hash, baseline, args, report,
              continuing=None):
    entry = continuing or {"round": number, "source": source.name, "receiver": receiver.name,
                           "started_utc": utc(), "result": "RUNNING", "progress": []}
    if continuing is None:
        report.data["rounds"].append(entry)
        report.save()
        arm_lab(devices)
    source_info = parse_self(source.command("ota self"))
    require(source_info["body_hash16"] == expected_hash, "Source hash is not the expected build")
    source_slot = parse_slot(source.command("ota dev apply slot"))
    receiver_slot = parse_slot(receiver.command("ota dev apply slot"))
    if continuing is not None:
        # Adopt only an already-started download. Never reissue cancel/get or
        # install based solely on a saved report; verify the live session and
        # physical devices before observing it with a larger bounded deadline.
        require(entry.get("source") == source.name and entry.get("receiver") == receiver.name,
                "Continuation device direction does not match")
        require("install_reply" not in entry and "install_requested_utc" not in entry
                and entry.get("result") == "RUNNING",
                "Continuation cannot adopt a completed or installing round")
        require(entry.get("source_slot") == source_slot and entry.get("receiver_slot_before") == receiver_slot,
                "Application slots changed before continuation")
        require(entry.get("source_self") == source_info, "Source image changed before continuation")
        mid = entry.get("manifest_id", "")
        require(re.fullmatch(r"[0-9A-F]{8}", mid) is not None, "Continuation has no valid manifest ID")
        for device in devices:
            require_lab_profile(value_reply(device.command("get tempradio")))
            require_lab_profile(value_reply(device.command("get tempradio2")), True)
        own_status = source.checked("ota serve status")
        own_stats = source.checked("ota stats")
        own_mid = re.match(r"^OTA\s*\|\s*fw\s+\S+\s+id=([0-9A-Fa-f]{8})\b", own_stats)
        require("default:on serving:on" in own_status and own_mid is not None
                and own_mid[1].upper() == mid,
                "Original own-flash manifest is no longer being served")
        progress = parse_progress(receiver.command("ota status"), mid)
        require(progress["total"] == (source_info["image_bytes"] + 2047) // 2048,
                "Continued download has unexpected block geometry")
        require(progress["done"] >= entry["progress"][-1]["done"],
                "Continued download lost recorded block progress")
        report.event("Round %d: continuing live MID %s at %u/%u blocks without restarting RF" %
                     (number, mid, progress["done"], progress["total"]))
    else:
        entry["source_slot"], entry["receiver_slot_before"] = source_slot, receiver_slot
        clear = receiver.checked("ota cancel", timeout=30)
        require("OTA receive slot confirmed clear" in clear, "Receiver persistent OTA slot was not cleared")
        require("no download" in receiver.checked("ota status"), "Receiver did not return to idle")
        own = source.checked("ota serve self", timeout=30)
        match = re.search(r"OK serving own fw mid=([0-9A-Fa-f]{8})\b", own)
        require(match is not None and "flash-backed, unsigned" in own,
                "Source did not acknowledge a flash-backed own image")
        mid = match[1].upper()
        entry["manifest_id"], entry["source_self"] = mid, source_info
        own_status = source.checked("ota serve status")
        require("default:on serving:on" in own_status, "Source own-image serving is not active")
        entry["source_serve_status"] = own_status
        entry["catalog"] = discover(receiver, mid)
        start_reply = receiver.checked("ota get " + mid + " flash")
        require("OK pulling mid=" + mid in start_reply and "-> flash" in start_reply,
                "Receiver did not start a new full OTA flash download")
        report.event("Round %d: %s own flash -> %s, MID %s" % (number, source.name, receiver.name, mid))
    started, last_progress = time.monotonic(), time.monotonic()
    prior_elapsed = entry["progress"][-1]["elapsed_seconds"] if continuing is not None else 0
    if continuing is not None:
        # RF keeps running while its observer is stopped. Include that gap in
        # pace/download duration rather than reporting an artificially fast run.
        recorded = datetime.fromisoformat(entry["progress"][-1]["utc"].replace("Z", "+00:00"))
        prior_elapsed += max(0, time.time() - recorded.timestamp())
    previous = progress["done"] if continuing is not None else -1
    observed_intermediate = any(0 < p["done"] < p["total"] for p in entry["progress"])
    ready = False
    last_log = 0.0
    while time.monotonic() - started < args.timeout:
        progress = parse_progress(receiver.command("ota status"), mid)
        done, total = progress["done"], progress["total"]
        require(total == (source_info["image_bytes"] + 2047) // 2048
                or (progress["state"] == "starting" and total == 0),
                "OTA download block geometry changed")
        if 0 < done < total:
            observed_intermediate = True
        if done > previous:
            last_progress = time.monotonic()
        require(done >= previous, "OTA completed-block count moved backwards")
        previous = done
        if not entry["progress"] or done != entry["progress"][-1]["done"]:
            entry["progress"].append({"utc": utc(), "elapsed_seconds": round(prior_elapsed+time.monotonic()-started, 2),
                                      **progress})
            report.save()
        if time.monotonic() - last_log >= 30:
            elapsed = prior_elapsed+time.monotonic()-started
            rate = done/elapsed if elapsed else 0
            report.event("Round %d: %u/%u blocks, %.2f blocks/s, %s" %
                         (number, done, total, rate, progress["state"]))
            last_log = time.monotonic()
        if progress["state"] == "ready to install":
            require(done == total, "Ready state does not include every firmware block")
            ready = True
            break
        require(time.monotonic()-last_progress < args.stall_timeout,
                "OTA download stalled beyond the configured progress timeout")
        time.sleep(args.poll_interval)
    require(ready, "OTA download exceeded its per-round timeout")
    require(observed_intermediate, "No intermediate RF block progress was observed; cannot prove transfer")
    entry["download_seconds"] = round(prior_elapsed+time.monotonic()-started, 2)
    entry["intermediate_rf_progress_observed"] = True
    entry["ready_status"] = progress["status"]
    report.save()
    # Persist intent BEFORE sending. A transport interruption after transmission
    # must not be misclassified as a safe, never-installed continuation.
    entry["install_requested_utc"] = utc()
    report.save()
    install = receiver.checked("ota install", timeout=30)
    require(install.startswith("OK"), "Verified fetched image was not accepted for install")
    entry["install_reply"] = install
    report.event("Round %d: all blocks received; guarded OTA install accepted" % number)
    receiver.close()
    time.sleep(4)
    entry["receiver_self_after"] = receiver.reconnect(expected_hash)
    after_slot = parse_slot(receiver.command("ota dev apply slot"))
    before_slot = entry["receiver_slot_before"]
    require(after_slot["inactive_address"] != before_slot["inactive_address"],
            "Receiver did not switch its running A/B application slot")
    require(after_slot["size_bytes"] == before_slot["size_bytes"], "OTA changed app partition geometry")
    entry["receiver_slot_after"] = after_slot
    require_normal_profiles([receiver])
    after = snapshot(receiver)
    changes = [key for key in baseline[receiver.name] if baseline[receiver.name][key] != after[key]]
    entry["snapshot_after"] = after
    entry["preservation"] = {"equal": not changes, "changed_fields": changes}
    report.save()
    require(not changes, "Receiver identity/ACL/saved settings changed across OTA install")
    entry["result"], entry["finished_utc"] = "PASS", utc()
    report.event("Round %d PASS: hash, A/B slot flip, key digest, ACL, and settings preserved" % number)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("action", choices=("probe", "prepare", "run"), nargs="?", default="run")
    parser.add_argument("--serial-a", required=True, help="Exact physical USB serial, not a tty path")
    parser.add_argument("--serial-b", required=True, help="Exact physical USB serial, not a tty path")
    parser.add_argument("--expected-body-hash16", required=True, help="16 hex digits from this build's EndF")
    parser.add_argument("--report", required=True, help="New JSON report path (must not already exist)")
    parser.add_argument("--prepare", action="store_true", help="Seed lab saved settings/ACLs and reboot before run")
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--start-source", choices=("a", "b"), default="a",
                        help="Which physical radio serves the first round")
    parser.add_argument("--timeout", type=float, default=5400, help="Maximum seconds per download observation")
    parser.add_argument("--continue-report", help="Adopt a live, uninstalled download from an interrupted report")
    parser.add_argument("--stall-timeout", type=float, default=120, help="Maximum seconds without block progress")
    parser.add_argument("--poll-interval", type=float, default=15)
    args = parser.parse_args(argv)
    if not HEX16.fullmatch(args.expected_body_hash16):
        parser.error("--expected-body-hash16 must contain exactly 16 hexadecimal digits")
    if args.rounds < 1 or args.timeout <= 0 or args.stall_timeout <= 0 or args.poll_interval <= 0:
        parser.error("Round count and timeout/interval values must be positive")
    if normalized_serial(args.serial_a) == normalized_serial(args.serial_b):
        parser.error("Two distinct physical USB serials are required")
    expected_hash = args.expected_body_hash16.upper()
    if args.continue_report and (args.action != "run" or args.prepare):
        parser.error("--continue-report requires run without --prepare")
    devices, report = [], None
    try:
        report = Report(args.report, args)
        devices = [V4Device("A", args.serial_a), V4Device("B", args.serial_b)]
        public_keys = preflight(devices, expected_hash, report)
        if args.action == "prepare" or (args.action == "run" and args.prepare):
            prepare(devices, public_keys, expected_hash, report)
        if not args.continue_report:
            if args.action == "run":
                disarm_lab(devices)
            else:
                require_normal_profiles(devices)
        baseline = {device.name: snapshot(device) for device in devices}
        require(baseline["A"]["private_key_sha256"] != baseline["B"]["private_key_sha256"],
                "Radios have duplicated private identities")
        continuing = None
        first_round = 1
        if args.continue_report:
            previous_report = json.loads(Path(args.continue_report).read_text(encoding="utf-8"))
            require(previous_report.get("schema") == 1 and previous_report.get("action") == "run"
                    and previous_report.get("expected_body_hash16") == expected_hash
                    and previous_report.get("lab_radio") == LAB_RADIO
                    and previous_report.get("requested_rounds") == args.rounds
                    and previous_report.get("first_source", "a") == args.start_source
                    and previous_report.get("baseline_mode") == BASELINE_MODE,
                    "Continuation report does not match this test definition")
            require(previous_report.get("result") == "ABORTED" or
                    (previous_report.get("result") == "FAIL" and previous_report.get("failure") ==
                     "OTA download exceeded its per-round timeout"),
                    "Only an interrupted or timed-out download report can be continued")
            require(all(live_snapshot_matches_saved(previous_report["baseline"][name], baseline[name])
                        for name in ("A", "B")),
                    "Identity, ACL or settings changed before continuation")
            for device in devices:
                require(previous_report["devices"][device.name]["identity"]["usb_serial"] == device.serial_number,
                        "Continuation physical USB identities do not match")
            prior_rounds = previous_report.get("rounds", [])
            require(bool(prior_rounds) and len(prior_rounds) <= args.rounds,
                    "Continuation report has no pending round")
            require(all(r.get("result") == "PASS" and r.get("round") == n
                        for n, r in enumerate(prior_rounds[:-1], 1)),
                    "Continuation has invalid completed rounds")
            continuing = prior_rounds[-1]
            require(continuing.get("result") == "RUNNING" and continuing.get("round") == len(prior_rounds)
                    and bool(continuing.get("progress")), "Continuation has no observed uninstalled RF download")
            first_round = len(prior_rounds)
            report.data["rounds"] = prior_rounds
            # Retain the original SAVED baseline, not the effective TempRadio
            # getter values just observed while the interrupted transfer runs.
            baseline = previous_report["baseline"]
            report.data["continued_from"] = str(Path(args.continue_report).resolve())
            report.event("Adopting interrupted observer report; original RF transfer remains active")
        report.data["baseline"] = baseline
        report.data["baseline_mode"] = BASELINE_MODE
        report.save()
        if args.action == "run":
            for number in range(first_round, args.rounds+1):
                ordered = devices if args.start_source == "a" else list(reversed(devices))
                source, receiver = ordered if number % 2 else list(reversed(ordered))
                run_round(number, source, receiver, devices, expected_hash, baseline, args, report,
                          continuing if number == first_round else None)
            # Never report A/B coverage from just a single successful transfer.
            sources = {entry["source_slot"]["inactive_address"] for entry in report.data["rounds"]}
            destinations = {entry["receiver_slot_before"]["inactive_address"] for entry in report.data["rounds"]}
            report.data["both_source_slots_covered"] = len(sources) == 2
            report.data["both_destination_slots_covered"] = len(destinations) == 2
            if args.rounds >= 3:
                require(len(sources) == 2 and len(destinations) == 2,
                        "Three-round run did not exercise both source and destination A/B slots")
        report.data["result"] = "PASS"
        report.data["finished_utc"] = utc()
        report.event(args.action.upper() + " PASS")
        return 0
    except KeyboardInterrupt:
        if report:
            report.data["result"], report.data["failure"] = "ABORTED", "Operator interrupted the test"
            report.data["finished_utc"] = utc()
            report.save()
        return 130
    except Exception as error:
        # Third-party serial exceptions could include a raw buffer in their
        # message. Only our explicitly non-secret failures are reportable.
        message = str(error) if isinstance(error, TestFailure) else type(error).__name__
        if report:
            report.data["result"], report.data["failure"] = "FAIL", message
            report.data["finished_utc"] = utc()
            report.event("FAIL: " + message)
        else:
            print("FAIL: " + message, file=sys.stderr)
        return 1
    finally:
        for device in devices:
            device.close()


if __name__ == "__main__":
    sys.exit(main())
