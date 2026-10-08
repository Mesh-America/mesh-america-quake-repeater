#include "ManagementReporter.h"
#include "CommonCLI.h"
#include <cassert>
#include <cstdio>
#include <cstring>
#include <new>
#include <string>

static bool fail_nothrow_allocation = false;
static unsigned failed_allocations = 0;

// Exercise the standard public nothrow allocation-failure path, not a
// substituted ManagementReporter constructor or command implementation.
void* operator new(size_t size, const std::nothrow_t&) noexcept {
  if (fail_nothrow_allocation) { ++failed_allocations; return nullptr; }
  try { return ::operator new(size); } catch (const std::bad_alloc&) { return nullptr; }
}

namespace mesh {
UsbLoggingStatus usbLoggingStatus() { return UsbLoggingStatus(); }
}

#include "production_path_parser.inc"

// The route parser has independent source-linked storage tests. Its routing
// boundary records what this wrapper delegates; management commands do not
// depend on or change route state in this focused fixture.
bool CommonCLI::handleDataTxCommand(char* command, char* reply) {
  data_commands.emplace_back(command);
  if (!strncmp(command, "set data.tx path ", 17)) {
    uint8_t path[MAX_PATH_SIZE], path_len = OUT_PATH_UNKNOWN;
    const char* error = nullptr;
    if (!mesh::parseDataPath(command + 17, path, path_len, error)) {
      snprintf(reply, 160, "%s", error ? error : "Err - invalid path");
      return true;
    }
  }
  if (!strncmp(command, "get data.tx", 11) || !strncmp(command, "set data.tx", 11)) {
    strcpy(reply, "route boundary");
    return true;
  }
  return false;
}

#include "production_wrapper.inc"

struct Fixture {
  MemoryFS fs;
  mesh::Mesh mesh;
  mesh::MainBoard board;
  SensorManager sensors;
  ClientACL acl;
  NodePrefs prefs;
  CommonCLICallbacks callbacks;
  CommonCLI cli;

  Fixture() {
    cli._board = &board; cli._sensors = &sensors; cli._acl = &acl;
    cli._prefs = &prefs; cli._callbacks = &callbacks;
  }
  ~Fixture() { delete cli._management; }
  void enableContext() { cli._management_mesh = &mesh; cli._management_fs = &fs; }
};

static void password(Fixture& fixture, const std::string& value,
                     const char* expected_reply) {
  unsigned char guarded[320]; memset(guarded, 0xa5, sizeof(guarded));
  char* command = reinterpret_cast<char*>(guarded + 8);
  memcpy(command, "set mgmt.password ", 18);
  memcpy(command + 18, value.c_str(), value.size() + 1);
  const size_t length = 18 + value.size();
  char reply[160] = {};
  assert(fixture.cli.handleManagementCommand(command, reply));
  assert(!strcmp(reply, expected_reply));
  assert(!memcmp(command, "set mgmt.password ", 18));
  for (size_t index = 18; index <= length; ++index) {
    if (command[index] != 0) {
      fprintf(stderr, "password byte %zu survived reply '%s'\n", index - 18, reply);
      assert(false);
    }
  }
  for (size_t index = 0; index < 8; ++index) assert(guarded[index] == 0xa5);
  for (size_t index = 8 + length + 1; index < sizeof(guarded); ++index)
    assert(guarded[index] == 0xa5);
}

int main() {
  for (unsigned missing : {0u, 1u, 2u}) {
    Fixture fixture;
    if (missing == 1) fixture.cli._management_mesh = &fixture.mesh;
    if (missing == 2) fixture.cli._management_fs = &fixture.fs;
    for (size_t length : {0u, 5u, 12u, 96u, 97u, 200u})
      password(fixture, std::string(length, 's'), "ERR: management unavailable");
    assert(!fixture.cli._management && fixture.fs.files.empty());
  }
  {
    Fixture fixture; fixture.enableContext(); fail_nothrow_allocation = true;
    const auto before = failed_allocations;
    for (size_t length : {0u, 5u, 12u, 96u, 97u, 200u})
      password(fixture, std::string(length, 's'), "ERR: management unavailable");
    assert(failed_allocations == before + 6 && !fixture.cli._management);
    assert(fixture.fs.files.empty()); fail_nothrow_allocation = false;
    password(fixture, "a real management password", "OK");
    assert(fixture.cli._management && fixture.fs.files.count("/management"));
  }
  {
    Fixture fixture; fixture.enableContext();
    for (size_t length : {0u, 5u, 97u, 200u})
      password(fixture, std::string(length, 's'), "ERR: password must be 12..96 bytes");
    assert(fixture.fs.files.empty());
    password(fixture, "a real management password", "OK");
    fixture.fs.fail_write = true;
    password(fixture, "another management password", "ERR: save failed; reporting stopped");
    fixture.fs.fail_write = false;
    password(fixture, "third management password", "ERR: management state fault; repair storage/reboot first");
  }
  {
    Fixture fixture;
    for (const char* untouched : {"get mgmt", "set mgmt.enabled on", "get mgmt.password",
                                  "set mgmt.passwordExtra secret", "set mgmt.password\tsecret"}) {
      char command[160], reply[160] = {}; strcpy(command, untouched);
      assert(fixture.cli.handleManagementCommand(command, reply));
      assert(!strcmp(command, untouched));
      assert(!strcmp(reply, "ERR: management unavailable"));
    }
    for (const char* unknown : {"get mgm", "set mgm.password secret", "get management",
                                "set management.password secret"}) {
      char command[160], reply[160] = "not handled"; strcpy(command, unknown);
      assert(!fixture.cli.handleManagementCommand(command, reply));
      assert(!strcmp(command, unknown) && !strcmp(reply, "not handled"));
    }
    for (const char* alias : {"get mgmt.path", "set mgmt.path 2:12abcd34"}) {
      char command[160], reply[160] = {}; strcpy(command, alias);
      assert(fixture.cli.handleManagementCommand(command, reply));
      assert(!strcmp(reply, "route boundary"));
      assert(fixture.cli.data_commands.back()
          == (!strncmp(alias, "get", 3) ? "get data.tx path" : "set data.tx path 2:12abcd34"));
      assert(!fixture.cli._management);
    }
    const std::string largest_spec = "1:" + std::string(126, '1') + std::string(14, ' ');
    const std::string largest_alias = "set mgmt.path " + largest_spec;
    assert(largest_alias.size() == 156);
    char boundary[160], boundary_reply[160] = {}; strcpy(boundary, largest_alias.c_str());
    assert(fixture.cli.handleManagementCommand(boundary, boundary_reply));
    assert(!strcmp(boundary_reply, "route boundary"));
    // Exact expanded capacity is accepted, including its null terminator.
    // trimDataRoute mutates the delegated buffer after validation.
    assert(fixture.cli.data_commands.back().size() == 159);
    // This fits the 159-byte ordinary repeater CLI input limit. Expanding the
    // alias prefix by three bytes must not discard malformed suffix bytes and
    // turn an invalid setting into an accepted 63-hop direct route.
    const std::string spec = largest_spec + "bad";
    std::string direct = spec;
    uint8_t path[MAX_PATH_SIZE], path_len = OUT_PATH_UNKNOWN;
    const char* error = nullptr;
    assert(!mesh::parseDataPath(&direct[0], path, path_len, error));
    const std::string alias = "set mgmt.path " + spec;
    assert(alias.size() == 159);
    char command[160], reply[160] = {}; strcpy(command, alias.c_str());
    const auto delegated = fixture.cli.data_commands.size();
    assert(fixture.cli.handleManagementCommand(command, reply));
    if (!strcmp(reply, "route boundary")) {
      fprintf(stderr, "malformed alias accepted after truncation: '%s'\n", reply);
      assert(false);
    }
    assert(!strcmp(reply, "Err - data.tx path too long"));
    // The wrapper probes the original command once before recognizing aliases;
    // rejection must not make a second call with a truncated expanded alias.
    assert(fixture.cli.data_commands.size() == delegated + 1);
    for (size_t excess : {1u, 2u, 100u}) {
      std::string long_alias = largest_alias + std::string(excess, ' ');
      char long_reply[160] = {};
      assert(fixture.cli.handleManagementCommand(&long_alias[0], long_reply));
      assert(!strcmp(long_reply, "Err - data.tx path too long"));
    }
  }
}
