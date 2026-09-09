#include <cassert>
#include <cstring>
#include <fstream>
#include <iostream>
#include <iterator>
#include <string>
#include <vector>
#include "helpers/Nrf52BootloaderVersion.h"

using namespace mesh;
using namespace mesh::ota;

static void put16(std::vector<uint8_t>& image, size_t pos, uint16_t value) {
  image[pos] = value; image[pos + 1] = value >> 8;
}
static void put32(std::vector<uint8_t>& image, size_t pos, uint32_t value) {
  for (unsigned i = 0; i < 4; ++i) image[pos + i] = value >> (8 * i);
}
static std::vector<uint8_t> image(size_t size = 0xa000, uint32_t start = 0xf4000) {
  std::vector<uint8_t> bytes(size, 0xff);
  put32(bytes, 0, 0x20040000); put32(bytes, 4, start + 0x101);
  return bytes;
}
static void text(std::vector<uint8_t>& bytes, size_t offset, const std::string& version) {
  const std::string line = "UF2 Bootloader " + version + "\r\nModel: test\r\n";
  assert(offset + line.size() <= bytes.size());
  memcpy(bytes.data() + offset, line.data(), line.size());
}
static void refreshManifestCrc(std::vector<uint8_t>& bytes) {
  const size_t crc_offset = OTA_BOOT_CANDIDATE_MANIFEST_OFFSET + 40;
  put32(bytes, crc_offset, ota_boot_image_crc32(bytes.data(), bytes.size(), crc_offset));
}
static void manifest(std::vector<uint8_t>& bytes, uint32_t version) {
  const size_t offset = OTA_BOOT_CANDIDATE_MANIFEST_OFFSET;
  memset(bytes.data() + offset, 0, OTA_BOOT_ENVELOPE_SIZE);
  put32(bytes, offset, OTA_BOOT_MANIFEST_MAGIC0);
  put32(bytes, offset + 4, OTA_BOOT_MANIFEST_MAGIC1);
  put16(bytes, offset + 8, 1); put16(bytes, offset + 10, 44);
  put32(bytes, offset + 12, OTA_BOOT_IMAGE_START);
  put32(bytes, offset + 16, OTA_BOOT_IMAGE_SIZE);
  put32(bytes, offset + 20, 0x239a0071);
  memcpy(bytes.data() + offset + 24, "TOWER_V2_OTA", 12);
  put32(bytes, offset + 44, OTA_BOOT_CONTINUITY_MAGIC0);
  put32(bytes, offset + 48, OTA_BOOT_CONTINUITY_MAGIC1);
  put16(bytes, offset + 52, 2); put16(bytes, offset + 54, 32);
  put32(bytes, offset + 56, version);
  put16(bytes, offset + 60, 140); put16(bytes, offset + 62, 182);
  put32(bytes, offset + 64, 0x26000); put16(bytes, offset + 68, 1);
  refreshManifestCrc(bytes);
}
static void expect(const std::vector<uint8_t>& bytes, const char* expected,
                   uint32_t start = 0xf4000, uint32_t base = 0) {
  char output[128];
  memset(output, 0x55, sizeof(output));
  const bool ok = nrf52BootloaderVersion(bytes.data(), bytes.size(), start, base, output, sizeof(output));
  assert(ok == (expected != nullptr));
  assert(expected ? strcmp(output, expected) == 0 : output[0] == 0);
}

int main(int argc, char** argv) {
  if (argc > 1) {
    std::vector<uint8_t> bytes;
    if (std::string(argv[1]) == "--hex") {
      std::string hex;
      std::cin >> hex;
      if (hex.size() % 2) return 2;
      for (size_t i = 0; i < hex.size(); i += 2)
        bytes.push_back((uint8_t)std::stoul(hex.substr(i, 2), nullptr, 16));
    } else {
      std::ifstream file(argv[1], std::ios::binary);
      if (!file) return 2;
      bytes.assign(std::istreambuf_iterator<char>(file), {});
    }
    char output[128];
    if (!nrf52BootloaderVersion(bytes.data(), bytes.size(), 0xf4000, 0, output, sizeof(output))) return 3;
    std::cout << output << '\n';
    return 0;
  }
  Nrf52BootloaderRegion r;
  assert(nrf52BootloaderRegion(4096, 256, UINT32_MAX, 0xf4000, r));
  assert(r.start == 0xf4000 && r.end == 0xfe000);
  assert(nrf52BootloaderRegion(4096, 256, 0xf0000, 0xf4000, r) && r.start == 0xf0000);
  assert(nrf52BootloaderRegion(4096, 128, UINT32_MAX, 0x74000, r));
  assert(r.start == 0x74000 && r.end == 0x7e000); // bounds only, not a supported-board claim
  assert(nrf52BootloaderRegion(4096, 256, UINT32_MAX, UINT32_MAX, r) && r.start == 0xf4000);
  for (uint32_t bad : {0u, 0x123u, 0xff000u, 0x100000u, 0x20000000u})
    assert(!nrf52BootloaderRegion(4096, 256, bad, 0xf4000, r)); // never ignore bad MBR priority
  assert(!nrf52BootloaderRegion(0, 256, UINT32_MAX, UINT32_MAX, r));
  assert(!nrf52BootloaderRegion(4096, UINT32_MAX, UINT32_MAX, UINT32_MAX, r));
  assert(!nrf52BootloaderRegion(4096, 8, UINT32_MAX, UINT32_MAX, r));

  // Test every byte alignment, both sides of the former FB000 window, and
  // long release/preview/fork/build versions that the old 32-byte buffer cut.
  const char* versions[] = {"0.6.4", "0.9.2", "0.11.0-OTAFIX2.4.2", "0.11.0-OTAFIX2.4.6",
    "0.11.0-OTAFIX2.4.6-preview.12", "0.11.0-OTAFIX2.4.3-dirty-test-version-0x02040401",
    "v0.9.2-Seeed", "0.8.2+build.abcdef", "0.6.1_RAK4631"};
  for (const char* version : versions) {
    for (size_t offset : {0x100u, 0x101u, 0x102u, 0x103u, 0x6ff0u, 0x7000u, 0x9e00u}) {
      auto bytes = image(); text(bytes, offset, version); expect(bytes, version);
    }
  }
  auto bytes = image(); text(bytes, 0x100, "0.11.0"); text(bytes, 0x8000, "0.11.0");
  expect(bytes, "0.11.0"); // identical copies are harmless
  text(bytes, 0x8000, "0.12.0"); expect(bytes, nullptr, 0xf4000, 0xb00);
  bytes = image(); memcpy(bytes.data() + 0x100, "UF2 Bootloader ", 15);
  text(bytes, 0x300, "0.11.0"); expect(bytes, "0.11.0"); // marker literal before real record
  for (const char* bad : {"", "garbage", "1", "v..", "1.2/evil", "1.2\x01"}) {
    bytes = image(); text(bytes, 0x100, bad); expect(bytes, nullptr);
  }
  bytes = image();
  const std::string boundary = "UF2 Bootloader 0.11.0";
  memcpy(bytes.data() + bytes.size() - boundary.size(), boundary.data(), boundary.size());
  expect(bytes, nullptr); // no terminator inside the region
  bytes.back() = '\n'; expect(bytes, nullptr); // incomplete numeric version is not a match
  bytes = image();
  const std::string terminated = boundary + "\n";
  memcpy(bytes.data() + bytes.size() - terminated.size(), terminated.data(), terminated.size());
  expect(bytes, "0.11.0"); // terminator at the final readable byte
  bytes = image();
  const std::string longest = "1.2.3-" + std::string(121, 'a');
  text(bytes, 0x100, longest); expect(bytes, longest.c_str());
  bytes = image(); text(bytes, 0x100, longest + "a"); expect(bytes, nullptr);

  bytes = image(); text(bytes, 0x100, "0.11.0");
  char tiny[4] = {'x', 'x', 'x', '!'};
  assert(!nrf52BootloaderVersion(bytes.data(), bytes.size(), 0xf4000, 0, nullptr, 5));
  assert(!nrf52BootloaderVersion(bytes.data(), bytes.size(), 0xf4000, 0, tiny, 0) && tiny[0] == 'x');
  assert(!nrf52BootloaderVersion(bytes.data(), bytes.size(), 0xf4000, 0, tiny, 1) && tiny[0] == 0);
  assert(!nrf52BootloaderVersion(bytes.data(), bytes.size(), 0xf4000, 0, tiny, 3) && tiny[0] == 0 && tiny[3] == '!');
  put32(bytes, 0, UINT32_MAX); expect(bytes, nullptr);
  bytes = image(); text(bytes, 0x100, "0.11.0"); put32(bytes, 4, 0x27001); expect(bytes, nullptr);
  bytes = image(); text(bytes, 0x100, "0.11.0"); put32(bytes, 4, 0xf4100); expect(bytes, nullptr);
  bytes = image(0xe000, 0xf0000); text(bytes, 0x100, "0.9.2"); expect(bytes, "0.9.2", 0xf0000);
  bytes = image(0xa000, 0x74000); text(bytes, 0x100, "0.6.4"); expect(bytes, "0.6.4", 0x74000);

  // Regression: the official MeshTower V2 SD 2.4.6 payload has NO UF2 text.
  // Its BLMF/BLM2 fields below match the release (the synthetic body/CRC do not).
  // It must report the OTAFIX release even if startup captured Adafruit 0.11.0.
  bytes = image(); manifest(bytes, 0x020406ff); expect(bytes, "OTAFIX2.4.6");
  expect(bytes, "OTAFIX2.4.6", 0xf4000, 0xb00);
  const std::string no_uf2(bytes.begin(), bytes.end());
  assert(no_uf2.find("UF2 Bootloader ") == std::string::npos);
  OtaBootloaderIdentity identity;
  assert(ota_bootloader_identity_from_image(bytes.data(), bytes.size(), identity));
  assert(identity.board_id == 0x239a0071 && identity.boot_version == 0x020406ff);
  assert(identity.softdevice_family == 140 && identity.softdevice_fwid == 182);
  assert(identity.app_base == 0x26000 && identity.layout_abi == 1);
  assert(strcmp(identity.device_name, "TOWER_V2_OTA") == 0);
  assert(!nrf52BootloaderVersion(bytes.data(), bytes.size(), 0xf4000, 0xb00, tiny, 3));
  assert(tiny[0] == 0 && tiny[3] == '!'); // no truncated metadata version
  bytes = image(); manifest(bytes, 0x0204060c); expect(bytes, "OTAFIX2.4.6-preview.12");
  bytes = image(); manifest(bytes, 0x020406ff); bytes[0x100] ^= 1; expect(bytes, nullptr);
  expect(bytes, "0.11.0 (base)", 0xf4000, 0xb00); // never claim the corrupted OTAFIX version
  bytes = image(); manifest(bytes, 0x02040600); expect(bytes, nullptr);
  bytes = image(); manifest(bytes, 0); expect(bytes, nullptr);
  bytes = image(); manifest(bytes, UINT32_MAX); expect(bytes, nullptr);
  // Even a fresh whole-image CRC must not legitimize malformed extension fields.
  for (size_t field : {44u, 48u, 52u, 54u, 60u, 62u, 64u, 68u}) {
    bytes = image(); manifest(bytes, 0x020406ff);
    put16(bytes, OTA_BOOT_CANDIDATE_MANIFEST_OFFSET + field, 0);
    if (field == 64u) put32(bytes, OTA_BOOT_CANDIDATE_MANIFEST_OFFSET + field, 0);
    refreshManifestCrc(bytes); expect(bytes, nullptr);
  }
  for (size_t field : {70u, 72u}) {
    bytes = image(); manifest(bytes, 0x020406ff);
    put16(bytes, OTA_BOOT_CANDIDATE_MANIFEST_OFFSET + field, 1);
    refreshManifestCrc(bytes); expect(bytes, nullptr);
  }
  bytes = image(); manifest(bytes, 0x020406ff);
  memset(bytes.data() + OTA_BOOT_CANDIDATE_MANIFEST_OFFSET + 44, 0xff, 32);
  refreshManifestCrc(bytes);
  expect(bytes, nullptr); // legacy BLMF alone has no version
  expect(bytes, "0.11.0 (base)", 0xf4000, 0xb00);
  bytes = image(); manifest(bytes, 0x020406ff);
  text(bytes, 0x100, "0.11.0-OTAFIX2.4.6"); manifest(bytes, 0x020406ff);
  expect(bytes, "0.11.0-OTAFIX2.4.6"); // preserve the complete original text
  bytes = image(); text(bytes, 0x100, "0.11.0"); text(bytes, 0x8000, "0.12.0");
  manifest(bytes, 0x020406ff); expect(bytes, "OTAFIX2.4.6");
  bytes = image(); expect(bytes, "0.11.0 (base)", 0xf4000, 0xb00);
  expect(bytes, nullptr, 0xf4000, UINT32_MAX);
  expect(bytes, nullptr, 0xf4000, 0);
  std::cout << "bootloader version native cases passed\n";
}
