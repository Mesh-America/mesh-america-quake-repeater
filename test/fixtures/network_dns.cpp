// The marked DNS methods and shared base are copied verbatim from production.
// This fixture replaces only SDK dispatch, address conversion, and link I/O.
#include <helpers/NetworkLink.h>
#include <array>
#include <atomic>
#include <cassert>
#include <climits>
#include <cstdio>
#include <cstring>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

static void require(bool condition, const char* message) {
  if (!condition) throw std::runtime_error(message);
}
constexpr int DNS_MAX_SERVERS = 3;
struct ip_addr_t {
  std::array<char, 48> text{};
  unsigned type = 0;
  bool operator==(const ip_addr_t& other) const {
    return type == other.type && text == other.text;
  }
};
static ip_addr_t address(const char* text, unsigned type = 4) {
  ip_addr_t value;
  if (*text) {
    require(strlen(text) < value.text.size(), "fixture address too long");
    strcpy(value.text.data(), text);
    value.type = type;
  }
  return value;
}
static const ip_addr_t empty_address;
#define IP_ADDR_ANY (&empty_address)
static bool ip_addr_isany_val(const ip_addr_t& value) { return !value.text[0]; }
static char* ipaddr_ntoa_r(const ip_addr_t* value, char* out, int size) {
  if (size <= 0 || strlen(value->text.data()) >= size_t(size)) return nullptr;
  strcpy(out, value->text.data());
  return out;
}
using esp_err_t = int;
constexpr esp_err_t ESP_OK = 0;
static bool on_tcpip_thread = false;
static unsigned tcpip_dispatches = 0;
static std::array<ip_addr_t, DNS_MAX_SERVERS> global_dns{};
static std::array<bool, DNS_MAX_SERVERS> null_dns{};
static std::vector<int> dns_reads, dns_writes;
static esp_err_t esp_netif_tcpip_exec(esp_err_t (*callback)(void*), void* context) {
  require(!on_tcpip_thread, "nested TCP/IP dispatch");
  ++tcpip_dispatches;
  on_tcpip_thread = true;
  const esp_err_t result = callback(context);
  on_tcpip_thread = false;
  return result;
}
static const ip_addr_t* dns_getserver(int index) {
  require(on_tcpip_thread, "DNS read escaped TCP/IP thread");
  dns_reads.push_back(index);
  return null_dns.at(index) ? nullptr : &global_dns.at(index);
}
static void dns_setserver(int index, const ip_addr_t* value) {
  require(on_tcpip_thread, "DNS write escaped TCP/IP thread");
  dns_writes.push_back(index);
  global_dns.at(index) = *value;
}
struct LinkEndpoint {
  IPAddress gateway;
  IPAddress gatewayIP() const { return gateway; }
} WiFi, CH390;

@HELPERS@
@BASE@

// Unchanged interface operations are irrelevant to DNS and have no SDK effects.
struct TestLink : NetworkLinkBase {
  const char* mediumName() const override { return "test"; }
  NetworkMedium medium() const override { return NetworkMedium::None; }
  const char* statusName() const override { return "test"; }
  int statusCode() const override { return 0; }
  bool configValid(const char*) const override { return true; }
  void setHostname(const char*) override {}
  bool begin(const char*, const char*) override { return false; }
  NetworkTransition maintain(uint32_t, uint8_t) override { return NetworkTransition::None; }
  bool isConnected() const override { return false; }
  IPAddress localIP() const override { return IPAddress(); }
  int rssi() const override { return INT_MIN; }
  bool resolveHost(const char*, IPAddress&) const override { return false; }
  void formatDiagnostics(char*, size_t) const override {}
};
struct WiFiNetworkLink : TestLink { @WiFiNetworkLink@ };
struct EthernetNetworkLink : TestLink { @EthernetNetworkLink@ };
struct AutomaticNetworkLink : TestLink {
  std::atomic<NetworkMedium> _selected{NetworkMedium::None};
  WiFiNetworkLink _wifi;
  EthernetNetworkLink _ethernet;
  @AutomaticNetworkLink@
};
static AutomaticNetworkLink automatic;
static unsigned link_lookups = 0;
NetworkLink& activeNetworkLink() { ++link_lookups; return automatic; }
static bool get(const char* config, char* reply) {
  @GETTER@ else { return false; }
  return true;
}

static void restore_scenario() {
  WiFiNetworkLink one, all;
  const std::array<ip_addr_t, 3> complete{{
      address("1.1.1.1"), address("8.8.8.8"), address("2001:db8::53", 6)}};
  const std::array<ip_addr_t, 3> single{{address("9.9.9.9"), {}, {}}};
  global_dns = complete;
  all.snapshotDns();
  global_dns = single;
  one.snapshotDns();
  dns_writes.clear();
  all.restoreDns();
  require(global_dns == complete, "DNS restore lost a populated third slot or typed address");
  require(dns_writes == std::vector<int>({0, 1, 2}), "DNS restore did not write every slot");
  dns_writes.clear();
  one.restoreDns();
  require(global_dns == single, "DNS restore retained another medium's empty-slot fallbacks");
  require(dns_writes == std::vector<int>({0, 1, 2}), "DNS restore omitted empty slots");
  require(tcpip_dispatches == 4, "DNS snapshots/restores bypassed thread dispatch");
}

static void never_leased_scenario() {
  WiFiNetworkLink never;
  const std::array<ip_addr_t, 3> complete{{address("1.1.1.1"), address("8.8.8.8"), address("9.9.9.9")}};
  global_dns = complete;
  never.restoreDns();
  require(global_dns == complete && dns_writes.empty(), "never-leased medium wiped live DNS");
  char lease[64] = {};
  never.formatLeaseDns(lease, sizeof(lease));
  require(std::string(lease) == "none", "never-leased DNS diagnostic is misleading");
  global_dns = {};
  never.snapshotDns();
  global_dns = complete;
  never.restoreDns();
  require(global_dns == complete && dns_writes.empty(), "resolver-free lease wiped live DNS");
  never.formatLeaseDns(lease, sizeof(lease));
  require(std::string(lease) == "none", "resolver-free lease invented captured DNS");
}

static void renewal_scenario() {
  WiFiNetworkLink link;
  const std::array<ip_addr_t, 3> third_only{{{}, {}, address("9.9.9.9")}};
  const std::array<ip_addr_t, 3> complete{{address("1.1.1.1"), address("8.8.8.8"), address("9.9.9.9")}};
  const std::array<ip_addr_t, 3> partial{{{}, address("10.10.10.10"), {}}};
  global_dns = third_only;
  link.snapshotDns();
  char lease[64] = {};
  link.formatLeaseDns(lease, sizeof(lease));
  require(std::string(lease) == "-,-,9.9.9.9", "third-slot-only lease was not captured");
  global_dns = complete;
  link.restoreDns();
  require(global_dns == third_only, "third-slot-only DNS restore lost its resolver");
  global_dns = complete;
  link.snapshotDns();
  global_dns = partial;
  link.snapshotDns();
  global_dns = complete;
  link.restoreDns();
  require(global_dns == partial, "valid DNS renewal retained obsolete resolver slots");
  global_dns = {};
  link.snapshotDns();
  global_dns = complete;
  link.restoreDns();
  require(global_dns == partial, "DNS-free renewal wiped the last valid lease");
  link.formatLeaseDns(lease, sizeof(lease));
  require(std::string(lease) == "-,10.10.10.10", "DNS-free renewal diagnostic lost the last valid lease");
}

static void prepare_automatic() {
  WiFi.gateway = IPAddress("10.0.0.1");
  CH390.gateway = IPAddress("192.168.1.1");
  global_dns = {{address("1.1.1.1"), {}, {}}};
  automatic._wifi.snapshotDns();
  global_dns = {{address("8.8.8.8"), {}, address("9.9.9.9")}};
  automatic._ethernet.snapshotDns();
  global_dns = {{address("4.4.4.4"), {}, {}}};
  automatic._selected = NetworkMedium::Ethernet;
}

static void format_scenario() {
  char list[64] = {};
  std::array<ip_addr_t, 3> servers{};
  formatDnsList(list, sizeof(list), servers.data(), 3);
  require(std::string(list) == "-", "empty resolver list differs from documented sentinel");
  servers = {{address("1.1.1.1"), {}, {}}};
  formatDnsList(list, sizeof(list), servers.data(), 3);
  require(std::string(list) == "1.1.1.1", "trailing empty resolver slots were retained");
  servers[2] = address("9.9.9.9");
  formatDnsList(list, sizeof(list), servers.data(), 3);
  require(std::string(list) == "1.1.1.1,-,9.9.9.9", "interior empty resolver slot was dropped");
  global_dns = servers;
  null_dns[0] = true;
  formatCurrentDnsServers(list, sizeof(list));
  require(std::string(list) == "-,-,9.9.9.9", "null lwIP resolver was not treated as empty");
  null_dns = {};

  prepare_automatic();
  const size_t writes_before = dns_writes.size();
  char reply[256] = {};
  const NetworkLink& wifi = automatic._wifi;
  wifi.formatDns(reply, sizeof(reply));
  require(std::string(reply) == "> dns:4.4.4.4 gw:10.0.0.1 lease:1.1.1.1", "WiFi DNS interface lost its own lease/gateway");
  const NetworkLink& ethernet = automatic._ethernet;
  ethernet.formatDns(reply, sizeof(reply));
  require(std::string(reply) == "> dns:4.4.4.4 gw:192.168.1.1 lease:8.8.8.8,-,9.9.9.9", "Ethernet DNS interface lost its own lease/gateway");
  const NetworkLink& selected = automatic;
  selected.formatDns(reply, sizeof(reply));
  require(std::string(reply) == "> dns:4.4.4.4 selected:ethernet gw:192.168.1.1\neth-lease:8.8.8.8,-,9.9.9.9 wifi-lease:1.1.1.1", "automatic DNS omitted global or medium lease data");
  automatic._selected = NetworkMedium::WiFi;
  selected.formatDns(reply, sizeof(reply));
  require(strstr(reply, "selected:wifi gw:10.0.0.1"), "automatic WiFi selection used the Ethernet gateway");
  automatic._selected = NetworkMedium::None;
  selected.formatDns(reply, sizeof(reply));
  require(strstr(reply, "selected:none gw:0.0.0.0"), "unselected diagnostic invented a gateway");

  // All three lists can exceed the real CLI's 160-byte buffer. Truncation is
  // allowed; writing beyond the declared capacity or losing NUL is not.
  global_dns = {{address("255.255.255.255"), address("255.255.255.255"), address("255.255.255.255")}};
  automatic._wifi.snapshotDns();
  automatic._ethernet.snapshotDns();
  automatic._selected = NetworkMedium::Ethernet;
  CH390.gateway = IPAddress("255.255.255.255");
  selected.formatDns(reply, sizeof(reply));
  require(strlen(reply) == 207, "long DNS diagnostic fixture no longer exercises truncation");
  const std::string full(reply);
  for (size_t size : {size_t(0), size_t(1), size_t(2), size_t(10), size_t(64), size_t(160)}) {
    std::array<unsigned char, 192> bounded;
    bounded.fill(0xA5);
    char* out = reinterpret_cast<char*>(bounded.data() + 8);
    selected.formatDns(out, size);
    for (size_t i = 0; i < 8; ++i) require(bounded[i] == 0xA5, "DNS formatter wrote before destination");
    for (size_t i = 8 + size; i < bounded.size(); ++i) require(bounded[i] == 0xA5, "DNS formatter overran declared capacity");
    if (size) require(std::string(out) == full.substr(0, size - 1), "bounded DNS reply lost NUL or changed prefix");
  }
  require(dns_writes.size() == writes_before, "read-only DNS diagnostics changed resolver state");
}

static void zero_scenario() {
  char canary = 'Z';
  formatDnsList(&canary, 0, global_dns.data(), 3);
  require(canary == 'Z', "zero-size DNS formatter wrote to its destination");
  formatDnsList(nullptr, 0, global_dns.data(), 3);
  formatDnsList(nullptr, 7, global_dns.data(), 3);
}

static void getter_scenario() {
  prepare_automatic();
  struct Reply { unsigned char before[8]; char text[160]; unsigned char after[8]; } reply;
  memset(&reply, 0xA5, sizeof(reply));
  require(get("link.dns", reply.text), "observer DNS getter was not recognized");
  require(link_lookups == 1 && strstr(reply.text, "> dns:4.4.4.4 selected:ethernet"), "observer DNS getter did not use the live NetworkLink interface");
  for (unsigned char c : reply.before) require(c == 0xA5, "observer DNS getter underflowed reply");
  for (unsigned char c : reply.after) require(c == 0xA5, "observer DNS getter overflowed reply");
  const std::string original(reply.text);
  for (const char* rejected : {"link.dnsX", "LINK.DNS", "link.dns ", "wifi.status"}) {
    require(!get(rejected, reply.text), "observer DNS getter accepted another command");
    require(std::string(reply.text) == original && link_lookups == 1, "rejected DNS command changed reply or queried the link");
  }
}

int main(int argc, char** argv) {
  try {
    require(argc == 2, "missing DNS scenario");
    const std::string scenario(argv[1]);
    if (scenario == "restore") restore_scenario();
    else if (scenario == "never-leased") never_leased_scenario();
    else if (scenario == "renewal") renewal_scenario();
    else if (scenario == "format") format_scenario();
    else if (scenario == "zero") zero_scenario();
    else if (scenario == "getter") getter_scenario();
    else throw std::runtime_error("unknown DNS scenario");
  } catch (const std::exception& error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
