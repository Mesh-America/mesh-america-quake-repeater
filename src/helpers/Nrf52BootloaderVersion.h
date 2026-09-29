#pragma once

#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "ota/OtaBootloaderUpdate.h"

namespace mesh {

struct Nrf52BootloaderRegion {
  uint32_t start = 0;
  uint32_t end = 0;
};

// The MBR's flash word takes precedence over UICR, just as it does at boot.
// Exclude the MBR-parameter and settings pages. Never search the application,
// an OTA staging slot, external flash, or beyond the chip's physical flash.
inline bool nrf52BootloaderRegion(uint32_t page_size, uint32_t page_count,
                                  uint32_t mbr_start, uint32_t uicr_start,
                                  Nrf52BootloaderRegion& region) {
  region = Nrf52BootloaderRegion();
  if (page_size != 4096u || page_count < 16u || page_count > 256u) return false;
  const uint32_t flash_size = page_size * page_count;
  const uint32_t end = flash_size - 2u * page_size;
  uint32_t start = mbr_start != UINT32_MAX ? mbr_start : uicr_start;
  // Historical Adafruit/OTAFIX installations can have both words erased.
  // Their 40 KiB layout is accepted only with valid vectors by the reader.
  if (start == UINT32_MAX) start = end - 0xA000u;
  if (start < 0x10000u || start >= end || start % page_size != 0u) return false;
  region.start = start;
  region.end = end;
  return true;
}

inline bool nrf52BootloaderVectorsValid(const uint8_t* image, size_t size,
                                        uint32_t start) {
  if (!image || size < 8u || size > UINT32_MAX - start) return false;
  const uint32_t sp = ota::ota_boot_rd32(image);
  const uint32_t reset = ota::ota_boot_rd32(image + 4u);
  return sp > 0x20000000u && sp <= 0x20040000u && (sp & 7u) == 0u &&
         (reset & 1u) != 0u && (reset & ~1u) >= start &&
         (reset & ~1u) < start + size;
}

inline bool nrf52BootVersionChar(uint8_t c) {
  return (c >= '0' && c <= '9') || (c >= 'A' && c <= 'Z') ||
         (c >= 'a' && c <= 'z') || c == '.' || c == '-' || c == '_' || c == '+';
}

// Return the complete token, never a truncated (and possibly different) version.
// An embedded marker literal with no actual version is not an INFO_UF2 record.
// Some Seeed stock bootloaders declare two components (e.g. "1.00"). Preserve
// those bytes; adding a synthetic patch number would misreport their version.
inline size_t nrf52BootVersionTokenSize(const uint8_t* token, size_t available) {
  size_t pos = available && token[0] == 'v' ? 1u : 0u;
  for (unsigned component = 0; component < 3u; ++component) {
    const size_t begin = pos;
    while (pos < available && token[pos] >= '0' && token[pos] <= '9') ++pos;
    if (pos == begin) return 0;
    if (component == 2u) break;
    if (component == 1u && (pos >= available || token[pos] != '.')) break;
    if (pos >= available || token[pos++] != '.') return 0;
  }
  size_t n = 0;
  for (; n < available && n <= 127u; ++n) {
    const uint8_t c = token[n];
    if (c == 0 || c == ' ' || c == '\t' || c == '\r' || c == '\n')
      return n;
    if (!nrf52BootVersionChar(c)) return 0;
  }
  return 0; // unterminated or too long
}

inline bool nrf52BootDecimalComponent(const uint8_t* token, size_t length, size_t& pos) {
  const size_t begin = pos;
  while (pos < length && token[pos] >= '0' && token[pos] <= '9') ++pos;
  return pos != begin;
}

// Recent OTAFIX images embed the INFO_UF2 version value without the older
// "UF2 Bootloader " label. Match only that explicit version shape, not an
// arbitrary dotted number or a SoftDevice/application string.
inline bool nrf52BootStandaloneOtafixToken(const uint8_t* token, size_t length) {
  if (!token || length == 0u || token[0] != 'v') return false;
  size_t pos = 1u;
  for (unsigned component = 0; component < 3u; ++component) {
    if (!nrf52BootDecimalComponent(token, length, pos)) return false;
    if (component != 2u && (pos >= length || token[pos++] != '.')) return false;
  }
  static const char marker[] = "-OTAFIX";
  const size_t marker_size = sizeof(marker) - 1u;
  if (length - pos < marker_size || memcmp(token + pos, marker, marker_size) != 0)
    return false;
  pos += marker_size;
  if (!nrf52BootDecimalComponent(token, length, pos) ||
      pos >= length || token[pos++] != '.' ||
      !nrf52BootDecimalComponent(token, length, pos)) return false;
  if (pos < length && token[pos] == '.') {
    ++pos;
    if (!nrf52BootDecimalComponent(token, length, pos)) return false;
  }
  return pos == length || token[pos] == '-' || token[pos] == '+' || token[pos] == '_';
}

inline bool nrf52BootloaderVersion(const uint8_t* image, size_t size,
                                   uint32_t start, uint32_t cached_base_version,
                                   char* out, size_t capacity) {
  if (!out || capacity == 0u) return false;
  out[0] = 0;
  if (capacity < 2u || !nrf52BootloaderVectorsValid(image, size, start)) return false;

  static const char marker[] = "UF2 Bootloader ";
  const size_t marker_size = sizeof(marker) - 1u;
  const uint8_t* selected = nullptr;
  size_t selected_size = 0;
  bool conflicting = false;
  for (size_t offset = 0; offset + marker_size < size; ++offset) {
    if (image[offset] != 'U' || memcmp(image + offset, marker, marker_size) != 0) continue;
    const uint8_t* token = image + offset + marker_size;
    const size_t length = nrf52BootVersionTokenSize(token, size - offset - marker_size);
    if (length == 0u) continue;
    if (selected && (length != selected_size || memcmp(selected, token, length) != 0))
      conflicting = true;
    selected = token;
    selected_size = length;
  }
  if (selected && !conflicting) {
    if (selected_size >= capacity) return false;
    memcpy(out, selected, selected_size);
    out[selected_size] = 0;
    return true;
  }

  // Reuse the installer's whole-image CRC and unique BLMF/BLM2 validation.
  // Metadata contains the OTAFIX version, not Adafruit's base release number;
  // do not fabricate a 0.x.y prefix when INFO_UF2 is absent or ambiguous.
  ota::OtaBootloaderIdentity identity;
  if (start == ota::OTA_BOOT_IMAGE_START && size == ota::OTA_BOOT_IMAGE_SIZE &&
      ota::ota_bootloader_identity_from_image(image, size, identity) &&
      identity.continuity_present) {
    const uint32_t version = identity.boot_version;
    const unsigned preview = version & 0xffu;
    int written;
    if (preview == 0xffu) {
      written = snprintf(out, capacity, "OTAFIX%u.%u.%u",
                         (unsigned)(version >> 24), (unsigned)((version >> 16) & 0xffu),
                         (unsigned)((version >> 8) & 0xffu));
    } else {
      written = snprintf(out, capacity, "OTAFIX%u.%u.%u-preview.%u",
                         (unsigned)(version >> 24), (unsigned)((version >> 16) & 0xffu),
                         (unsigned)((version >> 8) & 0xffu), preview);
    }
    if (written > 0 && (size_t)written < capacity) return true;
    out[0] = 0;
    return false;
  }
  if (conflicting) return false;

  // Only as a fallback, inspect at most the first 40 KiB of the already
  // identified bootloader region. A unique standalone OTAFIX version is useful
  // on boards whose installed image lacks a reader-recognized BLMF identity.
  // If a canonical identity is present but corrupt, do not let its printable
  // version string make that image look healthy.
  bool allow_standalone = true;
  if (size == ota::OTA_BOOT_IMAGE_SIZE) {
    const size_t offset = ota::OTA_BOOT_CANDIDATE_MANIFEST_OFFSET;
    const bool magic0 = ota::ota_boot_rd32(image + offset) == ota::OTA_BOOT_MANIFEST_MAGIC0;
    const bool magic1 = ota::ota_boot_rd32(image + offset + 4u) == ota::OTA_BOOT_MANIFEST_MAGIC1;
    if (magic0 || magic1) {
      ota::OtaBootloaderIdentity continuity;
      allow_standalone =
          magic0 && magic1 &&
          ota::ota_boot_rd16(image + offset + 8u) == ota::OTA_BOOT_MANIFEST_VERSION &&
          ota::ota_boot_rd16(image + offset + 10u) == ota::OTA_BOOT_MANIFEST_SIZE &&
          ota::ota_boot_rd32(image + offset + 12u) == ota::OTA_BOOT_IMAGE_START &&
          ota::ota_boot_rd32(image + offset + 16u) == ota::OTA_BOOT_IMAGE_SIZE &&
          ota::ota_bootloader_board_id_valid(ota::ota_boot_rd32(image + offset + 20u)) &&
          ota::ota_boot_image_crc32(image, size, offset + 40u) ==
              ota::ota_boot_rd32(image + offset + 40u) &&
          ota::ota_bootloader_continuity_parse(image + offset, size - offset,
                                                continuity) &&
          continuity.continuity_present;
    }
  }
  const size_t scan_size = size < ota::OTA_BOOT_IMAGE_SIZE ? size : ota::OTA_BOOT_IMAGE_SIZE;
  const uint8_t* standalone = nullptr;
  size_t standalone_size = 0;
  for (size_t offset = 0; allow_standalone && offset < scan_size; ++offset) {
    if (image[offset] != 'v' ||
        (offset != 0u && nrf52BootVersionChar(image[offset - 1u]))) continue;
    const uint8_t* token = image + offset;
    const size_t length = nrf52BootVersionTokenSize(token, scan_size - offset);
    if (length == 0u || !nrf52BootStandaloneOtafixToken(token, length)) continue;
    if (standalone &&
        (length != standalone_size || memcmp(standalone, token, length) != 0)) return false;
    standalone = token;
    standalone_size = length;
  }
  if (standalone) {
    if (standalone_size >= capacity) return false;
    memcpy(out, standalone, standalone_size);
    out[standalone_size] = 0;
    return true;
  }

  // Adafruit's core captures TIMER2->CC[0] at startup, before the timer can
  // be reused. This is only a base version (no OTAFIX/fork suffix). Never read
  // the live timer here or reinterpret Nordic settings with a different layout.
  if (cached_base_version != 0u && cached_base_version <= 0x00ffffffu) {
    const int written = snprintf(out, capacity, "%u.%u.%u (base)",
                                 (unsigned)(cached_base_version >> 16),
                                 (unsigned)((cached_base_version >> 8) & 0xffu),
                                 (unsigned)(cached_base_version & 0xffu));
    if (written > 0 && (size_t)written < capacity) return true;
    out[0] = 0;
  }
  return false;
}

} // namespace mesh
