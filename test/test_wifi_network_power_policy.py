#!/usr/bin/env python3
"""Run the shared WiFi outage policy against deterministic clocks and owners.

The production header is compiled directly, without Arduino or PlatformIO.
Independent translation units and concurrent service holds exercise the actual
handoff used between the network worker and foreground service owners.
"""

from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]

HARNESS = r'''
#include <helpers/WiFiNetworkPowerPolicy.h>
#include <atomic>
#include <cstring>
#include <iostream>
#include <stdexcept>
#include <thread>
#include <vector>

using mesh::wifi::NetworkPowerControl;
using mesh::wifi::NetworkPowerHold;
using mesh::wifi::NetworkPowerPolicy;
using mesh::wifi::networkPower;
using Action = NetworkPowerPolicy::Action;

extern NetworkPowerControl* otherControl();
extern void otherSetWebHold(bool value);
extern bool otherSuspended();

static void require(bool value, const char* reason) {
  if (!value) throw std::runtime_error(reason);
}

static void expect(NetworkPowerPolicy& policy, uint32_t now,
                   bool useful, bool foreground, Action expected,
                   bool probe = false) {
  require(policy.update(now, useful, foreground, probe) == expected,
          "unexpected network power transition");
  require(policy.suspended() == (expected == Action::Suspend),
          "transition and suspension state disagree");
}

// Keep expected timings independent of the production constants. Altering a
// timeout must be an intentional policy change, rather than a self-passing test.
static const uint32_t grace = 300000U;
static const uint32_t probe_budget = 120000U;
static const uint32_t cooldown = 1800000U;

static void graceBoundary() {
  for (uint32_t start : {0U, 1234U, UINT32_MAX - 10000U}) {
    NetworkPowerPolicy policy;
    expect(policy, start, false, false, Action::Run);
    expect(policy, start + grace - 1U, false, false, Action::Run);
    expect(policy, start + grace, false, false, Action::Suspend);
    expect(policy, start + grace + 1U, false, false, Action::Suspend);
  }
}

static void failedServicesCannotRenew() {
  // Serial event stream: associations succeed, SNTP alternates success/failure,
  // and MQTT handshakes keep failing. None means the configured broker works.
  enum Event { GotIp, NtpTimeout, NtpReply, MqttConnectFailure, MqttRetry };
  const Event events[] = {GotIp, NtpTimeout, MqttConnectFailure,
                         NtpReply, MqttRetry};
  for (uint32_t start : {0U, UINT32_MAX - 70000U}) {
    NetworkPowerPolicy policy;
    expect(policy, start, false, false, Action::Run);
    for (uint32_t offset = 1000U; offset < grace; offset += 1000U) {
      const Event event = events[(offset / 1000U) % 5U];
      require(event == GotIp || event == NtpTimeout || event == NtpReply
              || event == MqttConnectFailure || event == MqttRetry,
              "invalid simulated network event");
      expect(policy, start + offset, false, false, Action::Run);
    }
    expect(policy, start + grace, false, false, Action::Suspend);
    // Both services keep wanting retries. Their failure notifications cannot
    // restart either the grace period or the 30-minute suspension clock.
    for (uint32_t offset = 1000U; offset < cooldown; offset += 1000U) {
      expect(policy, start + grace + offset, false, false, Action::Suspend);
    }
    expect(policy, start + grace + cooldown, false, false, Action::Resume);
  }
}

static void successfulBrokerRenews() {
  for (uint32_t start : {0U, UINT32_MAX - 200000U}) {
    NetworkPowerPolicy policy;
    expect(policy, start, false, false, Action::Run);
    expect(policy, start + grace - 1U, true, false, Action::Run);
    const uint32_t last_healthy = start + 2U * grace;
    expect(policy, last_healthy, true, false, Action::Run);
    expect(policy, last_healthy + grace - 1U, false, false, Action::Run);
    expect(policy, last_healthy + grace, false, false, Action::Suspend);
    // A genuine healthy connection observed during suspension cancels it and
    // receives the normal grace budget, rather than a short recovery probe.
    const uint32_t recovered = last_healthy + grace + 20U;
    expect(policy, recovered, true, false, Action::Resume);
    expect(policy, recovered + probe_budget, false, false, Action::Run);
    expect(policy, recovered + grace, false, false, Action::Suspend);
  }
}

static void boundedRecoveryCycles() {
  for (uint32_t start : {0U, UINT32_MAX - 10000U}) {
    NetworkPowerPolicy policy;
    expect(policy, start, false, false, Action::Run);
    uint32_t suspended_at = start + grace;
    expect(policy, suspended_at, false, false, Action::Suspend);
    for (unsigned cycle = 0; cycle < 20; ++cycle) {
      expect(policy, suspended_at + cooldown - 1U, false, false,
             Action::Suspend);
      const uint32_t resumed_at = suspended_at + cooldown;
      expect(policy, resumed_at, false, false, Action::Resume);
      for (uint32_t offset = 1000U; offset < probe_budget; offset += 1000U) {
        expect(policy, resumed_at + offset, false, false, Action::Run);
      }
      expect(policy, resumed_at + probe_budget - 1U, false, false,
             Action::Run);
      suspended_at = resumed_at + probe_budget;
      expect(policy, suspended_at, false, false, Action::Suspend);
    }
  }
}

static void foregroundPreservesAccess() {
  NetworkPowerPolicy policy;
  expect(policy, 0, false, true, Action::Run);
  expect(policy, grace, false, true, Action::Run);
  expect(policy, 3U * grace, false, true, Action::Run);
  // Closing the foreground session does not grant a new background grace.
  expect(policy, 3U * grace + 1U, false, false, Action::Suspend);
  expect(policy, 3U * grace + 2U, false, true, Action::Resume);
  expect(policy, 3U * grace + 2U + probe_budget, false, true, Action::Run);
  expect(policy, 3U * grace + 3U + probe_budget, false, false,
         Action::Suspend);
}

static void manualProbeOnlyOnDemand() {
  NetworkPowerPolicy policy;
  expect(policy, 100U, false, false, Action::Run);
  expect(policy, 100U + grace, false, false, Action::Suspend);
  expect(policy, 101U + grace, false, false, Action::Suspend);
  const uint32_t requested_at = 102U + grace;
  expect(policy, requested_at, false, false, Action::Resume, true);
  // Repeated manual requests while running cannot renew the probe deadline.
  expect(policy, requested_at + probe_budget - 1U, false, false,
         Action::Run, true);
  expect(policy, requested_at + probe_budget, false, false,
         Action::Suspend, true);
  expect(policy, requested_at + probe_budget + 1U, false, false,
         Action::Suspend);
  expect(policy, requested_at + probe_budget + cooldown - 1U, false, false,
         Action::Suspend);
  expect(policy, requested_at + probe_budget + cooldown, false, false,
         Action::Resume);
}

static void usefulProbeBecomesNormalOperation() {
  NetworkPowerPolicy policy;
  expect(policy, 0, false, false, Action::Run);
  expect(policy, grace, false, false, Action::Suspend);
  const uint32_t resumed_at = grace + cooldown;
  expect(policy, resumed_at, false, false, Action::Resume);
  const uint32_t recovered_at = resumed_at + probe_budget - 1U;
  expect(policy, recovered_at, true, false, Action::Run);
  expect(policy, recovered_at + probe_budget, false, false, Action::Run);
  expect(policy, recovered_at + grace - 1U, false, false, Action::Run);
  expect(policy, recovered_at + grace, false, false, Action::Suspend);
}

static void clearControl(NetworkPowerControl& control) {
  control.setManaged(false);
  control.setHold(NetworkPowerHold::CompanionClient, false);
  control.setHold(NetworkPowerHold::WebConfig, false);
  control.setHold(NetworkPowerHold::OtaSeeder, false);
  control.consumeProbeRequest();
}

static void programWideRegistry() {
  NetworkPowerControl& control = networkPower();
  clearControl(control);
  require(&control == otherControl(), "service translation units split registry");
  control.setManaged(true);
  control.setSuspended(true);
  require(otherSuspended(), "worker suspension invisible to station owner");
  otherSetWebHold(true);
  require(control.foregroundActive(), "foreground hold invisible to worker");
  control.setHold(NetworkPowerHold::OtaSeeder, true);
  otherSetWebHold(false);
  require(control.foregroundActive(), "closing web session cleared OTA hold");
  control.setHold(NetworkPowerHold::OtaSeeder, false);
  require(!control.foregroundActive(), "closed services retained WiFi lease");
  control.requestProbe();
  require(otherControl()->consumeProbeRequest(), "probe invisible across tasks");
  require(!control.consumeProbeRequest(), "probe request was not one-shot");
  control.setManaged(false);
  require(!otherSuspended(), "disabled manager retained suspension");
}

static void controlLifecycle() {
  NetworkPowerControl control;
  require(!control.managed() && !control.backgroundSuspended()
          && !control.foregroundActive() && !control.consumeProbeRequest(),
          "new control has active service state");
  control.setSuspended(true);
  require(!control.backgroundSuspended(), "unmanaged owner imposed suspension");
  control.setManaged(true);
  require(control.backgroundSuspended(), "managed suspension was lost");
  control.requestProbe();
  control.setManaged(false);
  require(!control.backgroundSuspended() && !control.consumeProbeRequest(),
          "stopping worker preserved stale suspension or probe");
  control.setHold(NetworkPowerHold::CompanionClient, true);
  control.setManaged(true);
  require(!control.backgroundSuspended() && control.foregroundActive(),
          "restarting manager lost foreground owner or kept stale suspension");
  control.setHold(NetworkPowerHold::CompanionClient, false);
  require(!control.foregroundActive(), "last foreground owner failed to release");
}

static void concurrentServiceHolds() {
  NetworkPowerControl control;
  const NetworkPowerHold owners[] = {NetworkPowerHold::CompanionClient,
                                     NetworkPowerHold::WebConfig,
                                     NetworkPowerHold::OtaSeeder};
  for (unsigned round = 0; round < 256; ++round) {
    std::atomic<unsigned> ready{0};
    std::atomic<bool> go{false};
    std::atomic<bool> release[3] = {};
    std::atomic<bool> removed[3] = {};
    std::vector<std::thread> threads;
    for (unsigned index = 0; index < 3; ++index) {
      threads.emplace_back([&, index]() {
        ready.fetch_add(1, std::memory_order_release);
        while (!go.load(std::memory_order_acquire)) std::this_thread::yield();
        control.setHold(owners[index], true);
        ready.fetch_add(1, std::memory_order_release);
        while (!release[index].load(std::memory_order_acquire)) {
          std::this_thread::yield();
        }
        control.setHold(owners[index], false);
        removed[index].store(true, std::memory_order_release);
      });
    }
    while (ready.load(std::memory_order_acquire) != 3U) std::this_thread::yield();
    go.store(true, std::memory_order_release);
    while (ready.load(std::memory_order_acquire) != 6U) std::this_thread::yield();
    const bool opens_preserved = control.foregroundActive();
    bool remaining_holds_preserved = true;
    for (unsigned index = 0; index < 3; ++index) {
      release[index].store(true, std::memory_order_release);
      while (!removed[index].load(std::memory_order_acquire)) {
        std::this_thread::yield();
      }
      if (index < 2 && !control.foregroundActive()) remaining_holds_preserved = false;
    }
    for (auto& thread : threads) thread.join();
    require(opens_preserved, "simultaneous opens lost all leases");
    require(remaining_holds_preserved, "one owner cleared another owner's lease");
    require(!control.foregroundActive(), "concurrent closes leaked WiFi hold");
  }
}

static void serviceLeaseEventSequence() {
  NetworkPowerPolicy policy;
  NetworkPowerControl control;
  control.setManaged(true);
  auto update = [&](uint32_t now, bool useful = false) {
    const Action action = policy.update(now, useful, control.foregroundActive(),
                                        control.consumeProbeRequest());
    control.setSuspended(action == Action::Suspend);
    return action;
  };
  require(update(0) == Action::Run, "network failed to start");
  require(update(grace) == Action::Suspend, "outage left WiFi active");
  control.setHold(NetworkPowerHold::WebConfig, true);
  require(update(grace + 1U) == Action::Resume, "admin did not wake network");
  control.setHold(NetworkPowerHold::OtaSeeder, true);
  control.setHold(NetworkPowerHold::WebConfig, false);
  require(update(grace + probe_budget + 1U) == Action::Run,
          "closing admin page interrupted active OTA");
  control.setHold(NetworkPowerHold::OtaSeeder, false);
  require(update(grace + probe_budget + 2U) == Action::Suspend,
          "completed OTA kept failed background network on");
  control.requestProbe();
  require(update(grace + probe_budget + 3U) == Action::Resume,
          "explicit retry could not recover network");
  require(!control.consumeProbeRequest(), "owner probe did not get consumed");
  require(update(grace + probe_budget + 4U, true) == Action::Run,
          "healthy broker did not resume normal service");
  require(!control.backgroundSuspended(), "healthy broker left station suspended");
}

int main(int argc, char** argv) {
  if (argc != 2) return 2;
  try {
    const char* name = argv[1];
    if (!strcmp(name, "grace")) graceBoundary();
    else if (!strcmp(name, "failures")) failedServicesCannotRenew();
    else if (!strcmp(name, "healthy")) successfulBrokerRenews();
    else if (!strcmp(name, "cycles")) boundedRecoveryCycles();
    else if (!strcmp(name, "foreground")) foregroundPreservesAccess();
    else if (!strcmp(name, "manual")) manualProbeOnlyOnDemand();
    else if (!strcmp(name, "recovery")) usefulProbeBecomesNormalOperation();
    else if (!strcmp(name, "registry")) programWideRegistry();
    else if (!strcmp(name, "lifecycle")) controlLifecycle();
    else if (!strcmp(name, "threads")) concurrentServiceHolds();
    else if (!strcmp(name, "leases")) serviceLeaseEventSequence();
    else return 2;
  } catch (const std::exception& error) {
    std::cerr << argv[1] << ": " << error.what() << '\n';
    return 1;
  }
  std::cout << "PASS: " << argv[1] << '\n';
  return 0;
}
'''

OTHER_OWNER = r'''
#include <helpers/WiFiNetworkPowerPolicy.h>

mesh::wifi::NetworkPowerControl* otherControl() {
  return &mesh::wifi::networkPower();
}
void otherSetWebHold(bool value) {
  mesh::wifi::networkPower().setHold(mesh::wifi::NetworkPowerHold::WebConfig, value);
}
bool otherSuspended() {
  return mesh::wifi::networkPower().backgroundSuspended();
}
'''


class WiFiNetworkPowerPolicyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = os.environ.get("CXX") or shutil.which("g++") or shutil.which("clang++")
        if not compiler:
            raise RuntimeError("a host C++ compiler is required")
        cls.temporary = tempfile.TemporaryDirectory(prefix="meshcore-wifi-outage-")
        cls.addClassCleanup(cls.temporary.cleanup)
        work = Path(cls.temporary.name)
        source = work / "policy.cpp"
        owner = work / "owner.cpp"
        source.write_text(HARNESS, encoding="ascii")
        owner.write_text(OTHER_OWNER, encoding="ascii")
        cls.binary = work / "policy"
        built = subprocess.run(
            [compiler, "-std=c++11", "-pthread", "-Wall", "-Wextra", "-Werror",
             "-I", str(ROOT / "src"), str(source), str(owner), "-o", str(cls.binary)],
            capture_output=True, text=True, timeout=60,
        )
        if built.returncode:
            raise RuntimeError(built.stdout + built.stderr)

    def run_case(self, name):
        result = subprocess.run([str(self.binary), name], capture_output=True,
                                text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("PASS: " + name, result.stdout)

    def test_initial_five_minute_grace_and_millis_rollover(self):
        self.run_case("grace")

    def test_ntp_replies_association_and_mqtt_failures_do_not_renew_outage(self):
        self.run_case("failures")

    def test_healthy_broker_renews_grace_and_cancels_suspension(self):
        self.run_case("healthy")

    def test_two_minute_probes_and_thirty_minute_cooldowns_repeat_bounded(self):
        self.run_case("cycles")

    def test_foreground_access_resumes_and_protects_wifi_until_released(self):
        self.run_case("foreground")

    def test_requested_probe_is_explicit_and_does_not_extend_active_probe(self):
        self.run_case("manual")

    def test_successful_probe_returns_to_normal_grace(self):
        self.run_case("recovery")

    def test_two_translation_units_share_owner_holds_and_probe_requests(self):
        self.run_case("registry")

    def test_worker_lifecycle_clears_stale_suspension_and_probe(self):
        self.run_case("lifecycle")

    def test_concurrent_foreground_owners_preserve_each_others_holds(self):
        self.run_case("threads")

    def test_admin_and_ota_lease_sequence_during_combined_background_outage(self):
        self.run_case("leases")


if __name__ == "__main__":
    unittest.main()
