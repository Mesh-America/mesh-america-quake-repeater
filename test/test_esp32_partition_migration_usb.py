"""Regression contracts for the callback-free USB migration bridge runtime."""

from pathlib import Path
import hashlib
import importlib.util
import os
import shutil
import subprocess
import tempfile
from unittest import mock
import unittest


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "examples/esp32_partition_migrator/main.cpp"
RECOVERY = ROOT / "src/helpers/ESP32PartitionMigrationUsbRecovery.h"
GUARD = ROOT / "scripts/esp32_partition_migration_nvs_guard.py"
SPEC = importlib.util.spec_from_file_location("migration_nvs_guard", GUARD)
NVS_GUARD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(NVS_GUARD)

SDK_MOCK = r'''
#pragma once
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <stdexcept>
#define IRAM_ATTR
#define DRAM_ATTR
#define ESP_OK 0
#define RTC_CNTL_OPTION1_REG rom_flag
#define RTC_CNTL_FORCE_DOWNLOAD_BOOT 1U
#define REG_SET_BIT(reg, bits) ((reg) |= (bits))
using esp_err_t = int;
using shutdown_handler_t = void (*)();
using esp_efuse_desc_t = int;
static uint32_t rom_flag = 0;
static bool encrypted = false, secure = false, registration_fails = false;
static const esp_efuse_desc_t** disabled_field = nullptr;
static shutdown_handler_t handlers[4] = {};
static size_t handler_count = 0;
static const esp_efuse_desc_t* ESP_EFUSE_DIS_FORCE_DOWNLOAD[] = {nullptr};
static const esp_efuse_desc_t* ESP_EFUSE_DIS_DOWNLOAD_MODE[] = {nullptr};
static const esp_efuse_desc_t* ESP_EFUSE_DIS_USB_SERIAL_JTAG_DOWNLOAD_MODE[] = {nullptr};
static const esp_efuse_desc_t* ESP_EFUSE_DIS_USB_SERIAL_JTAG[] = {nullptr};
static const esp_efuse_desc_t* ESP_EFUSE_DIS_USB_DEVICE[] = {nullptr};
static const esp_efuse_desc_t* ESP_EFUSE_UART_DOWNLOAD_DIS[] = {nullptr};
static bool esp_efuse_read_field_bit(const esp_efuse_desc_t** field) { return field == disabled_field; }
static bool esp_flash_encryption_enabled() { return encrypted; }
static bool esp_secure_boot_enabled() { return secure; }
static int esp_efuse_mac_get_default(uint8_t* mac) {
  for (int i = 0; i < 6; ++i) mac[i] = i + 1;
  return ESP_OK;
}
static int esp_register_shutdown_handler(shutdown_handler_t handler) {
  if (registration_fails || handler_count == 4) return 1;
  handlers[handler_count++] = handler;
  return ESP_OK;
}
static int esp_unregister_shutdown_handler(shutdown_handler_t handler) {
  for (size_t i = 0; i < handler_count; ++i) {
    if (handlers[i] != handler) continue;
    for (size_t j = i + 1; j < handler_count; ++j) handlers[j - 1] = handlers[j];
    --handler_count;
    return ESP_OK;
  }
  return 1;
}
static void esp_restart() {
  for (size_t i = 0; i < handler_count; ++i) handlers[i]();
  throw 123;
}
struct SerialMock { void flush() {} void end() {} void begin(int) {} };
static SerialMock Serial;
enum restart_type_t { RESTART_BOOTLOADER };
static void sdkForceDownload() { rom_flag |= RTC_CNTL_FORCE_DOWNLOAD_BOOT; }
static void usb_persist_restart(restart_type_t) {
  if (esp_register_shutdown_handler(sdkForceDownload) == ESP_OK) esp_restart();
}
'''

RECOVERY_HARNESS = r'''
#include <helpers/ESP32PartitionMigrationUsbRecovery.h>
static void require(bool ok, const char* why) { if (!ok) throw std::runtime_error(why); }
static void resetMock() {
  rom_flag = 0; handler_count = 0; registration_fails = false;
  disabled_field = nullptr; encrypted = secure = false;
#if CONFIG_IDF_TARGET_ESP32S3 || CONFIG_IDF_TARGET_ESP32C3
  mesh::esp32_partition_usb::force_download_armed = false;
#endif
}
int main() {
  try {
    resetMock();
    mesh::esp32_partition_usb::Recovery recovery;
    require(recovery.prepare() == nullptr, "normal recovery preflight failed");
    require(strcmp(recovery.deviceMac(), "010203040506") == 0, "ROM MAC not canonical");
    // The migration-table restart MUST boot the bridge, not bypass restoration.
    try { esp_restart(); } catch (int) {}
    require(rom_flag == 0, "first restart bypassed config restoration");
#if CONFIG_IDF_TARGET_ESP32S3 || CONFIG_IDF_TARGET_ESP32C3
    bool rebooted = false;
    try { recovery.returnToRom(); } catch (int) { rebooted = true; }
    require(rebooted && rom_flag == 1, "settled native bridge did not return to ROM");
    resetMock();
    registration_fails = true;
    mesh::esp32_partition_usb::Recovery no_slot;
    require(no_slot.prepare() != nullptr, "missing shutdown slot allowed migration");
    require(!no_slot.returnToRom(), "unprepared native bridge tried to restart");
    resetMock();
    disabled_field = ESP_EFUSE_DIS_FORCE_DOWNLOAD;
    mesh::esp32_partition_usb::Recovery fused;
    require(fused.prepare() != nullptr && handler_count == 0, "fused recovery route accepted");
    resetMock();
    encrypted = true;
    mesh::esp32_partition_usb::Recovery protected_flash;
    require(protected_flash.prepare() != nullptr, "encrypted installation accepted");
    rebooted = false;
    try { protected_flash.returnToRom(); } catch (int) { rebooted = true; }
    require(rebooted && rom_flag == 1, "protected refusal was not recoverable");
#else
    require(!recovery.returnToRom() && rom_flag == 0, "classic UART guessed native ROM force entry");
    resetMock();
    disabled_field = ESP_EFUSE_UART_DOWNLOAD_DIS;
    mesh::esp32_partition_usb::Recovery fused;
    require(fused.prepare() != nullptr, "disabled UART recovery route accepted");
#endif
    return 0;
  } catch (const std::exception& error) {
    fprintf(stderr, "%s\n", error.what()); return 1;
  }
}
'''


class UsbPartitionMigrationRuntimeTest(unittest.TestCase):
    def test_distinct_image_marker_is_retained_by_runtime_use(self):
        header = RECOVERY.read_text(encoding="utf-8")
        source = SOURCE.read_text(encoding="utf-8")
        self.assertIn('"MeshCore USB partition migration bridge v1"', header)
        self.assertIn('"meshcore-usb-partition-migration-v1"', header)
        self.assertIn("Serial.println(mesh::esp32_partition_usb::kImageMarker)", source)
        self.assertIn('extern "C" const char* meshEsp32MigrationNvsGuardMarker(void)', header)
        self.assertIn("Serial.println(meshEsp32MigrationNvsGuardMarker())", source)
        self.assertEqual("MeshCore USB NVS no-autoerase guard v1", NVS_GUARD.BINARY_MARKER)

    def test_native_usb_callbacks_cannot_start_in_usb_bridge(self):
        header = RECOVERY.read_text(encoding="utf-8")
        self.assertIn("#if ARDUINO_USB_CDC_ON_BOOT || ARDUINO_USB_MSC_ON_BOOT", header)
        self.assertIn("ARDUINO_USB_DFU_ON_BOOT || ARDUINO_USB_ON_BOOT", header)
        self.assertIn('#error "The USB partition migration image must not start application USB"', header)
        self.assertNotIn("\n    USB.begin(", header)
        self.assertNotIn("\n    tinyusb_init(", header)
        source = SOURCE.read_text(encoding="utf-8")
        self.assertIn("#if !defined(MESHCORE_MIGRATION_USB) || !MESHCORE_MIGRATION_USB\n#include <WiFi.h>", source)
        self.assertIn("#if !defined(MESHCORE_MIGRATION_USB) || !MESHCORE_MIGRATION_USB\nvoid sendHome", source)

    def test_preflight_happens_on_both_boots_before_nvs_writes(self):
        source = SOURCE.read_text(encoding="utf-8")
        setup = source[source.index("void setup()") : source.index("void loop()")]
        self.assertLess(setup.index("usb_recovery.prepare()"), setup.index("findPartitions(refs, geometry)"))
        self.assertLess(setup.index("usb_recovery.prepare()"), setup.index("restoreStagedIdentity()"))
        self.assertIn("settleUsbMigration(false);\n    return;", setup)
        header = RECOVERY.read_text(encoding="utf-8")
        for symbol in ("ESP_EFUSE_DIS_FORCE_DOWNLOAD", "ESP_EFUSE_DIS_DOWNLOAD_MODE",
                       "ESP_EFUSE_DIS_USB_SERIAL_JTAG_DOWNLOAD_MODE",
                       "ESP_EFUSE_DIS_USB_SERIAL_JTAG", "ESP_EFUSE_DIS_USB_DEVICE",
                       "ESP_EFUSE_UART_DOWNLOAD_DIS", "esp_flash_encryption_enabled()",
                       "esp_secure_boot_enabled()"):
            self.assertIn(symbol, header)
        self.assertNotIn("ESP_EFUSE_DIS_USB_JTAG)", header)

    def test_rom_shutdown_slot_reserved_before_partition_changes(self):
        header = RECOVERY.read_text(encoding="utf-8")
        prepare = header[header.index("const char* prepare()") : header.index("const char* deviceMac()")]
        self.assertIn("esp_register_shutdown_handler(forceDownloadBoot)", prepare)
        self.assertIn("static void IRAM_ATTR forceDownloadBoot()", header)
        callback = header[header.index("static void IRAM_ATTR forceDownloadBoot()") : header.index("class Recovery")]
        self.assertIn("static DRAM_ATTR bool force_download_armed = false", header)
        self.assertIn("if (force_download_armed)", callback)
        self.assertIn("REG_SET_BIT(RTC_CNTL_OPTION1_REG, RTC_CNTL_FORCE_DOWNLOAD_BOOT)", callback)
        self.assertNotIn("Serial.", callback)
        self.assertNotIn("esp_flash_", callback)
        restore = header[header.index("bool returnToRom()") : header.index("private:")]
        self.assertIn("force_download_armed = true", restore)
        self.assertLess(restore.index("esp_unregister_shutdown_handler(forceDownloadBoot)"),
                        restore.index("usb_persist_restart(RESTART_BOOTLOADER)"))
        self.assertIn("#if CONFIG_IDF_TARGET_ESP32C3\n    esp_restart()", restore)

    def test_completion_requires_restored_files_and_persisted_markers(self):
        source = SOURCE.read_text(encoding="utf-8")
        setup = source[source.index("void setup()") : source.index("void loop()")]
        self.assertLess(setup.index("restoreStagedIdentity()"), setup.index("restoreStagedConfig()"))
        self.assertLess(setup.index("restoreStagedConfig()"), setup.index("verifyExpandedIdentityFile()"))
        self.assertLess(setup.index("verifyExpandedIdentityFile()"), setup.index("verifiedUsbHandoff()"))
        self.assertIn("const bool restored = identity_ready && verifiedUsbHandoff()", setup)
        proof = source[source.index("bool verifiedUsbHandoff()") : source.index("void sendUsbState()")]
        for marker in ("kMigrationConfigRestoredKey", "kMigrationConfigPendingKey", "kMigrationIdentityPendingKey"):
            self.assertIn(marker, proof)
        self.assertIn("&& !nvs.getBool(kMigrationConfigPendingKey, false)", proof)
        self.assertIn("&& !nvs.getBool(kMigrationIdentityPendingKey, false)", proof)

    def test_table_publish_reboots_to_restore_not_directly_to_rom(self):
        source = SOURCE.read_text(encoding="utf-8")
        body = source[source.index("void runMigration()") : source.index("void sendHome")]
        self.assertIn("Migration complete; restarting USB restore bridge", body)
        self.assertNotIn("returnToRom()", body)
        self.assertLess(body.index("Serial.end()"), body.index("publishExpandedPartitionTable(*plan)"))
        self.assertLess(body.index("publishExpandedPartitionTable(*plan)"), body.index("Serial.begin(115200)"))
        self.assertIn("chip->os_func = original_hooks", source)

    def test_uart_status_is_explicit_bounded_and_public_only(self):
        source = SOURCE.read_text(encoding="utf-8")
        status = source[source.index("void sendUsbState()") : source.index("void settleUsbMigration")]
        self.assertIn("MESHCORE_USB_MIGRATION_STATE", status)
        for key in ('\\\"device_mac\\\"', '\\\"settled\\\"', '\\\"restored\\\"'):
            self.assertIn(key, status)
        self.assertNotIn("kMigrationIdentity", status)
        self.assertNotIn("nvs.get", status)
        self.assertIn('strcmp(usb_command, "migration status")', source)
        self.assertIn("usb_command_bytes + 1 < sizeof(usb_command)", source)
        self.assertIn("millis() - usb_status_at) >= 1000", source)
        loop = source[source.index("void loop()") :]
        self.assertIn("if (!migration_complete) settleUsbMigration(false)", loop)

    def test_startup_nvs_autoformat_removed_without_changing_other_initialization(self):
        fixture = "void initArduino() {\n    esp_err_t err = nvs_flash_init();\n" + NVS_GUARD.AUTOFORMAT + "    if(err) log_e(\"NVS init failed\");\n}\n"
        fixture_hash = hashlib.sha256(fixture.encode()).hexdigest()
        with mock.patch.object(NVS_GUARD, "PINNED_MISC_SHA256", fixture_hash):
            patched = NVS_GUARD.patched_misc_source(fixture)
            self.assertNotIn("esp_partition_erase_range", patched)
            self.assertIn("esp_err_t err = nvs_flash_init()", patched)
            self.assertIn('if(err) log_e("NVS init failed")', patched)
            self.assertIn(NVS_GUARD.GUARD_MARKER, patched)
            self.assertIn(NVS_GUARD.BINARY_MARKER, patched)
            self.assertEqual(patched, NVS_GUARD.patched_misc_source(patched))
            self.assertEqual(patched, NVS_GUARD.patched_misc_source(fixture.replace("\n", "\r\n")))

    def test_changed_sdk_fails_closed_instead_of_guessing_erase_branch(self):
        for source in ("void initArduino() {}", NVS_GUARD.AUTOFORMAT,
                       NVS_GUARD.AUTOFORMAT.replace("partition->size", "0x5000")):
            with self.assertRaisesRegex(RuntimeError, "review SDK update"):
                NVS_GUARD.patched_misc_source(source)

    def test_nvs_middleware_does_not_affect_normal_firmware(self):
        class BuildEnv(dict):
            pass
        self.assertFalse(NVS_GUARD.usb_migration_enabled(BuildEnv(CPPDEFINES=[])))
        self.assertFalse(NVS_GUARD.usb_migration_enabled(BuildEnv(CPPDEFINES=[("MESHCORE_MIGRATION_USB", 0)])))
        self.assertTrue(NVS_GUARD.usb_migration_enabled(BuildEnv(CPPDEFINES=[("MESHCORE_MIGRATION_USB", 1)])))
        self.assertTrue(NVS_GUARD.usb_migration_enabled(BuildEnv(CPPDEFINES=["MESHCORE_MIGRATION_USB"])))
        sentinel = object()
        self.assertIs(sentinel, NVS_GUARD.replace_source(BuildEnv(CPPDEFINES=[]), sentinel))

    def test_scons_compiles_private_guard_copy_without_patching_shared_sdk(self):
        fixture = "void initArduino() {\n    esp_err_t err = nvs_flash_init();\n" + NVS_GUARD.AUTOFORMAT + "}\n"
        fixture_hash = hashlib.sha256(fixture.encode()).hexdigest()
        class SourceNode:
            def __init__(self, path): self.path = path
            def srcnode(self): return self
            def get_abspath(self): return str(self.path)
        class BuildEnv(dict):
            def subst(self, value): return self["build_dir"]
            def AppendUnique(self, **kwargs): self["paths"] = kwargs["CPPPATH"]
            def File(self, path): return Path(path)
        with tempfile.TemporaryDirectory(prefix="meshcore-nvs-middleware-") as temp:
            sdk = Path(temp) / "shared-sdk" / "esp32-hal-misc.c"
            sdk.parent.mkdir()
            sdk.write_text(fixture, encoding="utf-8")
            env = BuildEnv(CPPDEFINES=[("MESHCORE_MIGRATION_USB", 1)],
                           build_dir=str(Path(temp) / "build"))
            with mock.patch.object(NVS_GUARD, "PINNED_MISC_SHA256", fixture_hash):
                result = NVS_GUARD.replace_source(env, SourceNode(sdk))
            self.assertEqual(fixture, sdk.read_text(encoding="utf-8"))
            self.assertNotEqual(sdk, result)
            self.assertEqual(Path(env["build_dir"]) / "patched-esp32-migration" / sdk.name, result)
            self.assertIn(NVS_GUARD.BINARY_MARKER, result.read_text(encoding="utf-8"))
            self.assertNotIn("esp_partition_erase_range", result.read_text(encoding="utf-8"))
            self.assertEqual([str(sdk.parent)], env["paths"])

    def test_recovery_state_machine_preserves_first_boot_and_returns_only_when_armed(self):
        compiler = os.environ.get("CXX") or shutil.which("c++") or shutil.which("g++")
        self.assertIsNotNone(compiler, "a C++ compiler is required for USB recovery state tests")
        with tempfile.TemporaryDirectory(prefix="meshcore-usb-recovery-") as temp:
            directory = Path(temp)
            (directory / "mock_sdk.h").write_text(SDK_MOCK, encoding="utf-8")
            for name in ("Arduino.h", "esp_attr.h", "esp_efuse.h", "esp_efuse_table.h",
                         "esp_flash_encrypt.h", "esp_mac.h", "esp_secure_boot.h", "esp_system.h",
                         "soc/rtc_cntl_reg.h", "soc/soc.h", "esp32-hal-tinyusb.h"):
                stub = directory / name
                stub.parent.mkdir(parents=True, exist_ok=True)
                stub.write_text('#include "mock_sdk.h"\n', encoding="utf-8")
            harness = directory / "recovery.cpp"
            harness.write_text(RECOVERY_HARNESS, encoding="utf-8")
            for chip in ("ESP32S3", "ESP32C3", "ESP32"):
                with self.subTest(chip=chip):
                    executable = directory / (chip + (".exe" if os.name == "nt" else ""))
                    command = [str(compiler), "-std=c++11", "-I", str(directory), "-I", str(ROOT / "src"),
                               "-DMESHCORE_MIGRATION_USB=1", "-DCONFIG_TINYUSB_ENABLED=1",
                               "-DCONFIG_IDF_TARGET_" + chip + "=1", str(harness), "-o", str(executable)]
                    result = subprocess.run(command, text=True, capture_output=True)
                    self.assertEqual(0, result.returncode, result.stdout + result.stderr)
                    result = subprocess.run([str(executable)], text=True, capture_output=True)
                    self.assertEqual(0, result.returncode, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
