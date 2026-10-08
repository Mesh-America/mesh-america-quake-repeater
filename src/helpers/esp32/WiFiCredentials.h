#pragma once

#include <Preferences.h>
#include <helpers/CLICommandUtils.h>
#include <helpers/WiFiPowerSave.h>

namespace mesh {
namespace wifi {

// Read/write/resolve are loop-task-only, like CLI and queued portal writes.
// MQTT Core 0 uses a separate snapshot; it must never call this NVS API.
// Runtime only: the fixed /mqtt_prefs password field must remain 64 bytes.
struct Credentials {
  char ssid[32] = {};
  char password[65] = {};
  uint8_t power_save = kDefaultPowerSave;
};

enum class CredentialState { Absent, Unconfigured, Ready, Invalid, Unavailable };

inline CredentialState readCredentials(Credentials& out) {
  out = Credentials{};
  Preferences nvs;
  // Missing keys are normal on a fresh device; avoid Preferences NOT_FOUND logs.
  if (!nvs.begin("mesh-wifi", false)) return CredentialState::Unavailable;
  const bool ssid_present = nvs.isKey("ssid");
  const bool password_present = nvs.isKey("password");
  const bool ps_present = nvs.isKey("powersave");
  const bool pending_present = nvs.isKey("pending");
  bool valid = (!ssid_present || nvs.getType("ssid") == PT_STR)
      && (!password_present || nvs.getType("password") == PT_STR)
      && (!ps_present || nvs.getType("powersave") == PT_U8)
      && (!pending_present || (nvs.getType("pending") == PT_U8
                              && nvs.getUChar("pending", 1) == 0));
  const String ssid = ssid_present && valid ? nvs.getString("ssid", "") : String();
  const String password = password_present && valid ? nvs.getString("password", "") : String();
  out.power_save = ps_present && valid
      ? nvs.getUChar("powersave", kDefaultPowerSave) : kDefaultPowerSave;
  // Readers reject any write still in progress, including one that began
  // after the initial marker read. Firmware writers/readers run on the loop;
  // the MQTT worker only sees its frozen snapshot.
  valid = valid && (!nvs.isKey("pending")
      || (nvs.getType("pending") == PT_U8 && nvs.getUChar("pending", 1) == 0));
  nvs.end();
  valid = valid && ssid.length() < sizeof(out.ssid)
      && password.length() < sizeof(out.password)
      && cli::standaloneWiFiPasswordValid(password.c_str())
      && out.power_save <= kPowerSaveMax;
  if (!valid) { out = Credentials{}; return CredentialState::Invalid; }
  memcpy(out.ssid, ssid.c_str(), ssid.length() + 1);
  memcpy(out.password, password.c_str(), password.length() + 1);
  if (!ssid_present && !password_present) return CredentialState::Absent;
  // Historical SSID-only saves describe an open network. Password-only/empty
  // configurations never revive old credentials; interrupted writes are pending.
  return ssid_present && out.ssid[0]
      ? CredentialState::Ready : CredentialState::Unconfigured;
}

inline CredentialState resolveCredentials(Credentials& out,
    const char* legacy_ssid = nullptr, const char* legacy_password = nullptr,
    uint8_t legacy_power_save = kDefaultPowerSave) {
  const CredentialState state = readCredentials(out);
  if (state != CredentialState::Absent) return state;
  const uint8_t canonical_ps = out.power_save;
  Preferences nvs;
  if (!nvs.begin("mesh-wifi", false)) return CredentialState::Unavailable;
  const bool canonical_power_save = nvs.isKey("powersave");
  nvs.end();
  if (!legacy_ssid || !legacy_password) return state;
  const size_t ssid_len = strnlen(legacy_ssid, 32);
  const size_t password_len = strnlen(legacy_password, 64);
  if (ssid_len >= 32 || password_len >= 64
      || !cli::standaloneWiFiPasswordValid(legacy_password)) {
    out = Credentials{};
    return CredentialState::Invalid;
  }
  memcpy(out.ssid, legacy_ssid, ssid_len + 1);
  memcpy(out.password, legacy_password, password_len + 1);
  out.power_save = canonical_power_save ? canonical_ps
      : (legacy_power_save <= kPowerSaveMax ? legacy_power_save : kDefaultPowerSave);
  return ssid_len ? CredentialState::Ready : CredentialState::Unconfigured;
}

inline bool writeCredentials(const Credentials& candidate) {
  if (strnlen(candidate.ssid, sizeof(candidate.ssid)) >= sizeof(candidate.ssid)
      || strnlen(candidate.password, sizeof(candidate.password)) >= sizeof(candidate.password)
      || !cli::standaloneWiFiPasswordValid(candidate.password)
      || candidate.power_save > kPowerSaveMax) return false;
  Credentials previous;
  const CredentialState previous_state = readCredentials(previous);
  if (previous_state == CredentialState::Unavailable) return false;
  Preferences nvs;
  if (!nvs.begin("mesh-wifi", false)) return false;
  const bool had_ssid = nvs.isKey("ssid"), had_password = nvs.isKey("password");
  const bool had_ps = nvs.isKey("powersave");
  // Corrupt/held settings may be repaired by a complete explicit portal save.
  const String old_ssid = had_ssid ? nvs.getString("ssid", "") : String();
  const String old_password = had_password ? nvs.getString("password", "") : String();
  const uint8_t old_ps = had_ps ? nvs.getUChar("powersave", kDefaultPowerSave) : kDefaultPowerSave;
  // Fail closed if power is lost between independent NVS key writes.
  if (nvs.putUChar("pending", 1) != 1) { nvs.end(); return false; }
  nvs.putString("ssid", candidate.ssid);
  nvs.putString("password", candidate.password); // empty string can return zero
  nvs.putUChar("powersave", candidate.power_save);
  bool ok = nvs.getType("ssid") == PT_STR && nvs.getType("password") == PT_STR
      && nvs.getType("powersave") == PT_U8
      && nvs.getString("ssid", "\x01") == candidate.ssid
      && nvs.getString("password", "\x01") == candidate.password
      && nvs.getUChar("powersave", 255) == candidate.power_save;
  if (ok) ok = nvs.putUChar("pending", 0) == 1
      && nvs.getUChar("pending", 1) == 0;
  if (!ok) {
    // A failed commit can have changed the visible marker. Restore the barrier
    // before touching any rollback fields, or leave the complete candidate.
    const bool blocked = nvs.putUChar("pending", 1) == 1
        && nvs.getUChar("pending", 0) == 1;
    if (!blocked) { nvs.end(); return false; }
    if (had_ssid) nvs.putString("ssid", old_ssid); else nvs.remove("ssid");
    if (had_password) nvs.putString("password", old_password); else nvs.remove("password");
    if (had_ps) nvs.putUChar("powersave", old_ps); else nvs.remove("powersave");
    const bool restored = nvs.isKey("ssid") == had_ssid
        && nvs.isKey("password") == had_password && nvs.isKey("powersave") == had_ps
        && (!had_ssid || nvs.getString("ssid", "\x01") == old_ssid)
        && (!had_password || nvs.getString("password", "\x01") == old_password)
        && (!had_ps || nvs.getUChar("powersave", 255) == old_ps);
    if (restored && previous_state != CredentialState::Invalid) nvs.putUChar("pending", 0);
    // Otherwise leave pending=1: no consumer may use a partially saved pair.
  }
  nvs.end();
  return ok;
}

}  // namespace wifi
}  // namespace mesh
