#!/usr/bin/env python3
"""Qualified two-V4 USB host-reboot evidence; this tool NEVER reboots the host.

Run prepare after the OTA test to restore saved primary radio settings, disable
radio2/logging, enable powersaving, and reboot the two exact radios. Wait more
than three minutes before probe. After the operator reboots the Pi, probe again
to a NEW report, then compare the two probes offline.

All actions require both physical USB serials and the expected running-image
hash. Preparation sends each setting once, with a bounded acknowledgement
deadline. Only normal USB CLI commands are used; no bootloader or flash access.
Private keys are retained solely as SHA-256 digests through the OTA helper.
Final reports are owner-readable only and new paths are required.
OTA autofetch/autoinstall must already be off. Comparison assumes the Pi wall
clock remains stable across reboot; retain an independent operator timestamp
if clock synchronization or a large clock correction is suspected.
"""

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import re
import sys
import tempfile
import time

from esp32_self_serve_ota import (
    HEX16, Report, TestFailure, V4Device, normalized_serial, parse_self,
    parse_slot, require, snapshot, utc, value_reply,
)


KIND = "esp32_usb_host_warm_reboot"
CORE_KEYS = {"battery_mv", "uptime_secs", "errors", "queue_len"}
RADIO_DIAG = re.compile(
    r"state=(\d+)\((RX|IDLE|TX_WAIT|INT_READY|\?)\), recv=(\d+), sent=(\d+), "
    r"errors=(\d+), err_flags=(\d+), outbound=(yes|no), last_rx=(\d+)s ago"
)
RADIO2_OFF = re.compile(
    r"off; RX=\d+,\d+ TX=\d+,\d+ switches=\d+ errors=\d+ "
    r"max=\d+us preamble=\d+,\d+"
)
MAX_REPORT_BYTES = 4 * 1024 * 1024


class EvidenceReport(Report):
    """Reuse atomic owner-only reporting, adding no-clobber creation/sealing."""

    def __init__(self, path, args):
        self.created = False
        self.sealed = False
        super().__init__(path, args)
        self.data.update(
            evidence_kind=KIND, firmware_transport="none; USB CLI evidence only",
            host_reboot_performed_by_tool=False, minimum_board_age_seconds=args.min_age,
            uptime_tolerance_seconds=args.uptime_tolerance,
        )
        self.save()

    def save(self):
        require(not self.sealed, "A finalized evidence report cannot be modified")
        if self.created:
            return super().save()
        fd, temporary = tempfile.mkstemp(prefix=self.path.name + ".", suffix=".tmp",
                                         dir=self.path.parent)
        temporary = Path(temporary)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(self.data, stream, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            # Atomic no-clobber: a simultaneous creator must not be overwritten.
            os.link(temporary, self.path)
            self.created = True
        except FileExistsError:
            raise TestFailure("Report path already exists; select a new report") from None
        finally:
            temporary.unlink(missing_ok=True)

    def seal(self):
        self.data["finished_utc"] = utc()
        self.save()
        os.chmod(self.path, 0o400)
        self.sealed = True


def parse_core(text):
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        raise TestFailure("stats-core is not complete JSON") from None
    require(isinstance(data, dict) and set(data) == CORE_KEYS,
            "stats-core has unexpected fields")
    require(all(type(value) is int and 0 <= value <= 0xFFFFFFFF
                for value in data.values()), "stats-core has invalid integer fields")
    return data


def parse_radio_diag(text):
    match = RADIO_DIAG.fullmatch(text)
    require(match is not None, "stats-radio-diag has incomplete or unexpected fields")
    values = [int(match[index]) for index in (1, 3, 4, 5, 6, 8)]
    require(all(value <= 0xFFFFFFFF for value in values),
            "stats-radio-diag integer exceeded its bound")
    return dict(zip(("state", "recv", "sent", "errors", "err_flags", "last_rx_secs"),
                    values), state_name=match[2], outbound=match[7] == "yes")


def require_quiet(core, diag):
    require(core["queue_len"] == 0, "Radio has a nonempty outbound queue")
    require(diag["state"] == 1 and diag["state_name"] == "RX" and not diag["outbound"],
            "Radio is not in idle receive with no outbound packet")


def require_idle(device, timeout=5):
    text = value_reply(device.command("ota status", timeout=timeout))
    require(" | no download | " in text, device.name + ": OTA session is not idle")


def wait_quiet(devices, timeout=30):
    """Wait out short beacons, never wait through or mutate an active download."""
    deadline = time.monotonic() + timeout
    while True:
        samples = {}
        for device in devices:
            def query(command):
                remaining = deadline - time.monotonic()
                require(remaining > 0, "Bounded idle-receive observation timed out")
                return value_reply(device.command(command, timeout=min(5, remaining)))

            status = query("ota status")
            require(" | no download | " in status, device.name + ": OTA session is not idle")
            started = time.time()
            core = parse_core(query("stats-core"))
            finished = time.time()
            diag = parse_radio_diag(query("stats-radio-diag"))
            samples[device.name] = {
                "core": core, "radio_diag": diag,
                "observed_unix_seconds": (started + finished) / 2,
                "sample_uncertainty_seconds": (finished - started) / 2,
            }
        if all(item["core"]["queue_len"] == 0 and item["radio_diag"]["state"] == 1
               and item["radio_diag"]["state_name"] == "RX"
               and not item["radio_diag"]["outbound"] for item in samples.values()):
            return samples
        remaining = deadline - time.monotonic()
        require(remaining > 0, "Bounded idle-receive observation timed out")
        time.sleep(min(.5, remaining))


def logging_state(device):
    text = value_reply(device.command("get usb.logging"))
    if text == "Error: unknown setting: usb.logging":
        return {"available": False, "enabled": False}
    require(text in ("on", "off"), device.name + ": USB logging state is unavailable")
    return {"available": True, "enabled": text == "on"}


def manual_ota_policy(device):
    text = value_reply(device.command("ota config"))
    values = {}
    for key in ("autofetch", "autoinstall"):
        found = re.findall(r"\b" + key + r"=([a-z]+)\b", text)
        require(len(found) == 1 and found[0] == "off",
                device.name + ": automatic OTA policy must already be off")
        values[key] = found[0]
    return values


def verified_device(device, expected_hash):
    device.connect()
    info = parse_self(device.command("ota self"))
    require(info["body_hash16"] == expected_hash,
            device.name + ": running firmware does not match the expected hash")
    require(info["image_bytes"] > info["body_bytes"] > 0,
            device.name + ": running image geometry is invalid")
    slot = parse_slot(device.command("ota dev apply slot"))
    require(info["image_bytes"] <= slot["size_bytes"], "Image does not fit the inactive slot")
    return {"identity": dict(device.identity), "self": info, "inactive_slot": slot,
            "ota_policy": manual_ota_policy(device)}


def native_usb_state(device, root=Path("/")):
    endpoint = Path(device.endpoint).name
    require(re.fullmatch(r"ttyACM\d+", endpoint) is not None,
            "Qualified V4 is not a Linux native USB serial endpoint")
    tty = root / "sys/class/tty" / endpoint / "device"
    resolved = tty.resolve(strict=True)
    parents = (resolved,) + tuple(resolved.parents)
    for parent in parents:
        if not all((parent / field).is_file()
                   for field in ("idVendor", "idProduct", "serial", "speed")):
            continue
        serial = normalized_serial((parent / "serial").read_text(encoding="ascii").strip())
        require(serial == device.serial_number, "Native USB sysfs serial does not match")
        vid = (parent / "idVendor").read_text(encoding="ascii").strip().lower()
        pid = (parent / "idProduct").read_text(encoding="ascii").strip().lower()
        require(vid == "303a" and pid == "1001",
                "Qualified V4 is not the expected native USB/JTAG interface")
        speed = (parent / "speed").read_text(encoding="ascii").strip()
        require(speed in ("12", "12.0"), "Native USB link is not full-speed 12 Mbps")
        return {"usb_serial": serial, "speed_mbps": 12, "sysfs_path": str(parent),
                "vid": vid, "pid": pid}
    raise TestFailure("Native USB device attributes were not found in sysfs")


def pi_state(root=Path("/")):
    boot_id = (root / "proc/sys/kernel/random/boot_id").read_text(encoding="ascii").strip()
    require(re.fullmatch(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}",
                         boot_id) is not None, "Pi boot identity is invalid")
    uptime = float((root / "proc/uptime").read_text(encoding="ascii").split()[0])
    require(math.isfinite(uptime) and uptime >= 0, "Pi uptime is invalid")
    cmdline = (root / "proc/cmdline").read_text(encoding="ascii").strip()
    speed_tokens = [word for word in cmdline.split() if word.startswith("dwc_otg.speed=")]
    require(speed_tokens == ["dwc_otg.speed=1"], "Pi USB 1.1 host configuration is not retained")
    model = (root / "proc/device-tree/model").read_bytes().rstrip(b"\0").decode("ascii")
    require("Raspberry Pi" in model and len(model) <= 128, "Host is not a qualified Raspberry Pi")
    return {"boot_id": boot_id.lower(), "uptime_seconds": uptime, "model": model,
            "kernel": platform.release(), "dwc_otg_speed": 1,
            # Do not copy arbitrary kernel arguments (which may contain secrets).
            "cmdline_sha256": hashlib.sha256(cmdline.encode("ascii")).hexdigest()}


def capture_device(device, expected_hash, min_age):
    result = verified_device(device, expected_hash)
    require_idle(device)
    result["snapshot"] = snapshot(device)
    state = {key: value_reply(device.command("get " + key))
             for key in ("radio", "radio2", "tempradio", "tempradio2", "powersaving",
                         "radio2.status")}
    require(re.fullmatch(r"[0-9.]+,[0-9.]+,\d+,\d+", state["radio"]) is not None,
            "Saved primary radio tuple is invalid")
    require(state["radio2"] == "off" and RADIO2_OFF.fullmatch(state["radio2.status"]),
            device.name + ": radio2 is not disabled in both saved and current state")
    require(state["tempradio"] == "off" and state["tempradio2"] == "off",
            device.name + ": a temporary radio profile is still active or pending")
    require(state["powersaving"] == "on", device.name + ": powersaving is not enabled")
    state["usb.logging"] = logging_state(device)
    require(not state["usb.logging"]["enabled"], device.name + ": USB logging remains active")
    # Firmware exposes saved primary settings, not an instantaneous tuple.
    state["primary_current_inferred_from"] = "saved tuple; no temporary profile; radio2 off; RX"
    result["radio_state"] = state
    powerlog = value_reply(device.command("powerlog"))
    match = re.fullmatch(r"Last reset reason: ([ -~]{1,100})", powerlog)
    require(match is not None, "powerlog lacks a bounded reset reason")
    result["reset_reason"] = match[1]
    sample = wait_quiet([device])[device.name]
    core, diag = sample["core"], sample["radio_diag"]
    require(core["uptime_secs"] > min_age,
            device.name + ": board is still within the post-boot sleep grace period")
    require_quiet(core, diag)
    # Check OTA again after all telemetry so an intervening download fails closed.
    require_idle(device)
    require(manual_ota_policy(device) == result["ota_policy"],
            "OTA policy changed during the probe")
    result.update(sample, ota_idle=True, usb=native_usb_state(device))
    return result


def temporary_profiles(device, deadline=None):
    state = {}
    for key in ("tempradio", "tempradio2"):
        remaining = 5 if deadline is None else deadline - time.monotonic()
        require(remaining > 0, "Temporary profile restoration timed out")
        value = value_reply(device.command("get " + key, timeout=min(5, remaining)))
        # Secondary replies append timing recommendations. Retain only the
        # bounded profile fields, never arbitrary diagnostic/log tails.
        if key == "tempradio2":
            value = value.split(";", 1)[0]
        pattern = (r"[0-9.]+,[0-9.]+,\d+,\d+,\d+" if key == "tempradio"
                   else r"[0-9.]+,[0-9.]+,\d+,\d+,(?:rx|rxtx),\d+(?: \(auto\))?")
        require(value == "off" or len(value) <= 100 and re.fullmatch(pattern, value),
                "Temporary radio state has invalid profile fields")
        state[key] = value
    return state


def wait_no_temporary_profiles(devices, timeout=30):
    deadline = time.monotonic() + timeout
    while True:
        states = {}
        for device in devices:
            remaining = deadline - time.monotonic()
            require(remaining > 0, "Temporary profile restoration timed out")
            require_idle(device, timeout=min(5, remaining))
            states[device.name] = temporary_profiles(device, deadline)
        if all(all(value == "off" for value in state.values()) for state in states.values()):
            return states
        remaining = deadline - time.monotonic()
        require(remaining > 0, "Temporary profile restoration timed out")
        time.sleep(min(.5, remaining))


def normalized_snapshot_differences(raw, saved, primary_was_temporary, name):
    require(all(raw[key] == saved[key] for key in ("private_key_sha256", "public_key", "acl")),
            name + ": temporary restoration changed identity or ACL")
    old, new = raw["settings"], saved["settings"]
    require(set(old) == set(new), name + ": normalized saved-setting fields changed")
    differences = {}
    for key, value in old.items():
        if value == new[key]:
            continue
        # These getters intentionally report runtime timing overrides, not
        # persisted prefs. Restoring normal radio exposes the saved values;
        # never set an assumed advert interval to make a comparison pass.
        masks = {"advert.interval": ("60", 510), "flood.advert.interval": ("3", 255)}
        expected = masks.get(key)
        require(primary_was_temporary and expected is not None and value == expected[0],
                name + ": temporary restoration changed an unrelated saved setting")
        require(re.fullmatch(r"0|[1-9]\d*", new[key]) is not None
                and int(new[key]) <= expected[1],
                name + ": normalized advert interval is invalid")
        differences[key] = {"live_before": value, "saved_after_normalradio": new[key],
                            "reason": "documented temporary radio timing getter override"}
    return differences


def prepare_devices(devices, expected_hash, report):
    before = {}
    # Qualify BOTH radios before issuing the first write to either.
    for device in devices:
        before[device.name] = verified_device(device, expected_hash)
        require_idle(device)
        before[device.name]["usb"] = native_usb_state(device)
        before[device.name]["temporary_profiles"] = temporary_profiles(device)
        before[device.name]["snapshot"] = snapshot(device)
        before[device.name]["snapshot_interpretation"] = (
            "raw live CLI getters; advert timing may be temporarily overridden")
        before[device.name]["logging"] = logging_state(device)
    report.data["devices"] = {name: {"before_prepare": value} for name, value in before.items()}
    report.save()
    # Both devices must be quiet in one bounded observation round, after the
    # potentially long ACL snapshots and before the first mutation.
    quiet = wait_quiet(devices)
    for name, sample in quiet.items():
        report.data["devices"][name]["before_prepare"].update(sample)
    report.save()
    for device in devices:
        for peer in devices:
            require_idle(peer)  # Refuse a newly active session before this group.
            manual_ota_policy(peer)
        # Clear only runtime overlays first. Snapshot getters for advert
        # intervals otherwise report the temporary policy rather than prefs.
        for command in ("normalradio", "set tempradio2 off"):
            require(device.checked(command, timeout=30).startswith("OK"),
                    device.name + ": temporary restoration was not acknowledged")
        report.event(device.name + ": temporary restoration acknowledged once")
    restored = wait_no_temporary_profiles(devices)
    normalized = {}
    for device in devices:
        require_idle(device)
        manual_ota_policy(device)
        saved = snapshot(device)
        entry = report.data["devices"][device.name]
        entry["normalized_saved_snapshot"] = saved
        entry["temporary_profiles_after_normalization"] = restored[device.name]
        report.save()  # Preserve observed values even if invariant checks fail.
        entry["normalization_differences"] = normalized_snapshot_differences(
            before[device.name]["snapshot"], saved,
            before[device.name]["temporary_profiles"]["tempradio"] != "off", device.name)
        normalized[device.name] = saved
        report.save()
    for device in devices:
        for peer in devices:
            require_idle(peer)
            manual_ota_policy(peer)
        commands = ["set radio2 off", "set powersaving on"]
        if before[device.name]["logging"]["available"]:
            commands.append("set usb.logging off")
        for command in commands:
            require(device.checked(command, timeout=30).startswith("OK"),
                    device.name + ": preparation setting was not acknowledged")
        report.event(device.name + ": idle-test settings acknowledged once")
    time.sleep(6)  # Existing commands persist settings; allow pending/lazy commits.
    for device in devices:
        for peer in devices:
            require_idle(peer)
            manual_ota_policy(peer)
        device.reboot(expected_hash)
        after = verified_device(device, expected_hash)
        require_idle(device)
        after["snapshot"] = snapshot(device)
        old, new = normalized[device.name], after["snapshot"]
        require(all(old[key] == new[key] for key in ("private_key_sha256", "public_key", "acl")),
                device.name + ": preparation changed identity or ACL")
        require(set(old["settings"]) == set(new["settings"])
                and all(value == new["settings"].get(key)
                    for key, value in old["settings"].items() if key != "radio2"),
                device.name + ": preparation changed an unrelated saved setting")
        require(new["settings"]["radio2"] == {"mode": "off"},
                device.name + ": radio2 off was not persisted")
        require(all(value_reply(device.command("get " + key)) == expected
                    for key, expected in (("tempradio", "off"), ("tempradio2", "off"),
                                          ("powersaving", "on"))),
                device.name + ": idle-test settings did not survive reboot")
        require(not logging_state(device)["enabled"],
                device.name + ": USB logging was not disabled after reboot")
        report.data["devices"][device.name]["after_prepare"] = after
        report.save()
    report.data["board_reboots_intentionally_performed"] = True
    report.event("Both radios rebooted; wait over 180 seconds, then create a pre-host-reboot probe")


def validate_probe(data, expected_hash, serials):
    require(isinstance(data, dict) and data.get("schema") == 1
            and data.get("evidence_kind") == KIND and data.get("action") == "probe"
            and data.get("result") == "PASS", "Input is not a successful reboot probe")
    require(data.get("expected_body_hash16") == expected_hash, "Probe expected hash differs")
    require(data.get("host_reboot_performed_by_tool") is False, "Probe host action is unexpected")
    require(data["pi"]["dwc_otg_speed"] == 1, "Probe host speed differs")
    require(set(data["devices"]) == {"A", "B"}, "Probe does not contain exactly both radios")
    for name, serial in zip(("A", "B"), serials):
        item = data["devices"][name]
        ident = item["identity"]
        require(ident["usb_serial"] == serial and ident["vid"] == 0x303A
                and ident["pid"] == 0x1001 and ident["role"].lower() == "repeater"
                and re.search(r"Heltec\s+V4\b", ident["board"], re.I),
                "Probe physical identity or role differs")
        require(item["self"]["body_hash16"] == expected_hash
                and item["usb"]["usb_serial"] == serial and item["usb"]["speed_mbps"] == 12,
                "Probe image or native USB identity differs")
        require(item["ota_idle"] is True, "Probe OTA session was not idle")
        require(item["ota_policy"] == {"autofetch": "off", "autoinstall": "off"},
                "Probe automatic OTA policy was not disabled")
        core = parse_core(json.dumps(item["core"]))
        require(core["uptime_secs"] > max(180, data["minimum_board_age_seconds"]),
                "Probe was captured during the boot grace period")
        require_quiet(core, item["radio_diag"])
        state = item["radio_state"]
        require(state["radio2"] == "off" and RADIO2_OFF.fullmatch(state["radio2.status"])
                and state["tempradio"] == "off" and state["tempradio2"] == "off"
                and state["powersaving"] == "on"
                and state["usb.logging"]["enabled"] is False, "Probe sleep inhibitors are present")
        require(re.fullmatch(r"[0-9a-f]{64}", item["snapshot"]["private_key_sha256"]) is not None,
                "Probe identity digest is malformed")
        require(math.isfinite(item["observed_unix_seconds"])
                and 0 <= item["sample_uncertainty_seconds"] <= 5,
                "Probe observation timestamp is invalid")


def load_probe(path, expected_hash, serials):
    source = Path(path)
    require(source.is_file() and source.stat().st_size <= MAX_REPORT_BYTES,
            "Probe report is absent or exceeded its size bound")
    with source.open(encoding="utf-8") as stream:
        data = json.load(stream)
    validate_probe(data, expected_hash, serials)
    return data


def compare_probes(before, after, tolerance):
    require(before["pi"]["boot_id"] != after["pi"]["boot_id"],
            "Pi boot identity did not change; a host reboot was not demonstrated")
    require(before["pi"]["dwc_otg_speed"] == after["pi"]["dwc_otg_speed"] == 1
            and before["pi"]["cmdline_sha256"] == after["pi"]["cmdline_sha256"],
            "Pi USB host configuration changed")
    require(before["pi"]["model"] == after["pi"]["model"]
            and before["pi"]["kernel"] == after["pi"]["kernel"], "Pi hardware/kernel changed")
    compared = {}
    for name in ("A", "B"):
        old, new = before["devices"][name], after["devices"][name]
        require(all(old["identity"][key] == new["identity"][key]
                    for key in ("usb_serial", "vid", "pid", "board", "role")),
                name + ": physical radio identity changed")
        require(all(old[key] == new[key]
                    for key in ("self", "inactive_slot", "snapshot", "reset_reason", "ota_policy")),
                name + ": firmware, A/B slot, identity, saved settings or reset reason changed")
        require(all(old["radio_state"][key] == new["radio_state"][key]
                    for key in ("radio", "radio2", "tempradio", "tempradio2",
                                "powersaving", "usb.logging")),
                name + ": saved/current radio or logging settings changed")
        elapsed = new["observed_unix_seconds"] - old["observed_unix_seconds"]
        uptime_gain = new["core"]["uptime_secs"] - old["core"]["uptime_secs"]
        require(math.isfinite(elapsed) and elapsed > 0 and uptime_gain > 0,
                name + ": board uptime did not continue across the host reboot")
        uncertainty = old["sample_uncertainty_seconds"] + new["sample_uncertainty_seconds"]
        require(abs(uptime_gain - elapsed) <= tolerance + uncertainty,
                name + ": board uptime gain is inconsistent with the elapsed wall time")
        compared[name] = {"usb_serial": new["identity"]["usb_serial"],
                          "body_hash16": new["self"]["body_hash16"],
                          "wall_interval_seconds": elapsed, "board_uptime_gain_seconds": uptime_gain,
                          "sample_uncertainty_seconds": uncertainty,
                          "uptime_tolerance_seconds": tolerance, "board_reboot_observed": False,
                          "identity_settings_slots_unchanged": True, "native_usb_speed_mbps": 12}
    return {"pi_boot_id_before": before["pi"]["boot_id"], "pi_boot_id_after": after["pi"]["boot_id"],
            "devices": compared, "wall_clock_stability_required": True,
            "interpretation": "Exact USB CLI recovered with uptime-consistent board continuity"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "probe", "compare"))
    parser.add_argument("--serial-a", required=True)
    parser.add_argument("--serial-b", required=True)
    parser.add_argument("--expected-body-hash16", required=True)
    parser.add_argument("--report", required=True, help="new owner-only evidence report path")
    parser.add_argument("--min-age", type=int, default=180)
    parser.add_argument("--uptime-tolerance", type=float, default=10)
    parser.add_argument("--before", help="successful pre-host-reboot probe report")
    parser.add_argument("--after", help="successful post-host-reboot probe report")
    args = parser.parse_args()
    serials = tuple(normalized_serial(value) for value in (args.serial_a, args.serial_b))
    if not all(re.fullmatch(r"[0-9A-F]{12}", serial) for serial in serials) or serials[0] == serials[1]:
        parser.error("two distinct complete 12-hex physical USB serials are required")
    if not HEX16.fullmatch(args.expected_body_hash16):
        parser.error("expected image body hash must contain 16 hex digits")
    if args.min_age < 180 or not math.isfinite(args.uptime_tolerance) or not 1 <= args.uptime_tolerance <= 60:
        parser.error("minimum age must be at least 180s; uptime tolerance must be 1..60s")
    if args.action == "compare":
        if not args.before or not args.after or Path(args.before).resolve() == Path(args.after).resolve():
            parser.error("compare needs two different successful probe paths")
    elif args.before or args.after:
        parser.error("before/after paths are only valid for compare")
    args.expected_body_hash16 = args.expected_body_hash16.upper()
    args.rounds, args.timeout, args.poll_interval = 0, 30, 0
    report, devices = None, []
    try:
        report = EvidenceReport(args.report, args)
        if args.action == "compare":
            before = load_probe(args.before, args.expected_body_hash16, serials)
            after = load_probe(args.after, args.expected_body_hash16, serials)
            report.data["comparison"] = compare_probes(before, after, args.uptime_tolerance)
        else:
            report.data["pi"] = pi_state()
            devices = [V4Device(name, serial) for name, serial in zip(("A", "B"), serials)]
            if args.action == "prepare":
                prepare_devices(devices, args.expected_body_hash16, report)
            else:
                for device in devices:
                    report.data["devices"][device.name] = capture_device(
                        device, args.expected_body_hash16, args.min_age)
                    report.save()
                validate_probe(dict(report.data, result="PASS"), args.expected_body_hash16, serials)
            require(pi_state()["boot_id"] == report.data["pi"]["boot_id"],
                    "Host rebooted while a probe/preparation was being captured")
        report.data["result"] = "PREPARED" if args.action == "prepare" else "PASS"
        report.event("Reboot evidence " + report.data["result"])
        report.seal()
        return 0
    except (Exception, KeyboardInterrupt) as error:
        # Never print unexpected exception text, which may contain raw serial data.
        reason = str(error) if isinstance(error, TestFailure) else type(error).__name__
        print("Reboot evidence failed: " + reason, file=sys.stderr)
        if report is not None and not report.sealed:
            report.data.update(result="ABORTED" if isinstance(error, KeyboardInterrupt) else "FAIL",
                               failure=reason)
            report.seal()
        return 130 if isinstance(error, KeyboardInterrupt) else 1
    finally:
        for device in devices:
            try:
                device.close()
            except Exception:
                pass


if __name__ == "__main__":
    sys.exit(main())
