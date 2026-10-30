#include <helpers/ClientACL.cpp>
#include <helpers/GuestCLI.h>
#include <helpers/LoginHistory.h>
#include <helpers/CLICommandUtils.h>
#include <cstdio>
#include <cstdlib>
#include <string>
#include <vector>

static unsigned setting_calls = 0;
static mesh::LoginHistory login_history;
static bool handleGuestCommand(const char* command, char* reply, size_t capacity) {
  if (strcmp(command, "get guest") != 0 && strcmp(command, "set guest on") != 0
      && strcmp(command, "set guest off") != 0) return false;
  ++setting_calls;
  snprintf(reply, capacity, "guest setting handled");
  return true;
}

#include "production.h"

#define CHECK(condition) do { if (!(condition)) { \
  std::fprintf(stderr, "FAIL line %d: %s\n", __LINE__, #condition); std::exit(1); \
} } while (0)

static ClientInfo* add(ClientACL& acl, unsigned index, uint8_t permissions) {
  uint8_t key[PUB_KEY_SIZE];
  for (size_t i = 0; i < sizeof(key); ++i) key[i] = uint8_t(i * 7);
  key[30] = uint8_t(index >> 8);
  key[31] = uint8_t(index);
  auto* client = acl.putClient(mesh::Identity(key), permissions);
  CHECK(client != nullptr);
  memset(client->shared_secret, 0xFA, sizeof(client->shared_secret));
  client->last_activity = index + 123;
  client->last_timestamp = index + 456;
  return client;
}

static std::string row(const ClientInfo* client) {
  char key[PUB_KEY_SIZE * 2 + 1], activity[32];
  mesh::Utils::toHex(key, client->id.pub_key, PUB_KEY_SIZE);
  snprintf(activity, sizeof(activity), " last=%lu",
           static_cast<unsigned long>(client->last_activity));
  return std::string(key) + activity;
}

static std::string query(const ClientACL& acl, const char* command) {
  char reply[160];
  memset(reply, '#', sizeof(reply));
  CHECK(mesh::cli::handleGuestsGet(acl, command, reply, 157));
  CHECK(reply[157] == '#' && reply[158] == '#' && reply[159] == '#');
  CHECK(strlen(reply) < 157);
  return reply;
}

static std::string login_query(const char* command) {
  char reply[160];
  memset(reply, '#', sizeof(reply));
  CHECK(mesh::cli::handleLoginsGet(login_history, command, reply, 157));
  CHECK(reply[157] == '#' && reply[158] == '#' && reply[159] == '#');
  CHECK(strlen(reply) < 157);
  return reply;
}

static void empty_and_guest_only() {
  FakeFilesystem fs; mesh::LocalIdentity self;
  ClientACL acl;
  acl.load(&fs, self);
  CHECK(query(acl, "get guests") == "Guests: empty");
  CHECK(query(acl, "get guests 1") == "Guests: empty");
  CHECK(query(acl, "get guests 2") == "Err - guest page range: 1-1");
  add(acl, 0, PERM_ACL_ADMIN);
  CHECK(query(acl, "get guests") == "Guests: empty");
  const auto* guest = add(acl, 1, PERM_ACL_GUEST);
  CHECK(query(acl, "get guests") == "Guests 1/1 (1)\n" + row(guest));
  CHECK(query(acl, "get guests 1") == query(acl, "get guests"));
}

static void skips_inactive_and_other_roles() {
  FakeFilesystem fs; mesh::LocalIdentity self;
  ClientACL acl;
  acl.load(&fs, self);
  add(acl, 0, PERM_ACL_ADMIN);
  const auto expected = "Guests 1/2 (2)\n" + row(add(acl, 1, 0xA0));
  add(acl, 2, PERM_ACL_READ_ONLY);
  add(acl, 3, PERM_ACL_READ_WRITE);
  add(acl, 4, PERM_ACL_REGION_MGR);
  add(acl, 5, PERM_ACL_FILTER_MGR);
  add(acl, 6, 6);
  add(acl, 7, 7);
  auto* clockless = add(acl, 8, PERM_ACL_GUEST);
  clockless->last_activity = 0;
  const auto clockless_row = row(clockless);
  memset(add(acl, 9, PERM_ACL_GUEST)->shared_secret, 0, PUB_KEY_SIZE);
  memset(add(acl, 10, PERM_ACL_GUEST)->id.pub_key, 0, PUB_KEY_SIZE);
  CHECK(query(acl, "get guests") == expected);
  CHECK(query(acl, "get guests 2") == "Guests 2/2 (2)\n" + clockless_row);
  CHECK(query(acl, "get guests 3") == "Err - guest page range: 1-2");
}

static void full_table_pages_preserve_full_keys() {
  FakeFilesystem fs; mesh::LocalIdentity self;
  ClientACL acl;
  acl.load(&fs, self);
  for (unsigned i = 0; i < MAX_CLIENTS; ++i) add(acl, i, PERM_ACL_GUEST);
  acl.getClientByIdx(MAX_CLIENTS - 1)->last_activity = UINT32_MAX;
  for (unsigned page = 1; page <= MAX_CLIENTS; ++page) {
    char command[32], header[48];
    snprintf(command, sizeof(command), "get guests %u", page);
    snprintf(header, sizeof(header), "Guests %u/%u (%u)\n", page,
             unsigned(MAX_CLIENTS), unsigned(MAX_CLIENTS));
    CHECK(query(acl, command) == header + row(acl.getClientByIdx(page - 1)));
  }
}

static void rejects_bad_pages() {
  FakeFilesystem fs; mesh::LocalIdentity self;
  ClientACL acl;
  acl.load(&fs, self);
  add(acl, 0, PERM_ACL_GUEST);
  for (const char* command : {
      "get guests 0", "get guests 0000000000000000000000000000000000000000",
      "get guests -1", "get guests +1", "get guests 1x", "get guests\n1",
      "get guests 1 2", "get guests 1.0", "get guests page 1",
      "get guests 65536", "get guests 4294967296",
      "get guests 99999999999999999999999999", "get guests 1\nset guest off"}) {
    CHECK(query(acl, command) == "Err - usage: get guests [page]");
  }
  CHECK(query(acl, "get guests 65535") == "Err - guest page range: 1-1");
  const auto expected = query(acl, "get guests");
  for (const char* command : {"get guests ", "get guests\r\n",
                             "get guests\t01 \r\n", "get guests 0000000000001"}) {
    CHECK(query(acl, command) == expected);
  }
}

static void matching_has_token_boundaries() {
  ClientACL acl;
  char reply[157] = "unchanged";
  for (const char* command : {"", "get", "get guest", "get guestsx",
                             "get guests.other", "set guests"}) {
    CHECK(!mesh::cli::handleGuestsGet(acl, command, reply, sizeof(reply)));
    CHECK(strcmp(reply, "unchanged") == 0);
  }
  CHECK(!mesh::cli::handleGuestsGet(acl, nullptr, reply, sizeof(reply)));
  CHECK(mesh::cli::handleGuestsGet(acl, "get guests", nullptr, sizeof(reply)));
}

static void bounds_never_truncate_keys() {
  FakeFilesystem fs; mesh::LocalIdentity self;
  ClientACL acl;
  acl.load(&fs, self);
  add(acl, 0, PERM_ACL_GUEST)->last_activity = UINT32_MAX;
  const auto expected = query(acl, "get guests");
  for (size_t capacity = 1; capacity <= 160; ++capacity) {
    char reply[161];
    memset(reply, '#', sizeof(reply));
    CHECK(mesh::cli::handleGuestsGet(acl, "get guests", reply, capacity));
    CHECK(reply[capacity] == '#');
    CHECK(strlen(reply) < capacity);
    if (capacity > expected.size()) CHECK(reply == expected);
    else CHECK(strstr(reply, "Guests 1/1") == nullptr);
  }
  char byte = '#';
  CHECK(mesh::cli::handleGuestsGet(acl, "get guests", &byte, 0));
  CHECK(byte == '#');
}

static void revocation_removes_guest_and_listing_is_read_only() {
  FakeFilesystem fs; mesh::LocalIdentity self;
  ClientACL acl;
  acl.load(&fs, self);
  const auto* removed = add(acl, 0, PERM_ACL_GUEST);
  uint8_t key[PUB_KEY_SIZE]; memcpy(key, removed->id.pub_key, sizeof(key));
  const auto* kept = add(acl, 1, PERM_ACL_GUEST);
  const auto expected = "Guests 1/1 (1)\n" + row(kept);
  add(acl, 2, PERM_ACL_ADMIN);
  CHECK(acl.applyPermissions(self, key, PUB_KEY_SIZE, 0));
  CHECK(acl.getClient(key, PUB_KEY_SIZE) == nullptr);
  CHECK(query(acl, "get guests") == expected);
  std::vector<ClientInfo> before;
  for (int i = 0; i < acl.getNumClients(); ++i) before.push_back(*acl.getClientByIdx(i));
  const auto writes = fs.bytes_written;
  const auto files = fs.files;
  for (const char* command : {"get guests", "get guests 1", "get guests 2", "get guests 0"}) {
    query(acl, command);
  }
  CHECK(acl.getNumClients() == int(before.size()));
  for (int i = 0; i < acl.getNumClients(); ++i) {
    CHECK(memcmp(acl.getClientByIdx(i), &before[i], sizeof(ClientInfo)) == 0);
  }
  CHECK(fs.bytes_written == writes && fs.files == files);
}

static void disabling_removes_every_guest_and_preserves_other_roles() {
  FakeFilesystem fs; mesh::LocalIdentity self;
  ClientACL acl;
  acl.load(&fs, self);
  fs.files["/login-replay-test"] = {1, 2, 3, 4};
  const auto files = fs.files;
  const auto writes = fs.bytes_written;
  std::vector<ClientInfo> kept;
  for (unsigned i = 0; i < MAX_CLIENTS; ++i) {
    const uint8_t role = uint8_t(i % 8);
    auto* client = add(acl, i, uint8_t(role | 0xA0));
    client->out_path[0] = uint8_t(i);
    client->out_path_len = 1;
    client->permissions_are_explicit = true;
    if (role != PERM_ACL_GUEST) kept.push_back(*client);
    else {
      // Invalid/inactive rows and RTC=0 sessions must all be removed too.
      if (i % 16 == 0) client->last_activity = 0;
      if (i % 32 == 0) memset(client->shared_secret, 0, PUB_KEY_SIZE);
    }
  }
  const int old_count = acl.getNumClients();
  CHECK(acl.removeGuestClients() == old_count - int(kept.size()));
  CHECK(acl.getNumClients() == int(kept.size()));
  CHECK(query(acl, "get guests") == "Guests: empty");
  for (int i = 0; i < acl.getNumClients(); ++i) {
    CHECK(memcmp(acl.getClientByIdx(i), &kept[i], sizeof(ClientInfo)) == 0);
  }
  const ClientInfo empty = {};
  for (int i = acl.getNumClients(); i < old_count; ++i) {
    CHECK(memcmp(acl.getClientByIdx(i), &empty, sizeof(ClientInfo)) == 0);
  }
  CHECK(acl.removeGuestClients() == 0);
  CHECK(fs.files == files && fs.bytes_written == writes);

  ClientACL all;
  all.load(&fs, self);
  for (unsigned i = 0; i < MAX_CLIENTS; ++i) add(all, i, PERM_ACL_GUEST);
  CHECK(all.removeGuestClients() == MAX_CLIENTS && all.getNumClients() == 0);
  CHECK(all.removeGuestClients() == 0);
  CHECK(add(all, MAX_CLIENTS, PERM_ACL_ADMIN) != nullptr);
  CHECK(all.getNumClients() == 1);
  ClientACL empty_acl;
  CHECK(empty_acl.removeGuestClients() == 0);
}

static void actual_dispatch_keeps_guest_controls_admin_only() {
  FakeFilesystem fs; mesh::LocalIdentity self;
  ClientACL acl;
  acl.load(&fs, self);
  auto* sender = add(acl, 0, PERM_ACL_ADMIN);
  add(acl, 1, PERM_ACL_GUEST);
  uint8_t key[PUB_KEY_SIZE];
  memset(key, 0xAB, sizeof(key));
  login_history.record(key, 1234, mesh::LoginHistory::Result::GuestsDisabled);
  CHECK(login_query("get logins") ==
      "Logins 1/1 (1)\nABABABABABAB n=1 last=1234 guests-disabled");
  for (auto handler : guest_handlers) {
    for (unsigned permissions = 0; permissions <= 255; ++permissions) {
      sender->permissions = uint8_t(permissions);
      for (const char* input : {"get guests", "get guests 1", "xy|GET guests",
                               "xy|get guests 1", "get guest", "set guest on",
                               "xy|set guest off", "get logins", "get logins 1",
                               "xy|GET logins", "xy|get logins 1"}) {
        char command[40], reply[161];
        strcpy(command, input);
        memset(reply, '#', sizeof(reply));
        setting_calls = 0;
        handler(acl, sender, 0, command, reply);
        CHECK(reply[160] == '#');
        CHECK(strlen(reply) < 160);
        const char* body = input[2] == '|' ? reply + 3 : reply;
        if ((permissions & PERM_ACL_ROLE_MASK) != PERM_ACL_ADMIN) {
          CHECK(strcmp(body, "Err - not permitted") == 0);
          CHECK(setting_calls == 0);
        } else {
          CHECK(strstr(body, "not permitted") == nullptr);
          if (strstr(input, "guests")) {
            CHECK(setting_calls == 0);
            CHECK(std::string(body) == query(acl, "get guests"));
          } else if (strstr(input, "logins")) {
            CHECK(setting_calls == 0);
            CHECK(std::string(body) == login_query("get logins"));
            CHECK(strstr(body, "ABABABABABABAB") == nullptr);
          } else {
            CHECK(setting_calls == 1);
            CHECK(strcmp(body, "guest setting handled") == 0);
          }
        }
      }
    }
    // Physical/local command dispatch has no peer role and remains available.
    for (const char* input : {"get guests", "get logins"}) {
      char command[16], reply[160] = {};
      strcpy(command, input);
      handler(acl, nullptr, 0, command, reply);
      CHECK(std::string(reply) == (strstr(input, "guests")
          ? query(acl, "get guests") : login_query("get logins")));
    }
  }
}

int main() {
  empty_and_guest_only();
  skips_inactive_and_other_roles();
  full_table_pages_preserve_full_keys();
  rejects_bad_pages();
  matching_has_token_boundaries();
  bounds_never_truncate_keys();
  revocation_removes_guest_and_listing_is_read_only();
  disabling_removes_every_guest_and_preserves_other_roles();
  actual_dispatch_keeps_guest_controls_admin_only();
  puts("9 guest CLI checks passed");
}
