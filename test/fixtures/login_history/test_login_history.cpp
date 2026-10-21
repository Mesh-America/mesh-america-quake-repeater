#include <helpers/LoginHistory.h>
#include <cassert>
#include <cstdio>
#include <cstdlib>
#include <new>
#include <string>

static bool forbid_allocations = false;

void* operator new(size_t size) {
  assert(!forbid_allocations);
  if (void* memory = std::malloc(size)) return memory;
  throw std::bad_alloc();
}
void* operator new[](size_t size) { return ::operator new(size); }
void operator delete(void* memory) noexcept { std::free(memory); }
void operator delete[](void* memory) noexcept { std::free(memory); }

using mesh::LoginHistory;
using Result = LoginHistory::Result;
static_assert(LoginHistory::KEY_SIZE == 32, "deduplicate complete public keys");
static_assert(sizeof(LoginHistory) <= 720, "bounded embedded RAM");

static void make_key(uint8_t* key, unsigned number) {
  for (size_t i = 0; i < LoginHistory::KEY_SIZE; ++i) key[i] = uint8_t(i * 11 + 0xAB);
  key[30] = uint8_t(number >> 8);
  key[31] = uint8_t(number);
}

static void record(LoginHistory& history, unsigned number, uint32_t timestamp,
                   Result result = Result::Accepted) {
  uint8_t key[LoginHistory::KEY_SIZE];
  make_key(key, number);
  history.record(key, timestamp, result);
}

static std::string query(const LoginHistory& history, const char* command = "get logins") {
  char reply[160];
  memset(reply, '#', sizeof(reply));
  assert(mesh::cli::handleLoginsGet(history, command, reply, 157));
  assert(reply[157] == '#' && reply[158] == '#' && reply[159] == '#');
  assert(strlen(reply) < 157);
  return reply;
}

static void empty_history() {
  LoginHistory history;
  assert(history.size() == 0 && history.get(0) == nullptr);
  assert(history.get(size_t(-1)) == nullptr);
  assert(query(history) == "Logins: empty");
  assert(query(history, "get logins 1") == "Logins: empty");
  assert(query(history, "get logins 2") == "Err - login page range: 1-1");
  history.record(nullptr, 1, Result::Accepted);
  assert(history.size() == 0);
}

static void newest_first_and_aggregate() {
  LoginHistory history;
  record(history, 1, 123, Result::WrongPassword);
  record(history, 2, 124, Result::GuestsDisabled);
  record(history, 1, 125);
  assert(history.size() == 2);
  assert(history.get(0)->key[31] == 1 && history.get(1)->key[31] == 2);
  assert(history.get(0)->attempts == 2 && history.get(1)->attempts == 1);
  assert(history.get(0)->timestamp == 125 && history.get(0)->result == Result::Accepted);
  assert(query(history) == "Logins 1/1 (2)\nABB6C1CCD7E2 n=2 last=125 accepted\n"
                           "ABB6C1CCD7E2 n=1 last=124 guests-disabled");
}

static void complete_key_deduplication() {
  LoginHistory history;
  for (unsigned i = 0; i < LoginHistory::CAPACITY; ++i) record(history, i, i);
  assert(history.size() == LoginHistory::CAPACITY);
  for (unsigned i = 0; i < LoginHistory::CAPACITY; ++i) {
    assert(history.get(i)->key[31] == LoginHistory::CAPACITY - 1 - i);
    assert(history.get(i)->attempts == 1);
  }
  uint8_t key[32];
  make_key(key, 15);
  key[6] ^= 1;  // Same displayed prefix and suffix, but another complete key.
  history.record(key, 100, Result::ACLUnavailable);
  assert(history.size() == LoginHistory::CAPACITY);
  assert(history.get(0)->attempts == 1 && history.get(1)->attempts == 1);
  assert(memcmp(history.get(0)->key, history.get(1)->key, 6) == 0);
  assert(memcmp(history.get(0)->key, history.get(1)->key, 32) != 0);
}

static void eviction_and_recency_ignore_clock() {
  LoginHistory history;
  for (unsigned i = 0; i < LoginHistory::CAPACITY; ++i) record(history, i, 100 + i);
  record(history, 0, 0, Result::ReplayOrStateRejected);
  assert(history.get(0)->key[31] == 0 && history.get(0)->timestamp == 0);
  assert(history.get(0)->attempts == 2);
  record(history, 16, 1);
  assert(history.get(0)->key[31] == 16 && history.get(1)->key[31] == 0);
  for (size_t i = 0; i < history.size(); ++i) assert(history.get(i)->key[31] != 1);
  record(history, 1, 2);
  assert(history.get(0)->key[31] == 1 && history.get(0)->attempts == 1);
  assert(history.get(1)->key[31] == 16);
}

static void saturates_and_updates_latest() {
  LoginHistory history;
  record(history, 42, UINT32_MAX);
  auto* entry = const_cast<LoginHistory::Entry*>(history.get(0));
  entry->attempts = UINT32_MAX - 1;
  record(history, 42, 0, Result::WrongPassword);
  assert(history.get(0)->attempts == UINT32_MAX);
  record(history, 42, 1, Result::ACLUnavailable);
  assert(history.get(0)->attempts == UINT32_MAX);
  assert(history.get(0)->timestamp == 1 && history.get(0)->result == Result::ACLUnavailable);
  const uint8_t* internal_key = history.get(0)->key;
  history.record(internal_key, 2, Result::GuestsDisabled);
  assert(history.size() == 1 && history.get(0)->timestamp == 2);
}

static void pages_and_results() {
  LoginHistory history;
  const Result results[] = {Result::Accepted, Result::WrongPassword, Result::GuestsDisabled,
                           Result::ReplayOrStateRejected, Result::ACLUnavailable};
  for (unsigned i = 0; i < 16; ++i) record(history, i, 100 + i, results[i % 5]);
  for (unsigned page = 1; page <= 8; ++page) {
    char command[32], expected[32];
    snprintf(command, sizeof(command), "get logins %u", page);
    snprintf(expected, sizeof(expected), "Logins %u/8 (16)\n", page);
    const auto actual = query(history, command);
    assert(actual.compare(0, strlen(expected), expected) == 0);
    const size_t newline = actual.find('\n');
    const size_t second = actual.find('\n', newline + 1);
    assert(second != std::string::npos && actual.find('\n', second + 1) == std::string::npos);
    assert(actual[newline + 13] == ' ' && actual[second + 13] == ' ');
    const unsigned index = (page - 1) * 2;
    assert(actual.find(mesh::cli::loginResultName(history.get(index)->result)) != std::string::npos);
    assert(actual.find(mesh::cli::loginResultName(history.get(index + 1)->result)) != std::string::npos);
  }
  assert(query(history, "get logins 9") == "Err - login page range: 1-8");
  LoginHistory odd;
  for (unsigned i = 0; i < 3; ++i) record(odd, i, 10 + i);
  assert(query(odd, "get logins 2") == "Logins 2/2 (3)\nABB6C1CCD7E2 n=1 last=10 accepted");
  assert(strcmp(mesh::cli::loginResultName(static_cast<Result>(255)), "unknown") == 0);
}

static void strict_page_and_command_parsing() {
  LoginHistory history;
  record(history, 0, 0);
  const char* invalid[] = {
    "get logins 0", "get logins -1", "get logins +1", "get logins 1x",
    "get logins 1 2", "get logins 1.0", "get logins page 1", "get logins 65536",
    "get logins 4294967296", "get logins 9999999999999999999999999999",
    "get logins 1\nset guest on",
  };
  for (const char* command : invalid) {
    assert(query(history, command) == "Err - usage: get logins [page]");
  }
  const char* whitespace[] = {"get logins ", "get logins\r\n", "get logins\t01 \r\n",
                              "get logins 0000000000001"};
  for (const char* command : whitespace) assert(query(history, command) == query(history));
  assert(query(history, "get logins 65535") == "Err - login page range: 1-1");
  char reply[157] = "unchanged";
  for (const char* command : {"", "get", "get login", "get loginsx", "get logins.other",
                             "set logins", "get logins/1"}) {
    assert(!mesh::cli::handleLoginsGet(history, command, reply, sizeof(reply)));
    assert(strcmp(reply, "unchanged") == 0);
  }
  assert(!mesh::cli::handleLoginsGet(history, nullptr, reply, sizeof(reply)));
  assert(mesh::cli::handleLoginsGet(history, "get logins", nullptr, sizeof(reply)));
}

static void bounded_replies_never_truncate_prefixes() {
  LoginHistory history;
  for (unsigned i = 0; i < 16; ++i) record(history, i, UINT32_MAX, Result::GuestsDisabled);
  for (size_t i = 0; i < history.size(); ++i) {
    const_cast<LoginHistory::Entry*>(history.get(i))->attempts = UINT32_MAX;
  }
  const auto expected = query(history);
  assert(expected.size() < 157);
  assert(expected == "Logins 1/8 (16)\nABB6C1CCD7E2 n=4294967295 last=4294967295 guests-disabled\n"
                     "ABB6C1CCD7E2 n=4294967295 last=4294967295 guests-disabled");
  for (size_t capacity = 0; capacity <= 180; ++capacity) {
    char reply[181];
    memset(reply, '#', sizeof(reply));
    assert(mesh::cli::handleLoginsGet(history, "get logins", reply, capacity));
    assert(reply[capacity] == '#');
    if (capacity == 0) continue;
    assert(strlen(reply) < capacity);
    if (capacity > expected.size()) assert(std::string(reply) == expected);
    else assert(strstr(reply, "Logins") == nullptr);
  }
}

static void never_prints_remaining_key_bytes() {
  LoginHistory history;
  uint8_t key[32];
  memset(key, 0xDE, sizeof(key));
  for (size_t i = 0; i < 6; ++i) key[i] = uint8_t(i);
  history.record(key, 7, Result::WrongPassword);
  const auto reply = query(history);
  assert(reply == "Logins 1/1 (1)\n000102030405 n=1 last=7 wrong-password");
  assert(reply.find("DEDE") == std::string::npos);
}

static void record_and_format_never_allocate_or_mutate_on_read() {
  LoginHistory history;
  uint8_t keys[20][32];
  for (unsigned i = 0; i < 20; ++i) make_key(keys[i], i);
  char reply[157];
  forbid_allocations = true;
  for (unsigned round = 0; round < 1000; ++round) {
    history.record(keys[round % 20], round, Result::WrongPassword);
    assert(mesh::cli::handleLoginsGet(history, "get logins", reply, sizeof(reply)));
  }
  LoginHistory snapshot = history;
  for (unsigned i = 0; i < 8; ++i) {
    char command[32];
    snprintf(command, sizeof(command), "get logins %u", i + 1);
    assert(mesh::cli::handleLoginsGet(history, command, reply, sizeof(reply)));
  }
  forbid_allocations = false;
  assert(history.size() == snapshot.size());
  for (size_t i = 0; i < history.size(); ++i) {
    const auto& actual = *history.get(i);
    const auto& before = *snapshot.get(i);
    assert(memcmp(actual.key, before.key, 32) == 0);
    assert(actual.timestamp == before.timestamp && actual.attempts == before.attempts);
    assert(actual.result == before.result);
  }
}

int main() {
  empty_history();
  newest_first_and_aggregate();
  complete_key_deduplication();
  eviction_and_recency_ignore_clock();
  saturates_and_updates_latest();
  pages_and_results();
  strict_page_and_command_parsing();
  bounded_replies_never_truncate_prefixes();
  never_prints_remaining_key_bytes();
  record_and_format_never_allocate_or_mutate_on_read();
  puts("10 login history checks passed");
}
