#pragma once

#include <stdint.h>
#include <stddef.h>
#include <string.h>
#include <math.h>
#include "UsbLoggingStatus.h"

// Portable management wire format. No update authorization is granted by this
// protocol. See docs/management_reports.md for the byte layout and trust model.
namespace mesh { namespace management {
constexpr size_t HEADER = 83, TAG = 16, ENTRY = 13, PER_PAGE = 6;
constexpr size_t USB_STATUS_SIZE = 15;
constexpr size_t WATCHDOG_EVENT_OFFSET = HEADER + USB_STATUS_SIZE;
constexpr size_t CURRENT_HEADER = WATCHDOG_EVENT_OFFSET + USB_WATCHDOG_EVENT_SIZE;
constexpr size_t CURRENT_PER_PAGE = 4;
constexpr size_t MAX_KEYS = 36, MAX_PAGES = 9;
constexpr size_t MAX_PAYLOAD = CURRENT_HEADER + TAG + CURRENT_PER_PAGE * ENTRY;
static_assert(MAX_PAYLOAD == 179, "MGR2 must fit the legacy padded payload budget");
constexpr uint32_t DAY = 86400, FLOOD_INTERVAL = 21 * DAY;
enum Feature : uint8_t { WIFI = 1, GPS = 2, NTP = 4, USB = 8, OTA = 16 };
enum Valid : uint16_t { FIRMWARE = 1, BOOTLOADER = 2, BASE = 4, STORE = 8,
  PARTIAL_WEEK = 16, PARTIAL_PERIOD = 32, MCU_TEMPERATURE = 64 };
enum Permission : uint8_t { ADMIN = 1, OTA_SIGNER = 2 };

inline uint16_t read16(const uint8_t* p) { return p[0] | (uint16_t(p[1]) << 8); }
inline uint32_t read32(const uint8_t* p) { return read16(p) | (uint32_t(read16(p + 2)) << 16); }
inline void write16(uint8_t* p, uint16_t n) { p[0] = n; p[1] = n >> 8; }
inline void write32(uint8_t* p, uint32_t n) { write16(p, n); write16(p + 2, n >> 16); }
inline void erase(void* p, size_t n) { volatile uint8_t* b = static_cast<volatile uint8_t*>(p); while (n--) *b++ = 0; }

// 0 missing, 1..251 = -50..200 C, 252 below range, 253 above range.
inline uint8_t temperature(float c) {
  if (!isfinite(c)) return 0;
  if (c < -50) return 252;
  if (c > 200) return 253;
  return uint8_t(lroundf(c) + 51);
}
inline int tempOrder(uint8_t t) { return t == 252 ? -1 : t == 253 ? 252 : t; }
struct Extrema {
  uint16_t voltage = 0;
  uint8_t low = 0, high = 0;
  void add(uint16_t v, uint8_t t) {
    if (v && (!voltage || v < voltage)) voltage = v;
    if (t && (!low || tempOrder(t) < tempOrder(low))) low = t;
    if (t && (!high || tempOrder(t) > tempOrder(high))) high = t;
  }
  void merge(const Extrema& e) { add(e.voltage, e.low); add(0, e.high); }
  void encode(uint8_t* p) const { write16(p, voltage); p[2] = low; p[3] = high; }
};

// Hourly extrema, retaining at least seven days, at most seven days + one
// hour. Sampling once a minute includes all samples, not only the first one
// in each bucket. No RTC dependence and no claim of pre-boot history.
class History {
  Extrema hours[169] = {};
  uint32_t hour = 0;
  bool started = false;
public:
  Extrema period;
  void advance(uint32_t seconds) {
    const uint32_t h = seconds / 3600;
    if (!started || h < hour || h - hour >= 169) memset(hours, 0, sizeof(hours));
    else for (uint32_t i = hour + 1; i <= h; ++i) hours[i % 169] = Extrema();
    started = true; hour = h;
  }
  void sample(uint32_t seconds, uint16_t v, float c) {
    advance(seconds); const uint8_t t = temperature(c);
    hours[hour % 169].add(v, t); period.add(v, t);
  }
  Extrema week() const { Extrema result; for (const auto& h : hours) result.merge(h); return result; }
};

// Countdown seconds survive reboot via conservative hourly checkpoints.
// Wall-clock changes never accelerate reporting. Offline time is not credited.
struct Schedule {
  uint32_t direct = 5 * DAY, flood = 21 * DAY;
  static uint32_t sub(uint32_t n, uint32_t elapsed) { return elapsed < n ? n - elapsed : 0; }
  void advance(uint32_t elapsed) { direct = sub(direct, elapsed); flood = sub(flood, elapsed); }
  static bool validDirect(unsigned days) { return days >= 5 && days <= 90; }
  static bool validFlood(unsigned days) { return days >= 21 && days <= 90; }
  void reserve(bool is_flood, unsigned direct_days, unsigned flood_days,
               uint32_t jitter) {
    if (is_flood) {
      flood = flood_days * DAY + jitter;
      // A flood replaces a direct copy only when that copy is already due.
      // Otherwise the independent direct cadence is left untouched.
      if (!direct && direct_days) direct = direct_days * DAY + jitter;
    } else {
      direct = direct_days * DAY + jitter;
    }
  }
};

void passwordKey(const char* password, uint8_t key[32]);
void deriveKey(const uint8_t key[32], const char* domain, const uint8_t radio[16], uint8_t out[32]);
void fingerprint(const uint8_t key[32], const uint8_t radio[16], const uint8_t admin[32], uint8_t out[12]);
// RFC 5297 AES-SIV with one associated-data string. Tag is stored separately.
// Bound to packet-sized data; decrypt erases plaintext on authentication failure.
bool seal(const uint8_t key[32], const uint8_t* aad, size_t aad_len,
          uint8_t* data, size_t len, uint8_t tag[16]);
bool open(const uint8_t key[32], const uint8_t* aad, size_t aad_len,
          uint8_t* data, size_t len, const uint8_t tag[16]);
bool equal(const uint8_t* a, const uint8_t* b, size_t size);
inline bool currentPage(const uint8_t* p) { return !memcmp(p, "MGR2", 4); }
inline bool usbPage(const uint8_t* p) { return currentPage(p); }
inline size_t headerSize(const uint8_t* p) {
  return currentPage(p) ? CURRENT_HEADER : HEADER;
}
inline size_t entriesPerPage(const uint8_t* p) {
  return currentPage(p) ? CURRENT_PER_PAGE : PER_PAGE;
}
inline size_t pageSize(const uint8_t* p) { return headerSize(p) + p[82] * ENTRY + TAG; }
inline size_t floodSize(size_t canonical) { return 3 + ((canonical - 3 + 15) / 16) * 16; }
#if defined(STM32_PLATFORM) && defined(__GNUC__) && !defined(__clang__)
// The two Mesh callers use different padding modes. Keep one validator on
// flash-constrained STM32 targets instead of LTO specializing each call site.
__attribute__((noinline, noclone))
#endif
inline bool validPage(const uint8_t* p, size_t size, bool flood_padding = false) {
  if (!p || size < HEADER + TAG || size > MAX_PAYLOAD) return false;
  const uint32_t magic = read32(p);
  if ((magic & 0xffffffu) != 0x52474du) return false; // exact MGR prefix
  const unsigned version = (magic >> 24) - '1';
  if (version > 1) return false;
  const size_t minimum = (version ? CURRENT_HEADER : HEADER) + TAG;
  const size_t per_page = version ? CURRENT_PER_PAGE : PER_PAGE;
  if (size < minimum) return false;
  // Reserved bits occupy the upper flag byte and upper two stage bits.
  if (version && (read16(p + HEADER + 1) & 0xc0f8u)) return false;
  if (version && !validUsbWatchdogEvent(p + WATCHDOG_EVENT_OFFSET)) return false;
  const unsigned page = p[78], pages = p[79], total = p[80], first = p[81], count = p[82];
  const unsigned expected_pages = total ? (total + per_page - 1) / per_page : 1;
  if (total > MAX_KEYS || pages != expected_pages || page >= pages || first != page * per_page) return false;
  // Canonical pages and page bounds imply first <= total (also for total 0).
  const unsigned remaining = total - first;
  if (count != (remaining < per_page ? remaining : per_page)) return false;
  const size_t canonical = minimum + count * ENTRY;
  // Exactly one length in [canonical, canonical + 15] is 3 modulo 16.
  // Unsigned underflow also rejects lengths shorter than canonical.
  const size_t padding = size - canonical;
  if (padding > (flood_padding ? 15u : 0u) ||
      (flood_padding && (size & 15u) != 3)) return false;
  for (size_t i = canonical; i < size; ++i) if (p[i]) return false;
  return true;
}

// MGR2 public USB snapshot. The AES-SIV AAD authenticates every byte.
inline void encodeUsbStatus(uint8_t* p, const UsbLoggingStatus& status) {
  const uint16_t flags = (status.supported ? 1u : 0u) |
      (status.logging_enabled ? 2u : 0u) | (status.watchdog_enabled ? 4u : 0u) |
      (status.host_connected ? 8u : 0u) | (status.reader_connected ? 16u : 0u) |
      (status.stalled ? 32u : 0u) | (status.recovering ? 64u : 0u) |
      (status.recovery_deferred ? 128u : 0u) | (status.persistence_ready ? 256u : 0u) |
      (status.watchdog_auto ? 512u : 0u) | (status.logger_active ? 1024u : 0u);
  write16(p, flags);
  p[2] = (status.stage & 3u) | ((status.backoff_step & 15u) << 2);
  write32(p + 3, status.retry_seconds); write32(p + 7, status.inactive_seconds);
  write32(p + 11, status.auto_connected_seconds);
}

struct AclList {
  uint8_t entries[MAX_KEYS][ENTRY] = {};
  uint8_t count = 0;
  bool add(const uint8_t token[12], uint8_t permissions) {
    for (uint8_t i = 0; i < count; ++i) {
      if (!memcmp(entries[i], token, 12)) { entries[i][12] |= permissions; return true; }
    }
    if (count == MAX_KEYS) return false;
    memcpy(entries[count], token, 12); entries[count++][12] = permissions; return true;
  }
  uint8_t pages(size_t per_page = CURRENT_PER_PAGE) const {
    return count ? (count + per_page - 1) / per_page : 1;
  }
};
} }
