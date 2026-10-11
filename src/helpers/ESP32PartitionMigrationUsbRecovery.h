#pragma once

// The USB migration image deliberately does not start an application USB
// driver.  The ROM, rather than a cache-sensitive CDC callback, owns the next
// USB session.  Keep this separate from normal firmware USB session handling.
#if !defined(MESHCORE_MIGRATION_USB) || !MESHCORE_MIGRATION_USB
#error "USB recovery is only for the dedicated USB partition migration image"
#endif
#if ARDUINO_USB_CDC_ON_BOOT || ARDUINO_USB_MSC_ON_BOOT || ARDUINO_USB_DFU_ON_BOOT || ARDUINO_USB_ON_BOOT
#error "The USB partition migration image must not start application USB"
#endif
#if defined(MESHCORE_MIGRATION_RESUME_OTA) || defined(MOTA_MIGRATION_TARGET_ID)
#error "USB migration cannot also be a LoRa bridge or Partition Expander"
#endif

#include <Arduino.h>
#include <esp_attr.h>
#include <esp_efuse.h>
#include <esp_efuse_table.h>
#include <esp_flash_encrypt.h>
#include <esp_mac.h>
#include <esp_secure_boot.h>
#include <esp_system.h>
#include <soc/rtc_cntl_reg.h>
#include <soc/soc.h>
#if CONFIG_IDF_TARGET_ESP32S3
#include <esp32-hal-tinyusb.h>
#if !CONFIG_TINYUSB_ENABLED
#error "ESP32-S3 ROM-return helper requires the pinned Arduino USB persistence API"
#endif
#elif !CONFIG_IDF_TARGET_ESP32C3 && !CONFIG_IDF_TARGET_ESP32
#error "USB partition migration supports ESP32, ESP32-C3 and ESP32-S3 only"
#endif

// Defined only by the reviewed, build-local patched Arduino startup source.
// A USB bridge built without its NVS preservation middleware must fail to link.
extern "C" const char* meshEsp32MigrationNvsGuardMarker(void);

namespace mesh {
namespace esp32_partition_usb {

constexpr char kImageMarker[] = "MeshCore USB partition migration bridge v1";
constexpr char kFormat[] = "meshcore-usb-partition-migration-v1";

#if CONFIG_IDF_TARGET_ESP32S3 || CONFIG_IDF_TARGET_ESP32C3
static DRAM_ATTR bool force_download_armed = false;
// esp_restart() calls this immediately before its cache-off reset path.  The
// force flag must survive any earlier SDK shutdown handlers; no flash, USB,
// logging, heap or FreeRTOS operation belongs in this callback.
static void IRAM_ATTR forceDownloadBoot() {
  // The first reboot must boot the expanded bridge normally so it restores
  // SPIFFS configuration and identity.  Reserving the slot must not force that
  // required restoration boot into the ROM prematurely.
  if (force_download_armed)
    REG_SET_BIT(RTC_CNTL_OPTION1_REG, RTC_CNTL_FORCE_DOWNLOAD_BOOT);
}
#endif

class Recovery {
 public:
  // Call on both the legacy and expanded-layout boots before opening writable
  // NVS/SPIFFS.  These bridges cannot migrate secure/encrypted installations,
  // and must not modify a board whose required recovery route is fused off.
  const char* prepare() {
    uint8_t mac[6] = {};
    if (esp_efuse_mac_get_default(mac) != ESP_OK)
      return "Refused: could not read the ROM device MAC";
    snprintf(mac_, sizeof(mac_), "%02x%02x%02x%02x%02x%02x",
             mac[0], mac[1], mac[2], mac[3], mac[4], mac[5]);

#if CONFIG_IDF_TARGET_ESP32S3 || CONFIG_IDF_TARGET_ESP32C3
    if (esp_efuse_read_field_bit(ESP_EFUSE_DIS_FORCE_DOWNLOAD)
        || esp_efuse_read_field_bit(ESP_EFUSE_DIS_DOWNLOAD_MODE)
        || esp_efuse_read_field_bit(ESP_EFUSE_DIS_USB_SERIAL_JTAG_DOWNLOAD_MODE)
#if CONFIG_IDF_TARGET_ESP32S3
        || esp_efuse_read_field_bit(ESP_EFUSE_DIS_USB_SERIAL_JTAG)
#else
        || esp_efuse_read_field_bit(ESP_EFUSE_DIS_USB_DEVICE)
#endif
        ) return "Refused: automatic USB ROM download is disabled by eFuse";
    // Reserve the shutdown-handler capacity now, not after changing a table.
    // S3's reviewed core helper needs this slot for its own PHY-aware handler.
    if (esp_register_shutdown_handler(forceDownloadBoot) != ESP_OK)
      return "Refused: could not reserve automatic ROM recovery";
    rom_ready_ = true;
#else
    if (esp_efuse_read_field_bit(ESP_EFUSE_UART_DOWNLOAD_DIS))
      return "Refused: UART ROM download is disabled by eFuse";
#endif
    if (esp_flash_encryption_enabled() || esp_secure_boot_enabled())
      return "Refused: encrypted or secure-boot flash cannot use USB migration";
    return nullptr;
  }

  const char* deviceMac() const { return mac_; }

  // Native USB returns automatically.  Classic ESP32 keeps the UART alive and
  // emits an explicit settled handshake; the host may then use the USB-UART
  // adapter's normal DTR/RTS ROM-entry sequence, never a timer-only reset.
  bool returnToRom() {
#if CONFIG_IDF_TARGET_ESP32S3 || CONFIG_IDF_TARGET_ESP32C3
    if (!rom_ready_) return false;
    force_download_armed = true;
    Serial.flush();
    Serial.end();
#if CONFIG_IDF_TARGET_ESP32S3
    // This API is callable without USB.begin()/tinyusb_init().  It changes the
    // internal PHY from OTG to Serial/JTAG, forces host re-enumeration, then
    // resets to the ROM downloader.  There are no further migration writes.
    esp_unregister_shutdown_handler(forceDownloadBoot);
    usb_persist_restart(RESTART_BOOTLOADER);
    // The reserved slot makes failure unexpected, but the API can return if
    // registration fails.  Do not use an abbreviated PHY-reset fallback: a
    // software reset does not reset every USB peripheral or GPIO route.  Stay
    // settled instead; a host timeout must stop, not flash an unproven target.
    Serial.begin(115200);
    rom_ready_ = false;
    return false;
#endif
#if CONFIG_IDF_TARGET_ESP32C3
    esp_restart();
#endif
    return false;  // defensive: esp_restart is documented as non-returning
#else
    return false;
#endif
  }

 private:
  char mac_[13] = {};
  bool rom_ready_ = false;
};

}  // namespace esp32_partition_usb
}  // namespace mesh
