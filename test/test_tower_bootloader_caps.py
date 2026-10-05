"""Check actual nRF52 capability parsing for SD-primary Tower storage."""

from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools/mota"))
import motalib as ml
from test_mota import _generic_bootloader_image, _rewrite_boot_image


SOURCE = r'''
#include <cassert>
#include <cstring>
#include <sys/mman.h>
#include "helpers/ota/OtaBlInfo.h"

using namespace mesh::ota;

static const uint8_t bundle[32] = {
  'M','O','T','A','R','A','M','A',1,0,72,0,0,0,1,0,
  'M','O','T','A','S','T','O','R',1,0,16,0,2,0,0,0,
};

static void imageFor(uint8_t* image, uint8_t primary, uint8_t optional) {
  memset(image, 0, 256);
  const uint8_t boot[16] = {
    'M','O','T','A','B','L','D','R',3,0,5,0,0,0,0,0,
  };
  memcpy(image, boot, sizeof(boot));
  image[12] = primary;
  if (optional) {
    memcpy(image + 32, bundle, sizeof(bundle));
    image[60] = optional;
  }
}

static void expectViews(const uint8_t* image, uint8_t primary,
                        uint8_t application, uint8_t optional) {
  const OtaBlCaps app = ota_bl_app_caps_scan(image, 256);
  assert(app.present && app.storage_flags == application);
  assert(app.optional_app_storage == optional);
  const OtaBlCaps update = ota_bl_update_caps_scan_aligned(image, 256, primary);
  assert(update.present && update.storage_flags == primary);
  assert(update.optional_app_storage == optional);
}

int main() {
  uint8_t image[256];
  imageFor(image, 0x09, 0x02);
  expectViews(image, 0x09, 0x0B, 0x02);
  assert(ota_bootloader_supports_expanded_stage(ota_bl_app_caps_scan(image, 256)));
  assert(ota_nrf52_effective_stage_ceiling(ota_bl_app_caps_scan(image, 256)) == 0xED000);

  // An ordinary SD loader remains valid for SD and privileged SD upgrades,
  // but its primary marker must never be mistaken for internal support.
  imageFor(image, 0x09, 0);
  expectViews(image, 0x09, 0x09, 0);
  assert(!ota_bootloader_supports_expanded_stage(ota_bl_app_caps_scan(image, 256)));
  assert(ota_nrf52_effective_stage_ceiling(ota_bl_app_caps_scan(image, 256)) == 0xD4000);

  // RAK keeps the deployed internal privileged contract and optional NOR.
  imageFor(image, 0x0A, 0x14);
  expectViews(image, 0x0A, 0x1E, 0x14);
  imageFor(image, 0x0A, 0);
  expectViews(image, 0x0A, 0x0A, 0);

  // Optional records are meaningful only under their exact primary profile.
  for (uint8_t primary : {uint8_t(0x09), uint8_t(0x0A), uint8_t(0x0E), uint8_t(0x1E)}) {
    for (uint8_t optional : {uint8_t(0x02), uint8_t(0x14)}) {
      imageFor(image, primary, optional);
      const bool qualified = (primary == 0x09 && optional == 2) ||
                             (primary == 0x0A && optional == 0x14);
      expectViews(image, primary, qualified ? primary | optional : primary,
                  qualified ? optional : 0);
    }
  }

  // Every field of the frozen adjacent bundle is enforced. A malformed
  // optional declaration cannot remove the still-valid SD primary profile.
  for (unsigned byte = 0; byte < sizeof(bundle); ++byte) {
    imageFor(image, 0x09, 0x02);
    image[32 + byte] ^= 1;
    expectViews(image, 0x09, 0x09, 0);
  }
  imageFor(image, 0x09, 0x02);
  memcpy(image + 80, bundle, sizeof(bundle));
  expectViews(image, 0x09, 0x09, 0);  // duplicate RAM and STOR
  imageFor(image, 0x09, 0x02);
  memcpy(image + 80, bundle, 16);
  expectViews(image, 0x09, 0x09, 0);  // duplicate RAM alone
  imageFor(image, 0x09, 0x02);
  memcpy(image + 80, bundle + 16, 16);
  expectViews(image, 0x09, 0x09, 0);  // duplicate STOR alone
  imageFor(image, 0x09, 0x02);
  memmove(image + 52, image + 48, 16);
  memset(image + 48, 0, 4);
  expectViews(image, 0x09, 0x09, 0);  // separated records
  imageFor(image, 0x09, 0x02);
  memmove(image + 33, image + 32, 32);
  image[32] = 0;
  expectViews(image, 0x09, 0x09, 0);  // byte-shifted bundle
  imageFor(image, 0x09, 0x02);
  assert(ota_bl_optional_app_storage(image, 63) == 0);
  assert(ota_bl_optional_app_storage(nullptr, 256) == 0);

  // A second privileged marker must not be hidden by optional metadata.
  memcpy(image + 128, image, 16);
  assert(!ota_bl_update_caps_scan_aligned(image, 256, 0x09).present);

  // Exercise the production memory-mapped entry points without defining the
  // retained-RAM application flag: this app retains the full SD RAM layout.
  void* flash = mmap(reinterpret_cast<void*>(uintptr_t(0xF4000)), 0xA000,
                     PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS | MAP_FIXED,
                     -1, 0);
  assert(flash == reinterpret_cast<void*>(uintptr_t(0xF4000)));
  memset(flash, 0, 0xA000);
#if defined(OTA_INTERNAL_BOOTLOADER_UPDATE)
  imageFor(static_cast<uint8_t*>(flash), 0x0A, 0x14);
  assert(ota_bootloader_update_storage_flags() == 0x0A);
  assert(ota_bootloader_app_caps().storage_flags == 0x1E);
  assert(ota_bootloader_update_caps().storage_flags == 0x0A);
#else
  imageFor(static_cast<uint8_t*>(flash), 0x09, 0x02);
  assert(ota_bootloader_update_storage_flags() == 0x09);
  assert(ota_bootloader_app_caps().storage_flags == 0x0B);
  OtaBlCaps update = ota_bootloader_update_caps();
  assert(update.storage_flags == 0x09 && update.optional_app_storage == 2);
  assert(ota_bootloader_self_update_caps_valid(update));
  imageFor(static_cast<uint8_t*>(flash), 0x09, 0);
  update = ota_bootloader_update_caps();
  assert(update.storage_flags == 0x09 && update.optional_app_storage == 0);
  assert(ota_bootloader_self_update_caps_valid(update));
#endif
  assert(!ota_bootloader_ram_caps().present);
  assert(munmap(flash, 0xA000) == 0);
}
'''

STREAM_SOURCE = r'''
#include <cassert>
#include <cstring>
#include <fstream>
#include <iterator>
#include <string>
#include <vector>
#include "helpers/ota/OtaBootloaderUpdate.h"
using namespace mesh::ota;
struct Store {
  std::vector<uint8_t> bytes;
  bool fail_read = false;
  bool read(uint32_t off, uint8_t* out, uint32_t len) {
    if (uint64_t(off) + len > bytes.size() || (fail_read && off == 37 + 512)) return false;
    memcpy(out, bytes.data() + off, len);
    return true;
  }
};
int main(int argc, char** argv) {
  assert(argc == 6);
  std::ifstream input(argv[1], std::ios::binary);
  Store store;
  store.bytes.resize(37, 0xA5);
  store.bytes.insert(store.bytes.end(), std::istreambuf_iterator<char>(input), {});
  assert(store.bytes.size() == 37 + OTA_BOOT_IMAGE_SIZE);
  store.fail_read = std::stoul(argv[5]) != 0;
  OtaBootloaderIdentity identity;
  OtaBootloaderCapsMarker caps;
  const bool actual = ota_bootloader_external_image_metadata(
      store, 37, uint8_t(std::stoul(argv[2])), identity, caps,
      uint8_t(std::stoul(argv[3])));
  assert(actual == (std::stoul(argv[4]) != 0));
  if (actual) {
    assert(identity.present && identity.crc_ok && identity.continuity_present);
    assert(identity.manifest_offset == OTA_BOOT_CANDIDATE_MANIFEST_OFFSET);
    assert(caps.storage_flags == std::stoul(argv[2]));
  }
}
'''

UTILS_DECLARATIONS = """#pragma once
#include <stddef.h>
#include <stdint.h>
namespace mesh { struct Utils {
  static void sha256(uint8_t*, size_t, const uint8_t*, int);
  static void sha256(uint8_t*, size_t, const uint8_t*, int, const uint8_t*, int);
}; }
"""


class TowerBootloaderCapsTest(unittest.TestCase):
    def test_sd_primary_and_rak_capability_views(self):
        for profile in ("OTA_SD_BOOTLOADER_UPDATE", "OTA_INTERNAL_BOOTLOADER_UPDATE"):
            with self.subTest(profile=profile), tempfile.TemporaryDirectory() as directory:
                path = Path(directory)
                source = path / "caps.cpp"
                source.write_text("#include <initializer_list>\n" + SOURCE, encoding="ascii")
                executable = path / "caps"
                subprocess.run([
                    "g++", "-std=c++17", "-Wall", "-Wextra", "-Werror",
                    "-DNRF52_PLATFORM=1", f"-D{profile}=1",
                    "-DMOTA_NRF52_TEST_LAYOUT_STAGE_CEILING=0xED000u",
                    "-I", str(ROOT / "src"), str(source), "-o", str(executable),
                ], check=True, timeout=30)
                subprocess.run([str(executable)], check=True, timeout=10)

    def test_auto_storage_guard_allows_only_sd_primary_tower(self):
        required = ["NRF52_PLATFORM", "HELTEC_TOWER_V2_SDCARD", "OTA_SD_STORE",
                    "OTA_FLASH_STORE", "OTA_SD_BOOTLOADER_UPDATE"]
        forbidden = ["OTA_QSPI_STORE", "QSPIFLASH", "OTA_RAK_AUTO_STORE",
                     "OTA_INTERNAL_BOOTLOADER_UPDATE", "OTA_QSPI_BOOTLOADER_UPDATE",
                     "OTA_HYBRID_RAM_STORE"]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / "Utils.h").write_text(UTILS_DECLARATIONS, encoding="ascii")
            source = path / "guard.cpp"
            source.write_text('#include "helpers/ota/OtaBootloaderUpdate.h"\n', encoding="ascii")
            cases = [(required + ["OTA_TOWER_AUTO_STORE"], True),
                     ([item for item in required if item != "OTA_FLASH_STORE"], True),
                     (required, False)]
            cases += [([item for item in required if item != missing]
                       + ["OTA_TOWER_AUTO_STORE"], False) for missing in required]
            cases += [(required + ["OTA_TOWER_AUTO_STORE", item], False) for item in forbidden]
            for flags, expected in cases:
                with self.subTest(flags=flags):
                    result = subprocess.run([
                        "g++", "-std=c++17", "-fsyntax-only", "-I", str(path),
                        "-I", str(ROOT / "src"), *[f"-D{flag}=1" for flag in flags],
                        str(source),
                    ], capture_output=True, text=True, timeout=30)
                    self.assertEqual(result.returncode == 0, expected, result.stderr)
                    if not expected:
                        self.assertIn("#error", result.stderr)

    def test_streamed_successors_retain_unique_adjacent_optional_storage(self):
        base = _generic_bootloader_image(0x239A0071, "TOWER_V2_OTA", ml.BOOT_STORAGE_SD_UPDATE)
        image = self.with_optional(base, 2)
        ram, optional = image[0x90:0xA0], image[0xA0:0xB0]
        cases = [(base, 9, 0, True, False), (base, 9, 2, False, False),
                 (image, 9, 2, True, False), (image, 9, 0, True, False),
                 (image, 9, 0x14, False, False), (image, 9, 2, False, True)]
        for offset in (480, 496, 500, 508, 512, 1020):
            def move_pair(data, offset=offset):
                data[0x90:0xB0] = b"\xff" * 32
                data[offset:offset + 32] = ram + optional
            cases.append((_rewrite_boot_image(image, move_pair), 9, 2, True, False))
        mutations = [
            lambda data: data.__setitem__(slice(0x200, 0x210), ram),
            lambda data: data.__setitem__(slice(0x200, 0x210), optional),
            lambda data: data.__setitem__(slice(0x70, 0x80), optional),
            lambda data: data.__setitem__(0xAC, 0x14),
            lambda data: data.__setitem__(0xAD, 1),
            lambda data: data.__setitem__(0x98, 2),
            lambda data: data.__setitem__(slice(0x90, 0xA0), b"\xff" * 16),
        ]
        for mutation in mutations:
            candidate = _rewrite_boot_image(image, mutation)
            cases += [(candidate, 9, 2, False, False), (candidate, 9, 0, True, False)]
        rak = self.with_optional(_generic_bootloader_image(), 0x14)
        cases += [(rak, 0x0A, 0x14, True, False), (rak, 0x0A, 2, False, False)]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / "Utils.h").write_text(UTILS_DECLARATIONS, encoding="ascii")
            source = path / "stream.cpp"
            source.write_text(STREAM_SOURCE, encoding="ascii")
            executable = path / "stream"
            subprocess.run([
                "g++", "-std=c++17", "-Wall", "-Wextra", "-Werror",
                "-I", str(path), "-I", str(ROOT / "src"), str(source),
                "-o", str(executable),
            ], check=True, timeout=30)
            for index, (candidate, primary, required, expected, fail_read) in enumerate(cases):
                with self.subTest(case=index):
                    payload = path / "image.bin"
                    payload.write_bytes(candidate)
                    subprocess.run([str(executable), str(payload), str(primary), str(required),
                                    str(int(expected)), str(int(fail_read))], check=True, timeout=10)

    @staticmethod
    def with_optional(image, optional):
        def add_storage(data):
            struct.pack_into("<I", data, 0, 0x20030000)
            data[0x90:0xB0] = (b"MOTARAMA" + struct.pack("<HHI", 1, 72, 65536)
                                + b"MOTASTOR" + struct.pack("<HHB3x", 1, 16, optional))
        return _rewrite_boot_image(image, add_storage)

    def test_python_admits_exact_tower_and_retains_rak_profiles(self):
        for board, name, primary, optional in (
            (0x239A0071, "TOWER_V2_OTA", ml.BOOT_STORAGE_SD_UPDATE, 2),
            (0x239A0029, "3401_DFU", ml.BOOT_STORAGE_INTERNAL_UPDATE, 0x14),
            (0x239A0029, "4631_DFU", ml.BOOT_STORAGE_INTERNAL_UPDATE, 0x14),
        ):
            with self.subTest(name=name):
                base = _generic_bootloader_image(board, name, primary)
                self.assertEqual(ml.bootloader_optional_app_storage(base), 0)
                image = self.with_optional(base, optional)
                self.assertEqual(ml.validate_bootloader_image(image).device_name, name)
                self.assertEqual(ml.bootloader_caps_storage(image), primary)
                self.assertEqual(ml.bootloader_optional_app_storage(image), optional)

    def test_python_rejects_corrupt_ambiguous_and_cross_profile_records(self):
        base = _generic_bootloader_image(0x239A0071, "TOWER_V2_OTA", ml.BOOT_STORAGE_SD_UPDATE)
        image = self.with_optional(base, 2)
        ram = image[0x90:0xA0]
        optional = image[0xA0:0xB0]
        mutations = [
            lambda data: data.__setitem__(0xAC, 3),
            lambda data: data.__setitem__(0xAD, 1),
            lambda data: data.__setitem__(slice(0xB0, 0xC0), optional),
            lambda data: data.__setitem__(slice(0xB0, 0xC0), ram),
            lambda data: data.__setitem__(slice(0x90, 0xA0), b"\xff" * 16),
            lambda data: struct.pack_into("<I", data, 0, 0x20040000),
        ]
        for mutation in mutations:
            with self.subTest(mutation=mutations.index(mutation)):
                with self.assertRaises(ValueError):
                    ml.validate_bootloader_image(_rewrite_boot_image(image, mutation))
        for board, name, primary, flags in (
            (0x239A0071, "TOWER_V2_OTA", ml.BOOT_STORAGE_SD_UPDATE, 0x14),
            (0x239A0029, "3401_DFU", ml.BOOT_STORAGE_INTERNAL_UPDATE, 2),
            (0x239A0029, "4631_DFU", ml.BOOT_STORAGE_INTERNAL_UPDATE, 2),
            (0x239A0071, "TOWER_V2_OTA", ml.BOOT_STORAGE_INTERNAL_UPDATE, 2),
        ):
            with self.subTest(name=name, primary=primary, flags=flags):
                candidate = self.with_optional(_generic_bootloader_image(board, name, primary), flags)
                with self.assertRaises(ValueError):
                    ml.validate_bootloader_image(candidate)


if __name__ == "__main__":
    unittest.main()
