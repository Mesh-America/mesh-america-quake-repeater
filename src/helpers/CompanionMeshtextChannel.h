#pragma once

#include "CompanionChannelAlias.h"
#include "MeshtextChat.h"
#include <initializer_list>

namespace mesh { namespace mt {

struct Channel {
  char name[12] = {};
  uint8_t key[32] = {};
  size_t key_length = 16;
  Preset preset = Preset::LongFast;
  bool named_preset = false;
};

// The app retains its original label and PSK. Only this volatile wire copy
// expands a recognized public preset alias into the Meshtext AQ== key.
// Explicit private keys, including 256-bit keys, must never become public.
template <typename Hash>
bool describeChannel(const char* name, const uint8_t secret[32], Channel& out, Hash hash) {
  const auto alias = parseCompanionChannelAlias(name);
  if (alias.kind != CompanionChannelKind::Meshtext || !secret) return false;
  Channel result;
  result.named_preset = parsePreset(alias.tail, result.preset);
  const char* wire_name = result.named_preset ? presetName(result.preset) : alias.tail;
  if (!wire_name || !*wire_name || strlen(wire_name) >= sizeof(result.name)) return false;
  memcpy(result.name, wire_name, strlen(wire_name) + 1);
  memcpy(result.key, secret, sizeof(result.key));
  for (size_t i = 16; i < sizeof(result.key); ++i) {
    if (result.key[i]) result.key_length = 32;
  }
  if (alias.hashtag && result.key_length == 16) {
    uint8_t derived[16];
    hash(derived, sizeof(derived), reinterpret_cast<const uint8_t*>(name), strlen(name));
    char canonical[32];
    if (!companionChannelCanonicalName(name, canonical, sizeof(canonical))) return false;
    const bool app_derived = memcmp(derived, secret, sizeof(derived)) == 0;
    hash(derived, sizeof(derived), reinterpret_cast<const uint8_t*>(canonical), strlen(canonical));
    const bool canonical_derived = memcmp(derived, secret, sizeof(derived)) == 0;
    if (app_derived || canonical_derived) {
      if (result.named_preset) memcpy(result.key, DefaultPsk, sizeof(DefaultPsk));
      else memcpy(result.key, derived, sizeof(derived));
    }
  }
  bool nonzero = false;
  for (size_t i = 0; i < result.key_length; ++i) nonzero |= result.key[i] != 0;
  if (!nonzero) return false; // Never silently fall back to an open channel.
  out = result;
  return true;
}

// The 902-915 MHz portion is unambiguously US among supported plans; 915-928
// overlaps US and ANZ, so it requires an explicit region instead of guessing.
inline Region inferRegion(float primary_frequency) {
  if (primary_frequency >= 902 && primary_frequency < 915) return Region::US;
  if (primary_frequency >= 869.4f && primary_frequency <= 869.65f) return Region::EU868;
  if (primary_frequency >= 433 && primary_frequency <= 434) return Region::EU433;
  return Region::Unset;
}

inline const char* regionName(Region region) {
  switch (region) {
    case Region::US: return "us";
    case Region::EU868: return "eu868";
    case Region::EU433: return "eu433";
    case Region::ANZ: return "anz";
    default: return "auto";
  }
}

inline bool parseRegion(const char* value, Region& region) {
  if (!value) return false;
  for (Region item : {Region::Unset, Region::US, Region::EU868, Region::EU433, Region::ANZ}) {
    if (!strcmp(value, regionName(item))) { region = item; return true; }
  }
  return false;
}

inline bool sameModulation(const RadioProfileParams& a, const RadioProfileParams& b) {
  return a.bw == b.bw && a.sf == b.sf && a.cr == b.cr;
}

inline bool frequencyInRegion(Region region, const RadioProfileParams& p) {
  const float half_width = p.bw / 2000.0f;
  float lower = 0, upper = 0;
  switch (region) {
    case Region::US: lower = 902; upper = 928; break;
    case Region::ANZ: lower = 915; upper = 928; break;
    case Region::EU868: lower = 869.4f; upper = 869.65f; break;
    case Region::EU433: lower = 433; upper = 434; break;
    default: return false;
  }
  return p.freq - half_width >= lower - 0.0001f && p.freq + half_width <= upper + 0.0001f;
}

} } // namespace mesh::mt
