#!/usr/bin/env python3
"""Execute production DNS snapshots, formatters, and CLI wiring without a network.

Only lwIP dispatch/address conversion and physical-link endpoints are mocked.
The real NetworkLink interface, complete shared base, and each DNS formatter
are compiled together, including the observer getter copied from production.
"""
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

from test_replay_reset_integration import extract_braced

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "test/fixtures/network_dns.cpp"

IP_ADDRESS = r'''
#pragma once
#include <string>
class IPAddress {
  std::string text;
 public:
  IPAddress() : text("0.0.0.0") {}
  explicit IPAddress(const char* value) : text(value) {}
  std::string toString() const { return text; }
};
'''


def production_harness():
    network = (ROOT / "src/helpers/NetworkLink.cpp").read_text(encoding="utf-8")
    helpers = network[network.index("namespace {") + len("namespace {"):
                      network.index("class NetworkLinkBase")]
    base = extract_braced(network, "class NetworkLinkBase") + ";"
    code = FIXTURE.read_text(encoding="ascii").replace("@HELPERS@", helpers)
    code = code.replace("@BASE@", base)
    for name in ("WiFiNetworkLink", "EthernetNetworkLink", "AutomaticNetworkLink"):
        implementation = extract_braced(network, "class " + name)
        methods = extract_braced(implementation, "void formatDns(")
        if name != "AutomaticNetworkLink":
            methods += "\n" + extract_braced(implementation, "IPAddress gatewayIP()")
        code = code.replace("@" + name + "@", methods)
    cli = (ROOT / "src/helpers/CommonCLI_Observer.cpp").read_text(encoding="utf-8")
    getter = extract_braced(cli, 'if (strcmp(config, "link.dns") == 0)')
    return code.replace("@GETTER@", getter)


class NetworkDnsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.compiler = os.environ.get("CXX") or shutil.which("g++") or shutil.which("clang++")
        if cls.compiler is None:
            raise unittest.SkipTest("a host C++17 compiler is required")
        cls.temporary = tempfile.TemporaryDirectory(prefix="meshcore-network-dns-")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.directory = Path(cls.temporary.name)
        (cls.directory / "Arduino.h").write_text("#pragma once\n", encoding="ascii")
        (cls.directory / "IPAddress.h").write_text(IP_ADDRESS, encoding="ascii")
        cls.source = production_harness()
        cls.binary = cls.compile(cls.source, "production")

    @classmethod
    def compile(cls, source, name):
        cpp = cls.directory / (name + ".cpp")
        binary = cls.directory / name
        cpp.write_text(source, encoding="utf-8")
        sanitizers = (["-fsanitize=address,undefined", "-fno-sanitize-recover=all",
                       "-fno-pie", "-no-pie"] if sys.platform.startswith("linux") else [])
        result = subprocess.run([
            cls.compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror", *sanitizers,
            "-DESP_PLATFORM=1", "-I", str(cls.directory), "-I", str(ROOT / "src"),
            str(cpp), "-o", str(binary)], capture_output=True, text=True, timeout=60)
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)
        return binary

    def run_scenario(self, scenario, binary=None):
        result = subprocess.run([str(binary or self.binary), scenario],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_three_slot_snapshot_restore_and_empty_slot_clearing(self):
        self.run_scenario("restore")

    def test_never_leased_medium_preserves_current_global_resolvers(self):
        self.run_scenario("never-leased")

    def test_renewals_keep_last_valid_lease_and_replace_obsolete_slots(self):
        self.run_scenario("renewal")

    def test_dns_lists_and_all_network_diagnostics_are_bounded(self):
        self.run_scenario("format")

    def test_zero_capacity_and_null_destination_do_not_write(self):
        self.run_scenario("zero")

    def test_observer_getter_uses_real_interface_and_exact_command(self):
        self.run_scenario("getter")
        cli = (ROOT / "src/helpers/CommonCLI_Observer.cpp").read_text(encoding="utf-8")
        self.assertIn('#ifdef ESP_PLATFORM\n#include "NetworkLink.h"', cli)
        self.assertIn('memcmp(config, "wifi.status", 11)', cli)

    def test_webconfig_mock_exposes_the_read_only_dns_getter(self):
        sys.path.insert(0, str(ROOT / "scripts"))
        try:
            import webconfig_mock_server as portal
        finally:
            sys.path.pop(0)
        self.assertEqual(portal.cli_get({}, "link.dns"),
                         (True, "> dns:192.168.1.1 gw:192.168.1.1 lease:192.168.1.1"))
        page = (ROOT / "webui/index.html").read_text(encoding="utf-8")
        self.assertRegex(page, r'\["link\.dns","[^"\n]+",1\]')

    def test_old_snapshot_and_restore_callbacks_lose_resolvers(self):
        snapshot = extract_braced(self.source, "static esp_err_t snapshotDnsOnTcpipThread(")
        # Reproduce the old write-before-validation callback. The retained
        # self-copy on a valid lease has no effect; an empty renewal overwrites
        # the snapshot before the captured flag can reject it.
        old_snapshot = snapshot.replace("ip_addr_t servers[kDnsServers] = {};", "")
        old_snapshot = old_snapshot.replace("servers[i]", "self->_dns_snapshot[i]")
        controls = (
            (self.source.replace("kDnsServers = DNS_MAX_SERVERS;", "kDnsServers = 2;"), "restore"),
            (self.source.replace("dns_setserver(i, &self->_dns_snapshot[i]);",
                                 "if (!ip_addr_isany_val(self->_dns_snapshot[i])) "
                                 "dns_setserver(i, &self->_dns_snapshot[i]);"), "restore"),
            (self.source.replace(snapshot, old_snapshot), "renewal"),
        )
        for index, (broken, scenario) in enumerate(controls):
            with self.subTest(control=index):
                self.assertNotEqual(broken, self.source)
                binary = self.compile(broken, "broken-" + str(index))
                result = subprocess.run([str(binary), scenario], capture_output=True,
                                        text=True, timeout=10)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("DNS-free renewal" if scenario == "renewal" else "DNS restore",
                              result.stderr)


if __name__ == "__main__":
    unittest.main()
