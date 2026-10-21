#!/usr/bin/env python3
"""Execute repeater guest authorization, saved toggles, and receive admission."""
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

from test_replay_reset_integration import extract_braced

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "test/fixtures/guest_login"

HARNESS = r'''
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <helpers/GuestLoginSettings.h>
#include <helpers/ClientLoginPersistence.h>
#include <helpers/ClientPathObservation.h>
#include <helpers/ClientPathPersistence.h>
#include <helpers/LazyPersistence.h>
#include <helpers/FloodCommandAliases.h>
#define PUB_KEY_SIZE 32
#define MAX_PATH_SIZE 64
#define MAX_CLIENTS 16
#define MESH_CLIENT_REPEATER_ONLY 1
#define MESH_ENABLE_FLOOD_RULE_ENGINE 1
#define MESH_DEBUG_PRINTLN(...) ((void)0)
@CONSTANTS@
namespace mesh {
struct Identity {
  uint8_t pub_key[PUB_KEY_SIZE];
  bool matches(const Identity& other) const {
    return memcmp(pub_key, other.pub_key, sizeof(pub_key)) == 0;
  }
  bool isHashMatch(const uint8_t* hash) const { return pub_key[0] == hash[0]; }
};
struct Packet {
  bool direct = true;
  bool isRouteDirect() const { return direct; }
};
}
@CLIENT_INFO@;
struct ClientACL {
  ClientInfo clients[MAX_CLIENTS]{};
  int num_clients = 0;
  unsigned authorizations = 0, allocations = 0;
  bool authorize_ok = true, allocate_ok = true;
  uint8_t authorized_role = 255;
  ClientInfo* getClient(const uint8_t* key, int length) {
    for (int i = 0; i < num_clients; ++i)
      if (memcmp(clients[i].id.pub_key, key, size_t(length)) == 0) return &clients[i];
    return nullptr;
  }
  int getNumClients() const { return num_clients; }
  ClientInfo* getClientByIdx(int i) { return &clients[i]; }
  const ClientInfo* getClientByIdx(int i) const { return &clients[i]; }
  ClientInfo* putClient(const mesh::Identity& id, uint8_t permissions) {
    ++allocations;
    if (auto* old = getClient(id.pub_key, PUB_KEY_SIZE)) return old;
    if (!allocate_ok || num_clients == MAX_CLIENTS) return nullptr;
    auto* client = &clients[num_clients++];
    *client = ClientInfo{};
    client->id = id;
    client->permissions = permissions;
    client->out_path_len = OUT_PATH_UNKNOWN;
    client->alt_path_len = OUT_PATH_UNKNOWN;
    client->observed_path_len = OUT_PATH_UNKNOWN;
    client->out_path_is_persistable = true;
    return client;
  }
  bool authorizeLoginTimestamp(const uint8_t*, uint32_t timestamp,
                               uint32_t floor, uint8_t role) {
    ++authorizations;
    authorized_role = role;
    return authorize_ok && mesh::planClientLoginReplay(floor, 0, timestamp).fresh;
  }
  int removeGuestClients();
};
@REMOVE_GUESTS@
struct Clock {
  uint32_t now = 1234567890;
  uint32_t getCurrentTime() const { return now; }
  uint32_t getCurrentTimeUnique() { return now + ++unique; }
  uint32_t unique = 0;
};
struct RNG { void random(uint8_t* data, size_t len) { memset(data, 0xB5, len); } };
@MANAGER_HELPERS@
struct MyMesh {
  GuestMemoryFS fs;
  mesh::GuestLoginSettings guest_login;
  ClientACL acl;
  Clock clock;
  RNG rng;
  struct Prefs { char password[16] = "admin"; char guest_password[16] = ""; } _prefs;
  unsigned long dirty_contacts_expiry = 0;
  uint8_t contacts_save_failures = 0, reply_data[160]{};
  int matching_peer_indexes[MAX_CLIENTS]{};
  unsigned received = 0;
  MyMesh() { assert(guest_login.begin(&fs)); }
  Clock* getRTCClock() { return &clock; }
  RNG* getRNG() { return &rng; }
  unsigned long futureMillis(unsigned long delay) { return 10000 + delay; }
  uint8_t handleLoginReq(const mesh::Identity&, const uint8_t*, uint32_t, const uint8_t*, bool);
  bool handleGuestCommand(const char*, char*, size_t);
  int searchPeersByHash(const uint8_t*);
  void onPeerDataRecv(mesh::Packet*, uint8_t, int, const uint8_t*, uint8_t*, size_t);
  bool onPeerPathRecv(mesh::Packet*, int, const uint8_t*, uint8_t*, uint8_t, uint8_t, uint8_t*, uint8_t);
  int handleRequest(ClientInfo*, uint32_t, uint8_t*, size_t, size_t);
  void dispatch(ClientInfo*, const char*, char*);
};
@LOGIN@
@COMMAND@
@SEARCH@
@PATH@
@DATA_ADMISSION@
@REQUEST_ADMISSION@
@DISPATCH@

static mesh::Identity identity(unsigned number) {
  mesh::Identity id;
  memset(id.pub_key, 0xAA, PUB_KEY_SIZE);
  id.pub_key[PUB_KEY_SIZE - 1] = uint8_t(number);
  return id;
}
static const uint8_t secret[PUB_KEY_SIZE] = {0xB7};
static uint8_t login(MyMesh& mesh, unsigned id, const char* password,
                     uint32_t timestamp = 100, bool flood = true) {
  guest_metadata_fs = &mesh.fs;
  return mesh.handleLoginReq(identity(id), secret, timestamp,
                             reinterpret_cast<const uint8_t*>(password), flood);
}
static ClientInfo* add(MyMesh& mesh, unsigned number, uint8_t role) {
  auto* client = mesh.acl.putClient(identity(number), role);
  assert(client);
  memcpy(client->shared_secret, secret, sizeof(secret));
  client->last_activity = 7;
  client->last_timestamp = 10;
  client->out_path_len = 1;
  client->out_path[0] = 0x42;
  return client;
}
static void command(MyMesh& mesh, const char* text, const char* expected) {
  guest_metadata_fs = &mesh.fs;
  char reply[160];
  memset(reply, '#', sizeof(reply));
  assert(mesh.handleGuestCommand(text, reply, 157));
  assert(strcmp(reply, expected) == 0);
  assert(reply[157] == '#' && reply[158] == '#' && reply[159] == '#');
}
static void defaultsAndPasswords() {
  MyMesh mesh;
  assert(!mesh.guest_login.enabled() && mesh.fs.files.empty());
  assert(login(mesh, 1, "") == 0 && mesh.acl.authorizations == 0);
  assert(login(mesh, 1, "wrong") == 0 && mesh.acl.num_clients == 0);
  command(mesh, "get guest", "> off");
  command(mesh, "set guest on", "OK - guest on");
  assert(login(mesh, 1, "") == 13);
  assert(mesh.reply_data[6] == 0 && mesh.reply_data[7] == PERM_ACL_GUEST);
  assert(mesh.acl.clients[0].last_activity == mesh.clock.now);
  assert(mesh.dirty_contacts_expiry == 0); // Guest sessions stay out of the ACL file.
  strcpy(mesh._prefs.guest_password, "guest-code");
  const ClientInfo before = mesh.acl.clients[0];
  assert(login(mesh, 1, "", 101) == 0); // Cached identity cannot bypass changed password.
  assert(login(mesh, 1, "wrong", 102) == 0);
  assert(memcmp(&before, &mesh.acl.clients[0], sizeof(before)) == 0);
  assert(login(mesh, 1, "guest-code", 103) == 13);
  assert(login(mesh, 1, "guest-code", 103) == 0); // Existing replay floor still applies.
  MyMesh reboot;
  reboot.fs.files = mesh.fs.files;
  guest_metadata_fs = &reboot.fs;
  assert(reboot.guest_login.begin(&reboot.fs) && reboot.guest_login.enabled());
  assert(reboot.acl.num_clients == 0);
  command(reboot, "set guest off", "OK - guest off");
  MyMesh off_reboot;
  off_reboot.fs.files = reboot.fs.files;
  guest_metadata_fs = &off_reboot.fs;
  assert(off_reboot.guest_login.begin(&off_reboot.fs) && !off_reboot.guest_login.enabled());
  assert(login(off_reboot, 2, "") == 0);
  MyMesh blank_admin;
  blank_admin._prefs.password[0] = 0;
  assert(login(blank_admin, 1, "") == 0);
  command(blank_admin, "set guest on", "OK - guest on");
  assert(login(blank_admin, 1, "") == 13 && blank_admin.reply_data[7] == PERM_ACL_GUEST);
}
static void assignedRoles() {
  for (unsigned permissions = 0; permissions < 256; ++permissions) {
    if ((permissions & PERM_ACL_ROLE_MASK) == PERM_ACL_GUEST) continue;
    MyMesh mesh;
    auto* client = add(mesh, 1, uint8_t(permissions));
    assert(login(mesh, 1, "wrong", 100, false) == 13);
    assert(client->permissions == permissions && client->out_path_len == 1);
    assert(client->last_timestamp == 100 && client->last_activity == mesh.clock.now);
    assert(mesh.reply_data[7] == permissions);
    assert(login(mesh, 1, "admin", 101) == 13);
    assert(client->permissions == ((permissions & ~PERM_ACL_ROLE_MASK) | PERM_ACL_ADMIN));
  }
  MyMesh guest;
  add(guest, 1, 0xA0);
  const ClientInfo before = guest.acl.clients[0];
  assert(login(guest, 1, "", 100) == 0 && guest.acl.authorizations == 0);
  assert(memcmp(&before, &guest.acl.clients[0], sizeof(before)) == 0);
  assert(login(guest, 1, "admin", 101) == 13);
  assert(guest.acl.clients[0].permissions == (0xA0 | PERM_ACL_ADMIN));
  MyMesh failure;
  failure.acl.authorize_ok = false;
  assert(login(failure, 1, "admin") == 0 && failure.acl.allocations == 0);
  failure.acl.authorize_ok = true;
  failure.acl.allocate_ok = false;
  assert(login(failure, 1, "admin") == 0 && failure.acl.num_clients == 0);
}
static void revocationAndFailures() {
  MyMesh mesh;
  command(mesh, "set guest on", "OK - guest on");
  add(mesh, 1, PERM_ACL_GUEST);
  const ClientInfo admin = *add(mesh, 2, PERM_ACL_ADMIN);
  add(mesh, 3, 0xF8);
  const ClientInfo manager = *add(mesh, 4, PERM_ACL_FILTER_MGR);
  command(mesh, "set guest off", "OK - guest off");
  assert(mesh.acl.num_clients == 2);
  assert(memcmp(&admin, &mesh.acl.clients[0], sizeof(admin)) == 0);
  assert(memcmp(&manager, &mesh.acl.clients[1], sizeof(manager)) == 0);
  ClientInfo zero{};
  assert(memcmp(&zero, &mesh.acl.clients[2], sizeof(zero)) == 0);
  assert(memcmp(&zero, &mesh.acl.clients[3], sizeof(zero)) == 0);
  command(mesh, "set guest on", "OK - guest on");
  assert(mesh.acl.getClient(identity(1).pub_key, PUB_KEY_SIZE) == nullptr);
  assert(login(mesh, 1, "", 200) == 13);
  mesh.fs.fail_open_write = true;
  command(mesh, "set guest off", "Err - guest setting save unconfirmed; reboot may differ");
  assert(mesh.guest_login.healthy() && mesh.guest_login.enabled());
  assert(mesh.acl.num_clients == 3); // Confirmed old setting remains live.
  mesh.fs.fail_open_write = false;
  mesh.fs.fail_public_read = true;
  command(mesh, "set guest off", "Err - guest setting save unconfirmed; reboot may differ");
  assert(!mesh.guest_login.healthy() && !mesh.guest_login.enabled());
  assert(mesh.acl.num_clients == 2); // Uncertain storage fails closed and revokes.
  assert(login(mesh, 1, "", 201) == 0);
  command(mesh, "get guest", "> off (settings unavailable)");
  assert(login(mesh, 2, "wrong", 300) == 13); // Assigned admin survives fail-closed guest storage.
}
static void commandPermissions() {
  MyMesh mesh;
  for (const char* invalid : {"get guest on", "set guest", "set guest 1", "set guest ON",
                             "set guest on extra", "set guest off extra"}) {
    command(mesh, invalid, "Err - use get guest or set guest on|off");
    assert(!mesh.guest_login.enabled() && mesh.fs.writes == 0);
  }
  for (const char* unrelated : {"get guests", "get guest.password", "set guest.password secret",
                               "get guestx", "set guestx on"}) {
    char reply[160] = "untouched";
    assert(!mesh.handleGuestCommand(unrelated, reply, sizeof(reply)));
    assert(strcmp(reply, "untouched") == 0);
  }
  for (uint8_t role : {PERM_ACL_GUEST, PERM_ACL_READ_ONLY, PERM_ACL_READ_WRITE,
                       PERM_ACL_REGION_MGR, PERM_ACL_FILTER_MGR, 6, 7}) {
    ClientInfo caller{};
    caller.permissions = role;
    char reply[160]{};
    mesh.dispatch(&caller, "set guest on", reply);
    assert(strcmp(reply, "Err - not permitted") == 0);
    assert(!mesh.guest_login.enabled());
    mesh.dispatch(&caller, "get guest", reply);
    assert(strcmp(reply, "Err - not permitted") == 0);
  }
  ClientInfo admin{};
  admin.permissions = PERM_ACL_ADMIN;
  char reply[160]{};
  mesh.dispatch(&admin, "set guest on", reply);
  assert(strcmp(reply, "OK - guest on") == 0 && mesh.guest_login.enabled());
  mesh.dispatch(nullptr, "set guest off", reply);
  assert(strcmp(reply, "OK - guest off") == 0 && !mesh.guest_login.enabled());
}
static void receiveAdmission() {
  MyMesh mesh;
  // Deliberately leave stale/in-flight guest state to exercise receive gates.
  auto* guest = add(mesh, 1, 0xA0);
  auto* admin = add(mesh, 2, PERM_ACL_ADMIN);
  const uint8_t hash[] = {0xAA};
  assert(mesh.searchPeersByHash(hash) == 1 && mesh.matching_peer_indexes[0] == 1);
  mesh::Packet packet;
  uint8_t data[8] = {1}, path[] = {0x55, 0x66};
  mesh.matching_peer_indexes[0] = 0;
  const ClientInfo before = *guest;
  mesh.onPeerDataRecv(&packet, 0, 0, secret, data, sizeof(data));
  assert(mesh.received == 0);
  assert(mesh.handleRequest(guest, 100, data, sizeof(data), 160) == 0);
  assert(!mesh.onPeerPathRecv(&packet, 0, secret, path, 2, 0x0F, nullptr, 0));
  assert(memcmp(&before, guest, sizeof(before)) == 0);
  mesh.matching_peer_indexes[0] = 1;
  mesh.onPeerDataRecv(&packet, 0, 0, secret, data, sizeof(data));
  assert(mesh.received == 1);
  assert(mesh.handleRequest(admin, 100, data, sizeof(data), 160) == 1);
  assert(!mesh.onPeerPathRecv(&packet, 0, secret, path, 2, 0x0F, nullptr, 0));
  assert(admin->out_path_len == 2 && admin->last_activity == mesh.clock.now);
  command(mesh, "set guest on", "OK - guest on");
  assert(mesh.searchPeersByHash(hash) == 2);
  mesh.matching_peer_indexes[0] = 0;
  mesh.onPeerDataRecv(&packet, 0, 0, secret, data, sizeof(data));
  assert(mesh.received == 3);
  assert(mesh.handleRequest(guest, 100, data, sizeof(data), 160) == 1);
  assert(!mesh.onPeerPathRecv(&packet, 0, secret, path, 2, 0x0F, nullptr, 0));
  assert(guest->out_path_len == 2 && guest->last_activity == mesh.clock.now);
  // A flood login still clears the old selected path and transient observation.
  guest->observed_path_pending = true;
  assert(login(mesh, 1, "", 200, true) == 13);
  assert(guest->out_path_len == OUT_PATH_UNKNOWN && !guest->observed_path_pending);
}
int main(int argc, char** argv) {
  assert(argc == 2);
  if (!strcmp(argv[1], "passwords")) defaultsAndPasswords();
  else if (!strcmp(argv[1], "roles")) assignedRoles();
  else if (!strcmp(argv[1], "revoke")) revocationAndFailures();
  else if (!strcmp(argv[1], "commands")) commandPermissions();
  else if (!strcmp(argv[1], "receive")) receiveAdmission();
  else assert(false);
  printf("repeater guest %s passed\n", argv[1]);
}
'''


class RepeaterGuestAccessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which("g++") or shutil.which("clang++")
        if compiler is None:
            raise unittest.SkipTest("host C++17 compiler required")
        source = (ROOT / "examples/simple_repeater/MyMesh.cpp").read_text()
        acl_header = (ROOT / "src/helpers/ClientACL.h").read_text()
        acl_source = (ROOT / "src/helpers/ClientACL.cpp").read_text()
        constants = "\n".join(line for line in acl_header.splitlines()
                              if line.startswith(("#define PERM_ACL_", "#define OUT_PATH_")))
        for name in ("FIRMWARE_VER_LEVEL", "RESP_SERVER_LOGIN_OK", "LAZY_CONTACTS_WRITE_DELAY"):
            constants += "\n" + re.search(r"^#define\s+" + name + r"\s+.*$", source, re.MULTILINE).group()
        manager_helpers = "\n".join(extract_braced(source, signature) for signature in (
            "static bool commandFamilyMatches(", "static bool commandListMatches(",
            "static bool isCommonManagerReadOnlyAllowed(", "static bool isRegionMgrAllowed(",
            "static bool isFilterMgrAllowed(",
        ))
        dispatch = extract_braced(source, "void MyMesh::handleCommand(uint32_t sender_timestamp,")
        call = dispatch.index("if (handleGuestCommand(command, reply, 157)")
        guard_start = dispatch.rindex("if (sender && !sender->isAdmin())", 0, call)
        guard = extract_braced(dispatch[guard_start:], "if (sender && !sender->isAdmin())")
        # Exercise the actual authorization branch and setter, excluding unrelated
        # radio commands and the independently tested guest-list formatter.
        command_dispatch = "void MyMesh::dispatch(ClientInfo* sender, const char* command, char* reply) {\n" + guard + "\nif (handleGuestCommand(command, reply, 157)) return;\nstrcpy(reply, \"unhandled\");\n}"
        peer = extract_braced(source, "void MyMesh::onPeerDataRecv(")
        gate_end = peer.index("#if defined(WITH_MQTT_NEIGHBORS)", peer.index("ClientInfo* client = acl.getClientByIdx(i);"))
        # Compile the real receive admission through the guest gate. Radio request
        # execution is replaced by a counter only after authorization succeeds.
        data_admission = peer[:gate_end] + "++received;\n}"
        request = extract_braced(source, "int MyMesh::handleRequest(")
        request_admission = request[:request.index("  if (reply_capacity >")] + "++received; return 1;\n}"
        cls.source_text = source
        replacements = {
            "@CONSTANTS@": constants,
            "@CLIENT_INFO@": extract_braced(acl_header, "struct ClientInfo {"),
            "@REMOVE_GUESTS@": extract_braced(acl_source, "int ClientACL::removeGuestClients("),
            "@MANAGER_HELPERS@": manager_helpers,
            "@LOGIN@": extract_braced(source, "uint8_t MyMesh::handleLoginReq("),
            "@COMMAND@": extract_braced(source, "bool MyMesh::handleGuestCommand("),
            "@SEARCH@": extract_braced(source, "int MyMesh::searchPeersByHash("),
            "@PATH@": extract_braced(source, "bool MyMesh::onPeerPathRecv("),
            "@DATA_ADMISSION@": data_admission,
            "@REQUEST_ADMISSION@": request_admission,
            "@DISPATCH@": command_dispatch,
        }
        generated = HARNESS
        for marker, text in replacements.items():
            generated = generated.replace(marker, text)
        cls.work = tempfile.TemporaryDirectory(prefix="mesh-repeater-guest-")
        cls.addClassCleanup(cls.work.cleanup)
        work = Path(cls.work.name)
        cpp = work / "test.cpp"
        cpp.write_text(generated)
        cls.binary = work / ("guest.exe" if sys.platform == "win32" else "guest")
        sanitizer = (["-fsanitize=address,undefined", "-fno-sanitize-recover=all",
                      "-fno-omit-frame-pointer", "-fno-pie", "-no-pie"]
                     if sys.platform.startswith("linux") else [])
        result = subprocess.run([
            compiler, "-std=c++17", "-O1", "-g", "-Wall", "-Wextra", "-Werror",
            "-Wno-unused-parameter", "-Wno-sign-compare", "-Wno-misleading-indentation",
            "-DESP32_PLATFORM", "-DESP32", *sanitizer,
            "-I", str(FIXTURE / "mocks"), "-I", str(ROOT / "src"),
            str(cpp), str(ROOT / "src/helpers/GuestLoginSettings.cpp"), "-o", str(cls.binary),
        ], capture_output=True, text=True, timeout=60)
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)

    def scenario(self, name):
        result = subprocess.run([str(self.binary), name], capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("repeater guest " + name + " passed", result.stdout)

    def test_default_password_change_and_reboot(self):
        self.scenario("passwords")

    def test_assigned_roles_and_admin_upgrade(self):
        self.scenario("roles")

    def test_disable_revokes_only_guests_and_storage_failure_fails_closed(self):
        self.scenario("revoke")

    def test_command_validation_and_admin_authorization(self):
        self.scenario("commands")

    def test_peer_request_and_path_admission(self):
        self.scenario("receive")

    def test_guest_controls_precede_portable_role_handoff(self):
        # Current FULL builds and legacy PORTABLE_MQTT_OBSERVER builds both need
        # the same saved policy and permissions, rather than a generic CLI fallback.
        body = extract_braced(self.source_text, "void MyMesh::handleCommand(uint32_t sender_timestamp,")
        self.assertEqual(body.count("handleGuestCommand(command, reply, 157)"), 2)
        self.assertEqual(body.count("mesh::cli::handleGuestsGet(acl, command, reply, 157)"), 2)


if __name__ == "__main__":
    unittest.main()
