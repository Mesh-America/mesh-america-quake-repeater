#include <helpers/ManagementReport.h>
#include <cassert>
#include <cstdio>
#include <vector>
#include <string>
using namespace mesh::management;
static std::vector<uint8_t> hex(const char* text) {
  std::vector<uint8_t> b;
  while (*text) { unsigned n; assert(sscanf(text, "%2x", &n) == 1); b.push_back(n); text += 2; }
  return b;
}
static void print(const uint8_t* p, size_t n) { while (n--) printf("%02x", *p++); puts(""); }
int main() {
  // RFC 5297 Appendix A.1 (real AES, never the repository's no-op AES mock).
  auto k = hex("fffefdfcfbfaf9f8f7f6f5f4f3f2f1f0f0f1f2f3f4f5f6f7f8f9fafbfcfdfeff");
  auto ad = hex("101112131415161718191a1b1c1d1e1f2021222324252627");
  auto plain = hex("112233445566778899aabbccddee"); auto p = plain;
  uint8_t tag[16]; assert(seal(k.data(), ad.data(), ad.size(), p.data(), p.size(), tag));
  assert(equal(tag, hex("85632d07c6e8f37f950acd320a2ecc93").data(), 16));
  assert(p == hex("40c02b9690c4dc04daef7f6afe5c"));
  assert(open(k.data(), ad.data(), ad.size(), p.data(), p.size(), tag)); assert(p == plain);
  for (size_t n : {size_t(0), size_t(1), size_t(15), size_t(16), size_t(17), size_t(78), size_t(177), MAX_PAYLOAD}) {
    std::vector<uint8_t> b(n, 0x39), original = b;
    assert(seal(k.data(), ad.data(), ad.size(), b.data(), n, tag));
    assert(open(k.data(), ad.data(), ad.size(), b.data(), n, tag)); assert(b == original);
    assert(seal(k.data(), ad.data(), ad.size(), b.data(), n, tag)); tag[4] ^= 1;
    assert(!open(k.data(), ad.data(), ad.size(), b.data(), n, tag));
    for (uint8_t c : b) assert(c == 0);
  }
  assert(!seal(k.data(), ad.data(), ad.size(), p.data(), MAX_PAYLOAD + 1, tag));
  History history;
  history.sample(0, 3900, -4); history.sample(59, 3100, 98);
  assert(history.week().voltage == 3100 && history.week().high == temperature(98));
  history.sample(3600, 3800, 28);
  history.advance(169 * 3600);
  assert(history.week().voltage == 3800 && history.period.voltage == 3100);
  history.advance(400 * 3600); assert(history.week().voltage == 0);
  assert(temperature(NAN) == 0 && temperature(-51) == 252 && temperature(201) == 253);
  Schedule schedule;
  assert(Schedule::validDirect(5) && Schedule::validDirect(90));
  assert(!Schedule::validDirect(4) && !Schedule::validDirect(91));
  assert(Schedule::validFlood(21) && Schedule::validFlood(90));
  assert(!Schedule::validFlood(20) && !Schedule::validFlood(91));
  schedule.advance(5 * DAY); assert(schedule.flood == 16 * DAY);
  schedule.reserve(false, 5, 21, 0); assert(schedule.flood == 16 * DAY);
  schedule.advance(16 * DAY); assert(!schedule.direct && !schedule.flood);
  schedule.reserve(true, 5, 21, 0); assert(schedule.flood == 21 * DAY);
  assert(schedule.direct == 5 * DAY);
  schedule.direct = 4 * DAY; schedule.flood = 0;
  schedule.reserve(true, 5, 21, 0); assert(schedule.direct == 4 * DAY);
  schedule.reserve(true, 5, 90, 0); assert(schedule.flood == 90 * DAY);
  Schedule restored = schedule; restored.advance(90 * DAY); assert(!restored.flood);
  uint8_t root[32], radio[16] = {}, admin[32] = {}, token[12], other[12];
  passwordKey("management test password", root);
  fingerprint(root, radio, admin, token); radio[0] = 1;
  fingerprint(root, radio, admin, other); assert(!equal(token, other, 12));
  AclList acl; assert(acl.add(token, ADMIN)); assert(acl.add(token, OTA_SIGNER));
  assert(acl.count == 1 && acl.entries[0][12] == 3);
  for (uint8_t i = 1; i < MAX_KEYS; ++i) { token[0] = i; assert(acl.add(token, ADMIN)); }
  token[0] = 240; assert(!acl.add(token, ADMIN)); assert(acl.pages() == MAX_PAGES);
  mesh::UsbLoggingStatus usb;
  usb.supported = usb.logging_enabled = usb.watchdog_enabled = true;
  usb.host_connected = usb.reader_connected = usb.logger_active = true;
  usb.stalled = usb.recovering = usb.recovery_deferred = usb.persistence_ready = true;
  usb.watchdog_auto = true; usb.auto_connected_seconds = 1209600;
  usb.stage = 2; usb.backoff_step = 8; usb.retry_seconds = 604800;
  usb.inactive_seconds = UINT32_MAX;
  usb.last_event.reasons = 15;
  usb.last_event.action = mesh::UsbLoggingWatchdogEvent::REBOOT_REQUESTED;
  usb.last_event.epoch = 1700000001; usb.last_event.uptime_seconds = 777;
  usb.last_event.sequence = 42; usb.last_event.persisted = true;
  uint8_t usb_block[USB_STATUS_SIZE] = {};
  encodeUsbStatus(usb_block, usb);
  assert(read16(usb_block) == 2047 && usb_block[2] == (2 | (8 << 2)));
  assert(read32(usb_block + 3) == 604800 && read32(usb_block + 7) == UINT32_MAX);
  assert(read32(usb_block + 11) == 1209600);
  usb.logger_active = false; encodeUsbStatus(usb_block, usb);
  assert(read16(usb_block) == 1023); // host/reader connection does not imply a logger
  usb.logger_active = true;
  // Emit all wire versions for independent Python and browser decoders.
  for (const char* magic : {"MGR1", "MGR2", "MGR3"}) {
    const auto* version = reinterpret_cast<const uint8_t*>(magic);
    const bool current = currentPage(version), has_usb = usbPage(version);
    const size_t header = headerSize(version), per_page = entriesPerPage(version);
    for (uint8_t page = 0; page < acl.pages(per_page); ++page) {
      uint8_t raw[179] = {}, enc[32]; memcpy(raw, magic, 4);
      memcpy(raw + 4, radio, 16);
      write32(raw + 20, 42); write32(raw + 28, 0x01110105); write16(raw + 76, FIRMWARE);
      raw[71] = 5; raw[78] = page; raw[79] = acl.pages(per_page); raw[80] = acl.count;
      raw[81] = page * per_page;
      raw[82] = acl.count - raw[81] < per_page ? acl.count - raw[81] : per_page;
      if (has_usb) encodeUsbStatus(raw + HEADER, usb);
      if (current) mesh::encodeUsbWatchdogEvent(raw + WATCHDOG_EVENT_OFFSET, usb.last_event);
      const size_t private_len = raw[82] * ENTRY, size = header + private_len + TAG;
      memcpy(raw + header, acl.entries[raw[81]], private_len);
      deriveKey(root, "MeshCore-MGR1-SIV", radio, enc);
      assert(seal(enc, raw, header, raw + header, private_len, raw + header + private_len));
      assert(validPage(raw, size)); print(raw, size);
      assert(size <= MAX_PAYLOAD && floodSize(size) <= 179);
      assert(validPage(raw, floodSize(size), true));
      if (floodSize(size) > size) {
        raw[floodSize(size) - 1] ^= 1;
        assert(!validPage(raw, floodSize(size), true)); raw[floodSize(size) - 1] ^= 1;
      }
      if (has_usb) {
        raw[85] |= 0x40; assert(!validPage(raw, size)); raw[85] &= ~0x40;
        raw[84] |= 0x08; assert(!validPage(raw, size)); raw[84] &= ~0x08;
      }
      if (current) {
        const uint8_t original = raw[98];
        for (uint8_t invalid : {uint8_t(original & 0xf0), uint8_t(original & 0x8f), uint8_t(0xdf)}) {
          raw[98] = invalid; assert(!validPage(raw, size));
        }
        raw[98] = original;
        write32(raw + 107, 0); assert(!validPage(raw, size)); write32(raw + 107, 42);
      }
      raw[81]++; assert(!validPage(raw, size)); raw[81]--;
      assert(!validPage(raw, size - 1)); raw[80] = 37; assert(!validPage(raw, size));
    }
  }
  // A current report with no recorded event is authenticated, not invented.
  {
    uint8_t raw[179] = {}, enc[32]; memcpy(raw, "MGR3", 4); memcpy(raw + 4, radio, 16);
    write32(raw + 20, 43); raw[79] = 1;
    deriveKey(root, "MeshCore-MGR1-SIV", radio, enc);
    assert(seal(enc, raw, CURRENT_HEADER, raw + CURRENT_HEADER, 0, raw + CURRENT_HEADER));
    assert(validPage(raw, CURRENT_HEADER + TAG)); print(raw, CURRENT_HEADER + TAG);
  }
  // Every ACL count retains complete coverage and the unchanged flood ceiling.
  for (unsigned total = 0; total <= MAX_KEYS; ++total) {
    for (unsigned page = 0; page < (total ? (total + 3) / 4 : 1); ++page) {
      uint8_t raw[179] = {}; memcpy(raw, "MGR3", 4);
      raw[78] = page; raw[79] = total ? (total + 3) / 4 : 1; raw[80] = total;
      raw[81] = page * 4; raw[82] = total - raw[81] < 4 ? total - raw[81] : 4;
      const size_t size = pageSize(raw);
      assert(validPage(raw, size) && floodSize(size) <= 179);
      assert(validPage(raw, floodSize(size), true));
    }
  }
  for (size_t n = 0; n < CURRENT_HEADER + TAG; ++n) {
    std::vector<uint8_t> truncated(n);
    for (size_t i = 0; i < n && i < 4; ++i) truncated[i] = "MGR3"[i];
    assert(!validPage(truncated.data(), n));
  }
  for (size_t n = 0; n < HEADER + TAG; ++n) assert(!validPage(plain.data(), n));
}
