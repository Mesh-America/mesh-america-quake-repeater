#include "NRF52VoltagePolicy.h"

#if defined(NRF52_PLATFORM) && defined(NRF52_POWER_MANAGEMENT)
#include <InternalFileSystem.h>
#include "IdentityStore.h"
#include "AtomicFileWriter.h"
#include "PersistentStoreFormat.h"
#include <stdio.h>
#include <string.h>

// A Companion using resilient internal ExtraFS has a custom primary LittleFS
// geometry. Its application supplies that config; ordinary roles use default.
extern "C" struct lfs_config* meshNrf52VoltagePrimaryFsConfig()
    __attribute__((weak));

namespace mesh {
namespace power {

static const char* POLICY_PATH = "/pwrmgt_v1";
enum Profile : uint8_t { LI_ION = 0, LIFEPO4 = 1, CUSTOM = 2 };
static bool supported = false;
static bool boot_off_allowed = false;
static uint16_t board_bootlock = 0;
static uint16_t saved_bootlock = 0;
static uint16_t saved_cutoff = 0;
static uint16_t empty_mv = 3000;
static uint16_t full_mv = 4200;
static uint16_t adc_permille = 1000;
static Profile profile = LI_ION;

static bool validPercentRange(uint16_t empty, uint16_t full, Profile kind) {
  return empty >= (kind == CUSTOM ? MIN_CUSTOM_MV : MIN_CONFIGURED_MV)
      && full <= MAX_CONFIGURED_MV
      && full >= empty + 100;
}

static void encode(uint8_t (&data)[20], uint16_t boot, uint16_t low,
                   uint16_t empty, uint16_t full, uint16_t adc, Profile kind) {
  data[0] = 'N'; data[1] = 'V'; data[2] = 'P'; data[3] = '2';
  mesh::storage::writeLE16(data + 4, boot);
  mesh::storage::writeLE16(data + 6, low);
  mesh::storage::writeLE16(data + 8, empty);
  mesh::storage::writeLE16(data + 10, full);
  mesh::storage::writeLE16(data + 12, adc);
  data[14] = kind;
  data[15] = 0;
  mesh::storage::writeLE32(data + 16,
      mesh::storage::updateCRC32(0xFFFFFFFFUL, data, 16));
}

static void readMountedPolicy() {
  File file(InternalFS);
  if (!file.open(POLICY_PATH, FILE_O_READ)) return;
  uint8_t data[20];
  const size_t length = file.size();
  const bool complete = (length == 12 || length == sizeof(data))
      && file.read(data, length) == length;
  file.close();
  if (!complete || memcmp(data, "NVP", 3) != 0) return;
  const bool old_format = length == 12 && data[3] == '1';
  const bool new_format = length == 20 && data[3] == '2';
  if ((!old_format && !new_format)
      || mesh::storage::readLE32(data + length - 4)
          != mesh::storage::updateCRC32(0xFFFFFFFFUL, data, length - 4)) return;
  const uint16_t boot = mesh::storage::readLE16(data + 4);
  const uint16_t low = mesh::storage::readLE16(data + 6);
  const Profile kind = new_format ? static_cast<Profile>(data[14]) : LI_ION;
  if (new_format && (data[14] > CUSTOM || data[15] != 0)) return;
  if (!validThresholdPair(boot, low, boot_off_allowed,
                          kind == CUSTOM ? MIN_CUSTOM_MV : MIN_CONFIGURED_MV)) return;
  if (new_format) {
    const uint16_t empty = mesh::storage::readLE16(data + 8);
    const uint16_t full = mesh::storage::readLE16(data + 10);
    const uint16_t adc = mesh::storage::readLE16(data + 12);
    if (!validPercentRange(empty, full, kind) || adc < 500 || adc > 1500) return;
    empty_mv = empty;
    full_mv = full;
    adc_permille = adc;
    profile = static_cast<Profile>(data[14]);
  }
  saved_bootlock = boot;
  saved_cutoff = low;
}

void loadVoltagePolicyAtBoot(uint16_t board_default_mv) {
  supported = true;
  board_bootlock = board_default_mv;
  boot_off_allowed = board_default_mv == 0;
  saved_bootlock = board_default_mv;
  saved_cutoff = 0;
  empty_mv = 3000;
  full_mv = 4200;
  adc_permille = 1000;
  profile = LI_ION;

  struct lfs_config* config = meshNrf52VoltagePrimaryFsConfig
      ? meshNrf52VoltagePrimaryFsConfig() : nullptr;
  const bool mounted = config == nullptr
      ? InternalFS.Adafruit_LittleFS::begin()
      : InternalFS.Adafruit_LittleFS::begin(config);
  if (mounted) readMountedPolicy();
  // Never call InternalFileSystem::begin() here: it auto-formats on failure.
  // The role's ordinary primary mount retains its existing recovery behavior.
  InternalFS.end();
}

bool voltagePolicySupported() { return supported; }
bool bootlockOffAllowed() { return boot_off_allowed; }
uint16_t configuredBootlock() { return saved_bootlock; }
uint16_t configuredCutoff() { return saved_cutoff; }
uint16_t configuredEmpty() { return empty_mv; }
uint16_t configuredFull() { return full_mv; }
uint16_t configuredAdcPermille() { return adc_permille; }
uint8_t configuredBatteryPercent(uint16_t mv) {
  return batteryPercent(mv, empty_mv, full_mv);
}

static bool save(uint16_t boot, uint16_t low, uint16_t empty, uint16_t full,
                 uint16_t adc, Profile kind) {
  if (!supported || !validThresholdPair(boot, low, boot_off_allowed,
                    kind == CUSTOM ? MIN_CUSTOM_MV : MIN_CONFIGURED_MV)
      || !validPercentRange(empty, full, kind)
      || adc < 500 || adc > 1500) return false;
  uint8_t data[20];
  encode(data, boot, low, empty, full, adc, kind);
  mesh::AtomicFileWriter writer(&InternalFS, POLICY_PATH);
  if (!writer || writer.write(data, sizeof(data)) != sizeof(data)
      || !writer.commit()) return false;
  saved_bootlock = boot;
  saved_cutoff = low;
  empty_mv = empty;
  full_mv = full;
  adc_permille = adc;
  profile = kind;
  return true;
}

bool setConfiguredBootlock(uint16_t mv) {
  return save(mv, saved_cutoff, empty_mv, full_mv, adc_permille, profile);
}
bool setConfiguredCutoff(uint16_t mv) {
  return save(saved_bootlock, mv, empty_mv, full_mv, adc_permille, profile);
}

static bool matchKey(const char* command, const char* key, bool set) {
  const char* prefix = set ? "set " : "get ";
  if (strncmp(command, prefix, 4) != 0) return false;
  command += 4;
  const size_t len = strlen(key);
  return strncmp(command, key, len) == 0
      && (command[len] == 0 || command[len] == ' ' || command[len] == '\t');
}

static const char* const KEYS[] = {
  "pwrmgt.bootlock", "pwrmgt.cutoff", "battery.profile",
  "battery.empty", "battery.full", "adc.multiplier"
};

static int commandKey(const char* command, bool set) {
  if (command == nullptr) return -1;
  for (unsigned i = 0; i < sizeof(KEYS) / sizeof(KEYS[0]); ++i) {
    if (matchKey(command, KEYS[i], set)) return (int)i;
  }
  return -1;
}

bool isVoltagePolicyCommand(const char* command) {
  return commandKey(command, false) >= 0 || commandKey(command, true) >= 0;
}

// Exact decimal with up to three fractional places. Zero restores factory scale.
static bool parseAdcPermille(const char* value, uint16_t& out) {
  if (*value == 0) return false;
  uint32_t whole = 0, fraction = 0;
  unsigned digits = 0;
  bool dot = false;
  for (const char* p = value; *p; ++p) {
    if (*p == '.') {
      if (dot) return false;
      dot = true;
    } else if (*p >= '0' && *p <= '9') {
      if (!dot) {
        whole = whole * 10 + (*p - '0');
        if (whole > 1) return false;
      } else {
        if (++digits > 3) return false;
        fraction = fraction * 10 + (*p - '0');
      }
    } else return false;
  }
  if (dot && digits == 0) return false;
  while (digits++ < 3) fraction *= 10;
  const uint32_t result = whole * 1000 + fraction;
  if (result == 0) { out = 1000; return true; }
  if (result < 500 || result > 1500) return false;
  out = (uint16_t)result;
  return true;
}

bool handleVoltagePolicyCommand(const char* command, char* reply,
                                size_t reply_capacity) {
  if (reply == nullptr || reply_capacity == 0) return false;
  const bool set = command != nullptr && strncmp(command, "set ", 4) == 0;
  const int key = commandKey(command, set);
  if (key < 0) return false;
  if (!supported) {
    snprintf(reply, reply_capacity, "Error: voltage policy unsupported");
    return true;
  }
  const char* value = command + 4 + strlen(KEYS[key]);
  while (*value == ' ' || *value == '\t') ++value;

  if (!set) {
    if (*value != 0) snprintf(reply, reply_capacity, "Error: get %s", KEYS[key]);
    else if (key == 0 || key == 1) {
      const uint16_t mv = key == 0 ? saved_bootlock : saved_cutoff;
      if (mv == 0) snprintf(reply, reply_capacity, "> off");
      else snprintf(reply, reply_capacity, "> %u mV", (unsigned)mv);
    } else if (key == 2) {
      snprintf(reply, reply_capacity, "> %s",
               profile == LIFEPO4 ? "lifepo4" : profile == CUSTOM ? "custom" : "liion");
    } else if (key == 5) {
      snprintf(reply, reply_capacity, "> %u.%03u",
               (unsigned)(adc_permille / 1000), (unsigned)(adc_permille % 1000));
    } else {
      snprintf(reply, reply_capacity, "> %u mV",
               (unsigned)(key == 3 ? empty_mv : full_mv));
    }
    return true;
  }

  if (key == 2) {
    uint16_t boot = saved_bootlock, low = saved_cutoff;
    uint16_t empty = empty_mv, full = full_mv;
    Profile next = profile;
    if (strcmp(value, "lifepo4") == 0) {
      next = LIFEPO4; boot = 2900; low = 2700; empty = 2700; full = 3550;
    } else if (strcmp(value, "liion") == 0) {
      next = LI_ION; boot = board_bootlock; low = 0; empty = 3000; full = 4200;
    } else if (strcmp(value, "custom") == 0) next = CUSTOM;
    else {
      snprintf(reply, reply_capacity, "Error: profile liion|lifepo4|custom");
      return true;
    }
    if (!save(boot, low, empty, full, adc_permille, next))
      snprintf(reply, reply_capacity, "Error: battery profile could not be saved");
    else snprintf(reply, reply_capacity, "OK - %s profile saved; reboot for bootlock", value);
    return true;
  }

  if (key == 5) {
    uint16_t adc;
    if (!parseAdcPermille(value, adc))
      snprintf(reply, reply_capacity, "Error: multiplier 0 or 0.500-1.500");
    else if (!save(saved_bootlock, saved_cutoff, empty_mv, full_mv, adc, profile))
      snprintf(reply, reply_capacity, "Error: multiplier could not be saved");
    else snprintf(reply, reply_capacity, "OK - ADC multiplier %u.%03u saved",
                  (unsigned)(adc / 1000), (unsigned)(adc % 1000));
    return true;
  }

  uint16_t mv = 0;
  const uint16_t minimum = (profile == CUSTOM || key == 3 || key == 4)
      ? MIN_CUSTOM_MV : MIN_CONFIGURED_MV;
  if (!parseVoltageMillivolts(value, mv,
                              key == 1 || (key == 0 && boot_off_allowed), minimum)) {
    snprintf(reply, reply_capacity, "Error: set %s %s%u-4200",
             KEYS[key], (key == 1 || (key == 0 && boot_off_allowed)) ? "off|" : "",
             (unsigned)minimum);
  } else if (key == 0 && saved_cutoff != 0 && (mv == 0 || mv < saved_cutoff)) {
    snprintf(reply, reply_capacity, "Error: bootlock must be at least cutoff");
  } else if (key == 1 && mv != 0 && (saved_bootlock == 0 || mv > saved_bootlock)) {
    snprintf(reply, reply_capacity, "Error: cutoff must not exceed bootlock");
  } else if ((key == 3 && mv + 100 > full_mv)
      || (key == 4 && mv < empty_mv + 100)) {
    snprintf(reply, reply_capacity, "Error: full must exceed empty by 100 mV");
  } else {
    const bool ok = save(key == 0 ? mv : saved_bootlock,
                         key == 1 ? mv : saved_cutoff,
                         key == 3 ? mv : empty_mv,
                         key == 4 ? mv : full_mv,
                         adc_permille, key >= 3 ? CUSTOM : profile);
    if (!ok) snprintf(reply, reply_capacity, "Error: voltage setting could not be saved");
    else snprintf(reply, reply_capacity, "OK - %s %s%s%s", KEYS[key], value,
                  key == 0 ? "; reboot required" : " (saved)",
                  mv != 0 && mv < MIN_CONFIGURED_MV
                    ? "; WARNING: below 2500 mV risks brownout/flash failure" : "");
  }
  return true;
}

} // namespace power
} // namespace mesh
#endif
