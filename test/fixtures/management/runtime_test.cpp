#include "ManagementReporter.h"
#include "CommonCLI.h"
#include <cassert>
#include <cstdio>
#include <memory>
#include <string>
using namespace mesh;
using namespace mesh::management;
namespace mesh {
UsbLoggingStatus test_usb_status;
unsigned usb_status_calls = 0;
UsbLoggingStatus usbLoggingStatus() { ++usb_status_calls; return test_usb_status; }
}
struct Fixture {
  MemoryFS fs;
  Mesh mesh;
  MainBoard board;
  SensorManager sensors;
  ClientACL acl;
  NodePrefs prefs;
  CommonCLI cli;
  CommonCLICallbacks callbacks;
  std::unique_ptr<ManagementReporter> reporter;
  Fixture() { test_millis = 0; test_usb_status = UsbLoggingStatus(); usb_status_calls = 0; reboot(); }
  void reboot() { reporter.reset(); test_millis = 0; reporter.reset(new ManagementReporter(mesh, board, sensors, acl, prefs, callbacks, cli, &fs)); }
  std::string cmd(const char* text, bool ok = true) {
    char b[200], reply[160] = {}; strcpy(b, text);
    assert(reporter->command(b, reply, sizeof(reply)));
    if (!strncmp(text, "set ", 4) && ((!strncmp(reply, "OK", 2)) != ok)) {
      fprintf(stderr, "%s: %s\n", text, reply); assert(false);
    }
    if (!strncmp(text, "set mgmt.password ", 18) && strlen(text + 18) >= 12) assert(b[18] == 0);
    return reply;
  }
  void advance(uint32_t seconds) {
    while (seconds) { const uint32_t step = seconds < 60 ? seconds : 60; test_millis += step * 1000;
      reporter->loop(); seconds -= step;
    }
  }
  void configure(bool direct = true) {
    cmd("set mgmt.enabled on", false);
    cmd("set mgmt.password short", false);
    cmd("set mgmt.password management test password");
    if (direct) cmd("set mgmt.interval 5");
    cmd("set mgmt.enabled on");
    // Simulate a route becoming unavailable after enable so fallback-only
    // tests exercise the scoped 21-day safety report.
    if (!direct) cli.path_len = 0xff;
    const auto& file = fs.files["/management"];
    assert(std::string(file.begin(), file.end()).find("management test password") == std::string::npos);
  }
};
int main() {
  {
    Fixture f;
    assert(f.cmd("get mgmt").find("direct=5d") != std::string::npos);
    assert(f.cmd("get mgmt").find("flood=21d") != std::string::npos);
    f.advance(100 * DAY); assert(f.mesh.packets.empty());
    f.configure(); f.cmd("set mgmt.interval 91", false);
    f.advance(5 * DAY - 60); assert(f.mesh.packets.empty());
    // Changes to RTC in either direction have no effect on flood eligibility.
    f.mesh.rtc.time = 0; f.advance(60); assert(f.mesh.packets.size() == 1 && !f.mesh.packets[0].flood);
    f.mesh.rtc.time = 0xffffffff; f.reboot();
    f.advance(5 * DAY + 3600); assert(f.mesh.packets.size() == 2);
    for (const auto& p : f.mesh.packets) assert(!p.flood);
  }
  {
    Fixture f; f.configure(); f.advance(21 * DAY + 601);
    assert(f.mesh.packets.size() == 5 && !f.mesh.packets[0].flood && f.mesh.packets.back().flood);
    const uint32_t seq = read32(f.mesh.packets.back().payload + 20); f.reboot(); f.advance(600);
    assert(f.mesh.packets.size() == 5);
    f.cmd("set mgmt.enabled off"); f.cmd("set mgmt.enabled on"); f.advance(600);
    assert(f.mesh.packets.size() == 5 && read32(f.mesh.packets.back().payload + 20) == seq);
  }
  {
    Fixture f; f.configure(); f.cmd("set mgmt.flood off");
    f.advance(21 * DAY + 3600); assert(f.mesh.packets.size() == 4);
    for (const auto& p : f.mesh.packets) assert(!p.flood);
  }
  {
    Fixture f; f.configure(); f.cmd("set mgmt.direct off");
    f.advance(21 * DAY + 60); assert(f.mesh.packets.size() == 1);
    assert(f.mesh.packets[0].flood);
  }
  {
    Fixture f; f.configure(); f.cmd("set mgmt.direct 10");
    f.cmd("set mgmt.flood 30"); f.advance(30 * DAY + 60);
    assert(f.mesh.packets.size() == 3 && f.mesh.packets.back().flood);
    assert(!f.mesh.packets[0].flood && !f.mesh.packets[1].flood);
  }
  {
    Fixture f; f.configure(false); f.advance(21 * DAY - 60); f.fs.fail_write = true; f.advance(120);
    assert(f.mesh.packets.empty()); assert(f.cmd("get mgmt").find("FAULT") != std::string::npos);
    // Last hourly checkpoint was one hour before the failed reservation.
    f.fs.fail_write = false; f.reboot(); f.advance(3600); assert(f.mesh.packets.size() == 1);
  }
  {
    Fixture f; f.configure(false); f.fs.files["/management"][72] ^= 1; f.reboot(); f.advance(100 * DAY);
    assert(f.mesh.packets.empty()); assert(f.cmd("get mgmt").find("FAULT") != std::string::npos);
  }
  {
    Fixture f; f.configure(false); f.fs.fail_read_open = true; f.reboot(); f.advance(100 * DAY);
    assert(f.mesh.packets.empty());
  }
  {
    Fixture f;
    for (unsigned i = 0; i < 36; ++i) { ClientInfo c; c.id.pub_key[0] = i; f.acl.clients.push_back(c); }
    test_usb_status.supported = true; test_usb_status.watchdog_enabled = true;
    test_usb_status.host_connected = test_usb_status.reader_connected = true;
    test_usb_status.stalled = true; test_usb_status.retry_seconds = 7200;
    test_usb_status.inactive_seconds = 3600; test_usb_status.backoff_step = 1;
    test_usb_status.last_event.reasons = UsbLoggingWatchdogEvent::TX_STALLED;
    test_usb_status.last_event.action = UsbLoggingWatchdogEvent::REENUMERATE;
    test_usb_status.last_event.sequence = 17; test_usb_status.last_event.uptime_seconds = 300;
    test_usb_status.last_event.persisted = true;
    f.configure(false); f.advance(21 * DAY + 600); assert(f.mesh.packets.size() == 9);
    assert(usb_status_calls == 1);
    for (unsigned i = 0; i < 9; ++i) {
      const auto& p = f.mesh.packets[i]; assert(validPage(p.payload, p.payload_len));
      assert(p.payload[78] == i && p.payload[80] == 36 && p.flood);
      assert(!memcmp(p.payload, "MGR3", 4) && read16(p.payload + HEADER) == 61);
      assert(!(read16(p.payload + HEADER) & 1024)); // an open reader is not an active logger
      assert(read32(p.payload + HEADER + 3) == 7200);
      assert(read32(p.payload + HEADER + 7) == 3600);
      UsbLoggingWatchdogEvent event;
      assert(decodeUsbWatchdogEvent(p.payload + WATCHDOG_EVENT_OFFSET, event));
      assert(event.reasons == UsbLoggingWatchdogEvent::TX_STALLED && event.action == UsbLoggingWatchdogEvent::REENUMERATE);
      assert(event.sequence == 17 && event.uptime_seconds == 300 && event.persisted && event.epoch == 0);
      assert(floodSize(p.payload_len) <= 179);
    }
  }
  {
    Fixture f;
    for (unsigned i = 0; i < 7; ++i) { ClientInfo c; c.id.pub_key[0] = i; f.acl.clients.push_back(c); }
    f.configure(false); f.advance(21 * DAY); assert(f.mesh.packets.size() == 1);
    assert(!memcmp(f.mesh.packets[0].payload, "MGR3", 4));
    assert(read16(f.mesh.packets[0].payload + HEADER) == 0); // unsupported is explicit
    test_usb_status.supported = true; test_usb_status.retry_seconds = 999;
    test_usb_status.watchdog_auto = true; test_usb_status.auto_connected_seconds = 100;
    test_usb_status.host_connected = test_usb_status.reader_connected = test_usb_status.logger_active = true;
    test_usb_status.last_event.reasons = UsbLoggingWatchdogEvent::CLIENT_INACTIVE;
    test_usb_status.last_event.action = UsbLoggingWatchdogEvent::SOFT_RECOVERY;
    test_usb_status.last_event.sequence = 1; test_usb_status.last_event.epoch = 1700000001;
    f.board.voltage = 2900; f.board.temperature = 60; f.advance(60);
    assert(f.mesh.packets.size() == 2);
    assert(read16(f.mesh.packets[1].payload + HEADER) == 0); // frozen report snapshot
    assert(read32(f.mesh.packets[1].payload + HEADER + 11) == 0);
    assert(read32(f.mesh.packets[1].payload + WATCHDOG_EVENT_OFFSET + 9) == 0);
    assert(usb_status_calls == 1);
    // The low reading was not in the first snapshot and must survive into the next one.
    f.board.voltage = 3740; f.board.temperature = 24; f.advance(21 * DAY + 3600);
    assert(f.mesh.packets.size() == 4);
    assert(read16(f.mesh.packets.back().payload + 66) == 2900);
    assert(f.mesh.packets.back().payload[69] == temperature(60));
    assert(read16(f.mesh.packets.back().payload + HEADER) == 1561);
    assert(read32(f.mesh.packets.back().payload + HEADER + 11) == 100);
    assert(read32(f.mesh.packets.back().payload + WATCHDOG_EVENT_OFFSET + 9) == 1);
    assert(usb_status_calls == 2);
  }
  {
    Fixture f; f.configure(false); f.mesh.temp = true; f.advance(22 * DAY); assert(f.mesh.packets.empty());
    f.mesh.temp = false; f.mesh.budget = 0; f.advance(60); assert(f.mesh.packets.empty());
    f.mesh.budget = 1000; f.advance(60); assert(f.mesh.packets.size() == 1);
  }
  {
    Fixture f; f.configure(false); f.cmd("set mgmt.flood 90"); f.advance(89 * DAY); assert(f.mesh.packets.empty());
    f.advance(DAY); assert(f.mesh.packets.size() == 1);
  }
}
