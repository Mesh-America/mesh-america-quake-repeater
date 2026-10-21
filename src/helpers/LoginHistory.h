#pragma once

#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

namespace mesh {

// Recent radio login decisions. RAM only: attempts never write flash or retain
// passwords. Keep the complete key internally even though the CLI shows a prefix.
class LoginHistory {
 public:
  static constexpr size_t KEY_SIZE = 32;
  static constexpr size_t CAPACITY = 16;

  enum class Result : uint8_t {
    Accepted,
    WrongPassword,
    GuestsDisabled,
    ReplayOrStateRejected,
    ACLUnavailable,
  };

  struct Entry {
    uint8_t key[KEY_SIZE];
    uint32_t timestamp;
    uint32_t attempts;
    Result result;
  };

  void record(const uint8_t* key, uint32_t timestamp, Result result) {
    if (key == nullptr) return;
    size_t index = 0;
    while (index < _size && memcmp(_entries[index].key, key, KEY_SIZE) != 0) ++index;

    Entry latest = {};
    if (index < _size) {
      latest = _entries[index];
      if (latest.attempts != UINT32_MAX) ++latest.attempts;
    } else {
      memcpy(latest.key, key, KEY_SIZE);
      latest.attempts = 1;
      if (_size < CAPACITY) ++_size;
      index = _size - 1;
    }
    latest.timestamp = timestamp;
    latest.result = result;
    if (index != 0) memmove(_entries + 1, _entries, index * sizeof(Entry));
    _entries[0] = latest;
  }

  size_t size() const { return _size; }
  const Entry* get(size_t index) const { return index < _size ? &_entries[index] : nullptr; }

 private:
  Entry _entries[CAPACITY] = {};
  uint8_t _size = 0;
};

namespace cli {

inline const char* loginResultName(LoginHistory::Result result) {
  switch (result) {
    case LoginHistory::Result::Accepted: return "accepted";
    case LoginHistory::Result::WrongPassword: return "wrong-password";
    case LoginHistory::Result::GuestsDisabled: return "guests-disabled";
    case LoginHistory::Result::ReplayOrStateRejected: return "replay/state";
    case LoginHistory::Result::ACLUnavailable: return "acl-unavailable";
  }
  return "unknown";
}

// Call after the repeater's admin authorization check. Two rows fit in the
// 157-byte radio reply even with maximum counters and UTC timestamps.
inline bool handleLoginsGet(const LoginHistory& history, const char* command,
                            char* reply, size_t capacity) {
  static const char prefix[] = "get logins";
  const size_t prefix_len = sizeof(prefix) - 1;
  if (command == nullptr || strncmp(command, prefix, prefix_len) != 0) return false;
  const char* arg = command + prefix_len;
  if (*arg && *arg != ' ' && *arg != '\t' && *arg != '\r' && *arg != '\n') return false;
  if (reply == nullptr || capacity == 0) return true;

  while (*arg == ' ' || *arg == '\t') ++arg;
  unsigned page = 1;
  if (*arg >= '0' && *arg <= '9') {
    page = 0;
    do {
      page = page * 10 + unsigned(*arg++ - '0');
      if (page > 65535) break;
    } while (*arg >= '0' && *arg <= '9');
  }
  while (*arg == ' ' || *arg == '\t' || *arg == '\r' || *arg == '\n') ++arg;
  if (*arg || page == 0 || page > 65535) {
    snprintf(reply, capacity, "Err - usage: get logins [page]");
    return true;
  }

  const unsigned total = unsigned(history.size());
  if (total == 0 && page == 1) {
    snprintf(reply, capacity, "Logins: empty");
    return true;
  }
  const unsigned pages = total == 0 ? 1 : (total + 1) / 2;
  if (page > pages) {
    snprintf(reply, capacity, "Err - login page range: 1-%u", pages);
    return true;
  }

  char rows[2][80] = {};
  unsigned count = 0;
  for (unsigned index = (page - 1) * 2; index < total && count < 2; ++index) {
    const auto& entry = *history.get(index);
    char key[13];
    static const char hex[] = "0123456789ABCDEF";
    for (size_t i = 0; i < 6; ++i) {
      key[i * 2] = hex[entry.key[i] >> 4];
      key[i * 2 + 1] = hex[entry.key[i] & 0x0F];
    }
    key[12] = 0;
    snprintf(rows[count], sizeof(rows[count]), "%s n=%lu last=%lu %s", key,
             static_cast<unsigned long>(entry.attempts),
             static_cast<unsigned long>(entry.timestamp), loginResultName(entry.result));
    ++count;
  }
  const char* separator = count == 2 ? "\n" : "";
  const int needed = snprintf(nullptr, 0, "Logins %u/%u (%u)\n%s%s%s",
                              page, pages, total, rows[0], separator, rows[1]);
  // Never accidentally expose a partly formatted public-key prefix.
  if (needed < 0 || size_t(needed) >= capacity) {
    snprintf(reply, capacity, "Err - login reply too small");
  } else {
    snprintf(reply, capacity, "Logins %u/%u (%u)\n%s%s%s",
             page, pages, total, rows[0], separator, rows[1]);
  }
  return true;
}

}  // namespace cli
}  // namespace mesh
