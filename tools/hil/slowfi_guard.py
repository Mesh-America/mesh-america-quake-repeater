#!/usr/bin/env python3
"""Future host recovery helper. Default is a read-only plan; not staged/live-tested."""
from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import time
import uuid

FIRST_DELAY_SECONDS = 660
RETRY_DELAY_SECONDS = 30
# The worker has32s for subprocesses; the service enforces35s including startup.
ATTEMPT_BUDGET_SECONDS = 32
CLEANUP_BUDGET_SECONDS = 75
NMCLI = "/usr/bin/nmcli"
SYSTEMCTL = "/usr/bin/systemctl"


def require(condition, code):
    if not condition:
        raise ValueError(code)


def valid_uuid(value):
    try:
        return str(uuid.UUID(value)) == value
    except (ValueError, TypeError, AttributeError):
        return False


def validate(config):
    require(config.get("schema") == 1, "schema_mismatch")
    require(valid_uuid(config.get("original_uuid")), "original_uuid_unbound")
    require(bool(re.fullmatch(r"[a-zA-Z0-9_.-]+", config.get("expected_hostname", ""))), "hostname_unbound")
    require(bool(re.fullmatch(r"[a-f0-9]{64}", config.get("expected_machine_id_sha256", ""))), "machine_id_unbound")
    require(bool(re.fullmatch(r"[a-zA-Z0-9_.-]{1,15}", config.get("interface", ""))), "interface_invalid")
    stem = config.get("unit_stem", "")
    require(bool(re.fullmatch(r"meshcore-slowfi-return-[a-z0-9-]{8,80}", stem)), "owned_unit_invalid")
    root = config.get("guard_dir", "")
    require(root == "/run/" + stem, "owned_guard_directory_invalid")
    for key, name in (("helper_path", "slowfi_guard.py"), ("config_path", "config.json")):
        require(config.get(key) == root + "/" + name, "owned_path_invalid")
    require(config.get("python_path") == "/usr/bin/python3", "python_path_invalid")
    require(type(config.get("live_execution_authorized")) is bool, "live_authorization_invalid")
    owned = config.get("owned_profiles", [])
    require(isinstance(owned, list) and len(owned) <= 4, "owned_profiles_invalid")
    seen = set()
    for item in owned:
        require(isinstance(item, dict) and set(item) == {"uuid", "id"}, "owned_profile_invalid")
        require(valid_uuid(item["uuid"]) and item["uuid"] != config["original_uuid"], "original_profile_must_not_be_owned")
        require(item["uuid"] not in seen, "duplicate_owned_profile")
        require(bool(re.fullmatch(r"meshcore-[a-z0-9-]{8,100}", item["id"])), "owned_profile_name_invalid")
        seen.add(item["uuid"])
    return config


def render_units(config):
    validate(config)
    stem = config["unit_stem"]
    timer = f"""[Unit]
Description=Return to original WiFi until connected ({stem})

[Timer]
OnActiveSec={FIRST_DELAY_SECONDS}s
OnUnitInactiveSec={RETRY_DELAY_SECONDS}s
AccuracySec=1s
RandomizedDelaySec=0
Unit={stem}.service
RemainAfterElapse=yes
"""
    service = f"""[Unit]
Description=One bounded original WiFi recovery attempt ({stem})
StartLimitIntervalSec=0

[Service]
Type=oneshot
RemainAfterExit=no
User=root
ExecStart={config['python_path']} {config['helper_path']} attempt --config {config['config_path']} --allow-live-host-recovery
TimeoutStartSec=35s
TimeoutStopSec=1s
KillMode=control-group
SendSIGKILL=yes
UMask=0077
"""
    return {stem + ".timer": timer, stem + ".service": service}


def parse_state(output):
    lines = output.strip().splitlines()
    if len(lines) != 2 or not valid_uuid(lines[0].strip()):
        return None
    match = re.fullmatch(r"(\d+)(?:\s+\([^\r\n]*\))?", lines[1].strip())
    if not match:
        return None
    return {"uuid": lines[0].strip(), "state": int(match[1])}


class LiveBackend:
    """No instantiation from plan/render/tests; commands never return raw output."""
    def __init__(self, config):
        require(config["live_execution_authorized"], "live_execution_not_authorized")
        require(os.geteuid() == 0, "live_requires_root")
        require(socket.gethostname() == config["expected_hostname"], "wrong_host")
        machine_id = Path("/etc/machine-id").read_text().strip().encode()
        require(hashlib.sha256(machine_id).hexdigest() == config["expected_machine_id_sha256"], "wrong_machine_id")
        root = Path(config["guard_dir"])
        stat = root.stat()
        require(root.is_dir() and not root.is_symlink() and stat.st_uid == 0 and not stat.st_mode & 0o022, "guard_directory_not_owned")
        for key in ("config_path", "helper_path"):
            item = Path(config[key])
            stat = item.stat()
            require(item.is_file() and not item.is_symlink() and stat.st_uid == 0 and not stat.st_mode & 0o022, "live_file_not_owned")
        self.interface = config["interface"]

    @staticmethod
    def call(argv, timeout):
        try:
            value = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=False, stdin=subprocess.DEVNULL)
            return value.returncode, value.stdout
        except subprocess.TimeoutExpired:
            return None, ""

    def state(self, interface, timeout):
        rc, output = self.call([NMCLI, "--terse", "--escape", "no", "--get-values", "GENERAL.CON-UUID,GENERAL.STATE", "device", "show", interface], timeout)
        return parse_state(output) if rc == 0 else None

    def activate(self, original_uuid, timeout):
        rc, _ = self.call([NMCLI, "--wait", "25", "connection", "up", "uuid", original_uuid, "ifname", self.interface], timeout)
        return rc == 0

    def stop_timer(self, unit, timeout):
        rc, _ = self.call([SYSTEMCTL, "stop", unit], timeout)
        return rc == 0

    def timer_state(self, unit, timeout):
        rc, output = self.call([SYSTEMCTL, "show", "--property=ActiveState", "--value", unit], timeout)
        state = output.strip()
        return state if rc == 0 and state in {"active", "inactive", "failed", "activating", "deactivating"} else None

    def profile_name(self, profile_uuid, timeout):
        rc, output = self.call([NMCLI, "--get-values", "connection.id", "connection", "show", "uuid", profile_uuid], timeout)
        return output.strip() if rc == 0 else None

    def delete_profile(self, profile_uuid, timeout):
        rc, _ = self.call([NMCLI, "--wait", "5", "connection", "delete", "uuid", profile_uuid], timeout)
        return rc == 0

    def stop_owned_units(self, timer, service, timeout):
        rc, _ = self.call([SYSTEMCTL, "stop", timer, service], timeout)
        return rc == 0


@contextlib.contextmanager
def owned_lock(path, expected_uid=None):
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        stat = os.fstat(fd)
        require(stat.st_nlink == 1 and (expected_uid is None or stat.st_uid == expected_uid), "lock_not_owned")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def attempt(config, backend, *, clock=time.monotonic):
    """Single bounded invocation; no sleep, global retry cap, or profile edit."""
    validate(config)
    begun = clock()
    deadline = begun + ATTEMPT_BUDGET_SECONDS
    report = {"schema": 1, "original_uuid_connected": False, "activation_attempted": False,
              "timer_stopped": False, "recurring_retry_retained": True,
              "attempt_budget_seconds": ATTEMPT_BUDGET_SECONDS, "errors": []}

    def bounded(limit):
        left = deadline - clock()
        if left <= 0:
            raise TimeoutError("attempt_deadline")
        return min(limit, left)

    def connected(state):
        return bool(state and state["uuid"] == config["original_uuid"] and state["state"] == 100)

    try:
        state = backend.state(config["interface"], bounded(3))
        if not connected(state):
            report["activation_attempted"] = True
            # Reserve3s for association and1s each for stop and state proof.
            allowance = min(24, deadline - clock() - 5)
            if allowance <= 0:
                raise TimeoutError("no_activation_budget")
            report["nmcli_activation_returned_success"] = backend.activate(config["original_uuid"], allowance)
            state = backend.state(config["interface"], bounded(3))
        report["original_uuid_connected"] = connected(state)
        if report["original_uuid_connected"]:
            timer = config["unit_stem"] + ".timer"
            report["recurring_retry_retained"] = None
            report["timer_state_after_stop"] = None
            report["timer_stop_returned_success"] = backend.stop_timer(timer, bounded(1))
            # Stop failure/timeout can occur after the side effect. Read the
            # exact unit rather than infer timer activity from the return code.
            report["timer_state_after_stop"] = backend.timer_state(timer, bounded(1))
            report["timer_stopped"] = report["timer_state_after_stop"] == "inactive"
            report["recurring_retry_retained"] = (
                True if report["timer_state_after_stop"] == "active" else
                False if report["timer_state_after_stop"] in {"inactive", "failed"} else None)
    except Exception as error:
        # Never store command output, SSIDs, credentials, or exception messages.
        report["errors"].append(type(error).__name__)
    report["elapsed_seconds"] = round(clock() - begun, 6)
    return report


def explicit_owned_cleanup(config, backend, *, clock=time.monotonic, lock_context=None):
    """Refuse cleanup while original WiFi is unproven; one bounded lock owner."""
    validate(config)
    deadline = clock() + CLEANUP_BUDGET_SECONDS
    stem = config["unit_stem"]
    report = {"ok": False, "cleanup_refused": False, "no_mutation": True,
              "original_profile_untouched": True, "owned_profiles": [],
              "cleanup_budget_seconds": CLEANUP_BUDGET_SECONDS}

    def bounded(limit):
        left = deadline - clock()
        if left <= 0:
            raise TimeoutError("cleanup_deadline")
        return min(left, limit)

    def original_connected():
        state = backend.state(config["interface"], bounded(3))
        return bool(state and state["uuid"] == config["original_uuid"] and state["state"] == 100)

    def refuse(code):
        report.update({"cleanup_refused": True, "reason": code})
        return report

    try:
        if not original_connected():
            return refuse("original_wifi_not_connected_before_lock")
        context = lock_context or (lambda path: owned_lock(path, expected_uid=0))
        with context(config["guard_dir"] + "/attempt.lock") as acquired:
            if not acquired:
                return refuse("cleanup_attempt_lock_busy")
            if not original_connected():
                return refuse("original_wifi_not_connected_under_lock")
            # Check all ownership before any mutation, avoiding partial cleanup
            # for a known collision in a later owned-profile entry.
            for item in config["owned_profiles"]:
                if backend.profile_name(item["uuid"], bounded(3)) != item["id"]:
                    return refuse("owned_profile_identity_changed")
            if not original_connected():
                return refuse("original_wifi_not_connected_before_unit_stop")
            report["no_mutation"] = False
            require(backend.stop_owned_units(stem + ".timer", stem + ".service", bounded(5)), "owned_units_stop_failed")
            report["owned_units_stopped"] = True
            for item in config["owned_profiles"]:
                # Recheck capturedUUID/name immediately before deletion too.
                require(backend.profile_name(item["uuid"], bounded(3)) == item["id"], "owned_profile_identity_changed")
                require(backend.delete_profile(item["uuid"], bounded(7)), "owned_profile_delete_failed")
                report["owned_profiles"].append({"owned_profile_deleted": True})
            report["ok"] = True
    except Exception as error:
        report["error_type"] = type(error).__name__
        if report["no_mutation"]:
            report["cleanup_refused"] = True
    return report


def plan(config):
    validate(config)
    return {"prepared_only": True, "not_staged_or_executed": True,
            "first_delay_seconds": FIRST_DELAY_SECONDS, "retry_delay_seconds": RETRY_DELAY_SECONDS,
            "accuracy_seconds": 1, "per_attempt_budget_seconds": ATTEMPT_BUDGET_SECONDS,
            "persistent_failure_retains_recurring_timer": True, "requires_fresh_owned_unit_stem": True,
            "stop_requires_original_uuid_and_connected_state": True,
            "original_profile_settings_are_never_modified": True,
            "cannot_retroactively_repair_offline_host": True, "unit_files": render_units(config)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("plan", "attempt", "cleanup"), nargs="?", default="plan")
    parser.add_argument("--config", required=True)
    parser.add_argument("--allow-live-host-recovery", action="store_true")
    args = parser.parse_args()
    config_path = Path(args.config)
    config = validate(json.loads(config_path.read_text()))
    if args.mode == "plan":
        print(json.dumps(plan(config), indent=2))
        return
    require(args.allow_live_host_recovery, "explicit_live_flag_required")
    require(str(config_path) == config["config_path"], "live_config_path_mismatch")
    require(str(Path(__file__)) == config["helper_path"], "live_helper_path_mismatch")
    backend = LiveBackend(config)
    if args.mode == "cleanup":
        result = explicit_owned_cleanup(config, backend)
    else:
        with owned_lock(config["guard_dir"] + "/attempt.lock", expected_uid=0) as acquired:
            if not acquired:
                result = {"schema": 1, "overlapping_attempt_skipped": True, "recurring_retry_retained": True}
            else:
                result = attempt(config, backend)
                destination = Path(config["guard_dir"]) / "attempt-last-safe.json"
                temporary = destination.with_suffix(".json.tmp")
                temporary.write_text(json.dumps(result, indent=2) + "\n")
                os.replace(temporary, destination)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
