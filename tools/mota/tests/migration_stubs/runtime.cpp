#include "Arduino.h"
#include "BootloaderMigrationResource.h"
#include "SHA256.h"
// The test app-base override bypasses the target linker's declarations.
namespace mesh { namespace ota {
extern "C" uint32_t __flash_arduino_end[];
extern "C" const uint8_t g_meshcore_internal_extrafs __attribute__((weak));
} }
#include "helpers/ota/OtaSelf.h"
#include "nrf.h"
#include "nrf_mbr.h"
#include "nrf_sdm.h"
#include "nrf_soc.h"

#include <cassert>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <stdexcept>
#if defined(_WIN32)
#include <windows.h>
#else
#include <sys/mman.h>
#endif

namespace migration_test {
uint32_t now = 0;
unsigned endf_checks = 0;
unsigned softdevice_checks = 0;
unsigned disables = 0;
unsigned resets = 0;
unsigned copies = 0;
unsigned retained_reads = 0;
unsigned retained_clears = 0;
unsigned retained_sets = 0;
bool candidate_installed = false;
bool interrupt_hash = false;
bool softdevice_enabled = false;
uint32_t softdevice_status = NRF_SUCCESS;
uint32_t retained_get_status = NRF_SUCCESS;
uint32_t retained_clear_status = NRF_SUCCESS;
uint32_t retained_set_status = NRF_SUCCESS;

void mbr_command() {
  ++copies;
  throw std::runtime_error("unexpected MBR command in state-machine test");
}
} // namespace migration_test

// Include the actual driver. Only its target-specific naked SVC adapter is
// replaced: function-like 'volatile(...)' captures the extended assembly, but
// leaves ordinary 'volatile uint8_t *' memory reads unchanged. The adapter is
// an explicit failing trap, never a successful simulated flash operation.
#define __attribute__(...)
#define __asm
#define volatile(...) migration_test::mbr_command()
#include "helpers/ota/BootloaderMigration.cpp"
#undef volatile
#undef __asm
#undef __attribute__

const uint8_t migration_candidate[40960] = {};
const uint8_t migration_candidate_sha256[32] = { 0x01, 0x23, 0x45, 0x67, 0x89, 0xAB, 0xCD, 0xEF };
const uint8_t migration_legacy_sha256[32] = {};
const bool migration_has_legacy = false;
const uint32_t migration_app_base = 0x26000, migration_boot_version = 0x02040CFF,
               migration_board_id = 0x239A0029;
const uint16_t migration_softdevice_fwid = 0xB6;
const char migration_device_name[16] = "4631_DFU";
namespace mesh { namespace ota {
extern "C" {
uint32_t __flash_arduino_start[1] = {};
uint32_t __flash_arduino_end[1] = {};
}
} }

MigrationTestPower power_registers = {};
MigrationTestPower *NRF_POWER = &power_registers;
MigrationTestFicr *NRF_FICR = nullptr;
MigrationTestAcl *NRF_ACL = nullptr;
MigrationTestUicr *NRF_UICR = nullptr;
MigrationTestWdt *NRF_WDT = nullptr;

uint32_t millis() {
  return migration_test::now;
}

void NVIC_SystemReset() {
  ++migration_test::resets;
  throw std::runtime_error("unexpected reset in state-machine test");
}

uint32_t sd_softdevice_is_enabled(uint8_t *enabled) {
  ++migration_test::softdevice_checks;
  *enabled = migration_test::softdevice_enabled;
  return migration_test::softdevice_status;
}

uint32_t sd_softdevice_disable() {
  ++migration_test::disables;
  throw std::runtime_error("unexpected SoftDevice disable in state-machine test");
}

uint32_t sd_power_gpregret_get(uint32_t index, uint32_t *result) {
  assert(index == 0);
  ++migration_test::retained_reads;
  *result = power_registers.GPREGRET;
  return migration_test::retained_get_status;
}

uint32_t sd_power_gpregret_clr(uint32_t index, uint32_t mask) {
  assert(index == 0 && mask == 0xFF);
  assert(!mesh::ota::bootloader_migration_pending());
  ++migration_test::retained_clears;
  if (migration_test::retained_clear_status == NRF_SUCCESS)
    power_registers.GPREGRET &= ~mask;
  return migration_test::retained_clear_status;
}

uint32_t sd_power_gpregret_set(uint32_t index, uint32_t mask) {
  assert(index == 0 && mask == mesh::ota::ATTEMPT_MARKER);
  assert(!mesh::ota::bootloader_migration_pending());
  ++migration_test::retained_sets;
  if (migration_test::retained_set_status == NRF_SUCCESS)
    power_registers.GPREGRET |= mask;
  return migration_test::retained_set_status;
}

void SHA256::reset() {
  if (migration_test::interrupt_hash)
    throw std::runtime_error("interrupted bootloader check");
}
void SHA256::update(const void *, size_t) {
}
void SHA256::finalize(void *out, size_t size) {
  assert(size == 32);
  // Scheduling tests exercise the full memory-read loop; cryptography itself
  // is the production SHA256 library's contract, not this hardware stub.
  std::memset(out, 0, size);
  if (migration_test::candidate_installed)
    std::memcpy(out, migration_candidate_sha256, size);
}

namespace mesh {
namespace ota {
bool ota_self_firmware(SelfFwInfo &) {
  ++migration_test::endf_checks;
  return false; // Stop at the first install preflight, before hardware access.
}
} // namespace ota
} // namespace mesh

namespace {
using namespace mesh::ota;
const char confirmation[] = "0123456789ABCDEF";
char reply[160];

void wr16(uint8_t *p, uint16_t value) {
  p[0] = value;
  p[1] = value >> 8;
}

void wr32(uint8_t *p, uint32_t value) {
  wr16(p, value);
  wr16(p + 2, value >> 16);
}

uint8_t *installed_manifest(uint32_t version) {
  uint8_t *boot = reinterpret_cast<uint8_t *>(migration::BOOT_BASE);
  std::memset(boot, 0xFF, migration::BOOT_SIZE);
  uint8_t *p = boot + OTA_BOOT_CANDIDATE_MANIFEST_OFFSET;
  wr32(p, OTA_BOOT_MANIFEST_MAGIC0);
  wr32(p + 4, OTA_BOOT_MANIFEST_MAGIC1);
  wr16(p + 8, 1);
  wr16(p + 10, 44);
  wr32(p + 12, migration::BOOT_BASE);
  wr32(p + 16, migration::BOOT_SIZE);
  wr32(p + 20, migration_board_id);
  std::memcpy(p + 24, migration_device_name, 16);
  wr32(p + 44, OTA_BOOT_CONTINUITY_MAGIC0);
  wr32(p + 48, OTA_BOOT_CONTINUITY_MAGIC1);
  wr16(p + 52, 2);
  wr16(p + 54, 32);
  wr32(p + 56, version);
  wr16(p + 60, 140);
  wr16(p + 62, migration_softdevice_fwid);
  wr32(p + 64, migration_app_base);
  wr16(p + 68, 1);
  wr16(p + 70, 0);
  wr32(p + 72, 0);
  return p;
}

void seal_manifest(uint8_t *p) {
  const uint8_t *boot = reinterpret_cast<const uint8_t *>(migration::BOOT_BASE);
  wr32(p + 40, ota_boot_image_crc32(boot, migration::BOOT_SIZE,
                                  OTA_BOOT_CANDIDATE_MANIFEST_OFFSET + 40));
}

void arm() {
  assert(bootloader_migration_request(confirmation, reply, sizeof(reply)));
  assert(bootloader_migration_pending());
  assert(std::strstr(reply, "OK migration armed"));
  assert(power_registers.GPREGRET == mesh::ota::ATTEMPT_MARKER);
}

void no_install(unsigned softdevice_reads = 0) {
  assert(migration_test::endf_checks == 0);
  assert(migration_test::softdevice_checks == softdevice_reads);
  assert(migration_test::disables == 0);
  assert(migration_test::resets == 0);
  assert(migration_test::copies == 0);
}

void status_result(unsigned result) {
  bootloader_migration_status(reply, sizeof(reply));
  char expected[24];
  std::snprintf(expected, sizeof(expected), "last=%u", result);
  assert(std::strstr(reply, expected));
}

void restart_application() {
  // Recreate zero-initialized driver state while retaining GPREGRET, as a
  // hardware reset would. Test counters deliberately survive for assertions.
  mesh::ota::pending = false;
  mesh::ota::automatic_attempted = false;
  mesh::ota::automatic_blocked = false;
  mesh::ota::armed_at = 0;
  mesh::ota::last_result = 0;
  mesh::ota::result_is_current = false;
  mesh::ota::already_installed = false;
  migration_test::now = 0;
}
} // namespace

int main(int argc, char **argv) {
  assert(argc == 2);
  using namespace migration_test;
#if defined(_WIN32)
  assert(VirtualAlloc(reinterpret_cast<void *>(0xF0000), 0x10000,
                      MEM_RESERVE | MEM_COMMIT, PAGE_READWRITE) != nullptr);
#else
  assert(mmap(reinterpret_cast<void *>(0xF0000), 0x10000, PROT_READ | PROT_WRITE,
              MAP_PRIVATE | MAP_ANONYMOUS | MAP_FIXED, -1, 0) != MAP_FAILED);
#endif
  const char *scenario = argv[1];
  if (std::strcmp(scenario, "automatic-delay") == 0 ||
      std::strcmp(scenario, "automatic-arm-enabled") == 0) {
    softdevice_enabled = std::strcmp(scenario, "automatic-arm-enabled") == 0;
    assert(!bootloader_migration_service_due());
    now = 69999;
    assert(!bootloader_migration_service_due());
    bootloader_migration_tick(true, true);
    assert(!bootloader_migration_pending());
    no_install();
    now = 70000;
    assert(bootloader_migration_service_due());
    bootloader_migration_tick(true, true);
    assert(bootloader_migration_pending());
    assert(bootloader_migration_service_due());
    no_install(3);
    assert(power_registers.GPREGRET == mesh::ota::ATTEMPT_MARKER);
    assert(retained_reads == (softdevice_enabled ? 3u : 0u));
    assert(retained_clears == (softdevice_enabled ? 1u : 0u));
    assert(retained_sets == (softdevice_enabled ? 1u : 0u));
    now = 71499;
    bootloader_migration_tick(true, true);
    assert(bootloader_migration_pending());
    no_install(3);
    now = 71500;
    bootloader_migration_tick(true, true);
    assert(endf_checks == 1);
    assert(!bootloader_migration_pending());
    assert(!bootloader_migration_service_due());
    now = 140000;
    bootloader_migration_tick(true, true);
    assert(endf_checks == 1); // A failed preflight must not be retried automatically.
    assert(softdevice_checks == 3);
    status_result(1);
  } else if (std::strcmp(scenario, "automatic-busy") == 0) {
    now = 70000;
    bootloader_migration_tick(false, true);
    assert(!bootloader_migration_pending());
    assert(bootloader_migration_service_due());
    no_install();
    now = 72000;
    bootloader_migration_tick(true, false);
    assert(!bootloader_migration_pending());
    assert(bootloader_migration_service_due());
    no_install();
    now = 74000;
    bootloader_migration_tick(false, false);
    assert(!bootloader_migration_pending());
    assert(bootloader_migration_service_due());
    no_install();
    now = 76000;
    bootloader_migration_tick(true, true);
    assert(bootloader_migration_pending());
    no_install(3);
    now = 77499;
    bootloader_migration_tick(true, true);
    no_install(3);
    now = 77500;
    bootloader_migration_tick(true, true);
    assert(endf_checks == 1); // Grace starts when the deferred request is armed.
  } else if (std::strcmp(scenario, "automatic-same-version") == 0 ||
             std::strcmp(scenario, "automatic-same-version-enabled") == 0 ||
             std::strcmp(scenario, "automatic-newer-version") == 0 ||
             std::strcmp(scenario, "automatic-exact-image") == 0) {
    softdevice_enabled = std::strcmp(scenario, "automatic-same-version-enabled") == 0;
    if (std::strcmp(scenario, "automatic-exact-image") == 0) {
      candidate_installed = true;
    } else {
      seal_manifest(installed_manifest(
          (std::strcmp(scenario, "automatic-same-version") == 0 || softdevice_enabled)
              ? migration_boot_version : 0x02040D01));
    }
    now = 70000;
    bootloader_migration_tick(true, true);
    assert(!bootloader_migration_pending());
    assert(!bootloader_migration_service_due());
    no_install(3);
    assert(power_registers.GPREGRET == 0); // Clear the provisional check marker.
    assert(retained_reads == (softdevice_enabled ? 3u : 0u));
    assert(retained_clears == (softdevice_enabled ? 2u : 0u));
    assert(retained_sets == (softdevice_enabled ? 1u : 0u));
    now = 140000;
    bootloader_migration_tick(true, true);
    assert(!bootloader_migration_pending());
    assert(!bootloader_migration_service_due());
    no_install(3);
    bootloader_migration_status(reply, sizeof(reply));
    assert(std::strstr(reply, candidate_installed ? "already installed" : "up to date"));
  } else if (std::strcmp(scenario, "automatic-retained-failure") == 0) {
    power_registers.GPREGRET = 0xCC;
    now = 70000;
    bootloader_migration_tick(true, true);
    assert(!bootloader_migration_pending());
    assert(!bootloader_migration_service_due());
    no_install(1);
    now = 140000;
    bootloader_migration_tick(true, true);
    no_install(1); // Retained failures must not create a warm-reset retry loop.
    bootloader_migration_status(reply, sizeof(reply));
    assert(std::strstr(reply, "auto=blocked"));
    assert(bootloader_migration_request(nullptr, reply, sizeof(reply)));
    assert(bootloader_migration_pending());
    assert(std::strstr(reply, "OK migration armed"));
    now = 141500;
    bootloader_migration_tick(true, true);
    assert(endf_checks == 1); // An explicit operator request may still retry.
    assert(!bootloader_migration_pending());
  } else if (std::strcmp(scenario, "manual-cancel-consumes-automatic") == 0 ||
             std::strcmp(scenario, "manual-failure-consumes-automatic") == 0) {
    arm();
    now = 1500;
    const bool cancel = std::strcmp(scenario, "manual-cancel-consumes-automatic") == 0;
    bootloader_migration_tick(true, !cancel);
    assert(!bootloader_migration_pending());
    assert(endf_checks == (cancel ? 0u : 1u));
    now = 70000;
    assert(!bootloader_migration_service_due());
    bootloader_migration_tick(true, true);
    assert(!bootloader_migration_pending());
    assert(endf_checks == (cancel ? 0u : 1u));
    assert(softdevice_checks == 1);
  } else if (std::strcmp(scenario, "automatic-cancel") == 0) {
    now = 70000;
    bootloader_migration_tick(true, true);
    assert(bootloader_migration_pending());
    now = 70100;
    bootloader_migration_tick(true, false);
    assert(!bootloader_migration_pending());
    assert(!bootloader_migration_service_due());
    no_install(3);
    now = 140000;
    bootloader_migration_tick(true, true);
    assert(!bootloader_migration_pending());
    assert(!bootloader_migration_service_due());
    no_install(3);
    status_result(16);
  } else if (std::strcmp(scenario, "invalid-confirmation-preserves-automatic") == 0) {
    now = 1000;
    assert(!bootloader_migration_request("0123456789ABCDE0", reply, sizeof(reply)));
    assert(!bootloader_migration_pending());
    now = 70000;
    assert(bootloader_migration_service_due());
    bootloader_migration_tick(true, true);
    assert(bootloader_migration_pending());
    no_install(3);
    now = 71500;
    bootloader_migration_tick(true, true);
    assert(endf_checks == 1);
    assert(!bootloader_migration_pending());
    assert(!bootloader_migration_service_due());
  } else if (std::strcmp(scenario, "automatic-status-read-failure") == 0 ||
             std::strcmp(scenario, "automatic-marker-read-failure") == 0) {
    power_registers.GPREGRET = mesh::ota::ATTEMPT_MARKER;
    if (std::strcmp(scenario, "automatic-status-read-failure") == 0) {
      softdevice_status = 1;
    } else {
      softdevice_enabled = true;
      retained_get_status = 1;
    }
    now = 70000;
    bootloader_migration_tick(true, true);
    assert(!bootloader_migration_pending());
    assert(!bootloader_migration_service_due());
    no_install(1);
    assert(retained_reads == (softdevice_enabled ? 1u : 0u));
    assert(retained_clears == 0 && retained_sets == 0);
    assert(power_registers.GPREGRET == mesh::ota::ATTEMPT_MARKER);
    bootloader_migration_status(reply, sizeof(reply));
    assert(std::strstr(reply, "auto=blocked"));
  } else if (std::strcmp(scenario, "guard-softdevice-enabled") == 0) {
    softdevice_enabled = true;
    power_registers.GPREGRET = 0xAA;
    arm();
    assert(retained_clears == 1 && retained_sets == 1);
    no_install(1);
    assert(bootloader_migration_request(nullptr, reply, sizeof(reply)));
    assert(retained_clears == 1 && retained_sets == 1); // Duplicates do no work.
    now = 1500;
    bootloader_migration_tick(true, true);
    assert(endf_checks == 1);
    assert(power_registers.GPREGRET == mesh::ota::ATTEMPT_MARKER);
  } else if (std::strcmp(scenario, "guard-softdevice-status-failure") == 0 ||
             std::strcmp(scenario, "guard-marker-read-failure") == 0 ||
             std::strcmp(scenario, "guard-clear-failure") == 0 ||
             std::strcmp(scenario, "guard-set-failure") == 0) {
    power_registers.GPREGRET = 0x37;
    if (std::strcmp(scenario, "guard-softdevice-status-failure") == 0) {
      softdevice_status = 1;
    } else {
      softdevice_enabled = true;
      if (std::strcmp(scenario, "guard-marker-read-failure") == 0)
        retained_get_status = 1;
      else if (std::strcmp(scenario, "guard-clear-failure") == 0)
        retained_clear_status = 1;
      else
        retained_set_status = 1;
    }
    assert(!bootloader_migration_request(nullptr, reply, sizeof(reply)));
    assert(std::strstr(reply, "ERR bootloader reboot guard unavailable"));
    assert(!bootloader_migration_pending());
    no_install(1);
    assert(retained_clears == (softdevice_enabled && !retained_get_status ? 1u : 0u));
    assert(retained_sets == (retained_set_status ? 1u : 0u));
    assert(power_registers.GPREGRET == (retained_set_status ? 0u : 0x37u));
    now = 70000;
    assert(!bootloader_migration_service_due());
    bootloader_migration_tick(true, true);
    no_install(1);
    status_result(17);
  } else if (std::strcmp(scenario, "automatic-interrupted-check") == 0 ||
             std::strcmp(scenario, "automatic-interrupted-arm") == 0) {
    const bool during_check = std::strcmp(scenario, "automatic-interrupted-check") == 0;
    now = 70000;
    interrupt_hash = during_check;
    bool interrupted = false;
    try {
      bootloader_migration_tick(true, true);
    } catch (const std::runtime_error &error) {
      assert(during_check);
      assert(std::strcmp(error.what(), "interrupted bootloader check") == 0);
      interrupted = true;
    }
    assert(interrupted == during_check);
    assert(bootloader_migration_pending() == !during_check);
    assert(power_registers.GPREGRET == mesh::ota::ATTEMPT_MARKER);
    assert(endf_checks == 0);
    const unsigned initial_reads = softdevice_checks;
    restart_application();
    interrupt_hash = false;
    now = 69999;
    assert(!bootloader_migration_service_due());
    now = 70000;
    assert(bootloader_migration_service_due());
    bootloader_migration_tick(true, true);
    assert(!bootloader_migration_pending());
    assert(!bootloader_migration_service_due());
    assert(power_registers.GPREGRET == mesh::ota::ATTEMPT_MARKER);
    no_install(initial_reads + 1);
    now = 140000;
    bootloader_migration_tick(true, true);
    no_install(initial_reads + 1); // A second reset-time check must not repeat.
    bootloader_migration_status(reply, sizeof(reply));
    assert(std::strstr(reply, "auto=blocked"));
    arm(); // An operator can retry after correcting an interruption's cause.
    now = 141500;
    bootloader_migration_tick(true, true);
    assert(endf_checks == 1);
    assert(!bootloader_migration_pending());
  } else if (std::strcmp(scenario, "already-installed") == 0) {
    power_registers.GPREGRET = 0x37;
    candidate_installed = true;
    assert(bootloader_migration_request(confirmation, reply, sizeof(reply)));
    assert(!bootloader_migration_pending());
    assert(std::strstr(reply, "already installed"));
    now = 2000;
    bootloader_migration_tick(true, true);
    no_install();
    assert(power_registers.GPREGRET == 0x37);
    bootloader_migration_status(reply, sizeof(reply));
    assert(std::strstr(reply, "already installed"));
  } else if (std::strcmp(scenario, "same-version") == 0 ||
             std::strcmp(scenario, "newer-version") == 0) {
    power_registers.GPREGRET = 0x37;
    const uint32_t version = std::strcmp(scenario, "same-version") == 0
                                 ? migration_boot_version : 0x02040D01;
    seal_manifest(installed_manifest(version));
    // Live status has to detect this before any request, as it would after reboot.
    bootloader_migration_status(reply, sizeof(reply));
    assert(std::strstr(reply, "up to date"));
    assert(!bootloader_migration_pending());
    assert(!bootloader_migration_request("0123456789ABCDE0", reply, sizeof(reply)));
    assert(!bootloader_migration_pending());
    softdevice_checks = 0; // Status may read the retained diagnostic result.
    const char *tokens[] = {nullptr, confirmation};
    for (const char *token : tokens) {
      assert(bootloader_migration_request(token, reply, sizeof(reply)));
      assert(!bootloader_migration_pending());
      assert(std::strstr(reply, "up to date"));
      now += 2000;
      bootloader_migration_tick(true, true);
      no_install();
      assert(power_registers.GPREGRET == 0x37);
    }
  } else if (std::strcmp(scenario, "easy-update") == 0 ||
             std::strcmp(scenario, "older-preview") == 0) {
    if (std::strcmp(scenario, "older-preview") == 0)
      seal_manifest(installed_manifest(0x02040CFE));
    assert(bootloader_migration_request(nullptr, reply, sizeof(reply)));
    assert(bootloader_migration_pending());
    assert(std::strstr(reply, "OK migration armed"));
    now = 1499;
    bootloader_migration_tick(true, true);
    no_install(1);
    ++now;
    bootloader_migration_tick(true, true);
    assert(endf_checks == 1);
    assert(!bootloader_migration_pending());
  } else if (std::strncmp(scenario, "invalid-version-", 16) == 0) {
    uint8_t *p = installed_manifest(0x02040DFF);
    const char *mutation = scenario + 16;
    if (std::strcmp(mutation, "board") == 0) wr32(p + 20, migration_board_id ^ 1);
    else if (std::strcmp(mutation, "name") == 0) p[24] = 'X';
    else if (std::strcmp(mutation, "family") == 0) wr16(p + 60, 132);
    else if (std::strcmp(mutation, "fwid") == 0) wr16(p + 62, 0x123);
    else if (std::strcmp(mutation, "app") == 0) wr32(p + 64, 0x27000);
    else if (std::strcmp(mutation, "abi") == 0) wr16(p + 68, 2);
    else if (std::strcmp(mutation, "continuity") == 0) std::memset(p + 44, 0xFF, 32);
    else assert(std::strcmp(mutation, "crc") == 0);
    seal_manifest(p);
    if (std::strcmp(mutation, "crc") == 0) p[40] ^= 1;
    bootloader_migration_status(reply, sizeof(reply));
    assert(!std::strstr(reply, "up to date"));
    assert(bootloader_migration_request(nullptr, reply, sizeof(reply)));
    assert(bootloader_migration_pending());
    assert(!std::strstr(reply, "up to date"));
    now = 1500;
    bootloader_migration_tick(true, true);
    // The production install preflight still runs, and the EndF stub refuses it.
    assert(endf_checks == 1);
    assert(!bootloader_migration_pending());
  } else if (std::strcmp(scenario, "wrong-confirmation") == 0) {
    assert(!bootloader_migration_request("0123456789ABCDE0", reply, sizeof(reply)));
    assert(!bootloader_migration_request("0123456789abcdef", reply, sizeof(reply)));
    assert(!bootloader_migration_request("0123456789ABCDEF ", reply, sizeof(reply)));
    assert(!bootloader_migration_pending());
    now = 2000;
    bootloader_migration_tick(true, true);
    no_install();
  } else if (std::strcmp(scenario, "grace-and-drain") == 0) {
    arm();
    now = 1499;
    bootloader_migration_tick(true, true);
    no_install(1);
    now = 1500;
    bootloader_migration_tick(false, true);
    no_install(1);
    now = 29999;
    bootloader_migration_tick(false, true);
    no_install(1);
    assert(bootloader_migration_pending());
    bootloader_migration_tick(true, true);
    assert(endf_checks == 1);
    assert(!bootloader_migration_pending());
    assert(disables == 0 && resets == 0 && copies == 0);
    status_result(1);
  } else if (std::strcmp(scenario, "duplicate-arm") == 0) {
    arm();
    now = 1499;
    assert(!bootloader_migration_request("0123456789ABCDE0", reply, sizeof(reply)));
    assert(bootloader_migration_pending());
    assert(bootloader_migration_request(nullptr, reply, sizeof(reply)));
    assert(std::strstr(reply, "OK bootloader update already armed"));
    assert(bootloader_migration_request(confirmation, reply, sizeof(reply)));
    assert(std::strstr(reply, "already armed"));
    now = 1500;
    bootloader_migration_tick(true, true);
    assert(endf_checks == 1); // A duplicate must not extend the grace period.
  } else if (std::strcmp(scenario, "timeout") == 0) {
    arm();
    now = 30000;
    bootloader_migration_tick(true, true);
    assert(!bootloader_migration_pending());
    no_install(1);
    status_result(15);
    bootloader_migration_tick(true, true);
    assert(endf_checks == 0);
  } else if (std::strcmp(scenario, "ota-cancel-rearm") == 0) {
    arm();
    now = 100;
    bootloader_migration_tick(false, false);
    assert(!bootloader_migration_pending());
    no_install(1);
    status_result(16);
    now = 2000;
    bootloader_migration_tick(true, true);
    assert(endf_checks == 0); // Becoming idle must not revive cancelled work.
    arm();
    now = 3499;
    bootloader_migration_tick(true, true);
    assert(endf_checks == 0);
    now = 3500;
    bootloader_migration_tick(true, true);
    assert(endf_checks == 1);
  } else if (std::strcmp(scenario, "ota-cancel-at-install") == 0) {
    arm();
    now = 1500;
    bootloader_migration_tick(true, false);
    assert(!bootloader_migration_pending());
    no_install(1);
    status_result(16);
  } else if (std::strcmp(scenario, "stale-retained-result") == 0) {
    power_registers.GPREGRET = 0xCC;
    status_result(12);
    arm();
    status_result(0);
    now = 30000;
    bootloader_migration_tick(true, true);
    assert(!bootloader_migration_pending());
    status_result(15);
    arm();
    status_result(0);
    ++now;
    bootloader_migration_tick(true, false);
    assert(!bootloader_migration_pending());
    status_result(16);
    assert(power_registers.GPREGRET == mesh::ota::ATTEMPT_MARKER);
    assert(endf_checks == 0);
  } else if (std::strcmp(scenario, "clock-wrap") == 0) {
    now = UINT32_MAX - 999u;
    arm();
    now += 1499u;
    bootloader_migration_tick(true, true);
    no_install(1);
    ++now;
    bootloader_migration_tick(true, true);
    assert(endf_checks == 1);
  } else {
    throw std::runtime_error("unknown scenario");
  }
  assert(disables == 0 && resets == 0 && copies == 0);
}
