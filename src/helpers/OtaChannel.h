#pragma once
#include <stdint.h>
#include <string.h>
#include <limits.h>

// OTA release-channel selector, persisted in NodePrefs::ota_channel.
enum OtaChannel : uint8_t {
  OTA_CH_NATIVE = 0,  // follow the channel this build was made for
  OTA_CH_STABLE = 1,  // production
  OTA_CH_DEV    = 2,  // beta
};

// Resolve the effective manifest base URL for a channel selector.
// build.sh injects the three bases as compile-time macros:
//   OTA_MANIFEST_BASE        = this build's native channel (defined on every OTA build)
//   OTA_MANIFEST_BASE_STABLE = stable (production) channel
//   OTA_MANIFEST_BASE_DEV    = dev (beta) channel
// stable/dev fall back to the native base when their macro is undefined (legacy/local
// builds that only define OTA_MANIFEST_BASE), so this never returns nullptr on an
// OTA-capable build. On a non-OTA build it returns nullptr.
//
// Each base is stored behind an "ota-base-<channel>:" tag so CI can read a binary's
// channels back with scripts/verify_ota_channel.py. Returning a pointer
// into the tagged array keeps the tag referenced, so the linker cannot drop it.
#if defined(OTA_MANIFEST_BASE)
#define OTA_BASE_TAG_NATIVE "ota-base-native:"
#define OTA_BASE_TAG_STABLE "ota-base-stable:"
#define OTA_BASE_TAG_DEV    "ota-base-dev:"
#if !defined(OTA_MANIFEST_BASE_STABLE)
#define OTA_MANIFEST_BASE_STABLE OTA_MANIFEST_BASE
#endif
#if !defined(OTA_MANIFEST_BASE_DEV)
#define OTA_MANIFEST_BASE_DEV OTA_MANIFEST_BASE
#endif
static const char ota_tagged_native[] = OTA_BASE_TAG_NATIVE OTA_MANIFEST_BASE;
static const char ota_tagged_stable[] = OTA_BASE_TAG_STABLE OTA_MANIFEST_BASE_STABLE;
static const char ota_tagged_dev[]    = OTA_BASE_TAG_DEV OTA_MANIFEST_BASE_DEV;
#endif

static inline const char* ota_resolve_base(uint8_t channel) {
#if defined(OTA_MANIFEST_BASE)
  switch (channel) {
    case OTA_CH_STABLE: return ota_tagged_stable + sizeof(OTA_BASE_TAG_STABLE) - 1;
    case OTA_CH_DEV:    return ota_tagged_dev + sizeof(OTA_BASE_TAG_DEV) - 1;
    case OTA_CH_NATIVE:
    default:            return ota_tagged_native + sizeof(OTA_BASE_TAG_NATIVE) - 1;
  }
#else
  (void)channel;
  return nullptr;
#endif
}

// Human label for a selector (for the `ota branch` report).
static inline const char* ota_channel_name(uint8_t channel) {
  switch (channel) {
    case OTA_CH_STABLE: return "prod";
    case OTA_CH_DEV:    return "beta";
    default:            return "default";
  }
}

// Label for the channel this build was made for, by matching its native base.
static inline const char* ota_native_channel_name() {
  const char* native = ota_resolve_base(OTA_CH_NATIVE);
  if (native == nullptr) return "none";
  if (strcmp(native, ota_resolve_base(OTA_CH_STABLE)) == 0) return "prod";
  if (strcmp(native, ota_resolve_base(OTA_CH_DEV)) == 0) return "beta";
  return "custom";
}

// Parse an `ota branch` argument. Returns true and sets *out on a known keyword
// (prod|stable, beta|dev, default); returns false and leaves *out untouched otherwise.
static inline bool ota_parse_channel(const char* arg, uint8_t* out) {
  if (strcmp(arg, "prod") == 0 || strcmp(arg, "stable") == 0) { *out = OTA_CH_STABLE; return true; }
  if (strcmp(arg, "beta") == 0 || strcmp(arg, "dev") == 0)    { *out = OTA_CH_DEV;    return true; }
  if (strcmp(arg, "default") == 0)                            { *out = OTA_CH_NATIVE; return true; }
  return false;
}

// Compatibility tag, read from the download before committing a channel switch.
// A switch can land on an older build, which would boot without state it cannot read
// or without a transport this node depends on. Bump OTA_STATE_GEN when a build starts
// storing state that older builds cannot read.
// Generation numbers are only comparable within a state format family. This fork
// writes /com_prefs and versioned /mqtt_prefs; upstream's generation 2 means
// /mqtt.json and does not promise it preserves this fork's common preference tail.
// Require the explicit keymind1 capability as well as the generation, so a larger
// upstream generation cannot accidentally authorize a cross-fork state downgrade.
#ifndef OTA_STATE_GEN
#define OTA_STATE_GEN 1
#endif
#define OTA_CAP_ETH 0x01  // carries MQTT over Ethernet
#define OTA_CAP_KEYMIND_PREFS 0x02  // preserves this fork's binary common/MQTT state
#if defined(NETWORK_PREFER_ETHERNET)
#define OTA_CAPS_STR "+keymind1+eth"
#else
#define OTA_CAPS_STR "+keymind1"
#endif
#define OTA_STR_(x) #x
#define OTA_STR(x) OTA_STR_(x)
#define OTA_COMPAT_TAG "ota-compat:"
static const char ota_compat_tag[] = OTA_COMPAT_TAG OTA_STR(OTA_STATE_GEN) OTA_CAPS_STR;

struct OtaCompat {
  int gen;
  uint8_t caps;
};

// Parse the tag value "<gen>[+cap...]"; unknown caps are ignored.
static inline bool ota_compat_parse(const char* s, OtaCompat* out) {
  if (*s < '0' || *s > '9') return false;
  OtaCompat parsed = {0, 0};
  while (*s >= '0' && *s <= '9') {
    const int digit = *s++ - '0';
    if (parsed.gen > (INT_MAX - digit) / 10) return false;
    parsed.gen = parsed.gen * 10 + digit;
  }
  while (*s == '+') {
    const char* cap = ++s;
    while (*s && *s != '+') s++;
    if (s == cap) return false;
    if ((size_t)(s - cap) == 3 && memcmp(cap, "eth", 3) == 0) parsed.caps |= OTA_CAP_ETH;
    if ((size_t)(s - cap) == 8 && memcmp(cap, "keymind1", 8) == 0) parsed.caps |= OTA_CAP_KEYMIND_PREFS;
  }
  if (*s != 0) return false;
  *out = parsed;
  return true;
}

// Find the tag in an image chunk; returns the NUL-terminated value text, or nullptr when
// the chunk holds no complete tag. Skips the bare OTA_COMPAT_TAG search literal, which
// every image also contains.
static inline const char* ota_compat_find(const uint8_t* buf, size_t len) {
  const size_t tag_len = sizeof(OTA_COMPAT_TAG) - 1;
  for (size_t i = 0; i + tag_len < len; i++) {
    if (memcmp(buf + i, OTA_COMPAT_TAG, tag_len) != 0) continue;
    if (buf[i + tag_len] < '0' || buf[i + tag_len] > '9') continue;
    if (memchr(buf + i + tag_len, 0, len - i - tag_len)) return (const char*)buf + i + tag_len;
  }
  return nullptr;
}

// A target must read this node's state and keep every transport this node has.
static inline bool ota_compat_ok(const OtaCompat& own, const OtaCompat& target) {
  return target.gen >= own.gen && (target.caps & own.caps) == own.caps;
}

// Inspect only bytes received for this download, including tags split across
// arbitrary HTTP reads. Oversized or incomplete values fail closed. A bare
// search literal or malformed candidate is not a tag.
// Duplicate tags must match exactly, including capabilities unknown to this
// firmware, matching the publish verifier's unique compatibility-tag contract.
class OtaCompatScanner {
  static constexpr size_t kValueSize = 64;
  size_t _prefix = 0;
  size_t _length = 0;
  bool _reading = false;
  bool _found = false;
  bool _conflicting = false;
  OtaCompat _compat = {0, 0};
  char _value[kValueSize] = {};
  char _candidate[kValueSize] = {};

  void complete() {
    _candidate[_length] = 0;
    OtaCompat parsed;
    if (ota_compat_parse(_candidate, &parsed)) {
      if (_found && strcmp(_candidate, _value) != 0) {
        _conflicting = true;
      } else if (!_found) {
        _compat = parsed;
        strcpy(_value, _candidate);
        _found = true;
      }
    }
  }

public:
  void consume(const uint8_t* bytes, size_t size) {
    for (size_t i = 0; i < size; ++i) {
      const uint8_t byte = bytes[i];
      if (_reading) {
        // The search literal itself ends at the colon. Only a digit starts a
        // value; a following 'o' may begin another tag, so reuse that byte below.
        if (_length == 0 && (byte < '0' || byte > '9')) {
          _reading = false;
        } else if (byte == 0) {
          complete();
          _reading = false;
          _length = 0;
          continue;
        } else {
          if (_length + 1 >= sizeof(_candidate)) {
            _conflicting = true;
          } else {
            _candidate[_length++] = (char)byte;
          }
          continue;
        }
      }
      _prefix = byte == OTA_COMPAT_TAG[_prefix] ? _prefix + 1
          : (byte == OTA_COMPAT_TAG[0] ? 1 : 0);
      if (_prefix == sizeof(OTA_COMPAT_TAG) - 1) {
        _prefix = 0;
        _length = 0;
        _reading = true;
      }
    }
  }

  bool finish(OtaCompat* out) const {
    if (!_found || _conflicting || (_reading && _length != 0)) return false;
    *out = _compat;
    return true;
  }
};
