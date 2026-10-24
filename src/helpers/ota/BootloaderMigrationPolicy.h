#pragma once

#include <stddef.h>
#include <stdint.h>
#include "OtaBootloaderUpdate.h"

namespace mesh {
namespace ota {
namespace migration {

static const uint32_t APP_CEILING = 0xED000u;
static const uint32_t BOOT_BASE = 0xF4000u;
static const uint32_t BOOT_SIZE = 0xA000u;
static const uint32_t PARAMS_BASE = 0xFE000u;
static const uint32_t SETTINGS_BASE = 0xFF000u;
static const uint32_t ACL_READ_DENIED = 1u << 2;
static const uint32_t ACL_WRITE_DENIED = 1u << 1;

struct AclRegion {
  uint32_t address;
  uint32_t size;
  uint32_t permissions;
};

struct Snapshot {
  uint32_t part;
  uint32_t flash_page_size;
  uint32_t flash_pages;
  uint32_t softdevice_size;
  uint16_t softdevice_fwid;
  uint32_t app_base;
  uint32_t app_ceiling;
  uint16_t expected_softdevice_fwid;
  uint32_t mbr_boot_override;
  uint32_t mbr_params_override;
  uint32_t uicr_boot;
  uint32_t uicr_params;
  uint32_t source;
  uint32_t source_size;
  uint32_t app_body_size;
  uint32_t app_image_size;
  AclRegion acl[8];
};

enum class Gate { Ok, Chip, Softdevice, BootAddress, ParamsAddress, Source, Protection };

inline bool overlaps(uint32_t start, uint32_t size, uint32_t lo, uint32_t hi) {
  return size && uint64_t(start) < hi && uint64_t(start) + size > lo;
}

inline Gate preflight(const Snapshot &s) {
  if (s.part != 0x52840u || s.flash_page_size != 4096u || s.flash_pages != 256u) return Gate::Chip;
  if ((s.app_base != 0x26000u && s.app_base != 0x27000u) ||
      s.app_ceiling > APP_CEILING || s.app_ceiling <= s.app_base ||
      s.softdevice_size != s.app_base || s.softdevice_fwid != s.expected_softdevice_fwid ||
      (s.app_base == 0x26000u ? s.softdevice_fwid != 0xB6u : s.softdevice_fwid != 0x123u))
    return Gate::Softdevice;
  const uint32_t boot = s.mbr_boot_override == UINT32_MAX ? s.uicr_boot : s.mbr_boot_override;
  const uint32_t params = s.mbr_params_override == UINT32_MAX ? s.uicr_params : s.mbr_params_override;
  if (boot != BOOT_BASE) return Gate::BootAddress;
  if (params != PARAMS_BASE) return Gate::ParamsAddress;
  // The source is a linked application resource, never SRAM, external memory,
  // a filesystem, the live bootloader, or a dynamically chosen scratch bank.
  if (s.source_size != BOOT_SIZE || (s.source & 3u) || s.source < s.app_base || !s.app_body_size ||
      s.app_body_size > s.app_ceiling - s.app_base ||
      s.app_image_size != uint64_t(s.app_body_size) + ENDF_LEN ||
      s.app_image_size > s.app_ceiling - s.app_base ||
      uint64_t(s.source) + BOOT_SIZE > uint64_t(s.app_base) + s.app_body_size)
    return Gate::Source;
  for (const auto &r : s.acl) {
    // nRF52840 ACL bit 2 denies reads; bit 1 denies writes. COPY_BL also needs its
    // parameter page writable. Never try to unlock an existing ACL region.
    if ((r.permissions & ACL_READ_DENIED) &&
        (overlaps(r.address, r.size, s.app_base, s.app_base + s.app_body_size) ||
         overlaps(r.address, r.size, BOOT_BASE, SETTINGS_BASE)))
      return Gate::Protection;
    if ((r.permissions & ACL_WRITE_DENIED) && overlaps(r.address, r.size, BOOT_BASE, SETTINGS_BASE))
      return Gate::Protection;
  }
  return Gate::Ok;
}

inline bool candidate_matches_resource(const OtaBootloaderIdentity &candidate,
                                      uint32_t board_id, const char name[16],
                                      uint32_t version, uint32_t app_base, uint16_t fwid) {
  return ota_bootloader_candidate_identity_canonical(candidate) &&
         candidate.board_id == board_id && memcmp(candidate.device_name, name, 16) == 0 &&
         candidate.boot_version == version &&
         ota_bootloader_continuity_matches_runtime(candidate, 140, fwid, app_base, 1);
}

inline bool installed_can_migrate(const OtaBootloaderIdentity &installed,
                                 const OtaBootloaderIdentity &candidate,
                                 bool has_legacy, bool legacy_hash_matches,
                                 uint32_t app_base, uint16_t fwid) {
  if (!installed.present)
    return has_legacy && legacy_hash_matches;
  return installed.crc_ok && installed.continuity_present &&
         ota_bootloader_identity_matches(installed, candidate) &&
         ota_bootloader_continuity_gate(installed, candidate, candidate.boot_version,
                                       140, fwid, app_base, 1) == OTA_BOOT_CONTINUITY_OK;
}

inline bool installed_up_to_date(const OtaBootloaderIdentity &installed,
                                 uint32_t board_id, const char name[16],
                                 uint32_t version, uint32_t app_base, uint16_t fwid) {
  return installed.present && installed.crc_ok &&
         installed.image_start == BOOT_BASE && installed.image_size == BOOT_SIZE &&
         installed.board_id == board_id && memcmp(installed.device_name, name, 16) == 0 &&
         ota_bootloader_continuity_matches_runtime(installed, 140, fwid, app_base, 1) &&
         installed.boot_version >= version;
}

} // namespace migration
} // namespace ota
} // namespace mesh
