"""Pure fake-NM tests. No NetworkManager/systemd/SSH/hardware calls."""
import copy
import contextlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import importlib.util

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "hil_slowfi_guard", ROOT / "tools/hil/slowfi_guard.py")
guard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(guard)

ORIGINAL = "11111111-1111-4111-8111-111111111111"
OWNED = "22222222-2222-4222-8222-222222222222"
OTHER = "33333333-3333-4333-8333-333333333333"
STEM = "meshcore-slowfi-return-synthetic-20261007"
CONFIG = {
    "schema": 1, "original_uuid": ORIGINAL,
    "expected_hostname": "synthetic-no-hardware-host",
    "expected_machine_id_sha256": "1" * 64, "interface": "wlan0",
    "unit_stem": STEM, "guard_dir": "/run/" + STEM,
    "python_path": "/usr/bin/python3",
    "helper_path": "/run/" + STEM + "/slowfi_guard.py",
    "config_path": "/run/" + STEM + "/config.json",
    "live_execution_authorized": False,
    "owned_profiles": [{"uuid": OWNED, "id": "meshcore-owned-ap-synthetic-20261007"}],
}


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class FakeNM:
    def __init__(self, clock=None, failures=0):
        self.clock = clock or Clock()
        self.failures = failures
        self.attempts = 0
        self.current = {"uuid": OWNED, "state": 100}
        self.timer_active = True
        self.stop_ok = True
        self.stop_side_effect = False
        self.timer_state_unknown = False
        self.state_sequence = []
        self.calls = []
        self.activation_return = None
        self.activation_state = None
        self.names = {OWNED: CONFIG["owned_profiles"][0]["id"], ORIGINAL: "original-profile"}
        self.timeouts = False

    def state(self, interface, timeout):
        self.calls.append(("state", interface, timeout))
        self.clock.now += timeout if self.timeouts else 0.1
        if self.timeouts:
            return None
        if self.state_sequence:
            return copy.deepcopy(self.state_sequence.pop(0))
        return copy.deepcopy(self.current)

    def activate(self, original_uuid, timeout):
        self.calls.append(("activate", original_uuid, timeout))
        self.attempts += 1
        self.clock.now += timeout if self.timeouts else 0.1
        if self.timeouts:
            return False
        if self.activation_state is not None:
            self.current = copy.deepcopy(self.activation_state)
        elif self.attempts > self.failures:
            self.current = {"uuid": original_uuid, "state": 100}
        return self.activation_return if self.activation_return is not None else self.attempts > self.failures

    def stop_timer(self, timer, timeout):
        self.calls.append(("stop_timer", timer, timeout))
        self.clock.now += 0.1
        if self.stop_ok or self.stop_side_effect:
            self.timer_active = False
        return self.stop_ok

    def timer_state(self, timer, timeout):
        self.calls.append(("timer_state", timer, timeout))
        self.clock.now += 0.1
        return None if self.timer_state_unknown else "active" if self.timer_active else "inactive"

    def stop_owned_units(self, timer, service, timeout):
        self.calls.append(("stop_owned_units", timer, service, timeout))
        self.timer_active = False
        return True

    def profile_name(self, value, timeout):
        self.calls.append(("profile_name", value, timeout))
        return self.names.get(value)

    def delete_profile(self, value, timeout):
        self.calls.append(("delete_profile", value, timeout))
        del self.names[value]
        return True


class GuardTests(unittest.TestCase):
    def setUp(self):
        self.config = copy.deepcopy(CONFIG)

    def run_attempt(self, backend):
        return guard.attempt(self.config, backend, clock=backend.clock)

    def run_cleanup(self, backend, acquired=True):
        return guard.explicit_owned_cleanup(self.config, backend, clock=backend.clock,
            lock_context=lambda _: contextlib.nullcontext(acquired))

    def test_more_than_five_transient_failures_then_connected_stops_timer(self):
        backend = FakeNM(failures=8)
        receipts = []
        for number in range(9):
            receipts.append(self.run_attempt(backend))
            if number < 8:
                self.assertTrue(backend.timer_active)
                self.assertTrue(receipts[-1]["recurring_retry_retained"])
                backend.clock.now += guard.RETRY_DELAY_SECONDS
        self.assertEqual(backend.attempts, 9)
        self.assertTrue(receipts[-1]["original_uuid_connected"])
        self.assertTrue(receipts[-1]["timer_stopped"])
        self.assertFalse(backend.timer_active)

    def test_persistent_failures_leave_unlimited_future_attempts(self):
        backend = FakeNM(failures=10**9)
        for _ in range(100):
            result = self.run_attempt(backend)
            self.assertFalse(result["original_uuid_connected"])
            self.assertTrue(result["recurring_retry_retained"])
            self.assertTrue(backend.timer_active)
            backend.clock.now += guard.RETRY_DELAY_SECONDS
        self.assertEqual(backend.attempts, 100)
        self.assertFalse(any(row[0] == "stop_timer" for row in backend.calls))

    def test_return_zero_is_not_association_proof(self):
        backend = FakeNM(failures=10)
        backend.activation_return = True
        result = self.run_attempt(backend)
        self.assertTrue(result["nmcli_activation_returned_success"])
        self.assertFalse(result["original_uuid_connected"])
        self.assertTrue(backend.timer_active)

    def test_wrong_uuid_or_nonconnected_state_never_stops_timer(self):
        for state in ({"uuid": OTHER, "state": 100}, {"uuid": ORIGINAL, "state": 70}, {"uuid": ORIGINAL, "state": 30}):
            with self.subTest(state=state):
                backend = FakeNM()
                backend.activation_state = state
                result = self.run_attempt(backend)
                self.assertFalse(result["original_uuid_connected"])
                self.assertTrue(backend.timer_active)

    def test_already_original_connected_has_no_nm_activation(self):
        backend = FakeNM()
        backend.current = {"uuid": ORIGINAL, "state": 100}
        result = self.run_attempt(backend)
        self.assertTrue(result["timer_stopped"])
        self.assertEqual(backend.attempts, 0)

    def test_stop_timer_failure_keeps_recurring_retry(self):
        backend = FakeNM()
        backend.stop_ok = False
        result = self.run_attempt(backend)
        self.assertTrue(result["original_uuid_connected"])
        self.assertFalse(result["timer_stopped"])
        self.assertTrue(result["recurring_retry_retained"])

    def test_stop_timer_side_effect_then_failure_does_not_claim_retry_retained(self):
        backend = FakeNM()
        backend.stop_ok = False
        backend.stop_side_effect = True
        result = self.run_attempt(backend)
        self.assertFalse(result["timer_stop_returned_success"])
        self.assertTrue(result["timer_stopped"])
        self.assertFalse(result["recurring_retry_retained"])
        self.assertEqual(result["timer_state_after_stop"], "inactive")

    def test_stop_timer_state_unknown_does_not_claim_retry_retained(self):
        backend = FakeNM()
        backend.timer_state_unknown = True
        result = self.run_attempt(backend)
        self.assertTrue(result["timer_stop_returned_success"])
        self.assertIsNone(result["recurring_retry_retained"])
        self.assertFalse(result["timer_stopped"])

    def test_stop_exception_does_not_claim_retry_retained(self):
        backend = FakeNM()
        with patch.object(backend, "stop_timer", side_effect=TimeoutError("secret")):
            result = self.run_attempt(backend)
        self.assertIsNone(result["recurring_retry_retained"])
        self.assertFalse(result["timer_stopped"])

    def test_all_subprocess_timeouts_stay_under_35_seconds(self):
        backend = FakeNM()
        backend.timeouts = True
        result = self.run_attempt(backend)
        self.assertLessEqual(result["elapsed_seconds"], guard.ATTEMPT_BUDGET_SECONDS)
        self.assertTrue(result["recurring_retry_retained"])
        self.assertEqual([x[-1] for x in backend.calls], [3, 24, 3])

    def test_nonblocking_lock_skips_overlap_then_allows_next_invocation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "guard.lock"
            with guard.owned_lock(path) as first:
                self.assertTrue(first)
                with guard.owned_lock(path) as second:
                    self.assertFalse(second)
            with guard.owned_lock(path) as third:
                self.assertTrue(third)

    def test_lock_refuses_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            actual = Path(directory) / "actual"
            actual.touch()
            alias = Path(directory) / "alias"
            alias.symlink_to(actual)
            with self.assertRaises(OSError):
                with guard.owned_lock(alias):
                    pass

    def test_owned_cleanup_uses_only_captured_profile_and_units(self):
        backend = FakeNM()
        backend.current = {"uuid": ORIGINAL, "state": 100}
        result = self.run_cleanup(backend)
        self.assertTrue(result["ok"])
        self.assertTrue(result["original_profile_untouched"])
        self.assertIn(ORIGINAL, backend.names)
        self.assertNotIn(OWNED, backend.names)
        self.assertEqual([x[1] for x in backend.calls if x[0] == "delete_profile"], [OWNED])
        stopped = [row for row in backend.calls if row[0] == "stop_owned_units"]
        self.assertEqual(stopped[0][:3], ("stop_owned_units", STEM + ".timer", STEM + ".service"))
        self.assertEqual([row[0] for row in backend.calls[:4]], ["state", "state", "profile_name", "state"])

    def test_owned_cleanup_refuses_changed_profile_name(self):
        backend = FakeNM()
        backend.current = {"uuid": ORIGINAL, "state": 100}
        backend.names[OWNED] = "unowned-existing-profile"
        result = self.run_cleanup(backend)
        self.assertTrue(result["cleanup_refused"])
        self.assertTrue(result["no_mutation"])
        self.assertTrue(backend.timer_active)
        self.assertEqual(result["reason"], "owned_profile_identity_changed")
        self.assertFalse(any(x[0] == "delete_profile" for x in backend.calls))

    def test_cleanup_wrong_uuid_connecting_or_inconclusive_keeps_guard_running(self):
        for state in ({"uuid": OTHER, "state": 100}, {"uuid": ORIGINAL, "state": 70}, None):
            with self.subTest(state=state):
                backend = FakeNM()
                backend.current = state
                result = self.run_cleanup(backend)
                self.assertTrue(result["cleanup_refused"])
                self.assertTrue(result["no_mutation"])
                self.assertTrue(backend.timer_active)
                self.assertEqual([row[0] for row in backend.calls], ["state"])

    def test_cleanup_association_lost_under_lock_refuses_without_mutation(self):
        for state in ({"uuid": OWNED, "state": 100}, {"uuid": ORIGINAL, "state": 70}, None):
            with self.subTest(state=state):
                backend = FakeNM()
                backend.state_sequence = [{"uuid": ORIGINAL, "state": 100}, state]
                result = self.run_cleanup(backend)
                self.assertTrue(result["cleanup_refused"])
                self.assertTrue(result["no_mutation"])
                self.assertTrue(backend.timer_active)
                self.assertEqual([row[0] for row in backend.calls], ["state", "state"])

    def test_later_ownership_collision_prevents_all_cleanup_mutations(self):
        self.config["owned_profiles"].append({"uuid": OTHER, "id": "meshcore-owned-second-synthetic-20261007"})
        backend = FakeNM()
        backend.current = {"uuid": ORIGINAL, "state": 100}
        backend.names[OTHER] = "unowned-existing-profile"
        result = self.run_cleanup(backend)
        self.assertTrue(result["cleanup_refused"])
        self.assertTrue(result["no_mutation"])
        self.assertTrue(backend.timer_active)
        self.assertIn(OWNED, backend.names)
        self.assertFalse(any(row[0] in {"stop_owned_units", "delete_profile"} for row in backend.calls))

    def test_cleanup_lost_before_stop_refuses_without_mutation(self):
        backend = FakeNM()
        backend.state_sequence = [{"uuid": ORIGINAL, "state": 100}, {"uuid": ORIGINAL, "state": 100}, {"uuid": ORIGINAL, "state": 70}]
        result = self.run_cleanup(backend)
        self.assertTrue(result["cleanup_refused"])
        self.assertTrue(result["no_mutation"])
        self.assertTrue(backend.timer_active)
        self.assertFalse(any(row[0] in {"stop_owned_units", "delete_profile"} for row in backend.calls))

    def test_cleanup_busy_lock_does_not_stop_any_unit_or_delete_profile(self):
        backend = FakeNM()
        backend.current = {"uuid": ORIGINAL, "state": 100}
        result = self.run_cleanup(backend, acquired=False)
        self.assertTrue(result["cleanup_refused"])
        self.assertTrue(result["no_mutation"])
        self.assertTrue(backend.timer_active)
        self.assertEqual([row[0] for row in backend.calls], ["state"])

    def test_cleanup_state_error_does_not_stop_guard(self):
        backend = FakeNM()
        with patch.object(backend, "state", side_effect=RuntimeError("secret")):
            result = self.run_cleanup(backend)
        self.assertTrue(result["cleanup_refused"])
        self.assertTrue(result["no_mutation"])
        self.assertTrue(backend.timer_active)
        self.assertNotIn("secret", str(result))

    def test_original_profile_cannot_be_declared_owned(self):
        self.config["owned_profiles"][0]["uuid"] = ORIGINAL
        with self.assertRaisesRegex(ValueError, "original_profile"):
            guard.validate(self.config)

    def test_invalid_unit_or_path_rejected(self):
        for key, value in (("unit_stem", "NetworkManager"), ("helper_path", "/tmp/unowned.py")):
            with self.subTest(key=key):
                config = copy.deepcopy(CONFIG)
                config[key] = value
                with self.assertRaises(ValueError):
                    guard.validate(config)

    def test_actual_backend_command_builder_never_edits_original_profile(self):
        backend = guard.LiveBackend.__new__(guard.LiveBackend)
        backend.interface = "wlan0"
        with patch.object(backend, "call", return_value=(0, "SECRET-NOT-LOGGED")) as command:
            self.assertTrue(backend.activate(ORIGINAL, 25))
            command.assert_called_once_with([guard.NMCLI, "--wait", "25", "connection", "up", "uuid", ORIGINAL, "ifname", "wlan0"], 25)
        with patch.object(backend, "call", return_value=(0, "")) as command:
            self.assertTrue(backend.stop_timer(STEM + ".timer", 1))
            command.assert_called_once_with([guard.SYSTEMCTL, "stop", STEM + ".timer"], 1)

    def test_backend_exception_is_safe_and_does_not_disarm_timer(self):
        backend = FakeNM()
        with patch.object(backend, "state", side_effect=RuntimeError("SECRET-not-for-receipt")):
            result = self.run_attempt(backend)
        self.assertEqual(result["errors"], ["RuntimeError"])
        self.assertTrue(result["recurring_retry_retained"])
        self.assertNotIn("SECRET", str(result))
        self.assertTrue(backend.timer_active)

    def test_parse_exact_uuid_and_connected_state(self):
        self.assertEqual(guard.parse_state(ORIGINAL + "\n100 (connected)\n"), {"uuid": ORIGINAL, "state": 100})
        self.assertIsNone(guard.parse_state("--\n30 (disconnected)\n"))
        self.assertIsNone(guard.parse_state(ORIGINAL + "\n100\nextra"))

    def test_plan_does_not_construct_live_backend_or_run_command(self):
        with patch.object(guard.subprocess, "run", side_effect=AssertionError("unexpected command")), patch.object(guard, "LiveBackend", side_effect=AssertionError("unexpected live backend")):
            result = guard.plan(self.config)
        self.assertTrue(result["prepared_only"])
        files = result["unit_files"]
        timer, service = files[STEM + ".timer"], files[STEM + ".service"]
        self.assertIn("OnActiveSec=660s", timer)
        self.assertIn("OnUnitInactiveSec=30s", timer)
        self.assertIn("AccuracySec=1s", timer)
        self.assertIn("TimeoutStartSec=35s", service)
        self.assertIn("RemainAfterExit=no", service)
        self.assertNotIn("Restart=", service)
        self.assertNotIn("connection modify", timer + service)


if __name__ == "__main__":
    unittest.main(verbosity=2)
