#pragma once
#include <cassert>
#include <map>
#include <string>
#include <cstdint>

struct String {
  std::string value;
  String() = default;
  String(const char* s) : value(s) {}
  String(const std::string& s) : value(s) {}
  size_t length() const { return value.size(); }
  const char* c_str() const { return value.c_str(); }
  bool operator==(const char* s) const { return value == s; }
  bool operator==(const String& s) const { return value == s.value; }
};
enum PreferenceType { PT_INVALID, PT_STR, PT_U8 };
struct NvsValue { PreferenceType type; std::string string; uint8_t byte; };
inline std::map<std::string, NvsValue> nvs_values;
inline int nvs_writes = 0, nvs_fail_write = -1, nvs_opens = 0;
inline int nvs_side_effect_write = -1, nvs_fail_write_again = -1;
inline bool nvs_fail_forever = false, nvs_available = true;
inline bool nvs_write_allowed() {
  ++nvs_writes;
  if (nvs_writes == nvs_fail_write_again) return false;
  return nvs_fail_write < 0 || (nvs_fail_forever
      ? nvs_writes < nvs_fail_write : nvs_writes != nvs_fail_write);
}
struct Preferences {
  bool begin(const char* name, bool) {
    assert(std::string(name) == "mesh-wifi"); ++nvs_opens; return nvs_available;
  }
  void end() {}
  bool isKey(const char* key) { return nvs_values.count(key) != 0; }
  PreferenceType getType(const char* key) {
    return isKey(key) ? nvs_values.at(key).type : PT_INVALID;
  }
  String getString(const char* key, const char* fallback) {
    return getType(key) == PT_STR ? String(nvs_values.at(key).string) : String(fallback);
  }
  uint8_t getUChar(const char* key, uint8_t fallback) {
    return getType(key) == PT_U8 ? nvs_values.at(key).byte : fallback;
  }
  size_t putString(const char* key, const String& value) {
    const bool ok = nvs_write_allowed();
    if (ok || nvs_writes == nvs_side_effect_write) nvs_values[key] = {PT_STR, value.value, 0};
    return ok ? value.length() : 0;
  }
  size_t putUChar(const char* key, uint8_t value) {
    const bool ok = nvs_write_allowed();
    if (ok || nvs_writes == nvs_side_effect_write) nvs_values[key] = {PT_U8, {}, value};
    return ok ? 1 : 0;
  }
  bool remove(const char* key) {
    if (!nvs_write_allowed()) return false;
    nvs_values.erase(key); return true;
  }
};
inline void reset_nvs() {
  nvs_values.clear(); nvs_writes = nvs_opens = 0; nvs_fail_write = -1;
  nvs_fail_forever = false; nvs_available = true;
  nvs_side_effect_write = nvs_fail_write_again = -1;
}
