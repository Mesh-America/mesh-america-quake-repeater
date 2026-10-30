#include <helpers/UDPBridgePrefs.h>
#include <cassert>
#include <string>
#include <initializer_list>
static uint32_t millis() { return 0x11223344; }
struct Callbacks {
  virtual ~Callbacks() = default;
CALLBACKS_HERE
};
struct Fake : Callbacks {
  mesh::bridge::udp::Prefs prefs;
  unsigned writes = 0, statuses = 0, stats = 0, sends = 0, resets = 0;
  uint8_t peer = 255;
  uint32_t nonce = 0;
  bool save = true, available = true;
  std::string page;
  const mesh::bridge::udp::Prefs* getUDPBridgePrefs() const override { return available ? &prefs : nullptr; }
  bool setUDPBridgePrefs(const mesh::bridge::udp::Prefs& value) override {
    ++writes; if (!save) return false; prefs = value; return true;
  }
  void formatUDPBridgeStatus(char* reply, size_t capacity) override {
    ++statuses; assert(capacity == 157); snprintf(reply, capacity, "%s", std::string(300, 'x').c_str());
  }
  void formatUDPBridgeStats(const char* value, char* reply, size_t capacity) override {
    ++stats; page = value; snprintf(reply, capacity, "stats");
  }
  bool sendUDPBridgeTest(uint8_t value, uint32_t id) override { ++sends; peer = value; nonce = id; return true; }
  bool resetUDPBridgeStats() override { ++resets; return true; }
};
struct CommonCLI {
  Callbacks* _callbacks;
  bool handleUDPBridgeCommand(uint32_t, const char*, char*);
};
HANDLER_HERE
int main() {
  Fake fake; CommonCLI cli{&fake};
  char reply[160];
  auto command = [&](const char* value, uint32_t remote = 0) {
    memset(reply, 'Z', sizeof(reply));
    const bool handled = cli.handleUDPBridgeCommand(remote, value, reply);
    assert(reply[157] == 'Z' && reply[158] == 'Z' && reply[159] == 'Z');
    if (handled) assert(memchr(reply, 0, 157));
    return handled;
  };
  assert(command("get udp.status", 1) && strlen(reply) == 156);
  for (const char* page : {"", "rx", "tx", "drops", "test"}) {
    assert(command((std::string("get udp.stats") + (*page ? " " : "") + page).c_str(), 1));
    assert(fake.page == page);
  }
  assert(command("get udp.enabled") && !strcmp(reply, "off"));
  assert(command("get udp.port") && !strcmp(reply, "4404"));
  for (char index = '1'; index <= '8'; ++index) {
    std::string key = "udp.peer."; key += index;
    assert(command(("get " + key).c_str()) && !strcmp(reply, "off"));
    const std::string value = "192.168.1." + std::to_string(index - '0') + ":4404";
    assert(command(("set " + key + " " + value).c_str(), 1) && strstr(reply, "saved"));
    assert(command(("get " + key).c_str()) && value == reply);
    assert(command(("set " + key + " off").c_str()));
  }
  assert(command("set udp.enabled on", 5) && fake.prefs.enabled == 1);
  assert(command("set udp.port 65535", 5) && fake.prefs.port == 65535);
  assert(command("set udp.peer.1 192.168.1.1:4404"));
  unsigned writes = fake.writes;
  assert(command("set udp.peer.2 192.168.1.1:4404") && strstr(reply, "duplicate") && fake.writes == writes);
  for (const char* value : {"get udp.status x", "get udp.enabled ", "get udp.port 1", "get udp.statsrx",
      "get udp.stats ", "get udp.stats xxx", "set udp.enabled ON", "set udp.enabled on ",
      "set udp.port 0", "set udp.port -1", "set udp.port 65536", "set udp.port 1 ",
      "get udp.peer.0", "get udp.peer.9", "get udp.peer.10", "get udp.peer.1 x",
      "set udp.peer.1 off ", "set udp.peer.1 127.0.0.1:4404", "set udp.peer.1 224.1.2.3:1",
      "udp", "udp test", "udp test 0", "udp test 9", "udp test 10", "udp test 1 ",
      "udp test 1 1234567", "udp test 1 123456789", "udp test 1 ABCDEFGH", "udp test 1 12345678 ",
      "udp resetstats ", "udp resetstats x"}) {
    assert(command(value) && !strncmp(reply, "Error:", 6));
    assert(fake.writes == writes && fake.sends == 0 && fake.resets == 0);
  }
  for (const char* value : {"udptest", "udpx test", "get repeat", "get espnow.status"}) assert(!command(value));
  for (const char* value : {"udp test 1", "udp test 8 A1B2C3D4", "udp resetstats"}) {
    assert(command(value, 1) && strstr(reply, "local connection"));
    assert(fake.sends == 0 && fake.resets == 0);
  }
  assert(command("udp test 8 a1b2C3d4") && fake.peer == 7 && fake.nonce == 0xA1B2C3D4);
  assert(command("udp test 1") && fake.peer == 0 && fake.nonce == millis());
  assert(command("udp resetstats") && fake.resets == 1);
  fake.save = false; writes = fake.writes;
  assert(command("set udp.port 1234") && strstr(reply, "not saved") && fake.writes == writes + 1);
  assert(fake.prefs.port == 65535);
  fake.available = false;
  assert(command("get udp.port") && strstr(reply, "unavailable"));
  Callbacks unsupported; cli._callbacks = &unsupported;
  assert(command("get udp.status") && strstr(reply, "unavailable"));
  assert(command("get udp.stats") && strstr(reply, "unavailable"));
  assert(command("udp test 1") && strstr(reply, "not queued"));
}
