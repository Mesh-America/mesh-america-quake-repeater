#include <array>
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <limits>
#include <string>
#include <vector>

#define OUT_PATH_UNKNOWN 0xff

struct ClientInfo {
  bool admin = true;
  bool isAdmin() const { return admin; }
};

struct SharedRoute {
  bool available = true;
  unsigned lookups = 0;
  bool getDataTxPath(const uint8_t*& path, uint8_t& length) {
    static const uint8_t direct[] = {0};
    ++lookups; path = direct; length = available ? 0 : OUT_PATH_UNKNOWN;
    return available;
  }
};

struct Fixture {
  SharedRoute _cli;
  bool telemetry_history_tx_enabled = true;
  uint8_t telemetry_history_tx_interval_days = 7;
  uint8_t telemetry_history_tx_pending = 7;
  bool telemetry_history_tx_manual = true;
  uint8_t telemetry_history_tx_external_channel = 2;
  uint8_t telemetry_history_tx_external_chunk = 3;
  uint64_t telemetry_history_next_tx_uptime = 10000000000ULL;
  uint64_t telemetry_history_tx_resume_uptime = 20000000000ULL;
  bool fail_save = false;
  unsigned saves = 0;
  std::array<uint64_t, 8> persisted = state();

  std::array<uint64_t, 8> state() const {
    return {{telemetry_history_tx_enabled, telemetry_history_tx_interval_days,
             telemetry_history_tx_pending, telemetry_history_tx_manual,
             telemetry_history_tx_external_channel, telemetry_history_tx_external_chunk,
             telemetry_history_next_tx_uptime, telemetry_history_tx_resume_uptime}};
  }
  bool saveTelemetryHistoryTxPrefs() {
    ++saves;
    if (fail_save) return false;
    persisted = state(); return true;
  }
  void handle(char* command, char* reply, ClientInfo* sender);
  std::string command(const std::string& suffix, ClientInfo* sender = nullptr) {
    const std::string text = "set telemetry.tx schedule " + suffix;
    std::vector<char> buffer(text.begin(), text.end()); buffer.push_back(0);
    char reply[160] = {};
    handle(buffer.data(), reply, sender);
    return reply;
  }
};

// Includes the complete actual schedule-command branch and trim helper.
#include "production_telemetry_tx.inc"

static void assertUnchanged(const Fixture& f, const std::array<uint64_t, 8>& before) {
  assert(f.state() == before && f.persisted == before && f.saves == 0);
}

int main() {
  for (const std::string value : {"1", "30", "30d", " 0005d ", " 5 "}) {
    Fixture f;
    const unsigned expected = value.find('3') != std::string::npos ? 30
        : value.find('5') != std::string::npos ? 5 : 1;
    assert(f.command(value) == "OK - telemetry.tx schedule=" + std::to_string(expected) + "d");
    assert(f.telemetry_history_tx_enabled && f.telemetry_history_tx_interval_days == expected);
    assert(f.saves == 1 && f.persisted == f.state());
    const auto state = f.state();
    for (size_t i = 2; i < state.size(); ++i) assert(state[i] == 0);
  }
  {
    Fixture f;
    assert(f.command("off") == "OK - telemetry.tx schedule=off");
    assert(!f.telemetry_history_tx_enabled && f.telemetry_history_tx_interval_days == 7);
    assert(f.saves == 1 && f.persisted == f.state());
  }
  std::vector<std::string> malformed = {
      "", " ", "0", "31", "-1", "-4294967291", "-18446744073709551611",
      "+5", "5dd", "5days", "5 d", "1x", "5.0", "offx", "\t5",
      "4294967301", "18446744073709551621", std::string(500, '9')};
  // strtoul accepts the sign and negates modulo unsigned-long width. This
  // reproduces the wrapped-small-value defect on both 32- and 64-bit hosts.
  malformed.push_back("-" + std::to_string(std::numeric_limits<unsigned long>::max() - 4));
  for (const auto& value : malformed) {
    Fixture f;
    const auto before = f.state();
    const auto reply = f.command(value);
    if (reply.rfind("Err -", 0) != 0) {
      fprintf(stderr, "malformed telemetry schedule accepted: '%s': %s\n", value.c_str(), reply.c_str());
      assert(false);
    }
    assertUnchanged(f, before);
  }
  for (const std::string value : {"off", "5", "30d"}) {
    Fixture f; ClientInfo unauthorized; unauthorized.admin = false;
    const auto before = f.state();
    assert(f.command(value, &unauthorized) == "Err - not permitted");
    assertUnchanged(f, before); assert(f._cli.lookups == 0);
  }
  {
    Fixture f; f._cli.available = false;
    const auto before = f.state();
    assert(f.command("5") == "Err - configure data.tx path first");
    assertUnchanged(f, before);
    assert(f.command("off") == "OK - telemetry.tx schedule=off");
  }
  for (const std::string value : {"off", "5", "30d"}) {
    Fixture f; f.fail_save = true;
    const auto before = f.state();
    assert(f.command(value) == "Err - unable to save telemetry.tx schedule");
    assert(f.state() == before && f.persisted == before && f.saves == 1);
  }
  puts("telemetry schedule command checks passed");
}
