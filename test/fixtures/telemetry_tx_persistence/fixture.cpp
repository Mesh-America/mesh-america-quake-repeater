#include <IdentityStore.h>
#include "FileRead.h"
#include "FilePresence.h"
#include "PersistentStoreFormat.h"
#if defined(NRF52_PLATFORM) || defined(STM32_PLATFORM)
#define ATOMIC_FILE_WRITER_IMPLEMENTATION
#include "AtomicFileWriter.h"
#else
#include "ContactFileTransaction.h"
#endif
#include <helpers/TelemetryHistory.h>
#include <helpers/ExternalVoltageHistory.h>
#include <helpers/NoiseFloorHistory.h>
#include <helpers/CLICommandUtils.h>
#include <array>
#include <cassert>
#include <cstdio>
#include <cstdlib>

#define MAX_PATH_SIZE 64
#define MAX_PACKET_PAYLOAD 184
#define PAYLOAD_TYPE_RAW_CUSTOM 15
#define OUT_PATH_UNKNOWN 0xff
#define OUT_PATH_FORCE_FLOOD 0xfe
#define MESH_DEBUG_PRINTLN(...) do {} while (0)
static uint32_t test_millis = 0;
static uint32_t millis() { return test_millis; }

#if defined(ESP32_PLATFORM)
static MemoryFS* metadata_fs = nullptr;
// Exercise production FilePresence's stat/error handling without a real mount.
extern "C" int stat(const char* path, struct stat*) noexcept {
  if (!metadata_fs || metadata_fs->fail_metadata) { errno = EIO; return -1; }
  assert(!strncmp(path, "/spiffs", 7));
  if (metadata_fs->exists(path + 7)) return 0;
  errno = ENOENT; return -1;
}
#endif

namespace mesh {
struct Packet {
  uint8_t payload[184] = {};
  size_t payload_len = 0;
  uint8_t path_len = 0, path[MAX_PATH_SIZE] = {};
  uint8_t payload_type = PAYLOAD_TYPE_RAW_CUSTOM;
  bool forwarded = false;
  uint8_t getPayloadType() const { return payload_type; }
  static bool isValidPathLen(uint8_t);
  static size_t writePath(uint8_t*, const uint8_t*, uint8_t);
  static uint8_t copyPath(uint8_t*, const uint8_t*, uint8_t);
};
class Mesh {
protected:
  static bool isTelemetryHistoryPayload(const Packet*);
};
struct Utils { static void toHex(char*, const uint8_t*, size_t); };
struct DataRouteState;
}
struct TransportKey {};
struct RegionEntry { const char* name; };
class RegionMap {
public:
  RegionEntry* findByNamePrefix(const char*) { return nullptr; }
};
namespace mesh {
// Region selection is a boundary here; route storage and command handling are real.
static bool usableScope(const DataRouteState&, RegionEntry*, TransportKey&) { return false; }
}
class CommonCLI {
public:
  mesh::DataRouteState* _data_route = nullptr;
  RegionMap* _region_map = nullptr;
  bool adoptLegacyDataTxPath(const uint8_t*, uint8_t);
  bool getDataTxPath(const uint8_t*&, uint8_t&) const;
  bool resolveDataTxScope(TransportKey&, char*, size_t, bool* ambiguous = nullptr) const {
    if (ambiguous) *ambiguous = false;
    return false;
  }
  bool handleDataTxCommand(char*, char*);
  std::string routeCommand(const char* text) {
    std::vector<char> command(text, text + strlen(text) + 1);
    char reply[160] = {};
    assert(handleDataTxCommand(command.data(), reply));
    return reply;
  }
};
struct ClientInfo { bool admin = true; bool isAdmin() const { return admin; } };
class MyMesh : public mesh::Mesh {
public:
  FILESYSTEM* _fs;
  CommonCLI _cli;
  struct Identity { uint8_t pub_key[32] = {}; } self_id;
  mesh::TelemetryHistory telemetry_history;
  mesh::ExternalVoltageHistory external_voltage_history;
  mesh::NoiseFloorHistory noise_floor_history;
  bool dual = false;
  bool isDualRadioActive() const { return dual; }
  bool telemetry_history_tx_prefs_healthy = false;
  bool telemetry_history_tx_enabled = false;
  uint8_t telemetry_history_tx_interval_days = 2;
  uint8_t telemetry_history_tx_types = 31;
  uint8_t telemetry_history_tx_pending = 0;
  bool telemetry_history_tx_manual = false;
  uint8_t telemetry_history_tx_external_channel = 0;
  uint8_t telemetry_history_tx_external_chunk = 0;
  uint64_t telemetry_history_next_tx_uptime = 0;
  uint64_t telemetry_history_tx_resume_uptime = 0;
  uint64_t telemetry_history_last_tx_uptime = UINT64_MAX;
  uint64_t uptime_millis = 0;
  uint32_t last_millis = 0;
  std::vector<mesh::Packet> packets;
  std::vector<uint64_t> packet_times;
  std::vector<std::string> attempts;
  std::string reject_magic;
  unsigned rejected_sends = 0;
  explicit MyMesh(FILESYSTEM& fs) : _fs(&fs) {}
  void loadTelemetryHistoryTxPrefs();
  bool saveTelemetryHistoryTxPrefs();
  uint8_t availableTelemetryHistoryTxTypes() const;
  void finishTelemetryHistoryTxBatch(uint64_t);
  bool handleTelemetryHistoryTxTypesCommand(char*, char*, bool);
  void serviceTelemetryHistoryTx();
  bool sendTelemetryHistorySnapshot(mesh::TelemetryHistory::Series);
  bool sendExternalVoltageHistorySnapshot(uint8_t, uint8_t);
  bool sendNoiseFloorHistorySnapshot(uint8_t);
  void formatTelemetryHistoryTxStatus(char*, size_t) const;
  void recordTelemetryHistoryTx(const mesh::Packet*);
  void handle(char*, char*, ClientInfo*);
  // Radio queue boundary. Payload formatting and producer scheduling are real.
  mesh::Packet* createRawData(const uint8_t* data, size_t size) {
    assert(size <= 184);
    auto* packet = new mesh::Packet;
    memcpy(packet->payload, data, size); packet->payload_len = size;
    return packet;
  }
  bool sendDirect(mesh::Packet* packet, const uint8_t* path, uint8_t length) {
    const std::string magic(reinterpret_cast<char*>(packet->payload), 4);
    attempts.push_back(magic);
    if (magic == reject_magic && rejected_sends != 0) {
      --rejected_sends; delete packet; return false;
    }
    packet->path_len = mesh::Packet::copyPath(packet->path, path, length);
    packets.push_back(*packet);
    packet_times.push_back(uptime_millis + uint32_t(millis() - last_millis));
    delete packet; return true;
  }
  std::array<uint64_t, 9> state() const {
    return {{telemetry_history_tx_enabled, telemetry_history_tx_interval_days,
             telemetry_history_tx_pending, telemetry_history_tx_manual,
             telemetry_history_tx_external_channel, telemetry_history_tx_external_chunk,
             telemetry_history_next_tx_uptime, telemetry_history_tx_resume_uptime,
             telemetry_history_tx_types}};
  }
  std::string command(const char* text, ClientInfo* sender = nullptr) {
    std::vector<char> input(text, text + strlen(text) + 1);
    char reply[160] = {};
    handle(input.data(), reply, sender); return reply;
  }
};
#include "production.inc"

static const char target[] = "/telemetry_tx";
static const char temp[] = "/telemetry_tx.tmp";
static const char backup[] = "/telemetry_tx.bak";
static std::vector<uint8_t> current(bool enabled = true, uint8_t days = 7,
                                    uint8_t types = 31) {
  return {'T', 'H', 'T', '4', uint8_t(enabled), days, types};
}
static std::vector<uint8_t> previous(bool enabled = true, uint8_t days = 7) {
  return {'T', 'H', 'T', '3', uint8_t(enabled), days};
}
static std::vector<uint8_t> legacy(bool enabled = true, uint8_t length = 1,
                                   uint8_t days = 7) {
  std::vector<uint8_t> image(7 + MAX_PATH_SIZE, 0);
  memcpy(image.data(), "THT2", 4);
  image[4] = enabled; image[5] = length; image[6] = days;
  for (size_t i = 0; i < MAX_PATH_SIZE; ++i) image[7 + i] = uint8_t(i + 0x12);
  return image;
}
struct Fixture {
  MemoryFS fs;
  mesh::DataRouteState route;
  MyMesh node;
  Fixture() : node(fs) {
#if defined(ESP32_PLATFORM)
    metadata_fs = &fs;
#endif
    route.fs = &fs; node._cli._data_route = &route;
  }
  void boot() {
    route = mesh::DataRouteState(); route.fs = &fs;
    route.healthy = mesh::dataRouteLoad(route);
    node.loadTelemetryHistoryTxPrefs();
  }
  void seed(const std::vector<uint8_t>& image = current()) {
    fs.files[target] = image; boot();
  }
  void history() {
    for (uint32_t i = 0; i < mesh::TelemetryHistory::BINARY_MAX_SAMPLES; ++i) {
      node.telemetry_history.record(1000000 + i * 1800, 22, true, 3750, 0, 0, false);
    }
  }
  void noiseHistory(uint16_t count = 300, bool missing = false) {
    const uint32_t start = 999900;
    node.noise_floor_history.advance(start);
    for (uint32_t index = 0; index < count; ++index) {
      for (uint8_t profile = 0; profile < 2; ++profile) {
        for (uint8_t slot = 0; slot < 3; ++slot) {
          if (missing) continue;
          assert(node.noise_floor_history.observe(profile,
              start + index * 900 + slot * 300, profile ? -66.0f : -119.0f,
              index * 3 + slot));
        }
      }
      node.noise_floor_history.advance(start + (index + 1) * 900);
    }
    assert(node.noise_floor_history.sampleCount(0) == count);
  }
  void expectFault() {
    assert(!node.telemetry_history_tx_prefs_healthy);
    const auto before = node.state();
    const auto writes = fs.writes;
    node.serviceTelemetryHistoryTx();
    assert(node.packets.empty() && node.state() == before);
    assert(node.command("send telemetry.tx now") == "Err - telemetry.tx prefs unavailable");
    assert(node.state() == before && fs.writes == writes);
    for (const char* key : {"temp", "volt", "volt.i2c", "noise", "noise2", "types"}) {
      const std::string prefix = std::string("telemetry.tx.") + key;
      assert(node.command(("get " + prefix).c_str()) == "Err - telemetry.tx prefs unavailable");
      assert(node.command(("set " + prefix + " off").c_str()) == "Err - telemetry.tx prefs unavailable");
      assert(node.state() == before && fs.writes == writes);
    }
    char reply[160]; node.formatTelemetryHistoryTxStatus(reply, sizeof(reply));
    assert(strstr(reply, " fault=prefs"));
    ClientInfo unauthorized; unauthorized.admin = false;
    assert(node.command("send telemetry.tx now", &unauthorized) == "Err - not permitted");
    assert(!node.saveTelemetryHistoryTxPrefs() && fs.writes == writes);
  }
};

static void checkFreshAndValid() {
  Fixture f; f.boot();
  assert(f.node.telemetry_history_tx_prefs_healthy);
  assert(!f.node.telemetry_history_tx_enabled && f.node.telemetry_history_tx_interval_days == 2);
  assert(f.node.telemetry_history_tx_types == 31);
  assert(f.fs.files.empty());
  for (const bool enabled : {false, true}) {
    for (const uint8_t days : {uint8_t(1), uint8_t(2), uint8_t(30)}) {
      f.seed(current(enabled, days));
      assert(f.node.telemetry_history_tx_prefs_healthy);
      assert(f.node.telemetry_history_tx_enabled == enabled);
      assert(f.node.telemetry_history_tx_interval_days == days);
      assert(f.node.telemetry_history_tx_types == 31);
      assert(f.node.saveTelemetryHistoryTxPrefs() && f.fs.files.at(target) == current(enabled, days));
      assert(!f.fs.exists(temp) && !f.fs.exists(backup));
      char reply[160]; f.node.formatTelemetryHistoryTxStatus(reply, sizeof(reply));
      assert(!strstr(reply, "fault="));
    }
  }
  f.node._fs = nullptr; f.node.loadTelemetryHistoryTxPrefs(); f.expectFault();
}

static void checkLoadFailures() {
  for (size_t length = 0; length <= 80; ++length) {
    Fixture f; f.fs.files[target] = std::vector<uint8_t>(length, 0); f.boot();
    f.expectFault(); assert(f.fs.files.at(target) == std::vector<uint8_t>(length, 0));
  }
  for (const auto& image : {current(), previous(), legacy()}) {
    for (size_t limit = 0; limit < image.size(); ++limit) {
      Fixture f; f.fs.files[target] = image; f.fs.read_limit[target] = limit;
      f.boot(); f.expectFault(); assert(f.fs.files.at(target) == image);
      f.fs.clearFaults(); f.boot(); assert(f.node.telemetry_history_tx_prefs_healthy);
    }
    Fixture f; f.fs.files[target] = image; f.fs.fail_read_open.insert(target);
    f.boot(); f.expectFault(); assert(f.fs.files.at(target) == image);
  }
  for (unsigned value = 0; value <= 255; ++value) {
    for (const bool old : {false, true}) {
      for (const unsigned offset : {4U, old ? 6U : 5U}) {
        Fixture f; auto image = old ? legacy() : current(); image[offset] = uint8_t(value);
        f.fs.files[target] = image; f.boot();
        const bool valid = offset == 4 ? value <= 1 : value >= 1 && value <= 30;
        assert(f.node.telemetry_history_tx_prefs_healthy == valid);
        if (!valid) f.expectFault();
      }
    }
  }
#if !defined(RP2040_PLATFORM)
  Fixture metadata;
  metadata.fs.files[target] = current(); metadata.fs.fail_metadata = true;
  metadata.boot(); metadata.expectFault();
  assert(metadata.fs.files.at(target) == current());
#endif
}

static void checkLegacyMigration() {
  for (const bool enabled : {false, true}) {
    for (const uint8_t days : {uint8_t(1), uint8_t(30)}) {
      Fixture f; const auto image = previous(enabled, days); f.seed(image);
      assert(f.node.telemetry_history_tx_prefs_healthy);
      assert(f.node.telemetry_history_tx_enabled == enabled);
      assert(f.node.telemetry_history_tx_interval_days == days);
      assert(f.node.telemetry_history_tx_types == 31);
      assert(f.fs.files.at(target) == image); // old files are not rewritten on boot
      assert(f.node.saveTelemetryHistoryTxPrefs());
      assert(f.fs.files.at(target) == current(enabled, days));
    }
  }
  for (const uint8_t length : {uint8_t(0), uint8_t(1), uint8_t(0x42), uint8_t(0x82)}) {
    Fixture f; const auto image = legacy(true, length); f.seed(image);
    assert(f.node.telemetry_history_tx_prefs_healthy && f.node.telemetry_history_tx_enabled);
    assert(f.node.telemetry_history_tx_types == 31);
    assert(f.route.persisted && f.route.path_len == length);
    const size_t bytes = (length & 63) * ((length >> 6) + 1);
    assert(!memcmp(f.route.path, image.data() + 7, bytes));
    assert(f.fs.files.at(target) == image); // loading never rewrites the legacy file
    f.boot(); assert(f.node.telemetry_history_tx_prefs_healthy && f.route.path_len == length);
    assert(f.node.saveTelemetryHistoryTxPrefs());
    assert(f.fs.files.at(target) == current());
  }
  for (const uint8_t length : {uint8_t(0), uint8_t(0x42), uint8_t(OUT_PATH_UNKNOWN)}) {
    Fixture f; f.route.path_len = length;
    memset(f.route.path, 0xab, sizeof(f.route.path));
    assert(mesh::dataRouteSave(f.route));
    const auto saved_route = f.fs.files.at("/data_tx");
    f.fs.files[target] = legacy(); const auto writes = f.fs.writes;
    f.boot(); assert(f.node.telemetry_history_tx_prefs_healthy && f.route.path_len == length);
    assert(f.fs.files.at("/data_tx") == saved_route && f.fs.writes == writes);
  }
  Fixture disabled; disabled.seed(legacy(false, OUT_PATH_UNKNOWN));
  assert(disabled.node.telemetry_history_tx_prefs_healthy && !disabled.route.persisted);
  for (unsigned length = 0; length <= 255; ++length) {
    Fixture f; f.seed(legacy(true, uint8_t(length)));
    const bool valid = length != OUT_PATH_UNKNOWN && length != OUT_PATH_FORCE_FLOOD
        && mesh::Packet::isValidPathLen(uint8_t(length));
    assert(f.node.telemetry_history_tx_prefs_healthy == valid);
    if (!valid) f.expectFault();
  }
  // The actual adoption helper must fail before applying enabled legacy state.
  for (const int failure : {0, 1, 2}) {
    Fixture f; f.fs.files[target] = legacy();
    if (failure == 0) f.fs.fail_write_open.insert("/data_tx.tmp");
    if (failure == 1) f.fs.write_limit["/data_tx.tmp"] = 107;
    if (failure == 2) f.fs.fail_rename.insert({"/data_tx.tmp", "/data_tx"});
    f.boot(); f.history(); f.expectFault();
    assert(!f.node.telemetry_history_tx_enabled && !f.route.persisted);
    assert(f.fs.files.at(target) == legacy() && !f.fs.exists("/data_tx"));
    f.fs.clearFaults(); f.boot();
    assert(f.node.telemetry_history_tx_prefs_healthy && f.route.persisted && f.route.path_len == 1);
    assert(f.fs.files.at(target) == legacy());
  }
  Fixture bad_route; bad_route.fs.files["/data_tx"] = {'b', 'a', 'd'};
  bad_route.seed(legacy()); bad_route.expectFault();
  assert(bad_route.fs.files.at(target) == legacy());
}

static void verifyRollback(Fixture& f, const std::vector<uint8_t>& prior,
                           const std::array<uint64_t, 9>& state) {
  assert(f.node.state() == state && f.node.telemetry_history_tx_prefs_healthy);
  assert(f.fs.files.at(target) == prior);
  assert(!f.fs.exists(temp));
  f.fs.clearFaults(); f.boot();
  assert(f.node.telemetry_history_tx_prefs_healthy && f.node.telemetry_history_tx_enabled);
  assert(f.node.telemetry_history_tx_interval_days == 7);
  assert(f.node.command("set telemetry.tx schedule off") == "OK - telemetry.tx schedule=off");
  assert(f.fs.files.at(target) == current(false));
  f.boot(); assert(f.node.telemetry_history_tx_prefs_healthy && !f.node.telemetry_history_tx_enabled);
}

static void checkWriteAndValidationFailures() {
  for (const auto& prior : {current(), previous(), legacy()}) {
    for (size_t limit = 0; limit < current().size(); ++limit) {
      Fixture f; f.seed(prior); const auto before = f.node.state();
      f.fs.write_limit[temp] = limit;
      assert(f.node.command("set telemetry.tx schedule off") == "Err - unable to save telemetry.tx schedule");
      verifyRollback(f, prior, before);
    }
    for (const int failure : {0, 1}) {
      Fixture f; f.seed(prior); const auto before = f.node.state();
      if (failure == 0) f.fs.fail_write_open.insert(temp);
      else f.fs.fail_read_open.insert(temp);
      assert(f.node.command("set telemetry.tx schedule off") == "Err - unable to save telemetry.tx schedule");
      verifyRollback(f, prior, before);
    }
    for (size_t limit = 0; limit < current().size(); ++limit) {
      Fixture f; f.seed(prior); const auto before = f.node.state();
      f.fs.read_limit[temp] = limit;
      assert(f.node.command("set telemetry.tx schedule off") == "Err - unable to save telemetry.tx schedule");
      verifyRollback(f, prior, before);
    }
    Fixture f; f.seed(prior); const auto before = f.node.state();
    f.fs.fail_rename.insert({temp, target});
    assert(f.node.command("set telemetry.tx schedule off") == "Err - unable to save telemetry.tx schedule");
    verifyRollback(f, prior, before);
  }
  for (const int failure : {0, 1}) {
    Fixture f; f.seed();
    if (failure == 0) f.fs.fail_read_open.insert(target);
    else f.fs.read_limit[target] = 5;
    const auto writes = f.fs.writes;
    assert(f.node.command("set telemetry.tx schedule off") == "Err - unable to save telemetry.tx schedule");
    f.expectFault(); assert(f.fs.writes == writes && f.fs.files.at(target) == current());
  }
  // A failed fresh-install transaction is retryable only when still absent.
  Fixture fresh; fresh.boot(); fresh.fs.write_limit[temp] = 5;
  assert(fresh.node.command("set telemetry.tx schedule 5d") == "Err - unable to save telemetry.tx schedule");
  assert(fresh.node.telemetry_history_tx_prefs_healthy && !fresh.fs.exists(target));
  fresh.fs.clearFaults();
  assert(fresh.node.command("set telemetry.tx schedule 5d") == "OK - telemetry.tx schedule=5d");
  assert(fresh.fs.files.at(target) == current(true, 5));
}

static void checkRecoveryAndRenameFailures() {
#if defined(ESP32_PLATFORM) || defined(RP2040_PLATFORM)
  Fixture recovered; recovered.fs.files[backup] = current();
  recovered.boot(); assert(recovered.node.telemetry_history_tx_prefs_healthy);
  assert(recovered.fs.files.at(target) == current() && !recovered.fs.exists(backup));
  Fixture failed; failed.fs.files[backup] = current();
  failed.fs.fail_rename.insert({backup, target});
  failed.boot(); failed.expectFault();
  assert(!failed.fs.exists(target) && failed.fs.files.at(backup) == current());
  failed.fs.clearFaults(); failed.boot(); assert(failed.node.telemetry_history_tx_prefs_healthy);
  Fixture corrupt; corrupt.fs.files[target] = {'b', 'a', 'd'};
  corrupt.fs.files[backup] = current(); corrupt.boot(); corrupt.expectFault();
  assert(corrupt.fs.files.at(target) == std::vector<uint8_t>({'b', 'a', 'd'}));
  assert(corrupt.fs.files.at(backup) == current());
  for (const int failure : {0, 1, 2}) {
    Fixture f; f.seed(); const auto before = f.node.state();
    if (failure == 0) { f.fs.files[temp] = {1}; f.fs.fail_remove.insert(temp); }
    if (failure == 1) { f.fs.files[backup] = {1}; f.fs.fail_remove.insert(backup); }
    if (failure == 2) f.fs.fail_rename.insert({target, backup});
    assert(f.node.command("set telemetry.tx schedule off") == "Err - unable to save telemetry.tx schedule");
    assert(f.node.telemetry_history_tx_prefs_healthy && f.node.state() == before);
    assert(f.fs.files.at(target) == current());
    f.fs.clearFaults();
    assert(f.node.command("set telemetry.tx schedule off") == "OK - telemetry.tx schedule=off");
  }
  Fixture gap; gap.seed(); gap.history(); const auto before = gap.node.state();
  gap.fs.fail_rename.insert({temp, target}); gap.fs.fail_rename.insert({backup, target});
  assert(gap.node.command("set telemetry.tx schedule off") == "Err - unable to save telemetry.tx schedule");
  assert(gap.node.state() == before && gap.fs.files.at(backup) == current());
  assert(!gap.fs.exists(target)); gap.expectFault();
  gap.boot(); gap.expectFault(); // failed recovery remains fail-closed on reboot
  gap.fs.clearFaults(); gap.boot();
  assert(gap.node.telemetry_history_tx_prefs_healthy && gap.node.telemetry_history_tx_enabled);
  assert(gap.fs.files.at(target) == current());
#endif
  // Stale uncommitted candidates are never mistaken for a fresh durable image.
  Fixture stale; stale.fs.files[temp] = current(); stale.boot();
  assert(stale.node.telemetry_history_tx_prefs_healthy && !stale.node.telemetry_history_tx_enabled);
  assert(stale.node.command("set telemetry.tx schedule 5d") == "OK - telemetry.tx schedule=5d");
  assert(stale.fs.files.at(target) == current(true, 5) && !stale.fs.exists(temp));
}

static void checkAmbiguousPublicationAndServiceGate() {
  for (const int failure : {0, 1}) {
    Fixture f; f.seed(); f.history();
    f.node.telemetry_history_tx_pending = TELEMETRY_HISTORY_TX_TEMPERATURE | TELEMETRY_HISTORY_TX_VOLTAGE;
    f.node.telemetry_history_tx_manual = true;
    f.node.telemetry_history_tx_resume_uptime = 10000000;
    const auto before = f.node.state();
    if (failure == 0) f.fs.fail_final_read = true;
    else f.fs.corrupt_publish = true;
    assert(f.node.command("set telemetry.tx schedule off") == "Err - unable to save telemetry.tx schedule");
    assert(f.node.state() == before); f.expectFault();
    const auto published = f.fs.files.at(target);
    f.boot(); f.expectFault();
    assert(f.fs.files.at(target) == published);
    f.fs.clearFaults(); f.boot();
    if (failure == 0) {
      assert(f.node.telemetry_history_tx_prefs_healthy && !f.node.telemetry_history_tx_enabled);
      assert(f.fs.files.at(target) == current(false));
    } else f.expectFault();
  }
  for (int limit = 0; limit < int(current().size()); ++limit) {
    Fixture f; f.seed(); f.history();
    f.fs.final_read_limit = limit;
    assert(f.node.command("set telemetry.tx schedule off") == "Err - unable to save telemetry.tx schedule");
    assert(f.fs.files.at(target) == current(false));
    f.expectFault(); f.boot(); f.expectFault();
    assert(f.fs.files.at(target) == current(false));
    f.fs.clearFaults(); f.boot();
    assert(f.node.telemetry_history_tx_prefs_healthy && !f.node.telemetry_history_tx_enabled);
  }
  Fixture healthy; healthy.seed(); healthy.history();
  healthy.node.serviceTelemetryHistoryTx();
  assert(healthy.node.packets.size() == 1);
  assert(healthy.node.packets[0].payload_len == 184);
  assert(!memcmp(healthy.node.packets[0].payload, "TTB1", 4));
  test_millis += 89999; healthy.node.serviceTelemetryHistoryTx();
  assert(healthy.node.packets.size() == 1);
  test_millis += 1; healthy.node.serviceTelemetryHistoryTx(); test_millis = 0;
  assert(healthy.node.packets.size() == 2 && !memcmp(healthy.node.packets[1].payload, "TVB1", 4));
  assert(healthy.node.command("send telemetry.tx now").find("OK - telemetry.tx queued") == 0);
}

static void checkRoutePublicationAuthority() {
  for (const bool migration : {false, true}) {
    Fixture f; f.boot();
    if (!migration) assert(f.node._cli.routeCommand("set data.tx path 12") == "OK");
    f.fs.publication_path = "/data_tx";
#if defined(NRF52_PLATFORM) || defined(STM32_PLATFORM)
    // Atomic publication succeeds, but its mandatory public readback fails.
    f.fs.fail_final_read = true;
#else
    // The old image is backed up but neither publication nor rollback happens.
    if (migration) assert(mesh::dataRouteSave(f.route));
    f.fs.fail_rename.insert({"/data_tx.tmp", "/data_tx"});
    f.fs.fail_rename.insert({"/data_tx.bak", "/data_tx"});
#endif
    if (migration) {
      const uint8_t path = 0x34;
      // Force the legacy adoption path without discarding the existing disk image.
      f.route.persisted = false;
      assert(!f.node._cli.adoptLegacyDataTxPath(&path, 1));
    } else {
      assert(f.node._cli.routeCommand("set data.tx path 34") == "Err - unable to save data.tx");
    }
    // A reported failure cannot authorize old RAM when disk authority is unknown.
    assert(!f.route.healthy);
    const uint8_t* path = nullptr; uint8_t length = 0;
    assert(!f.node._cli.getDataTxPath(path, length));
    assert(f.node._cli.routeCommand("get data.tx") == "Err - data.tx storage fault");
    const auto writes = f.fs.writes;
    assert(f.node._cli.routeCommand("set data.tx path 56") == "Err - data.tx storage fault");
    assert(f.fs.writes == writes);
    f.fs.clearFaults(); f.boot();
    assert(f.route.healthy);
#if defined(NRF52_PLATFORM) || defined(STM32_PLATFORM)
    assert(f.route.path_len == 1 && f.route.path[0] == 0x34);
#else
    assert(f.route.path_len == (migration ? 0 : 1));
    if (!migration) assert(f.route.path[0] == 0x12);
#endif
  }
}

static void checkRouteReadbackAndRetry() {
  for (const bool region : {false, true}) {
    const char* command = region ? "set data.tx region none" : "set data.tx path 34";
    for (const int failure : {0, 1, 2, 3, 4, 5}) {
      Fixture f; f.boot();
      assert(f.node._cli.routeCommand("set data.tx path 12") == "OK");
      const auto previous = f.fs.files.at("/data_tx");
      f.fs.publication_path = "/data_tx";
      if (failure == 0) f.fs.fail_write_open.insert("/data_tx.tmp");
      if (failure == 1) f.fs.write_limit["/data_tx.tmp"] = 107;
      if (failure == 2) f.fs.fail_read_open.insert("/data_tx.tmp");
      if (failure == 3) f.fs.fail_final_read = true;
      if (failure == 4) f.fs.final_read_limit = 107;
      if (failure == 5) f.fs.corrupt_publish = true;
      assert(f.node._cli.routeCommand(command) == "Err - unable to save data.tx");
      assert(f.route.healthy == (failure < 3));
      assert(f.route.path_len == 1 && f.route.path[0] == 0x12);
      assert(f.route.region_mode == mesh::DATA_REGION_AUTO);
      if (failure < 3) {
        assert(f.fs.files.at("/data_tx") == previous);
        f.fs.clearFaults();
        assert(f.node._cli.routeCommand(command) == "OK");
        f.boot(); assert(f.route.healthy);
      } else {
        const auto writes = f.fs.writes;
        const uint8_t* path = nullptr; uint8_t length = 0;
        assert(!f.node._cli.getDataTxPath(path, length));
        assert(f.node._cli.routeCommand(command) == "Err - data.tx storage fault");
        assert(f.fs.writes == writes);
        f.fs.clearFaults(); f.boot();
        assert(f.route.healthy == (failure != 5));
      }
    }
  }
  for (const bool existing : {false, true}) {
    for (const bool no_op : {false, true}) {
      Fixture f; f.boot();
      if (existing) assert(f.node._cli.routeCommand("set data.tx path 12") == "OK");
      f.fs.publication_path = "/data_tx";
      f.fs.no_op_publish = no_op;
      f.fs.late_publish_error = !no_op;
      const auto reply = f.node._cli.routeCommand("set data.tx path 34");
      if (no_op) {
        assert(reply == "Err - unable to save data.tx");
#if defined(NRF52_PLATFORM) || defined(STM32_PLATFORM)
        assert(!f.route.healthy); // Atomic writer cannot prove old authority.
#else
        assert(f.route.healthy); // Observed unchanged move + successful rollback.
#endif
      } else {
        assert(reply == "OK" && f.route.healthy && f.route.path[0] == 0x34);
      }
      f.fs.clearFaults(); f.boot(); assert(f.route.healthy);
      if (!no_op) assert(f.route.path_len == 1 && f.route.path[0] == 0x34);
      else assert(f.route.path_len == (existing ? 1 : 0));
    }
  }
#if !defined(RP2040_PLATFORM)
  for (const bool existing : {false, true}) {
    Fixture f; f.boot();
    if (existing) assert(f.node._cli.routeCommand("set data.tx path 12") == "OK");
    const auto files = f.fs.files;
    f.fs.fail_metadata = true; f.boot();
    assert(!f.route.healthy && f.fs.files == files);
    const auto writes = f.fs.writes;
    assert(f.node._cli.routeCommand("set data.tx path 34") == "Err - data.tx storage fault");
    assert(f.fs.writes == writes);
    f.fs.clearFaults(); f.boot(); assert(f.route.healthy);
  }
#endif
}

static uint32_t read32(const uint8_t* bytes) {
  return uint32_t(bytes[0]) | uint32_t(bytes[1]) << 8
      | uint32_t(bytes[2]) << 16 | uint32_t(bytes[3]) << 24;
}

static uint8_t packedNoiseCode(const mesh::Packet& packet, unsigned index) {
  uint8_t value = 0;
  for (unsigned bit = 0; bit < 5; ++bit) {
    const unsigned at = index * 5 + bit;
    value = uint8_t((value << 1)
        | ((packet.payload[19 + at / 8] >> (7 - at % 8)) & 1));
  }
  return value;
}

static void verifyNoisePacket(const MyMesh& node, const mesh::Packet& packet,
                             unsigned profile, bool missing) {
  assert(packet.payload_len == 19 + (255 * 5 + 7) / 8);
  assert(!memcmp(packet.payload, profile ? "N2B1" : "N1B1", 4));
  assert(!memcmp(packet.payload + 4, node.self_id.pub_key, 8));
  assert(read32(packet.payload + 12) == 999900 + (300 - 255) * 900);
  assert(packet.payload[16] == 15 && packet.payload[17] == 0);
  assert(packet.payload[18] == 255);
  for (unsigned i = 0; i < 255; ++i) {
    assert(packedNoiseCode(packet, i) == (missing ? 31 : profile ? 28 : 1));
  }
  assert((packet.payload[packet.payload_len - 1] & 0x1f) == 0);
}

static void serviceDue(MyMesh& node) {
  node.uptime_millis = node.telemetry_history_next_tx_uptime;
  node.last_millis = test_millis;
  node.serviceTelemetryHistoryTx();
}

static void finishPending(MyMesh& node) {
  unsigned calls = 0;
  while (node.telemetry_history_tx_pending != 0) {
    assert(++calls < 20);
    serviceDue(node);
  }
}

static void checkNoiseHistoryTransmission() {
  for (const bool manual : {false, true}) {
    for (const bool dual : {false, true}) {
      for (const bool missing : {false, true}) {
        Fixture f; f.seed(current(!manual, 2)); f.history(); f.noiseHistory(300, missing);
        f.node.dual = dual;
        for (unsigned i = 0; i < 8; ++i) f.node.self_id.pub_key[i] = uint8_t(0x80 + i);
        if (manual) {
          const auto reply = f.node.command("send telemetry.tx now");
          assert(reply.find(dual ? "noise=1/1" : "noise=1/0") != std::string::npos);
          assert(f.node.telemetry_history_tx_pending == (dual ? 27 : 11));
          assert(f.node.packets.empty());
        } else {
          f.node.serviceTelemetryHistoryTx();
          assert(f.node.packets.size() == 1);
        }
        finishPending(f.node);
        assert(f.node.packets.size() == (dual ? 4U : 3U));
        assert(f.node.attempts.size() == f.node.packets.size());
        assert(!memcmp(f.node.packets[0].payload, "TTB1", 4));
        assert(!memcmp(f.node.packets[1].payload, "TVB1", 4));
        verifyNoisePacket(f.node, f.node.packets[2], 0, missing);
        if (dual) verifyNoisePacket(f.node, f.node.packets[3], 1, missing);
        assert(!f.node.telemetry_history_tx_manual);
        assert(bool(f.node.telemetry_history_next_tx_uptime) == !manual);
      }
    }
  }
}

static void checkNoiseHistoryRetries() {
  for (const bool second : {false, true}) {
    Fixture f; f.seed(current(false, 2)); f.history(); f.noiseHistory();
    f.node.dual = true;
    f.node.reject_magic = second ? "N2B1" : "N1B1";
    f.node.rejected_sends = 1;
    assert(f.node.command("send telemetry.tx now").find("noise=1/1") != std::string::npos);
    while (f.node.rejected_sends != 0) serviceDue(f.node);
    const auto attempts = f.node.attempts;
    const uint64_t retry = f.node.telemetry_history_next_tx_uptime;
    assert(retry == f.node.uptime_millis + TELEMETRY_HISTORY_TX_RETRY_MILLIS);
    assert(f.node.telemetry_history_tx_pending == (second ? 16 : 24));
    f.node.uptime_millis = retry - 1;
    f.node.serviceTelemetryHistoryTx();
    assert(f.node.attempts == attempts); // failed packet waits for its retry deadline
    finishPending(f.node);
    const std::vector<std::string> expected = second
        ? std::vector<std::string>{"TTB1", "TVB1", "N1B1", "N2B1", "N2B1"}
        : std::vector<std::string>{"TTB1", "TVB1", "N1B1", "N1B1", "N2B1"};
    assert(f.node.attempts == expected);
    assert(f.node.packets.size() == 4); // successful earlier packets were never resent
    assert(!f.node.telemetry_history_next_tx_uptime && !f.node.telemetry_history_tx_manual);
  }
  Fixture disabled; disabled.seed(current(false, 2));
  disabled.history(); disabled.noiseHistory(); disabled.node.dual = true;
  disabled.node.reject_magic = "N2B1"; disabled.node.rejected_sends = 1;
  assert(disabled.node.command("send telemetry.tx now").find("noise=1/1") != std::string::npos);
  while (disabled.node.rejected_sends != 0) serviceDue(disabled.node);
  assert(disabled.node.telemetry_history_tx_pending == TELEMETRY_HISTORY_TX_NOISE2);
  const auto attempts = disabled.node.attempts;
  disabled.node.dual = false;
  serviceDue(disabled.node);
  assert(!disabled.node.telemetry_history_tx_pending && disabled.node.attempts == attempts);
  assert(!disabled.node.telemetry_history_next_tx_uptime && !disabled.node.telemetry_history_tx_manual);
  assert(disabled.node.packets.size() == 3);
}

static std::string txStatus(const MyMesh& node) {
  char reply[160];
  node.formatTelemetryHistoryTxStatus(reply, sizeof(reply));
  return reply;
}

static void expectLastTx(const MyMesh& node, const char* age) {
  assert(txStatus(node).find(std::string(" last=") + age + " ") != std::string::npos);
}

static std::vector<mesh::Packet> historyPackets(Fixture& f) {
  f.history(); f.noiseHistory();
  const uint8_t channel = 7;
  assert(f.node.external_voltage_history.configure(&channel, 1));
  const mesh::ExternalVoltageHistory::Reading reading = {channel, 12.5f, true};
  f.node.external_voltage_history.record(1000000, &reading, 1);
  assert(f.node.sendTelemetryHistorySnapshot(mesh::TelemetryHistory::SERIES_TEMPERATURE));
  assert(f.node.sendTelemetryHistorySnapshot(mesh::TelemetryHistory::SERIES_VOLTAGE));
  assert(f.node.sendExternalVoltageHistorySnapshot(0, 0));
  assert(f.node.sendNoiseFloorHistorySnapshot(0));
  assert(f.node.sendNoiseFloorHistorySnapshot(1));
  assert(f.node.packets.size() == 5);
  return f.node.packets;
}

static void checkLastTxCompletionAndOwnership() {
  Fixture f; f.boot();
  for (unsigned i = 0; i < 8; ++i) f.node.self_id.pub_key[i] = uint8_t(0x90 + i);
  expectLastTx(f.node, "never");
  const auto packets = historyPackets(f);
  expectLastTx(f.node, "never"); // queue acceptance is not a completed RF send
  for (const auto& packet : packets) {
    f.node.uptime_millis += 1000;
    f.node.last_millis = test_millis;
    f.node.recordTelemetryHistoryTx(&packet);
    assert(f.node.telemetry_history_last_tx_uptime == f.node.uptime_millis);
    expectLastTx(f.node, "0s");
  }

  const uint64_t completed = f.node.telemetry_history_last_tx_uptime;
  f.node.uptime_millis += 30000;
  for (const auto& valid : packets) {
    auto other = valid;
    other.payload_type = 5;
    f.node.recordTelemetryHistoryTx(&other);
    other = valid; other.forwarded = true;
    f.node.recordTelemetryHistoryTx(&other);
    other = valid; other.payload[4] ^= 1;
    f.node.recordTelemetryHistoryTx(&other);
    for (const unsigned offset : {2U, 3U, 16U, 18U}) {
      other = valid;
      if (offset == 16) other.payload[16] = other.payload[17] = 0;
      else other.payload[offset] = 0;
      f.node.recordTelemetryHistoryTx(&other);
    }
    other = valid; --other.payload_len;
    f.node.recordTelemetryHistoryTx(&other);
    other = valid; other.payload_len = 0;
    f.node.recordTelemetryHistoryTx(&other);
    other = valid; other.payload_len = MAX_PACKET_PAYLOAD + 1;
    f.node.recordTelemetryHistoryTx(&other);
    assert(f.node.telemetry_history_last_tx_uptime == completed);
  }
  expectLastTx(f.node, "30s");

  f.node.reject_magic = "TTB1"; f.node.rejected_sends = 1;
  assert(!f.node.sendTelemetryHistorySnapshot(mesh::TelemetryHistory::SERIES_TEMPERATURE));
  assert(f.node.telemetry_history_last_tx_uptime == completed);
  expectLastTx(f.node, "30s");
  // A completed echo retry is another RF transmission and refreshes the age.
  f.node.recordTelemetryHistoryTx(&packets.front());
  expectLastTx(f.node, "0s");
  assert(f.node.telemetry_history_last_tx_uptime == completed + 30000);
}

static void checkLastTxAgeAndClockWrap() {
  Fixture f; f.boot();
  const auto packets = historyPackets(f);
  f.node.uptime_millis = 100000;
  f.node.last_millis = test_millis;
  f.node.recordTelemetryHistoryTx(&packets.front());
  struct AgeCase { uint32_t seconds; const char* text; };
  for (const auto& age : {AgeCase{0, "0s"}, {30, "30s"}, {59, "59s"},
                           {60, "1m"}, {1800, "30m"}, {3600, "1h"},
                           {7200, "2h"}, {172800, "48h"}}) {
    f.node.uptime_millis = 100000 + uint64_t(age.seconds) * 1000;
    expectLastTx(f.node, age.text);
  }

  // Account for the time since the main loop last sampled millis(), across
  // its 32-bit wrap, using the accumulated boot uptime rather than RTC time.
  f.node.uptime_millis = (uint64_t(1) << 32) + 4000;
  f.node.last_millis = UINT32_MAX - 999;
  test_millis = 500;
  const uint64_t sent = f.node.uptime_millis + 1500;
  f.node.recordTelemetryHistoryTx(&packets[1]);
  assert(f.node.telemetry_history_last_tx_uptime == sent);
  expectLastTx(f.node, "0s");
  test_millis += 30000;
  expectLastTx(f.node, "30s");

  // RTC jumps clear/rebuild the sample histories without changing the age.
  f.node.telemetry_history.record(2000000000, 21, true, 3750, 0, 0, false);
  f.node.telemetry_history.record(1000000, 21, true, 3750, 0, 0, false);
  f.node.noise_floor_history.advance(2000000000);
  f.node.noise_floor_history.advance(1000000);
  expectLastTx(f.node, "30s");
  f.node.uptime_millis = sent + 172800000;
  f.node.last_millis = test_millis;
  expectLastTx(f.node, "48h");
  test_millis = 0;
}

static void checkLastTxSurvivesScheduleAndStatusTruncation() {
  Fixture f; f.boot();
  const auto packets = historyPackets(f);
  f.node.uptime_millis = 1000;
  f.node.last_millis = test_millis;
  f.node.recordTelemetryHistoryTx(&packets.front());
  const uint64_t sent = f.node.telemetry_history_last_tx_uptime;
  for (const char* command : {"set telemetry.tx schedule 1d", "set telemetry.tx schedule off"}) {
    assert(f.node.command(command).find("OK - telemetry.tx schedule=") == 0);
    assert(f.node.telemetry_history_last_tx_uptime == sent);
    f.boot();
    assert(f.node.telemetry_history_last_tx_uptime == sent);
  }
  assert(f.node.command("send telemetry.tx now").find("OK - telemetry.tx queued") == 0);
  assert(f.node.telemetry_history_last_tx_uptime == sent);
  f.fs.fail_read_open.insert(target);
  f.node.loadTelemetryHistoryTxPrefs();
  assert(!f.node.telemetry_history_tx_prefs_healthy);
  f.node.uptime_millis += 1800000;
  expectLastTx(f.node, "30m");
  assert(txStatus(f.node).find("last=30m fault=prefs p=") != std::string::npos);

  f.fs.clearFaults(); f.boot();
  f.route.path_len = 63;
  memset(f.route.path, 0xab, sizeof(f.route.path));
  const auto reply = txStatus(f.node);
  assert(reply.size() == 159); // longest learned route exceeds the CLI reply
  assert(reply.find("last=30m") < reply.find(" p="));
  assert(reply.find("last=30m p=ABAB") != std::string::npos);
  char prefixed[161];
  memset(prefixed, '#', sizeof(prefixed));
  memcpy(prefixed, " > ", 3);
  f.node.formatTelemetryHistoryTxStatus(prefixed + 3, 157);
  assert(prefixed[159] == 0 && prefixed[160] == '#');
  assert(strstr(prefixed, "last=30m p=ABAB"));
  Fixture restarted; restarted.fs.files = f.fs.files; restarted.boot();
  expectLastTx(restarted.node, "never"); // boot-local; do not invent a timestamp
}

static const char* const type_keys[] = {"temp", "volt", "volt.i2c", "noise", "noise2"};

static void externalHistory(Fixture& f) {
  const uint8_t channels[] = {7, 9};
  assert(f.node.external_voltage_history.configure(channels, 2));
  const mesh::ExternalVoltageHistory::Reading readings[] = {{7, 12.5f, true}, {9, 5.0f, true}};
  for (unsigned i = 0; i < mesh::ExternalVoltageHistory::RETENTION_SAMPLES; ++i)
    f.node.external_voltage_history.record(1000800 + i * 1800, readings, 2);
  assert(f.node.external_voltage_history.binaryChunkCount() == 3);
}

static std::vector<std::string> selectedMagics(uint8_t types) {
  std::vector<std::string> expected;
  if (types & 1) expected.push_back("TTB1");
  if (types & 2) expected.push_back("TVB1");
  if (types & 8) expected.push_back("N1B1");
  if (types & 16) expected.push_back("N2B1");
  if (types & 4) for (unsigned i = 0; i < 6; ++i) expected.push_back("IVB1");
  return expected;
}

static void checkTypePreferencesAndCommands() {
  for (unsigned value = 0; value <= 255; ++value) {
    Fixture f; const auto image = current(true, 7, uint8_t(value)); f.seed(image);
    assert(f.fs.files.at(target) == image); // no eager format rewrite
    assert(f.node.telemetry_history_tx_prefs_healthy == (value < 32));
    if (value >= 32) { f.expectFault(); continue; }
    assert(f.node.telemetry_history_tx_types == value);
    assert(f.node.saveTelemetryHistoryTxPrefs() && f.fs.files.at(target) == image);
    f.boot(); assert(f.node.telemetry_history_tx_types == value);
  }
  Fixture f; f.seed();
  assert(f.node.command("get telemetry.tx.types") ==
      "> temp=on volt=on volt.i2c=on noise=on noise2=on");
  for (unsigned i = 0; i < 5; ++i) {
    const std::string key = std::string("telemetry.tx.") + type_keys[i];
    assert(f.node.command(("get " + key).c_str()) == "> on");
    assert(f.node.command(("set " + key + " off").c_str()) == "OK - " + key + "=off");
    assert(f.node.telemetry_history_tx_types == uint8_t(31 & ~(1U << i)));
    assert(f.fs.files.at(target) == current(true, 7, uint8_t(31 & ~(1U << i))));
    f.boot(); assert(f.node.command(("get " + key).c_str()) == "> off");
    const auto writes = f.fs.writes;
    assert(f.node.command(("set " + key + " off").c_str()) == "OK - " + key + "=off");
    assert(f.fs.writes == writes); // idempotent settings don't wear flash
    assert(f.node.command(("set " + key + " on").c_str()) == "OK - " + key + "=on");
    assert(f.node.telemetry_history_tx_types == 31);
    for (const auto& command : {"get " + key, "set " + key + " off"}) {
      ClientInfo unauthorized; unauthorized.admin = false;
      const auto before = f.node.state(); const auto files = f.fs.files;
      assert(f.node.command(command.c_str(), &unauthorized) == "Err - not permitted");
      assert(f.node.state() == before && f.fs.files == files);
    }
  }
  for (const char* command : {"set telemetry.tx.types off", "set telemetry.tx.types on"}) {
    const uint8_t expected = strstr(command, " off") ? 0 : 31;
    assert(f.node.command(command).find("OK -") == 0);
    assert(f.node.telemetry_history_tx_types == expected);
    f.boot(); assert(f.node.telemetry_history_tx_types == expected);
  }
  for (const char* command : {"set telemetry.tx.temp", "set telemetry.tx.temp ",
       "set telemetry.tx.temp true", "set telemetry.tx.temp 1", "set telemetry.tx.temp OFF",
       "set telemetry.tx.temp on junk", "set telemetry.tx.noise2x off",
       "get telemetry.tx.noise extra", "get telemetry.tx.types ",
       "set telemetry.tx.volt.i2cx off", "set telemetry.tx.gps on", "get telemetry.tx.gps"}) {
    const auto before = f.node.state(); const auto files = f.fs.files; const auto writes = f.fs.writes;
    assert(f.node.command(command).find("Err -") == 0);
    assert(f.node.state() == before && f.fs.files == files && f.fs.writes == writes);
  }
  ClientInfo unauthorized; unauthorized.admin = false;
  for (const char* command : {"get telemetry.tx.types", "set telemetry.tx.types off"})
    assert(f.node.command(command, &unauthorized) == "Err - not permitted");
}

static void checkSelectedManualAndScheduledBatches() {
  test_millis = 0;
  for (const bool manual : {false, true}) {
    for (uint8_t types = 0; types < 32; ++types) {
      Fixture f; f.seed(current(!manual, 2, types)); f.history(); f.noiseHistory(); externalHistory(f);
      f.node.dual = true;
      if (manual) {
        const auto reply = f.node.command("send telemetry.tx now");
        if (types == 0) assert(reply == "Err - no telemetry packet types enabled");
        else {
          const std::string expected = "OK - telemetry.tx queued temp=" + std::to_string(types & 1 ? 165 : 0)
              + " volt=" + std::to_string(types & 2 ? 165 : 0)
              + " i2c=" + std::to_string(types & 4 ? 2 : 0) + "/" + std::to_string(types & 4 ? 6 : 0)
              + " noise=" + std::to_string(bool(types & 8)) + "/" + std::to_string(bool(types & 16));
          assert(reply == expected);
        }
      }
      serviceDue(f.node); finishPending(f.node);
      assert(f.node.attempts == selectedMagics(types));
      assert(f.node.packets.size() == selectedMagics(types).size());
      for (size_t i = 1; i < f.node.packet_times.size(); ++i)
        assert(f.node.packet_times[i] - f.node.packet_times[i - 1] == 90000);
      assert(!f.node.telemetry_history_tx_pending && !f.node.telemetry_history_tx_manual);
      assert(f.node.telemetry_history_tx_types == types);
    }
  }
  // Manual selections use their own available history, without requiring base samples.
  for (const uint8_t types : {uint8_t(4), uint8_t(8), uint8_t(16)}) {
    Fixture f; f.seed(current(false, 2, types)); f.node.dual = true;
    if (types == 4) externalHistory(f); else f.noiseHistory(1);
    assert(f.node.telemetry_history.voltageSampleCount() == 0);
    assert(f.node.command("send telemetry.tx now").find("OK - telemetry.tx queued temp=0 volt=0") == 0);
    serviceDue(f.node); finishPending(f.node);
    assert(f.node.packets.size() == (types == 4 ? 6U : 1U));
    assert(f.node.attempts.front() == (types == 4 ? "IVB1" : types == 8 ? "N1B1" : "N2B1"));
  }
  for (const uint8_t types : {uint8_t(1), uint8_t(2), uint8_t(4), uint8_t(8), uint8_t(16)}) {
    Fixture f; f.seed(current(false, 2, types)); const auto before = f.node.state();
    assert(f.node.command("send telemetry.tx now") == "Err - no enabled telemetry data available");
    assert(f.node.state() == before && f.node.packets.empty());
  }
  Fixture warmup; warmup.seed(current(true, 2, 8)); warmup.noiseHistory(1);
  warmup.node.telemetry_history.record(1000000, 22, true, 3750, 0, 0, false);
  warmup.node.serviceTelemetryHistoryTx(); assert(warmup.node.packets.empty());
  warmup.history(); warmup.node.serviceTelemetryHistoryTx();
  assert(warmup.node.attempts == std::vector<std::string>{"N1B1"});
}

static void checkTypeSaveRollbackAndAmbiguity() {
  for (const bool all : {false, true}) {
    for (unsigned failure = 0; failure < 6; ++failure) {
      Fixture f; f.seed(); f.history(); externalHistory(f);
      f.node.telemetry_history_tx_pending = 31; f.node.telemetry_history_tx_manual = true;
      f.node.telemetry_history_tx_external_channel = 1; f.node.telemetry_history_tx_external_chunk = 2;
      f.node.telemetry_history_next_tx_uptime = 90000; f.node.telemetry_history_tx_resume_uptime = 9000000;
      const auto before = f.node.state(); const auto prior = f.fs.files.at(target);
      if (failure == 0) f.fs.fail_write_open.insert(temp);
      if (failure == 1) f.fs.write_limit[temp] = 6;
      if (failure == 2) f.fs.fail_rename.insert({temp, target});
      if (failure == 3) f.fs.fail_final_read = true;
      if (failure == 4) f.fs.final_read_limit = 6;
      if (failure == 5) f.fs.corrupt_publish = true;
      assert(f.node.command(all ? "set telemetry.tx.types off" : "set telemetry.tx.volt.i2c off") ==
          "Err - unable to save telemetry.tx types");
      assert(f.node.state() == before); // failed publication cannot prune work or reset timers/cursors
      if (failure < 3) {
        assert(f.node.telemetry_history_tx_prefs_healthy && f.fs.files.at(target) == prior);
        f.fs.clearFaults();
        assert(f.node.command(all ? "set telemetry.tx.types off" : "set telemetry.tx.volt.i2c off").find("OK -") == 0);
        assert(f.fs.files.at(target) == current(true, 7, all ? 0 : 27));
      } else {
        assert(!f.node.telemetry_history_tx_prefs_healthy); f.expectFault();
        f.boot(); f.expectFault(); // ambiguous storage remains closed across reboot
        f.fs.clearFaults(); f.boot();
        if (failure == 5) f.expectFault(); // corrupt published bytes never become authoritative
        else {
          assert(f.node.telemetry_history_tx_prefs_healthy);
          assert(f.node.telemetry_history_tx_types == (all ? 0 : 27));
          assert(f.node.telemetry_history_tx_enabled && f.node.telemetry_history_tx_interval_days == 7);
          assert(!f.node.telemetry_history_tx_pending && !f.node.telemetry_history_tx_manual);
        }
      }
    }
  }
}

static void checkTypeChangesDuringBatches() {
  test_millis = 0;
  Fixture f; f.seed(current(false, 2, 12)); f.noiseHistory(1); externalHistory(f);
  f.node.telemetry_history_next_tx_uptime = 9000000;
  assert(f.node.command("send telemetry.tx now").find("OK -") == 0);
  serviceDue(f.node); serviceDue(f.node); // N1B1, then first I2C chunk
  assert(f.node.attempts == std::vector<std::string>({"N1B1", "IVB1"}));
  assert(f.node.telemetry_history_tx_external_chunk == 1);
  const auto due = f.node.telemetry_history_next_tx_uptime;
  assert(f.node.command("set telemetry.tx.noise off").find("OK -") == 0);
  assert(f.node.command("set telemetry.tx.noise on").find("OK -") == 0);
  assert(f.node.telemetry_history_tx_pending == 4); // enabling adds nothing to the current batch
  assert(f.node.telemetry_history_next_tx_uptime == due && f.node.telemetry_history_tx_external_chunk == 1);
  f.node.uptime_millis = due - 1; f.node.last_millis = test_millis;
  f.node.serviceTelemetryHistoryTx(); assert(f.node.packets.size() == 2);
  serviceDue(f.node); // second I2C chunk, never repeat chunk zero
  assert(read32(f.node.packets[2].payload + 12) == read32(f.node.packets[1].payload + 12) + 64 * 1800);
  const size_t admitted = f.node.packets.size();
  assert(f.node.command("set telemetry.tx.volt.i2c off").find("OK -") == 0);
  assert(f.node.telemetry_history_tx_pending == 0 && !f.node.telemetry_history_tx_manual);
  assert(f.node.telemetry_history_tx_external_channel == 0 && f.node.telemetry_history_tx_external_chunk == 0);
  assert(f.node.telemetry_history_next_tx_uptime == 9000000 && !f.node.telemetry_history_tx_resume_uptime);
  assert(f.node.packets.size() == admitted); // producer cancellation cannot retract admitted radio packets
  f.node.uptime_millis += 90000; f.node.serviceTelemetryHistoryTx();
  assert(f.node.packets.size() == admitted);
  assert(f.node.command("set telemetry.tx.volt.i2c on").find("OK -") == 0);
  assert(!f.node.telemetry_history_tx_pending);
  assert(f.node.command("send telemetry.tx now").find("noise=1/0") != std::string::npos);
  assert(f.node.telemetry_history_tx_pending == 12);

  Fixture automatic; automatic.seed(); automatic.history();
  automatic.node.serviceTelemetryHistoryTx(); assert(automatic.node.packets.size() == 1);
  const uint64_t now = automatic.node.uptime_millis;
  assert(automatic.node.command("set telemetry.tx.volt off").find("OK -") == 0);
  assert(!automatic.node.telemetry_history_tx_pending);
  assert(automatic.node.telemetry_history_next_tx_uptime == now + 7ULL * 24 * 60 * 60 * 1000);
  automatic.node.serviceTelemetryHistoryTx(); assert(automatic.node.packets.size() == 1);

  Fixture stale; stale.seed(current(false)); stale.history();
  assert(stale.node.command("send telemetry.tx now").find("OK -") == 0);
  stale.node.telemetry_history_tx_types = 0; // defensive service filtering also works before its old due time
  stale.node.telemetry_history_next_tx_uptime = 1000000;
  stale.node.serviceTelemetryHistoryTx();
  assert(stale.node.packets.empty() && !stale.node.telemetry_history_tx_pending && !stale.node.telemetry_history_tx_manual);
}

int main() {
  checkFreshAndValid();
  checkLoadFailures();
  checkLegacyMigration();
  checkWriteAndValidationFailures();
  checkRecoveryAndRenameFailures();
  checkAmbiguousPublicationAndServiceGate();
  checkRoutePublicationAuthority();
  checkRouteReadbackAndRetry();
  checkNoiseHistoryTransmission();
  checkNoiseHistoryRetries();
  checkLastTxCompletionAndOwnership();
  checkLastTxAgeAndClockWrap();
  checkLastTxSurvivesScheduleAndStatusTruncation();
  checkTypePreferencesAndCommands();
  checkSelectedManualAndScheduledBatches();
  checkTypeSaveRollbackAndAmbiguity();
  checkTypeChangesDuringBatches();
  puts("telemetry persistence checks passed");
}
